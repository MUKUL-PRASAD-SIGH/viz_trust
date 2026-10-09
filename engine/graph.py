"""Call graph and blast radius for Python, built on the standard library `ast`.

Nodes are functions and methods (`app/signup.py::handle_signup`, `app/users.py::Store.add`).
An edge `(caller, callee)` means the caller's body calls the callee. Resolution is name based:
same-file functions, `from x import y`, `import x as m; m.y()`, `self.method()`, and a unique
method name anywhere in the repo as a last resort. It over-approximates a little and misses
dynamic calls, which is fine for a blast-radius picture.

Per edit, `analyze_edit` works out `touched` (functions whose source changed, were added or were
removed) and `blast` (their callers, walked upwards up to depth 3), and raises Impact Analyst
findings when a changed signature or a removed function leaves callers behind.
"""

from __future__ import annotations

import ast
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from engine.diffing import LineDiff
from engine.models import Edit, Finding

BLAST_DEPTH = 3
MAX_FILE_BYTES = 500_000
SKIP_DIRS = {"__pycache__", "node_modules", "venv", ".venv", "site-packages", "build", "dist"}

# Attribute calls on these are almost always builtins, never repo functions.
_BUILTIN_ATTRS = {
    name for kind in (dict, list, set, str, bytes, tuple, frozenset) for name in dir(kind)
} | {"read", "write", "close", "open", "join", "format", "info", "debug", "warning", "error", "exception"}


@dataclass
class FuncNode:
    id: str
    file: str
    qualname: str
    lineno: int
    end_lineno: int
    params: tuple[tuple[str, bool], ...]  # (name, has_default); *args/**kwargs count as defaulted
    segment: str

    @property
    def label(self) -> str:
        return self.qualname


@dataclass
class CallGraph:
    nodes: dict[str, FuncNode] = field(default_factory=dict)
    edges: set[tuple[str, str]] = field(default_factory=set)

    def callers_of(self, node_id: str) -> set[str]:
        return {a for a, b in self.edges if b == node_id}


@dataclass
class _FileInfo:
    path: str
    tree: ast.Module
    source: str
    functions: dict[str, ast.AST] = field(default_factory=dict)  # qualname -> def node
    classes: set[str] = field(default_factory=set)


def _params(node: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[tuple[str, bool], ...]:
    args = node.args
    positional = [*args.posonlyargs, *args.args]
    defaults = [False] * (len(positional) - len(args.defaults)) + [True] * len(args.defaults)
    out = [(a.arg, d) for a, d in zip(positional, defaults)]
    out += [(a.arg, d is not None) for a, d in zip(args.kwonlyargs, args.kw_defaults)]
    if args.vararg:
        out.append(("*" + args.vararg.arg, True))
    if args.kwarg:
        out.append(("**" + args.kwarg.arg, True))
    return tuple(out)


def parse_file(path: str, source: str) -> tuple[_FileInfo | None, dict[str, FuncNode]]:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None, {}
    info = _FileInfo(path=path, tree=tree, source=source)
    nodes: dict[str, FuncNode] = {}

    def add(qualname: str, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        node_id = f"{path}::{qualname}"
        info.functions[qualname] = node
        nodes[node_id] = FuncNode(
            id=node_id, file=path, qualname=qualname, lineno=node.lineno,
            end_lineno=node.end_lineno or node.lineno, params=_params(node),
            segment=ast.get_source_segment(source, node) or "",
        )

    for item in tree.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            add(item.name, item)
        elif isinstance(item, ast.ClassDef):
            info.classes.add(item.name)
            for sub in item.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    add(f"{item.name}.{sub.name}", sub)
    return info, nodes


def _module_file(sources: dict[str, str], dotted: str, from_file: str, level: int) -> str | None:
    """Repo path for an import, or None if it is not in the repo."""
    if level:
        base = PurePosixPath(from_file).parent
        for _ in range(level - 1):
            base = base.parent
        parts = [*base.parts, *([p for p in dotted.split(".") if p] if dotted else [])]
    else:
        parts = dotted.split(".")
    stem = "/".join(p for p in parts if p not in ("", "."))
    for candidate in (f"{stem}.py", f"{stem}/__init__.py"):
        if candidate in sources:
            return candidate
    return None


def _dotted(node: ast.AST) -> list[str] | None:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return parts[::-1]
    return None


def build_graph(sources: dict[str, str]) -> CallGraph:
    graph = CallGraph()
    infos: dict[str, _FileInfo] = {}
    for path, source in sources.items():
        if not path.endswith(".py"):
            continue
        info, nodes = parse_file(path, source)
        if info:
            infos[path] = info
            graph.nodes.update(nodes)

    by_bare_name: dict[str, list[str]] = {}
    for node in graph.nodes.values():
        by_bare_name.setdefault(node.qualname.split(".")[-1], []).append(node.id)

    for path, info in infos.items():
        names: dict[str, tuple[str, str]] = {}  # local name -> (module file, original name)
        modules: dict[str, str] = {}  # dotted alias -> module file
        for node in ast.walk(info.tree):
            if isinstance(node, ast.ImportFrom):
                module_path = _module_file(sources, node.module or "", path, node.level)
                for alias in node.names:
                    local = alias.asname or alias.name
                    sub = _module_file(sources, f"{node.module or ''}.{alias.name}".strip("."), path, node.level)
                    if sub and (not module_path or f"{alias.name}" not in infos.get(module_path, info).functions):
                        modules[local] = sub
                    elif module_path:
                        names[local] = (module_path, alias.name)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    target = _module_file(sources, alias.name, path, 0)
                    if target:
                        modules[alias.asname or alias.name] = target

        def resolve(callee: ast.AST, owner_class: str | None) -> str | None:
            def pick(file: str, qualname: str) -> str | None:
                if f"{file}::{qualname}" in graph.nodes:
                    return f"{file}::{qualname}"
                if f"{file}::{qualname}.__init__" in graph.nodes:  # constructing a class
                    return f"{file}::{qualname}.__init__"
                return None

            if isinstance(callee, ast.Name):
                if callee.id in names:
                    file, original = names[callee.id]
                    return pick(file, original)
                return pick(path, callee.id)
            parts = _dotted(callee)
            if parts and len(parts) >= 2:
                if parts[0] in ("self", "cls") and owner_class and len(parts) == 2:
                    found = pick(path, f"{owner_class}.{parts[1]}")
                    if found:
                        return found
                for cut in range(len(parts) - 1, 0, -1):  # longest module prefix wins
                    prefix = ".".join(parts[:cut])
                    if prefix in modules:
                        return pick(modules[prefix], ".".join(parts[cut:]))
                if parts[0] in names and len(parts) == 2:  # imported class: Cls.method
                    file, original = names[parts[0]]
                    return pick(file, f"{original}.{parts[1]}")
                if parts[0] in info.classes and len(parts) == 2:
                    return pick(path, ".".join(parts))
            if isinstance(callee, ast.Attribute) and callee.attr not in _BUILTIN_ATTRS:
                candidates = by_bare_name.get(callee.attr, [])
                if len(candidates) == 1:
                    return candidates[0]
            return None

        for qualname, func in info.functions.items():
            caller = f"{path}::{qualname}"
            owner = qualname.split(".")[0] if "." in qualname else None
            for call in ast.walk(func):
                if isinstance(call, ast.Call):
                    callee = resolve(call.func, owner)
                    if callee and callee != caller:
                        graph.edges.add((caller, callee))
    return graph


# ---------------------------------------------------------------------------
# Loading a repo from disk
# ---------------------------------------------------------------------------

_SOURCE_CACHE: dict[Path, tuple[tuple, dict[str, str]]] = {}


def load_sources(root: Path) -> dict[str, str]:
    """All .py files under `root` as {posix relative path: source}. Cached on mtimes."""
    if not root.is_dir():
        return {}
    files = [
        p for p in root.rglob("*.py")
        if not any(part in SKIP_DIRS or part.startswith(".") for part in p.relative_to(root).parts)
    ]
    signature = tuple(sorted((str(p), p.stat().st_mtime_ns, p.stat().st_size) for p in files))
    cached = _SOURCE_CACHE.get(root)
    if cached and cached[0] == signature:
        return cached[1]
    sources = {}
    for p in files:
        if p.stat().st_size <= MAX_FILE_BYTES:
            sources[p.relative_to(root).as_posix()] = p.read_text(errors="ignore")
    _SOURCE_CACHE[root] = (signature, sources)
    return sources


# ---------------------------------------------------------------------------
# Per-edit analysis
# ---------------------------------------------------------------------------


@dataclass
class EditAnalysis:
    touched: list[str] = field(default_factory=list)
    blast: list[str] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)


def _signature_text(params: tuple[tuple[str, bool], ...]) -> str:
    return "(" + ", ".join(f"{n}=…" if d and not n.startswith("*") else n for n, d in params) + ")"


def _breaking(old: tuple[tuple[str, bool], ...], new: tuple[tuple[str, bool], ...]) -> bool:
    old_names, new_map = {n for n, _ in old}, dict(new)
    if any(n not in new_map for n in old_names):
        return True  # a parameter was removed or renamed
    return any(not default for n, default in new if n not in old_names)  # new required parameter


def walk_up(edges: set[tuple[str, str]], start: list[str], depth: int = BLAST_DEPTH) -> list[str]:
    """Callers of `start`, nearest first, up to `depth` hops. `start` itself is excluded."""
    callers: dict[str, set[str]] = {}
    for caller, callee in edges:
        callers.setdefault(callee, set()).add(caller)
    seen, order = set(start), []
    queue = deque((s, 0) for s in start)
    while queue:
        node, hops = queue.popleft()
        if hops == depth:
            continue
        for caller in sorted(callers.get(node, ())):
            if caller not in seen:
                seen.add(caller)
                order.append(caller)
                queue.append((caller, hops + 1))
    return order


def analyze_edit(edit: Edit, repo_sources: dict[str, str], diff: LineDiff) -> EditAnalysis:
    if not edit.file.endswith(".py"):
        return EditAnalysis()

    rest = {path: src for path, src in repo_sources.items() if path != edit.file}
    before_sources = {**rest, **({edit.file: edit.before} if edit.before else {})}
    after_sources = {**rest, **({edit.file: edit.after} if edit.after else {})}
    before, after = build_graph(before_sources), build_graph(after_sources)

    old = {i: n for i, n in before.nodes.items() if n.file == edit.file}
    new = {i: n for i, n in after.nodes.items() if n.file == edit.file}
    touched = sorted(
        i for i in old.keys() | new.keys()
        if i not in old or i not in new or old[i].segment != new[i].segment
    )

    edges = before.edges | after.edges
    blast = [i for i in walk_up(edges, touched) if i in before.nodes or i in after.nodes]

    findings: list[Finding] = []
    for node_id in touched:
        direct = sorted(c for c in {a for a, b in edges if b == node_id} if c not in touched)
        if not direct:
            continue
        names = ", ".join(c.split("::")[1] for c in direct[:3]) + (", …" if len(direct) > 3 else "")
        if node_id in old and node_id not in new:
            gone = old[node_id]
            position = next(
                (pos for number, _, pos in diff.removed if gone.lineno <= number <= gone.end_lineno), 1)
            findings.append(Finding(
                check="impact_analyst", severity="medium", source="pattern", file=edit.file, line=position,
                message=f"{gone.qualname} was removed but {len(direct)} caller(s) remain: {names}",
                evidence=f"removed: def {gone.qualname}"))
        elif node_id in old and node_id in new and _breaking(old[node_id].params, new[node_id].params):
            changed = new[node_id]
            findings.append(Finding(
                check="impact_analyst", severity="medium", source="pattern", file=edit.file, line=changed.lineno,
                message=(f"Signature of {changed.qualname} changed from {_signature_text(old[node_id].params)} "
                         f"to {_signature_text(changed.params)}; {len(direct)} caller(s) may break: {names}"),
                evidence=f"def {changed.qualname}{_signature_text(changed.params)}"))
    return EditAnalysis(touched=touched, blast=blast, findings=findings)
