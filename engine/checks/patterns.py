"""Pattern checks. No LLM, no network: these run with Ollama stopped.

Four of the five checks have an exact, rule-based half here:

    Hardcode Hunter   secrets, high-entropy strings, credentialed URLs, local paths, fixed ports
    Test Guardian     .only / skip / xit / always-true asserts / deleted tests
    Reality Check     imports that are not stdlib, in the repo, requirements.txt or package.json
    Scope Guard       lockfile / .env / CI edits the prompt never mentioned

Impact Analyst lives in engine/graph.py because it needs the call graph. Only added lines are
checked (a secret already in the file is not this edit's fault).

Secrets are redacted before they go anywhere: findings, diffs and the event log only ever hold
`redact()`ed text.
"""

from __future__ import annotations

import ast
import json
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from engine.diffing import LineDiff, line_diff
from engine.models import Edit, Finding

# ---------------------------------------------------------------------------
# Secrets
# ---------------------------------------------------------------------------

# (name, regex). A match is always high severity.
TOKEN_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("Slack token", re.compile(r"xox[abprs]-[A-Za-z0-9-]{10,}")),
    ("GitHub token", re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}")),
    ("API key (sk-)", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}")),
    ("Stripe live key", re.compile(r"\b[sr]k_live_[A-Za-z0-9]{16,}")),
    ("AWS access key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("Private key", re.compile(r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----")),
]
CREDENTIAL_URL = re.compile(r"\b[a-z][a-z0-9+.-]*://([^/\s:@'\"]+):([^/\s@'\"]+)@", re.I)
SECRET_ASSIGN = re.compile(
    r"""(?ix)\b(password|passwd|secret|api[_-]?key|auth[_-]?token|access[_-]?token|token)\b
        ["']?\s*[:=]\s*["']([^"'\s]{6,})["']"""
)
QUOTED_BLOB = re.compile(r"""["']([A-Za-z0-9+/=_-]{24,})["']""")
LOCAL_PATH = re.compile(r"""["'](?:/home/|/Users/|[A-Za-z]:[\\/])[^"']*["']""")
FIXED_PORT = re.compile(
    r"(?i)(?:\bport\s*[=:]\s*([1-9]\d{1,4})\b|(?:localhost|127\.0\.0\.1|0\.0\.0\.0):([1-9]\d{1,4})\b)"
)
ENTROPY_MIN = 4.0


def shannon_entropy(value: str) -> float:
    if not value:
        return 0.0
    counts = {c: value.count(c) for c in set(value)}
    return -sum(n / len(value) * math.log2(n / len(value)) for n in counts.values())


def _is_high_entropy(value: str) -> bool:
    return (
        shannon_entropy(value) >= ENTROPY_MIN
        and any(c.isdigit() for c in value)
        and any(c.isalpha() for c in value)
    )


def redact(text: str) -> str:
    """Mask anything that looks like a secret: keep a short prefix, then an ellipsis."""
    for _, pattern in TOKEN_PATTERNS:
        text = pattern.sub(lambda m: m.group(0)[:5] + "…", text)
    text = CREDENTIAL_URL.sub(lambda m: m.group(0).replace(m.group(2), "…", 1), text)

    def mask_assign(match: re.Match[str]) -> str:
        if "…" in match.group(2):  # already masked above
            return match.group(0)
        return match.group(0).replace(match.group(2), match.group(2)[:3] + "…", 1)

    text = SECRET_ASSIGN.sub(mask_assign, text)

    def mask_blob(match: re.Match[str]) -> str:
        blob = match.group(1)
        return match.group(0).replace(blob, blob[:4] + "…") if _is_high_entropy(blob) else match.group(0)

    return QUOTED_BLOB.sub(mask_blob, text)


def _evidence(line: str) -> str:
    return redact(line.strip())[:200]


def _finding(edit: Edit, check: str, severity: str, line: int, message: str, text: str) -> Finding:
    return Finding(
        check=check, severity=severity, source="pattern", file=edit.file, line=line,
        message=message, evidence=_evidence(text),
    )


def hardcode_hunter(edit: Edit, diff: LineDiff) -> list[Finding]:
    findings: list[Finding] = []
    for number, text in diff.added:
        matched_secret = False
        for name, pattern in TOKEN_PATTERNS:
            if pattern.search(text):
                findings.append(_finding(edit, "hardcode_hunter", "high", number, f"{name} hardcoded", text))
                matched_secret = True
                break
        url = CREDENTIAL_URL.search(text)
        if url and not re.search(r"[{$%<]", url.group(2)):
            findings.append(_finding(edit, "hardcode_hunter", "high", number, "URL with embedded credentials", text))
            matched_secret = True
        if matched_secret:
            continue
        assign = SECRET_ASSIGN.search(text)
        if assign:
            findings.append(_finding(
                edit, "hardcode_hunter", "medium", number,
                f"Hardcoded value for '{assign.group(1)}'", text))
            continue
        if any(_is_high_entropy(m.group(1)) for m in QUOTED_BLOB.finditer(text)):
            findings.append(_finding(
                edit, "hardcode_hunter", "medium", number, "High-entropy string, possibly a secret", text))
            continue
        if LOCAL_PATH.search(text):
            findings.append(_finding(edit, "hardcode_hunter", "low", number, "Absolute local path", text))
        port = FIXED_PORT.search(text)
        if port:
            findings.append(_finding(
                edit, "hardcode_hunter", "low", number, f"Fixed port {port.group(1) or port.group(2)}", text))
    return findings


# ---------------------------------------------------------------------------
# Test Guardian
# ---------------------------------------------------------------------------

TEST_FILE = re.compile(r"(^|/)(tests?|__tests__)/|(^|/)test_[^/]*$|_test\.py$|\.(test|spec)\.[jt]sx?$")
SKIP_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("Focused test (.only) silences every other test",
     re.compile(r"\b(?:it|test|describe)\.only\(|\b(?:fit|fdescribe)\(")),
    ("Skipped test",
     re.compile(r"\b(?:it|test|describe)\.skip\(|\bx(?:it|describe|test)\(|@pytest\.mark\.skip|@unittest\.skip|\bpytest\.skip\(")),
    ("Assertion that always passes",
     re.compile(r"\bassert\s+True\b|\bassert\s+1\s*==\s*1\b|assertTrue\(\s*True\s*\)|expect\(\s*true\s*\)\.toBe\(\s*true\s*\)")),
]
PY_TEST_DEF = re.compile(r"^\s*(?:async\s+)?def\s+(test_\w+)", re.M)
JS_TEST_TITLE = re.compile(r"""\b(?:it|test)\(\s*["'`]([^"'`]+)""")


def is_test_file(path: str) -> bool:
    return bool(TEST_FILE.search(path))


def test_guardian(edit: Edit, diff: LineDiff) -> list[Finding]:
    if not is_test_file(edit.file):
        return []
    findings: list[Finding] = []
    for number, text in diff.added:
        for message, pattern in SKIP_PATTERNS:
            if pattern.search(text):
                findings.append(_finding(edit, "test_guardian", "medium", number, message, text))
                break
    for finder in (PY_TEST_DEF, JS_TEST_TITLE):
        gone = set(finder.findall(edit.before)) - set(finder.findall(edit.after))
        for name in sorted(gone):
            # Where the deleted test used to be, in the new file.
            position = next((after_pos for _, text, after_pos in diff.removed if name in text), 1)
            findings.append(Finding(
                check="test_guardian", severity="high", source="pattern", file=edit.file,
                line=position, message=f"Test deleted: {name}", evidence=f"removed: {name}"))
    return findings


# pytest would otherwise try to collect the function above as a test.
test_guardian.__test__ = False  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Reality Check (the exact part: "not installed")
# ---------------------------------------------------------------------------

PIP_ALIASES = {
    "yaml": "pyyaml", "pil": "pillow", "cv2": "opencv_python", "sklearn": "scikit_learn",
    "bs4": "beautifulsoup4", "dotenv": "python_dotenv", "jwt": "pyjwt", "dateutil": "python_dateutil",
    "attr": "attrs", "serial": "pyserial", "magic": "python_magic", "git": "gitpython",
}
NODE_BUILTINS = {
    "assert", "buffer", "child_process", "cluster", "crypto", "dns", "events", "fs", "http", "http2",
    "https", "net", "os", "path", "perf_hooks", "process", "querystring", "readline", "stream",
    "string_decoder", "timers", "tls", "url", "util", "vm", "worker_threads", "zlib",
}
JS_EXT = {".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"}
JS_IMPORT = re.compile(r"""(?:\bfrom\s+|\bimport\s+|\brequire\(\s*)["']([^"']+)["']""")


def _norm(name: str) -> str:
    return re.sub(r"[-.]+", "_", name.strip().lower())


@dataclass
class RepoContext:
    """What the repo already declares. Read on demand; nothing is cached across edits."""

    root: Path

    def python_modules(self) -> set[str]:
        names: set[str] = set()
        if not self.root.is_dir():
            return names
        for child in self.root.iterdir():
            if child.is_file() and child.suffix == ".py":
                names.add(_norm(child.stem))
            elif child.is_dir() and not child.name.startswith("."):
                names.add(_norm(child.name))
        return names

    def requirements(self) -> set[str]:
        found: set[str] = set()
        for path in self.root.glob("requirements*.txt"):
            for raw in path.read_text(errors="ignore").splitlines():
                line = raw.split("#", 1)[0].strip()
                if not line or line.startswith("-"):
                    continue
                found.add(_norm(re.split(r"[<>=!~;\[ ]", line, maxsplit=1)[0]))
        return found

    def node_deps(self) -> set[str]:
        path = self.root / "package.json"
        if not path.is_file():
            return set()
        try:
            data = json.loads(path.read_text(errors="ignore"))
        except ValueError:
            return set()
        return {
            name for key in ("dependencies", "devDependencies", "peerDependencies") for name in data.get(key, {})
        }


def _python_imports(source: str, wanted: set[int]) -> list[tuple[int, str]]:
    """(line, top-level module) for absolute imports that start on a wanted line."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and node.lineno in wanted:
            found.extend((node.lineno, alias.name.split(".")[0]) for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.lineno in wanted and node.level == 0 and node.module:
            found.append((node.lineno, node.module.split(".")[0]))
    return found


def _js_package(spec: str) -> str | None:
    if spec.startswith((".", "/", "node:", "@/", "~")):
        return None
    parts = spec.split("/")
    package = "/".join(parts[:2]) if spec.startswith("@") else parts[0]
    return None if package in NODE_BUILTINS else package


def reality_check(edit: Edit, diff: LineDiff, repo: RepoContext) -> list[Finding]:
    suffix = PurePosixPath(edit.file).suffix
    findings: list[Finding] = []
    lines = edit.after.splitlines()

    def report(number: int, module: str) -> None:
        text = lines[number - 1] if 0 < number <= len(lines) else module
        findings.append(_finding(
            edit, "reality_check", "medium", number,
            f"Import '{module}' is not installed: not stdlib, not in the repo, requirements.txt or package.json",
            text))

    if suffix == ".py":
        known = repo.python_modules() | repo.requirements()
        for number, module in _python_imports(edit.after, diff.added_numbers()):
            key = _norm(module)
            if module in sys.stdlib_module_names or key in known or PIP_ALIASES.get(key) in known:
                continue
            report(number, module)
    elif suffix in JS_EXT:
        deps = repo.node_deps()
        for number, text in diff.added:
            for spec in JS_IMPORT.findall(text):
                package = _js_package(spec)
                if package and package not in deps:
                    report(number, package)
    return findings


# ---------------------------------------------------------------------------
# Scope Guard (the exact part)
# ---------------------------------------------------------------------------

LOCKFILES = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "pipfile.lock", "uv.lock",
    "cargo.lock", "go.sum", "composer.lock", "gemfile.lock",
}
CI_FILES = {".gitlab-ci.yml", "jenkinsfile", "azure-pipelines.yml", ".travis.yml", "bitbucket-pipelines.yml"}
# Words in a prompt that make an edit to that kind of file expected.
ASKED_FOR = {
    "lockfile": ("lock", "dependenc", "upgrade", "install", "bump"),
    "env": ("env", "environment", "config", "secret"),
    "ci": ("ci", "workflow", "pipeline", "github action", "deploy", "build"),
}


def _sensitive_kind(path: str) -> str | None:
    name = PurePosixPath(path).name.lower()
    if name in LOCKFILES:
        return "lockfile"
    if name == ".env" or name.startswith(".env."):
        return "env"
    if name in CI_FILES or ".github/workflows/" in path or ".circleci/" in path:
        return "ci"
    return None


def scope_guard(edit: Edit) -> list[Finding]:
    kind = _sensitive_kind(edit.file)
    if kind is None:
        return []
    prompt = edit.prompt.lower()
    name = PurePosixPath(edit.file).name.lower()
    if name in prompt or edit.file.lower() in prompt:
        return []
    if any(re.search(rf"\b{re.escape(word)}", prompt) for word in ASKED_FOR[kind]):
        return []
    label = {"lockfile": "lockfile", "env": ".env file", "ci": "CI file"}[kind]
    return [Finding(
        check="scope_guard", severity="medium", source="pattern", file=edit.file, line=1,
        message=f"Edit to a {label} the prompt did not ask for",
        evidence=f"prompt: {edit.prompt.strip()[:120] or '(empty)'}")]


# ---------------------------------------------------------------------------


def run_patterns(edit: Edit, repo_root: Path, diff: LineDiff | None = None) -> list[Finding]:
    diff = diff or line_diff(edit.before, edit.after)
    findings = [
        *hardcode_hunter(edit, diff),
        *test_guardian(edit, diff),
        *reality_check(edit, diff, RepoContext(repo_root)),
        *scope_guard(edit),
    ]
    return sorted(findings, key=lambda f: (f.line, f.check))
