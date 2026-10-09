"""The Gemma judgement checks. The engine calls `review(edit)` on every edit.

Rules (see person/person_c.md):
1. Gemma only adds findings. It never approves anything; the engine's rules decide.
2. Every finding cites a line, and code checks the line exists in the edit. Others are dropped.
3. The edit is untrusted data (see prompts.SYSTEM).
4. Facts that code can check are checked in code. A package is only reported as missing after the
   package index says so (packages.py).
5. `review()` never raises and never runs past its deadline. On failure it returns what it has.

Checks run in order of how much they matter, sharing one deadline, and a check whose input is
empty (no imports, no hard-coded values, not a test file) costs no model call at all.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable

from engine.checks import packages
from engine.checks.diff import ChangedLines, changed_lines
from engine.llm import prompts
from engine.llm.client import GemmaClient
from engine.models import Edit, Finding

log = logging.getLogger("viz_trust.gemma_checks")

DEFAULT_TIMEOUT_S = 8.0
MIN_CALL_BUDGET_S = 0.5  # don't start a model call with less time than this left

_client: GemmaClient | None = None


def client() -> GemmaClient:
    global _client
    if _client is None:
        _client = GemmaClient()
    return _client


def set_client(new_client: GemmaClient | None) -> None:
    """Swap the client (tests, the evaluation, or a different model)."""
    global _client
    _client = new_client


# Lines worth showing Hardcode Hunter: string literals, URLs, ports, IPs and absolute paths.
_CANDIDATE = re.compile(
    r"""(["'`][^"'`\s]{6,}["'`])"""  # a quoted value with no spaces, 6+ chars
    r"|(://)"  # a URL
    r"|(:\d{2,5}\b)"  # a port
    r"|(\b\d{1,3}(?:\.\d{1,3}){3}\b)"  # an IPv4 address
    r"|((?:/home/|/Users/|[A-Za-z]:\\\\)\S+)"  # an absolute local path
)

# Reading a value from the environment is the fix, not the problem: hide those names from the check.
_ENV_LOOKUP = re.compile(
    r"""os\.environ(?:\.get)?[\[(]\s*["'][^"']*["']|getenv\(\s*["'][^"']*["']|process\.env\.\w+|import\.meta\.env\.\w+"""
)
# A "real secret" must have a secret-looking literal on its line: 16+ token characters, letters and digits.
_SECRET_LITERAL = re.compile(r"""["'`](?=[^"'`]*[A-Za-z])(?=[^"'`]*\d)[\w\-+/=.:]{16,}["'`]""")

_PACKAGE_NAME = re.compile(r"(@[a-z0-9][\w.-]*/)?[A-Za-z0-9][\w.-]*")
_PLACEHOLDERS = {"", "n/a", "na", "none", "null", "-", "unknown"}

_TEST_PATH = re.compile(r"(^|/)(tests?|__tests__|spec)/|(^|/)test_[^/]*$|_test\.\w+$|\.(test|spec)\.\w+$")

HARDCODE_SEVERITY = {
    "real_secret": "critical",
    "credential_in_url": "critical",
    "local_path": "medium",
    "fixed_port_or_host": "medium",
    "placeholder_data": "low",
}


def review(edit: Edit, timeout_s: float = DEFAULT_TIMEOUT_S) -> list[Finding]:
    """Gemma judgement checks for one edit. Never raises: on any failure returns what it has."""
    deadline = time.monotonic() + timeout_s
    findings: list[Finding] = []
    try:
        changes = changed_lines(edit.before, edit.after)
        if not changes.added and not changes.removed:
            return []
        checks: list[Callable[[Edit, ChangedLines, float], list[Finding]]] = [
            _hardcode_hunter,
            _reality_check,
            _test_guardian,
            _scope_guard,
        ]
        for check in checks:
            remaining = deadline - time.monotonic()
            if remaining < MIN_CALL_BUDGET_S:
                log.warning("edit %s: deadline reached before %s", edit.edit_id, check.__name__)
                break
            findings.extend(check(edit, changes, remaining))
    except Exception:  # noqa: BLE001 -- rule 5: a bug here must never block an edit
        log.exception("edit %s: gemma review failed", edit.edit_id)
    return _number(_dedupe(_drop_scope_overlap(findings)), edit.edit_id)


# ---------------------------------------------------------------- checks


def _hardcode_hunter(edit: Edit, changes: ChangedLines, budget: float) -> list[Finding]:
    candidates = {n: text for n, text in changes.added.items() if _CANDIDATE.search(_ENV_LOOKUP.sub("", text))}
    if not candidates:
        return []
    lines = "\n".join(f"L{n}  {text.strip()}" for n, text in sorted(candidates.items()))
    reply = client().structured(
        system=prompts.SYSTEM,
        user=prompts.hardcode_prompt(edit.file, lines),
        schema=prompts.HardcodeReply,
        prompt_version=prompts.HARDCODE_VERSION,
        timeout_s=budget,
    )
    if reply is None:
        return []
    in_tests = bool(_TEST_PATH.search(edit.file))
    found = []
    for item in reply.items:
        severity = HARDCODE_SEVERITY.get(item.kind)
        if severity is None or item.line not in candidates:
            continue  # "fine", or a line we never showed it
        if item.kind == "placeholder_data" and in_tests:
            continue  # fake data is what tests are for
        if item.kind == "real_secret" and not _SECRET_LITERAL.search(candidates[item.line]):
            continue  # the line uses a secret's name, not its value
        found.append(
            _finding(
                edit, "hardcode_hunter", severity, item.line,
                message=_redact(f"{item.kind.replace('_', ' ').capitalize()}: {item.reason}")
                if severity == "critical" else f"{item.kind.replace('_', ' ').capitalize()}: {item.reason}",
                evidence=_redact(candidates[item.line].strip()) if severity == "critical" else candidates[item.line].strip(),
                fix=_clean(item.fix),
            )
        )
    return found


def _reality_check(edit: Edit, changes: ChangedLines, budget: float) -> list[Finding]:
    language = packages.language_of(edit.file)
    local = set(edit.local_modules) | {edit.file.split("/")[0]}
    first_line: dict[str, int] = {}
    for number, text in sorted(changes.added.items()):
        for name in packages.imports_in_line(text, language):
            if name not in local:
                first_line.setdefault(name, number)
    if not first_line:
        return []

    # Rule 4: the package index decides. Only names it doesn't confirm go to the model.
    index = {name: packages.resolve(name, language) for name in first_line}
    unconfirmed = [name for name, exists in index.items() if exists is not True]
    if not unconfirmed:
        return []

    reply = client().structured(
        system=prompts.SYSTEM,
        user=prompts.reality_prompt(edit.file, unconfirmed, changes.rendered),
        schema=prompts.RealityReply,
        prompt_version=prompts.REALITY_VERSION,
        timeout_s=budget,
    )
    verdicts = {v.name: v for v in reply.imports} if reply else {}
    index_name = "PyPI" if language == "python" else "npm"
    found = []
    for name in unconfirmed:
        line = first_line[name]
        verdict = verdicts.get(name)
        # Gemma may know the real install name ("yaml" -> "PyYAML"). Only believed when Gemma calls
        # the package real *and* the index confirms that name exists.
        install_name = _clean(verdict.install_name) if verdict else ""
        if verdict and verdict.verdict == "real" and install_name and install_name != name:
            if _PACKAGE_NAME.fullmatch(install_name) and packages.exists_on_index(install_name, language) is True:
                continue
        if index[name] is False:
            found.append(
                _finding(
                    edit, "reality_check", "high", line,
                    message=f"Package '{name}' doesn't exist on {index_name}",
                    evidence=changes.added[line].strip(),
                    fix=(_clean(verdict.fix) if verdict else "")
                    or f"Remove the import of '{name}' and use a real, installed package instead.",
                )
            )
        elif verdict and verdict.verdict == "invented":  # index unreachable: report, but unverified
            found.append(
                _finding(
                    edit, "reality_check", "medium", line,
                    message=f"Package '{name}' looks invented (couldn't reach {index_name} to confirm)",
                    evidence=changes.added[line].strip(),
                    fix=_clean(verdict.fix),
                )
            )

    for call in reply.api_calls if reply else []:
        if changes.cites(call.line):
            found.append(
                _finding(
                    edit, "reality_check", "medium", call.line,
                    message=f"'{call.call}' doesn't appear to exist: {call.reason}",
                    evidence=changes.added[call.line].strip(),
                    fix=_clean(call.fix),
                )
            )
    return found


def _test_guardian(edit: Edit, changes: ChangedLines, budget: float) -> list[Finding]:
    if not _TEST_PATH.search(edit.file):
        return []
    reply = client().structured(
        system=prompts.SYSTEM,
        user=prompts.guardian_prompt(edit.prompt, edit.file, changes.rendered),
        schema=prompts.GuardianReply,
        prompt_version=prompts.GUARDIAN_VERSION,
        timeout_s=budget,
    )
    if reply is None:
        return []
    found = []
    for item in reply.items:
        if not changes.cites(item.line, item.side):
            continue
        text = (changes.added if item.side == "added" else changes.removed)[item.line].strip()
        found.append(
            _finding(
                edit, "test_guardian", "high", item.line,
                message=f"Test weakened ({item.kind.replace('_', ' ')}): {item.reason}",
                evidence=text if item.side == "added" else f"removed (old line {item.line}): {text}",
                fix=_clean(item.fix),
            )
        )
    return found


def _scope_guard(edit: Edit, changes: ChangedLines, budget: float) -> list[Finding]:
    if not changes.added:
        return []
    reply = client().structured(
        system=prompts.SYSTEM,
        user=prompts.scope_prompt(edit.prompt, edit.file, changes.rendered),
        schema=prompts.ScopeReply,
        prompt_version=prompts.SCOPE_VERSION,
        timeout_s=budget,
    )
    if reply is None:
        return []
    found = []
    for item in reply.items:
        if not changes.cites(item.line) or not changes.added[item.line].strip():
            continue  # not a changed line, or a blank one
        manipulation = item.kind == "reviewer_manipulation"
        found.append(
            _finding(
                edit, "scope_guard", "high" if manipulation else "medium", item.line,
                message=("Text aimed at the AI reviewer: " if manipulation else "Outside the task: ") + item.reason,
                evidence=changes.added[item.line].strip(),
                fix=_clean(item.fix),
            )
        )
    return found


# ---------------------------------------------------------------- helpers


def _finding(edit: Edit, check, severity, line, *, message, evidence, fix) -> Finding:
    return Finding(
        id="",  # numbered in _number
        edit_id=edit.edit_id,
        check=check,
        severity=severity,
        source="gemma",
        file=edit.file,
        line=line,
        area=edit.area,
        message=message[:300],
        evidence=evidence[:200],
        fix_prompt=fix[:300],
    )


def _drop_scope_overlap(findings: list[Finding]) -> list[Finding]:
    """Scope Guard judges the task, not security. A line another check reported isn't repeated."""
    flagged = {f.line for f in findings if f.check != "scope_guard"}
    return [
        f for f in findings
        if f.check != "scope_guard" or f.line not in flagged or f.message.startswith("Text aimed at")
    ]


def _clean(text: str) -> str:
    """The model sometimes fills an optional field with "N/A". Treat that as empty."""
    return "" if text.strip().lower() in _PLACEHOLDERS else text.strip()


def _dedupe(findings: list[Finding]) -> list[Finding]:
    seen: set[tuple[str, int]] = set()
    unique = []
    for finding in findings:
        key = (finding.check, finding.line)
        if key not in seen:
            seen.add(key)
            unique.append(finding)
    return unique


def _number(findings: list[Finding], edit_id: str) -> list[Finding]:
    return [f.model_copy(update={"id": f"g_{edit_id}_{i + 1}"}) for i, f in enumerate(findings)]


def _redact(text: str) -> str:
    """Keep a secret's first few characters as evidence, never the whole value."""
    return re.sub(r"""(["'`])([^"'`]{4})[^"'`]{4,}(["'`])""", r"\1\2…\3", text)
