"""Gemma judgement checks. Person C replaces this file.

The contract (person/README.md): `review` is called once per edit, never raises, and on any
failure (Ollama stopped, timeout, bad output) returns [] and logs why. Returned findings should
have source="gemma"; leave `id` and `edit_id` empty, the engine fills them in.

Helpers you may want from M's side:
    engine.checks.patterns.RepoContext(root).requirements() / .node_deps() / .python_modules()
    engine.checks.patterns.reality_check(...) lists imports marked "not installed" for you to judge
"""

from __future__ import annotations

from engine.models import Edit, Finding


def review(edit: Edit, timeout_s: float = 8.0) -> list[Finding]:
    """Stub: no Gemma findings. The engine works fine on pattern checks alone."""
    return []
