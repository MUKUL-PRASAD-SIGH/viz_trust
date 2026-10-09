"""Shared engine types. They match the contract in person/README.md exactly.

Person M owns this file and extends it with the agent, graph and state models. Person C started it
with only `Edit` and `Finding`, the two types the Gemma checks need, so the checks could be built
before the engine exists. Change the contract first, then this file.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Check = Literal["reality_check", "hardcode_hunter", "scope_guard", "test_guardian", "impact_analyst"]
Severity = Literal["low", "medium", "high", "critical"]
Source = Literal["pattern", "gemma"]
Area = Literal["auth", "payments", "migrations", "api", "ui", "tests", "config", "other"]
FindingStatus = Literal["open", "confirmed", "dismissed"]


class Edit(BaseModel):
    """One proposed edit to one file, as it arrives at POST /edits."""

    model_config = ConfigDict(extra="ignore")

    edit_id: str
    agent: str
    model: str = "unknown"
    prompt: str = ""  # the user's task, which Scope Guard judges the edit against
    file: str
    before: str = ""  # whole file before the edit; empty for a new file
    after: str = ""  # whole file after the edit; empty for a deleted file
    area: Area = "other"
    # Top-level module names that belong to the repo itself, so Reality Check doesn't look them up
    # on PyPI or npm. Optional; the engine fills it from the call graph.
    local_modules: list[str] = Field(default_factory=list)


class Finding(BaseModel):
    """One problem found in an edit, with the line it cites as evidence."""

    model_config = ConfigDict(extra="ignore")

    id: str
    edit_id: str
    check: Check
    severity: Severity
    source: Source
    file: str
    line: int = Field(..., ge=1)
    area: Area = "other"
    message: str
    evidence: str
    status: FindingStatus = "open"
    # Optional, added by the Gemma checks: a prompt the user can hand back to the coding agent.
    fix_prompt: str = ""
