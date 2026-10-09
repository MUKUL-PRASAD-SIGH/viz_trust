"""In-memory engine state: a pure replay of the event log.

`State.apply(event)` is the only way state changes, and it uses nothing but the event, so
`State.from_events(log.all())` after a restart gives exactly the state the live engine had.
Anything time dependent (graph heat) is computed at read time from timestamps in the log.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from engine import scoring
from engine.eventlog import Event
from engine.graph import CallGraph
from engine.models import (
    AgentEvent, AgentState, Factor, Finding, Graph, GraphEdge, GraphNode, LastEdit, Pending,
)

HEAT_PER_EDIT = 0.5
HEAT_HALF_LIFE_S = 300.0
RECENT_EVENTS = 10
TOP_FACTORS = 3


def iso(t: float) -> str:
    return datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class AgentRec:
    id: str
    name: str
    model: str
    score: int = scoring.START_SCORE
    previous_score: int = scoring.START_SCORE
    factors: dict[str, list[int]] = field(default_factory=dict)  # label -> [count, points]
    feed: list[AgentEvent] = field(default_factory=list)  # oldest first


@dataclass
class EditRec:
    edit_id: str
    seq: int
    t: float
    agent_id: str
    file: str
    prompt: str
    added: int
    removed: int
    diff: str
    touched: list[str]
    blast: list[str]
    finding_ids: list[str] = field(default_factory=list)
    decision: str | None = None  # allow | hold | deny
    decided_by: str | None = None
    hold_reason: str = ""
    held_t: float = 0.0


class State:
    def __init__(self) -> None:
        self.agents: dict[str, AgentRec] = {}
        self.edits: dict[str, EditRec] = {}
        self.findings: dict[str, Finding] = {}
        self.node_edits: dict[str, list[tuple[float, str]]] = {}  # node id -> [(t, agent id)]
        self.last_edit_id: str | None = None
        self.last_t: float | None = None

    @classmethod
    def from_events(cls, events: list[Event]) -> "State":
        state = cls()
        for event in events:
            state.apply(event)
        return state

    # -- writes: only through apply ------------------------------------------

    def apply(self, event: Event) -> None:
        data = event.data
        self.last_t = event.t
        handler = getattr(self, f"_on_{event.kind}", None)
        if handler:
            handler(event.t, data)

    def _on_edit_received(self, t: float, d: dict) -> None:
        if d["agent_id"] not in self.agents:
            self.agents[d["agent_id"]] = AgentRec(d["agent_id"], d["name"], d["model"])
        self.edits[d["edit_id"]] = EditRec(
            edit_id=d["edit_id"], seq=d["seq"], t=t, agent_id=d["agent_id"], file=d["file"],
            prompt=d["prompt"], added=d["added"], removed=d["removed"], diff=d["diff"],
            touched=d["touched"], blast=d["blast"])
        self.last_edit_id = d["edit_id"]

    def _on_finding_created(self, t: float, d: dict) -> None:
        finding = Finding(**d["finding"])
        self.findings[finding.id] = finding
        self.edits[finding.edit_id].finding_ids.append(finding.id)

    def _on_decision(self, t: float, d: dict) -> None:
        edit = self.edits[d["edit_id"]]
        edit.decision, edit.decided_by = d["decision"], d["by"]
        if d["decision"] == "hold":
            edit.hold_reason, edit.held_t = d["reason"], t
        elif d["decision"] == "allow":  # the edit lands: its functions heat up
            for node_id in edit.touched:
                self.node_edits.setdefault(node_id, []).append((t, edit.agent_id))

    def _on_verdict(self, t: float, d: dict) -> None:
        self.findings[d["finding_id"]].status = d["verdict"]

    def _push_feed(self, t: float, d: dict) -> None:
        agent = self.agents[d["agent_id"]]
        agent.feed.append(AgentEvent(
            type=d["feed_type"], job_id=d.get("seq"), value_usd=0.0,
            reason=d["reason"], delta=d.get("delta", 0), timestamp=iso(t)))

    def _on_score_change(self, t: float, d: dict) -> None:
        agent = self.agents[d["agent_id"]]
        agent.previous_score, agent.score = d["old"], d["new"]
        bucket = agent.factors.setdefault(d["factor"], [0, 0])
        bucket[0] += 1
        bucket[1] += d["delta"]
        self._push_feed(t, d)

    def _on_activity(self, t: float, d: dict) -> None:
        self._push_feed(t, d)

    def _on_tier_change(self, t: float, d: dict) -> None:
        self._push_feed(t, {**d, "feed_type": "tier_changed", "delta": 0})

    # -- reads ----------------------------------------------------------------

    def next_edit_seq(self) -> int:
        return len(self.edits) + 1

    def next_finding_seq(self) -> int:
        return len(self.findings) + 1

    def pending_edits(self) -> list[EditRec]:
        return sorted((e for e in self.edits.values() if e.decision == "hold"), key=lambda e: e.seq)

    def agent_states(self) -> list[AgentState]:
        return [self._agent_state(rec) for rec in self.agents.values()]

    def _agent_state(self, rec: AgentRec) -> AgentState:
        tier, previous_tier = scoring.tier_for(rec.score), scoring.tier_for(rec.previous_score)
        bps, pct = scoring.REVIEW_SHARE[tier]
        previous_bps, previous_pct = scoring.REVIEW_SHARE[previous_tier]
        ranked = sorted(rec.factors.items(), key=lambda kv: (-abs(kv[1][1]), kv[0]))[:TOP_FACTORS]
        return AgentState(
            address=rec.id, name=rec.name, model=rec.model, tier=tier,
            score=rec.score, previous_score=rec.previous_score,
            score_delta=rec.score - rec.previous_score,
            band=scoring.band_for(rec.score), previous_band=scoring.band_for(rec.previous_score),
            required_collateral_bps=bps, required_collateral_pct=pct,
            previous_required_collateral_bps=previous_bps, previous_required_collateral_pct=previous_pct,
            top_factors=[
                Factor(feature=label, value=float(count), impact=points, explanation=scoring.explain(label, count))
                for label, (count, points) in ranked
            ],
            recent_events=list(reversed(rec.feed[-RECENT_EVENTS:])),
            risk_flags=[],
        )

    def heat(self, node_id: str, now: float) -> float:
        total = sum(
            HEAT_PER_EDIT * 0.5 ** (max(0.0, now - t) / HEAT_HALF_LIFE_S)
            for t, _ in self.node_edits.get(node_id, ())
        )
        return round(min(1.0, total), 3)

    def graph(self, base: CallGraph, now: float) -> Graph:
        nodes: dict[str, tuple[str, str]] = {n.id: (n.file, n.label) for n in base.nodes.values()}
        # Functions an edit added are not on disk (the engine never writes the repo): keep them.
        for edit in self.edits.values():
            for node_id in (*edit.touched, *edit.blast):
                if node_id not in nodes and "::" in node_id:
                    file, label = node_id.split("::", 1)
                    nodes[node_id] = (file, label)
        last = self.edits.get(self.last_edit_id) if self.last_edit_id else None
        return Graph(
            nodes=[
                GraphNode(
                    id=node_id, file=file, label=label, heat=self.heat(node_id, now),
                    last_agent=self.node_edits[node_id][-1][1] if self.node_edits.get(node_id) else None)
                for node_id, (file, label) in sorted(nodes.items())
            ],
            edges=[GraphEdge(source=a, target=b) for a, b in sorted(base.edges)],
            last_edit=LastEdit(edit_id=last.edit_id, touched=last.touched, blast=last.blast) if last else None,
        )

    def pending(self) -> list[Pending]:
        return [
            Pending(
                edit_id=e.edit_id, agent=e.agent_id, file=e.file, added=e.added, removed=e.removed,
                diff=e.diff, reason=e.hold_reason, blast_count=len(e.blast), finding_ids=list(e.finding_ids))
            for e in self.pending_edits()
        ]
