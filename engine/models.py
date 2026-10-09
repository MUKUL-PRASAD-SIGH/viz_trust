"""Shared types for the engine. Owned by Person M; the JSON they produce is the contract in
person/README.md ("The shared contract"). Change that file first, then this one.

`Finding.id` and `Finding.edit_id` default to "" so a check (pattern or Gemma) can build a
finding without knowing either; the engine fills them in when it stores the finding.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Tier = Literal["probation", "standard", "trusted"]
Severity = Literal["high", "medium", "low"]
Check = Literal["reality_check", "hardcode_hunter", "scope_guard", "test_guardian", "impact_analyst"]
Decision = Literal["allow", "hold", "deny"]
EventType = Literal[
    "edit_clean", "edit_held", "edit_blocked", "finding_confirmed", "finding_dismissed", "tier_changed"
]


class Edit(BaseModel):
    """Body of POST /edits."""

    model_config = ConfigDict(extra="forbid")

    agent: str = Field(..., min_length=1)
    model: str = ""
    prompt: str = ""
    file: str = Field(..., min_length=1, description="Path relative to the repo root, posix slashes.")
    before: str = ""
    after: str = ""


class Finding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = ""
    edit_id: str = ""
    check: Check
    severity: Severity
    source: Literal["pattern", "gemma"] = "pattern"
    file: str
    line: int
    message: str
    evidence: str = ""
    status: Literal["open", "confirmed", "dismissed"] = "open"


class EditResult(BaseModel):
    """Reply to POST /edits."""

    edit_id: str
    decision: Decision
    finding_ids: list[str]


class EditStatus(BaseModel):
    """Reply to GET /edits/{id}. The hook polls `decision` while an edit is held."""

    edit_id: str
    decision: Decision


class DecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    edit_id: str
    decision: Literal["approve", "deny"]


class VerdictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    verdict: Literal["confirm", "dismiss"]


# ---------------------------------------------------------------------------
# GET /agents/state. Same fields as score/app.py's AgentsStateResponse so AgentCard,
# ActivityFeed, LiveStatus and StatusBanner keep working, plus the contract's new fields.
# ---------------------------------------------------------------------------


class Factor(BaseModel):
    feature: str
    value: float
    impact: int
    explanation: str


class AgentEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: EventType
    job_id: int | None = Field(..., description="Sequence number of the edit; null if none.")
    value_usd: float = 0.0
    reason: str
    delta: int
    timestamp: str


class RiskFlag(BaseModel):
    kind: str
    level: Literal["watch", "alert"]
    label: str
    reason: str


class AgentState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    address: str
    name: str
    model: str
    tier: Tier
    score: int
    previous_score: int
    score_delta: int
    band: str
    previous_band: str
    required_collateral_bps: int
    required_collateral_pct: str
    previous_required_collateral_bps: int
    previous_required_collateral_pct: str
    top_factors: list[Factor]
    recent_events: list[AgentEvent]
    risk_flags: list[RiskFlag] = Field(default_factory=list)


class GraphNode(BaseModel):
    id: str
    file: str
    label: str
    heat: float
    last_agent: str | None


class GraphEdge(BaseModel):
    source: str
    target: str


class LastEdit(BaseModel):
    edit_id: str
    touched: list[str]
    blast: list[str]


class Graph(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    last_edit: LastEdit | None


class Pending(BaseModel):
    edit_id: str
    agent: str
    file: str
    added: int
    removed: int
    diff: str
    reason: str
    blast_count: int
    finding_ids: list[str]


class AgentsStateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Literal["engine"] = "engine"
    notice: str | None = None
    oracle_live: bool = True
    updated_at: str | None
    chain_id: int | None = None
    block: int | None = None
    agents: list[AgentState]
    graph: Graph
    findings: list[Finding]
    pending: list[Pending]


class HealthResponse(BaseModel):
    status: str
    agents: int
    events: int
