"""Line-level diff helpers shared by the pattern checks, the graph and the event log."""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field


@dataclass
class LineDiff:
    # (1-based line number in `after`, text)
    added: list[tuple[int, str]] = field(default_factory=list)
    # (1-based line number in `before`, text, 1-based position in `after` where it was removed)
    removed: list[tuple[int, str, int]] = field(default_factory=list)

    @property
    def changed_lines(self) -> int:
        return len(self.added) + len(self.removed)

    def added_numbers(self) -> set[int]:
        return {n for n, _ in self.added}


def line_diff(before: str, after: str) -> LineDiff:
    a, b = before.splitlines(), after.splitlines()
    result = LineDiff()
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag in ("replace", "delete"):
            result.removed.extend((i + 1, a[i], j1 + 1) for i in range(i1, i2))
        if tag in ("replace", "insert"):
            result.added.extend((j + 1, b[j]) for j in range(j1, j2))
    return result


def unified_hunks(before: str, after: str, context: int = 3) -> str:
    """Hunks only (from the first `@@`), like the contract's `diff` field."""
    lines = list(
        difflib.unified_diff(before.splitlines(), after.splitlines(), n=context, lineterm="")
    )
    return "\n".join(lines[2:])
