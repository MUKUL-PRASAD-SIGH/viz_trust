"""The engine: review an edit, decide, score, and log every step.

Everything that changes state goes through `_emit`, which appends to the SQLite log and applies
the same event to the in-memory `State`. So a restart (replaying the log) gives the same answer.

Decision rules (person/person_m.md, task 4):

    high-severity secret (Hardcode Hunter)   deny, any tier
    probation                                hold everything
    standard                                 hold if any high finding, else allow
    trusted                                  hold if any high finding; else hold 1 edit in 5
                                             at random for a spot check; else allow

A held edit that nobody answers within HOLD_TIMEOUT_S counts as denied.
"""

from __future__ import annotations

import hashlib
import logging
import random
import threading
import time
from collections.abc import Callable
from pathlib import Path

from engine import scoring
from engine.checks import gemma_checks
from engine.checks.patterns import redact, run_patterns
from engine.diffing import line_diff, unified_hunks
from engine.eventlog import Event, EventLog
from engine.graph import CallGraph, analyze_edit, build_graph, load_sources
from engine.models import (
    AgentsStateResponse, Edit, EditResult, Finding, HealthResponse,
)
from engine.state import State, iso

log = logging.getLogger("engine")

HOLD_TIMEOUT_S = 120.0
GEMMA_TIMEOUT_S = 12.0  # was 8: a cold e4b on a 6 GB GPU needs the room (the hook waits up to 20 s)
SPOT_CHECK_RATE = 0.2
MAX_DIFF_CHARS = 4000
MAX_FINDINGS_SHOWN = 100


class EngineError(Exception):
    status = 400


class NotFound(EngineError):
    status = 404


class Conflict(EngineError):
    status = 409


def agent_identity(agent: str, model: str) -> tuple[str, str]:
    """(stable id, display name): `aider` + `gemma4:e4b` -> `aider:gemma4:e4b`, `aider·e4b`."""
    agent_id = f"{agent}:{model}" if model else agent
    short = model.split(":")[-1] if model else ""
    return agent_id, f"{agent}·{short}" if short else agent


def normalize_path(path: str) -> str:
    """Posix slashes, no leading `./` (but keep dotfiles like `.env`)."""
    path = path.replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    return path


SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2}


def merge_findings(findings: list[Finding]) -> list[Finding]:
    """Drop the duplicate when a pattern check and Gemma flag the same thing.

    Both often flag the same line, e.g. a Slack token: the pattern says "Slack token hardcoded",
    Gemma says "hardcoded secret". For one (check, file, line) flagged by both, keep a single
    finding: Gemma's only if it is strictly more severe, otherwise the pattern's (its message is
    exact). Several findings from the same source on one line (a local path and a fixed port) all
    stay. Order of first appearance is kept.
    """
    groups: dict[tuple[str, str, int], list[Finding]] = {}
    for finding in findings:
        groups.setdefault((finding.check, finding.file, finding.line), []).append(finding)

    merged: list[Finding] = []
    for group in groups.values():
        pattern = [f for f in group if f.source == "pattern"]
        gemma = [f for f in group if f.source != "pattern"]
        if pattern and gemma:
            best_pattern = min(SEVERITY_RANK[f.severity] for f in pattern)
            best_gemma = min(gemma, key=lambda f: SEVERITY_RANK[f.severity])
            merged.extend(pattern if best_pattern <= SEVERITY_RANK[best_gemma.severity] else [best_gemma])
        else:
            merged.extend({f.message: f for f in group}.values())  # exact repeats collapse
    return merged


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:16]


class Engine:
    def __init__(
        self,
        db_path: str | Path,
        repo_root: str | Path,
        clock: Callable[[], float] = time.time,
        rng: random.Random | None = None,
        hold_timeout_s: float = HOLD_TIMEOUT_S,
    ) -> None:
        self.log = EventLog(db_path)
        self.repo_root = Path(repo_root)
        self.clock = clock
        self.rng = rng or random.Random()
        self.hold_timeout_s = hold_timeout_s
        self.lock = threading.RLock()
        self.state = State.from_events(self.log.all())
        self._graph_sources: dict[str, str] | None = None
        self._graph: CallGraph = CallGraph()

    # -- plumbing ---------------------------------------------------------------

    def _emit(self, kind: str, data: dict) -> Event:
        event = self.log.append(kind, data, self.clock())
        self.state.apply(event)
        return event

    def _base_graph(self) -> CallGraph:
        sources = load_sources(self.repo_root)
        if sources is not self._graph_sources:  # load_sources hands back the same dict until files change
            self._graph, self._graph_sources = build_graph(sources), sources
        return self._graph

    def reset(self) -> None:
        with self.lock:
            self.log.wipe()
            self.state = State()

    def health(self) -> HealthResponse:
        with self.lock:
            return HealthResponse(status="ok", agents=len(self.state.agents), events=len(self.log.all()))

    # -- scoring ----------------------------------------------------------------

    def _score(
        self, agent_id: str, seq: int, edit_id: str, factor: str, delta: int, feed_type: str,
        reason: str, secret_leak: bool = False,
    ) -> None:
        agent = self.state.agents[agent_id]
        old = agent.score
        new = scoring.apply_delta(old, delta, secret_leak)
        self._emit("score_change", {
            "agent_id": agent_id, "edit_id": edit_id, "seq": seq, "feed_type": feed_type,
            "factor": factor, "delta": new - old, "old": old, "new": new, "reason": reason})
        before, after = scoring.tier_for(old), scoring.tier_for(new)
        if before != after:
            verb = "promoted to" if new > old else "dropped to"
            self._emit("tier_change", {
                "agent_id": agent_id, "edit_id": edit_id, "seq": seq, "old": before, "new": after,
                "score": new, "reason": f"{verb} {after} tier (score {new})"})

    def _activity(self, edit_id: str, feed_type: str, reason: str) -> None:
        edit = self.state.edits[edit_id]
        self._emit("activity", {
            "agent_id": edit.agent_id, "edit_id": edit_id, "seq": edit.seq, "feed_type": feed_type,
            "reason": reason, "delta": 0})

    def _gain(self, edit_id: str, factor: str, reason: str) -> None:
        edit = self.state.edits[edit_id]
        delta = scoring.clean_edit_points(factor, edit.added + edit.removed, len(edit.blast))
        self._score(edit.agent_id, edit.seq, edit_id, factor, delta, "edit_clean", reason)

    def _apply_verdict(self, finding: Finding, verdict: str, by: str) -> None:
        edit = self.state.edits[finding.edit_id]
        where = f"{finding.file}:{finding.line}"
        self._emit("verdict", {"finding_id": finding.id, "verdict": verdict, "by": by})
        if verdict == "confirmed":
            factor, delta = scoring.confirm_penalty(finding)
            leak = scoring.is_secret_leak(finding)
            reason = f"{edit.edit_id}: {finding.message} ({where}) confirmed"
            if leak:
                reason += ", reset to probation"
            self._score(edit.agent_id, edit.seq, edit.edit_id, factor, delta, "finding_confirmed", reason, leak)
        else:
            self._score(
                edit.agent_id, edit.seq, edit.edit_id, "finding_dismissed",
                scoring.POINTS["finding_dismissed"], "finding_dismissed",
                f"{edit.edit_id}: {finding.message} ({where}) dismissed as a false alarm")

    # -- analysis (no lock: may call a slow local model) ---------------------------

    def _analyze(self, edit: Edit) -> tuple[list[Finding], list[str], list[str]]:
        diff = line_diff(edit.before, edit.after)
        findings = run_patterns(edit, self.repo_root, diff)

        try:
            extra = [f for f in gemma_checks.review(edit, timeout_s=GEMMA_TIMEOUT_S) if isinstance(f, Finding)]
        except Exception as exc:  # noqa: BLE001 -- the contract says review never raises; belt and braces
            log.warning("gemma review failed: %s", exc)
            extra = []

        analysis = analyze_edit(edit, load_sources(self.repo_root), diff)
        unique = [
            f.model_copy(update={"evidence": redact(f.evidence)[:200]})
            for f in merge_findings([*findings, *extra, *analysis.findings])
        ]
        return unique, analysis.touched, analysis.blast

    def _decide(self, agent_id: str, findings: list[Finding]) -> tuple[str, str, str]:
        """(decision, by, reason)."""
        secrets = [f for f in findings if scoring.is_secret_leak(f)]
        if secrets:
            first = secrets[0]
            return "deny", "engine", f"{first.message} ({first.file}:{first.line})"
        tier = scoring.tier_for(self.state.agents[agent_id].score) if agent_id in self.state.agents else "probation"
        if tier == "probation":
            return "hold", "engine", "probation tier"
        if any(f.severity == "high" for f in findings):
            return "hold", "engine", "high-severity finding"
        if tier == "trusted" and self.rng.random() < SPOT_CHECK_RATE:
            return "hold", "engine", "trusted tier spot check"
        return "allow", "engine", f"{tier} tier, no high-severity findings"

    # -- public API -------------------------------------------------------------

    def submit_edit(self, edit: Edit) -> EditResult:
        edit = edit.model_copy(update={"file": normalize_path(edit.file)})
        findings, touched, blast = self._analyze(edit)
        agent_id, name = agent_identity(edit.agent, edit.model)
        diff = line_diff(edit.before, edit.after)
        after_lines = edit.after.splitlines()

        with self.lock:
            self._expire_holds()
            seq = self.state.next_edit_seq()
            edit_id = f"e_{seq:04d}"
            self._emit("edit_received", {
                "edit_id": edit_id, "seq": seq, "agent_id": agent_id, "name": name, "model": edit.model,
                "prompt": edit.prompt[:500], "file": edit.file, "content_hash": _hash(edit.after),
                "added": len(diff.added), "removed": len(diff.removed),
                "diff": redact(unified_hunks(edit.before, edit.after))[:MAX_DIFF_CHARS],
                "touched": touched, "blast": blast})

            stored: list[Finding] = []
            for finding in findings:
                finding = finding.model_copy(update={
                    "id": f"f_{self.state.next_finding_seq():04d}", "edit_id": edit_id, "status": "open"})
                line_text = after_lines[finding.line - 1] if 0 < finding.line <= len(after_lines) else ""
                self._emit("finding_created", {"finding": finding.model_dump(), "line_hash": _hash(line_text)})
                stored.append(finding)

            decision, by, reason = self._decide(agent_id, stored)
            self._emit("decision", {"edit_id": edit_id, "decision": decision, "by": by, "reason": reason})
            where = f"{edit.file} +{len(diff.added)} -{len(diff.removed)}"

            if decision == "deny":
                self._activity(edit_id, "edit_blocked", f"{edit_id} blocked: {reason}")
                for finding in stored:  # a known-format secret is certain: confirm it now
                    if scoring.is_secret_leak(finding):
                        self._apply_verdict(finding, "confirmed", by="engine")
            elif decision == "hold":
                self._activity(edit_id, "edit_held", f"{edit_id} held for review ({reason}): {where}")
            elif not stored:
                self._gain(edit_id, "clean_edit_allowed", f"{edit_id} clean edit allowed: {where}")
            else:
                self._activity(edit_id, "edit_clean",
                               f"{edit_id} allowed with {len(stored)} finding(s) to review: {where}")
            return EditResult(edit_id=edit_id, decision=decision, finding_ids=[f.id for f in stored])

    def get_edit_decision(self, edit_id: str) -> str:
        with self.lock:
            self._expire_holds()
            edit = self.state.edits.get(edit_id)
            if edit is None:
                raise NotFound(f"no edit {edit_id}")
            return edit.decision or "hold"

    def decide(self, edit_id: str, choice: str) -> str:
        with self.lock:
            self._expire_holds()
            edit = self.state.edits.get(edit_id)
            if edit is None:
                raise NotFound(f"no edit {edit_id}")
            if edit.decision != "hold":
                raise Conflict(f"{edit_id} is not waiting for a decision (it was {edit.decision})")
            if choice == "approve":
                self._emit("decision", {
                    "edit_id": edit_id, "decision": "allow", "by": "human", "reason": "approved by reviewer"})
                unresolved = [f for f in map(self.state.findings.get, edit.finding_ids)
                              if f and f.status in ("open", "confirmed")]
                where = f"{edit.file} +{edit.added} -{edit.removed}"
                if unresolved:
                    self._activity(edit_id, "edit_clean",
                                   f"{edit_id} approved with {len(unresolved)} unresolved finding(s): {where}")
                else:
                    self._gain(edit_id, "clean_edit_approved", f"{edit_id} clean edit approved: {where}")
                return "allow"
            self._emit("decision", {
                "edit_id": edit_id, "decision": "deny", "by": "human", "reason": "denied by reviewer"})
            self._activity(edit_id, "edit_blocked", f"{edit_id} denied by reviewer")
            return "deny"

    def verdict(self, finding_id: str, verdict: str) -> str:
        with self.lock:
            self._expire_holds()
            finding = self.state.findings.get(finding_id)
            if finding is None:
                raise NotFound(f"no finding {finding_id}")
            if finding.status != "open":
                raise Conflict(f"{finding_id} is already {finding.status}")
            status = "confirmed" if verdict == "confirm" else "dismissed"
            self._apply_verdict(finding, status, by="human")
            return status

    def _expire_holds(self) -> None:
        now = self.clock()
        for edit in self.state.pending_edits():
            if now - edit.held_t >= self.hold_timeout_s:
                self._emit("decision", {
                    "edit_id": edit.edit_id, "decision": "deny", "by": "timeout",
                    "reason": f"no answer in {self.hold_timeout_s:.0f}s"})
                self._activity(
                    edit.edit_id, "edit_blocked",
                    f"{edit.edit_id} timed out after {self.hold_timeout_s:.0f}s waiting for review; counted as denied")

    def expire_holds(self) -> None:
        with self.lock:
            self._expire_holds()

    def state_response(self) -> AgentsStateResponse:
        with self.lock:
            self._expire_holds()
            now = self.clock()
            findings = sorted(self.state.findings.values(), key=lambda f: f.id, reverse=True)
            return AgentsStateResponse(
                notice=None if self.state.agents else "No edits yet. Run demo/driver.py or connect the Claude Code hook.",
                updated_at=iso(now),
                agents=self.state.agent_states(),
                graph=self.state.graph(self._base_graph(), now),
                findings=findings[:MAX_FINDINGS_SHOWN],
                pending=self.state.pending(),
            )
