"""Line-numbered view of an edit, shared by the Gemma checks.

The model is shown only the changed lines (plus a little context), each tagged with its line
number. Every finding it returns must cite one of those numbers, and `ChangedLines.cites` is how the
checks verify that, so a model that invents a line number gets its finding dropped.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field

CONTEXT_LINES = 2
MAX_RENDERED_LINES = 160  # keep prompts small for an 8k-context laptop model


@dataclass
class ChangedLines:
    added: dict[int, str] = field(default_factory=dict)  # line number in `after` -> text
    removed: dict[int, str] = field(default_factory=dict)  # line number in `before` -> text
    rendered: str = ""  # what the model sees

    def cites(self, line: int, side: str = "added") -> bool:
        return line in (self.added if side == "added" else self.removed)


def changed_lines(before: str, after: str) -> ChangedLines:
    old = before.splitlines()
    new = after.splitlines()
    result = ChangedLines()
    out: list[str] = []

    matcher = difflib.SequenceMatcher(a=old, b=new, autojunk=False)
    for group in matcher.get_grouped_opcodes(CONTEXT_LINES):
        out.append("...")
        for tag, i1, i2, j1, j2 in group:
            if tag == "equal":
                for offset, text in enumerate(new[j1:j2]):
                    out.append(f"  L{j1 + offset + 1}  {text}")
                continue
            for offset, text in enumerate(old[i1:i2]):
                number = i1 + offset + 1
                result.removed[number] = text
                out.append(f"- old L{number}  {text}")
            for offset, text in enumerate(new[j1:j2]):
                number = j1 + offset + 1
                result.added[number] = text
                out.append(f"+ L{number}  {text}")

    if len(out) > MAX_RENDERED_LINES:
        out = out[:MAX_RENDERED_LINES] + [f"... ({len(out) - MAX_RENDERED_LINES} more lines not shown)"]
    result.rendered = "\n".join(out)
    return result
