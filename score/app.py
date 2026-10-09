"""AEGIS score service.

Turns an agent's job history into a credit score, a risk band, and the collateral the
chain will demand from it. Every number in every response comes from the fitted logistic
regression in models/, which is trained entirely on synthetic data (generate_data.py).

Usage:
    python generate_data.py
    python train.py
    uvicorn app:app --reload
"""

from __future__ import annotations

import json
import os
import threading
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import joblib
import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ConfigDict, Field

MODELS_DIR = Path(__file__).parent / "models"
DEPLOYMENTS_DIR = Path(__file__).resolve().parent.parent / "deployments"
STUB_PATH = Path(__file__).resolve().parent.parent / "docs" / "api_stub.json"

MIN_SCORE, MAX_SCORE = 0, 1000

# ESTIMATE, not an observation. OutcomeRecorded carries no counterparty, so when events arrive
# without counterparty labels, diversity is estimated as this fraction of completed jobs. 0.6
# sits near the training data's own ratio (generate_data.py draws it from Beta(4, 3), mean
# 0.57). Pinning it at 1 instead froze the model's strongest experience signal and made a clean
# job worth ~+1 point, or less than zero on a larger job. Unrounded, so every clean job moves
# it by the same amount. Replace with real counts once
# OutcomeRecorded carries a counterparty (SPEC.md section 10).
DIVERSITY_PER_JOB_ESTIMATE = 0.6


# ---------------------------------------------------------------------------
# Collateral curve
# ---------------------------------------------------------------------------


def required_collateral_bps(score: int) -> int:
    """Collateral the agent must post upfront, in basis points of job value.

    Step function from SPEC.md section 3. 10000 bps = 100% prepaid.

        score >= 800  ->  2000
        score >= 600  ->  4000
        score >= 400  ->  7000
        otherwise     -> 10000

    WARNING: this table is duplicated on-chain in `contracts/src/AegisRegistry.sol`
    (`requiredCollateralBps`). If the two ever disagree, this service quotes a collateral
    requirement the chain will refuse to honour and the product is broken. Change both
    together, or neither. See SPEC.md section 3.
    """
    if score >= 800:
        return 2000
    if score >= 600:
        return 4000
    if score >= 400:
        return 7000
    return 10000


def score_band(score: int) -> str:
    """Human-readable band. Same breakpoints as the collateral curve, SPEC.md section 4."""
    if score >= 800:
        return "excellent"
    if score >= 600:
        return "good"
    if score >= 400:
        return "fair"
    return "poor"


# ---------------------------------------------------------------------------
# Model artifacts
# ---------------------------------------------------------------------------


class ScoringModel:
    """The fitted model plus everything needed to explain a prediction."""

    def __init__(self, model, scaler, feature_names: list[str], metrics: dict, calibration: dict):
        self.model = model
        self.scaler = scaler
        self.feature_names = feature_names
        self.metrics = metrics
        self.calibration = calibration
        self.coefficients = model.coef_[0]

    @classmethod
    def load(cls) -> "ScoringModel":
        model = joblib.load(MODELS_DIR / "model.joblib")
        scaler = joblib.load(MODELS_DIR / "scaler.joblib")
        feature_names = json.loads((MODELS_DIR / "feature_names.json").read_text())
        metrics = json.loads((MODELS_DIR / "metrics.json").read_text())
        calibration = json.loads((MODELS_DIR / "calibration.json").read_text())
        return cls(model, scaler, feature_names, metrics, calibration)


def _load_model() -> ScoringModel | None:
    try:
        return ScoringModel.load()
    except FileNotFoundError:
        return None


SCORING_MODEL = _load_model()


def _require_model() -> ScoringModel:
    if SCORING_MODEL is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "Model artifacts not found in models/. "
                "Run `python generate_data.py` then `python train.py`."
            ),
        )
    return SCORING_MODEL


# ---------------------------------------------------------------------------
# Explanations
# ---------------------------------------------------------------------------

EXPLANATIONS: dict[str, dict[str, str]] = {
    "jobs_completed": {
        "much_high": "Very long track record of completed jobs",
        "high": "More completed jobs than most peers",
        "mid": "Typical number of completed jobs",
        "low": "Fewer completed jobs than most peers",
        "much_low": "Thin track record, very few completed jobs",
    },
    "dispute_rate": {
        "much_high": "Dispute rate far above peers",
        "high": "High dispute rate relative to peers",
        "mid": "Dispute rate close to the peer average",
        "low": "Dispute rate below peers",
        "much_low": "Almost no disputes across its history",
    },
    "avg_job_value_usd": {
        "much_high": "Handles jobs far larger than peers",
        "high": "Handles larger jobs than most peers",
        "mid": "Typical job size",
        "low": "Handles smaller jobs than most peers",
        "much_low": "Handles very small jobs",
    },
    "account_age_days": {
        "much_high": "Long-established account",
        "high": "Account older than most peers",
        "mid": "Typical account age",
        "low": "Account younger than most peers",
        "much_low": "Very new account with little history",
    },
    "on_time_payment_rate": {
        "much_high": "Clean settlement almost without exception",
        "high": "Settles clean more often than peers",
        "mid": "Clean-settlement rate close to the peer average",
        "low": "Settles clean less often than peers",
        "much_low": "Rarely settles clean",
    },
    "prior_defaults": {
        "much_high": "Many prior defaults on record",
        "high": "More prior defaults than peers",
        "mid": "Prior defaults close to the peer average",
        "low": "Fewer prior defaults than peers",
        "much_low": "Clean of prior defaults",
    },
    "counterparty_diversity": {
        "much_high": "Trusted by a wide range of counterparties",
        "high": "Works with more counterparties than peers",
        "mid": "Typical counterparty spread",
        "low": "Concentrated in a few counterparties",
        "much_low": "Almost all work with a single counterparty",
    },
}


def _tier(z: float) -> str:
    """Where this agent sits versus the training population, in standard deviations."""
    if z >= 1.0:
        return "much_high"
    if z >= 0.35:
        return "high"
    if z <= -1.0:
        return "much_low"
    if z <= -0.35:
        return "low"
    return "mid"


def _explain(feature: str, value: float, z: float) -> str:
    # Zero reads better than "below peers" for the two count-like risk features.
    if feature == "dispute_rate" and value == 0:
        return "No disputes on record"
    if feature == "prior_defaults" and value == 0:
        return "No prior defaults on record"
    return EXPLANATIONS[feature][_tier(z)]


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class AgentFeatures(BaseModel):
    """The seven features the model consumes. Frozen in SPEC.md section 7."""

    jobs_completed: int = Field(..., ge=0, description="Jobs this agent has delivered.")
    dispute_rate: float = Field(..., ge=0.0, le=1.0, description="Fraction of jobs disputed.")
    avg_job_value_usd: float = Field(..., gt=0, description="Mean job value in USD.")
    account_age_days: int = Field(..., ge=0, description="Days since first activity.")
    on_time_payment_rate: float = Field(
        ..., ge=0.0, le=1.0, description="Clean-settlement proxy: delivered and never disputed, over all jobs. No timing data."
    )
    prior_defaults: int = Field(..., ge=0, description="Jobs this agent failed to deliver.")
    # A float because the oracle path supplies an ESTIMATE (jobs * 0.6, unrounded); real
    # counterparty counts are whole numbers and pass through unchanged. SPEC.md section 7.
    counterparty_diversity: float = Field(
        ..., ge=0, description="Distinct agents transacted with (estimated when unlabelled)."
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "jobs_completed": 34,
                "dispute_rate": 0.06,
                "avg_job_value_usd": 120.0,
                "account_age_days": 260,
                "on_time_payment_rate": 0.94,
                "prior_defaults": 0,
                "counterparty_diversity": 19,
            }
        }
    }


class Factor(BaseModel):
    feature: str
    value: float
    impact: int = Field(..., description="Signed points this feature moved the score.")
    explanation: str


class ScoreResponse(BaseModel):
    score: int = Field(..., ge=MIN_SCORE, le=MAX_SCORE)
    band: str
    required_collateral_bps: int
    default_probability: float
    top_factors: list[Factor]


class JobEvent(BaseModel):
    """One settled job, as the chain would report it."""

    delivered: bool
    disputed: bool = False
    value_usd: float = Field(..., gt=0)
    timestamp: datetime
    counterparty: str | None = Field(
        default=None,
        description="Optional. Supplied, it makes counterparty_diversity real rather than assumed.",
    )


class EventsRequest(BaseModel):
    events: list[JobEvent] = Field(..., min_length=1)
    as_of: datetime | None = Field(
        default=None, description="Defaults to now. Used to compute account age."
    )
    registered_at: datetime | None = Field(
        default=None,
        description="Optional. When the agent's history starts; account age is measured from it. "
        "Omitted, age runs from the earliest event.",
    )


class EventsScoreResponse(ScoreResponse):
    derived_features: AgentFeatures


# ---------------------------------------------------------------------------
# Dashboard state. docs/api_stub.json is a sample of AgentsStateResponse; a test keeps the two
# identical in shape. Every field is ready to render: the dashboard computes nothing.
# ---------------------------------------------------------------------------

EventType = Literal["job_completed", "dispute_won", "dispute_lost", "payment_default"]


class AgentEvent(BaseModel):
    """One rescore, newest first in `recent_events`."""

    model_config = ConfigDict(extra="forbid")

    type: EventType
    job_id: int | None = Field(
        ..., description="Escrow job id. Null for history that never went through the escrow."
    )
    value_usd: float = Field(..., description="Whole dollars, not 6-decimal USDC units.")
    reason: str = Field(..., description="The reason string written on-chain with the score.")
    delta: int = Field(..., description="Signed points this event moved the score.")
    timestamp: str = Field(..., description="Chain time of the outcome, ISO 8601 UTC.")


class PublishedAgent(BaseModel):
    """What the oracle knows about one agent. Pushed, never read from the chain here."""

    model_config = ConfigDict(extra="forbid")

    address: str
    name: str
    score: int = Field(..., ge=MIN_SCORE, le=MAX_SCORE)
    previous_score: int = Field(..., ge=MIN_SCORE, le=MAX_SCORE)
    top_factors: list[Factor]
    recent_events: list[AgentEvent]


class JobRecord(BaseModel):
    """One escrow job as its events report it. Raw facts only; risk flags are derived here."""

    model_config = ConfigDict(extra="forbid")

    job_id: int
    hirer: str
    worker: str
    value_usd: float
    created_at: str = Field(..., description="Chain time of JobCreated, ISO 8601 UTC.")
    disputed: bool = False
    settled: bool = False


class OracleSnapshot(BaseModel):
    """Body of PUT /internal/agents/state, sent by oracle/watcher.py."""

    model_config = ConfigDict(extra="forbid")

    chain_id: int
    block: int
    agents: list[PublishedAgent]
    jobs: list[JobRecord] = Field(default_factory=list, description="Escrow jobs, for risk flags only.")


class RiskFlag(BaseModel):
    """ADVISORY. Shown beside the score; never changes the score or the collateral."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["dispute_burst", "serial_disputer", "closed_ring"]
    level: Literal["watch", "alert"]
    label: str
    reason: str


class AgentState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    address: str
    name: str
    score: int
    previous_score: int = Field(..., description="Score before the latest event; animate from here.")
    score_delta: int
    band: str
    previous_band: str
    required_collateral_bps: int
    required_collateral_pct: str = Field(..., description='Ready to render, e.g. "20%".')
    previous_required_collateral_bps: int
    previous_required_collateral_pct: str
    top_factors: list[Factor]
    recent_events: list[AgentEvent]
    risk_flags: list[RiskFlag] = Field(
        ..., description="Advisory signals. Empty means none. Never affect score or collateral."
    )


class AgentsStateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: Literal["oracle", "stub", "chain"]
    notice: str | None = Field(..., description="Human-readable warning to show, or null.")
    oracle_live: bool = Field(..., description="False if the oracle has stopped reporting.")
    updated_at: str | None = Field(..., description="Wall-clock time of the oracle's last report.")
    chain_id: int | None
    block: int | None
    agents: list[AgentState]


class HealthResponse(BaseModel):
    status: str
    model_loaded: bool
    test_roc_auc: float | None = None
    features: list[str] | None = None


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + np.exp(-x))


def _logit_to_points(logit: float, calibration: dict) -> float:
    """Map log-odds of default to the score scale, before clamping. SPEC.md section 7.

    Linear in log-odds so a feature's effect in points stays constant instead of saturating
    at the extremes. The raw probability is deliberately not used: at a ~15% base default
    rate it pushes most agents into the top band and the collateral tiers stop discriminating.
    """
    return calibration["anchor_score"] - calibration["factor"] * (
        logit - calibration["median_logit"]
    )


def _clamp_score(points: float) -> int:
    return max(MIN_SCORE, min(MAX_SCORE, int(round(points))))


def score_agent(features: AgentFeatures, scoring_model: ScoringModel) -> ScoreResponse:
    names = scoring_model.feature_names
    values = [float(getattr(features, name)) for name in names]
    # A DataFrame rather than a bare array so the scaler sees the feature names it was fit on.
    raw = pd.DataFrame([values], columns=names)

    standardized = scoring_model.scaler.transform(raw)[0]

    # For binary logistic regression this is exactly intercept + coefficients . standardized,
    # so the per-feature contributions below sum back to it.
    logit = float(scoring_model.model.decision_function(standardized.reshape(1, -1))[0])

    probability = float(_sigmoid(logit))
    points = _logit_to_points(logit, scoring_model.calibration)
    score = _clamp_score(points)

    contributions = scoring_model.coefficients * standardized

    # Rank by contribution size in logit space, then report each effect in score points as a
    # counterfactual: what this agent would have scored with that one feature at the peer
    # average. Because the mapping is linear in log-odds, this is stable at both extremes.
    ranked = np.argsort(-np.abs(contributions))[:3]

    top_factors: list[Factor] = []
    for index in ranked:
        counterfactual = _logit_to_points(logit - contributions[index], scoring_model.calibration)
        top_factors.append(
            Factor(
                feature=names[index],
                value=values[index],
                impact=int(round(points - counterfactual)),
                explanation=_explain(names[index], values[index], float(standardized[index])),
            )
        )

    return ScoreResponse(
        score=score,
        band=score_band(score),
        required_collateral_bps=required_collateral_bps(score),
        default_probability=round(probability, 4),
        top_factors=top_factors,
    )


def estimate_counterparty_diversity(jobs_completed: int) -> float:
    """ESTIMATE used only when no event carries a counterparty. See DIVERSITY_PER_JOB_ESTIMATE.

    Deliberately not rounded. Rounding made the estimate step up on only some jobs (21 -> 13,
    22 -> 13, 23 -> 14), so consecutive clean jobs alternated between about +11 and +1 points.
    """
    return max(1.0, jobs_completed * DIVERSITY_PER_JOB_ESTIMATE)


def derive_features(request: EventsRequest) -> AgentFeatures:
    """Collapse a job history into the seven model features.

    An agent with no events is unknown by definition, and the chain already charges such an
    address 100% collateral, so at least one event is required rather than invented.
    """
    events = request.events
    total = len(events)

    as_of = request.as_of or datetime.now(timezone.utc)
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=timezone.utc)

    timestamps = [
        event.timestamp if event.timestamp.tzinfo else event.timestamp.replace(tzinfo=timezone.utc)
        for event in events
    ]

    started = min(timestamps)
    if request.registered_at is not None:
        started = request.registered_at
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)

    delivered_count = sum(1 for event in events if event.delivered)
    disputed_count = sum(1 for event in events if event.disputed)

    # Proxy: the chain reports delivery and disputes, not payment timing. A job that was
    # delivered and never disputed is the closest on-chain evidence of a clean settlement.
    clean_count = sum(1 for event in events if event.delivered and not event.disputed)

    counterparties = {event.counterparty for event in events if event.counterparty}

    return AgentFeatures(
        jobs_completed=delivered_count,
        dispute_rate=disputed_count / total,
        avg_job_value_usd=sum(event.value_usd for event in events) / total,
        account_age_days=max(0, (as_of - started).days),
        on_time_payment_rate=clean_count / total,
        prior_defaults=total - delivered_count,
        counterparty_diversity=(
            len(counterparties)
            if counterparties
            else estimate_counterparty_diversity(delivered_count)
        ),
    )


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

def collateral_pct(bps: int) -> str:
    return f"{bps / 100:g}%"


# The oracle heartbeats every few seconds; silence longer than this means it has stopped.
ORACLE_STALE_SECONDS = 10.0


class _OracleState:
    """Latest snapshot from the oracle. In memory only; the oracle re-sends it on a heartbeat,
    so a restarted score service is repopulated within seconds."""

    snapshot: OracleSnapshot | None = None
    received_at: datetime | None = None
    received_monotonic: float = 0.0


ORACLE_STATE = _OracleState()


# ---------------------------------------------------------------------------
# Risk flags. ADVISORY and read-only: computed from escrow job facts the oracle forwards, shown
# beside the score, and never fed into the score, the features or the collateral.
# Counterparties exist only for escrow jobs (JobCreated names hirer and worker). Seeded history
# was recorded straight to the Registry and has none, so it is invisible here.
# ---------------------------------------------------------------------------

BURST_WINDOW_SECONDS = 3600
SERIAL_MIN_HIRES = 5
SERIAL_WATCH_MULTIPLE, SERIAL_ALERT_MULTIPLE = 3.0, 5.0
RING_MIN_JOBS, RING_MIN_SIZE, RING_INSIDE_SHARE = 3, 3, 0.8


def population_dispute_rate() -> float:
    """Mean dispute rate of the model's training population (the scaler's fitted mean)."""
    if SCORING_MODEL is None:
        return 0.07
    return float(SCORING_MODEL.scaler.mean_[SCORING_MODEL.feature_names.index("dispute_rate")])


def _when(job: JobRecord) -> datetime:
    return datetime.fromisoformat(job.created_at.replace("Z", "+00:00"))


def dispute_burst(agent: str, jobs: list[JobRecord]) -> RiskFlag | None:
    """Many disputes against one worker in a short window, relative to its own earlier record."""
    mine = [j for j in jobs if j.worker.lower() == agent.lower()]
    if not mine:
        return None
    latest = max(_when(j) for j in jobs)
    recent = [j for j in mine if (latest - _when(j)).total_seconds() <= BURST_WINDOW_SECONDS]
    earlier = [j for j in mine if j not in recent]
    disputes = sum(j.disputed for j in recent)
    if disputes < 2 or disputes / len(recent) < 0.5:
        return None
    earlier_rate = sum(j.disputed for j in earlier) / len(earlier) if earlier else 0.0
    if disputes / len(recent) < 2 * earlier_rate + 0.25:
        return None  # consistently disputed, not a burst: the score already carries it
    level = "alert" if disputes >= 3 else "watch"
    return RiskFlag(
        kind="dispute_burst", level=level, label="Dispute burst",
        reason=f"{disputes} of its last {len(recent)} jobs disputed within an hour, against "
               f"{earlier_rate:.0%} before. Possible griefing by hirers; worth a look before trusting the drop.",
    )


def serial_disputer(agent: str, jobs: list[JobRecord]) -> RiskFlag | None:
    """A hirer whose dispute rate is far above the population's."""
    hires = [j for j in jobs if j.hirer.lower() == agent.lower() and (j.disputed or j.settled)]
    if len(hires) < SERIAL_MIN_HIRES:
        return None
    rate, population = sum(j.disputed for j in hires) / len(hires), population_dispute_rate()
    if rate < SERIAL_WATCH_MULTIPLE * population:
        return None
    level = "alert" if rate >= SERIAL_ALERT_MULTIPLE * population else "watch"
    return RiskFlag(
        kind="serial_disputer", level=level, label="Serial disputer",
        reason=f"Disputed {rate:.0%} of its {len(hires)} hires, against a {population:.0%} "
               f"population average. Disputes cost a hirer nothing, so this one may be avoiding payment.",
    )


def closed_rings(jobs: list[JobRecord]) -> list[set[str]]:
    """Groups of RING_MIN_SIZE+ agents that each do RING_INSIDE_SHARE of their escrow jobs with
    one another. Peel off agents that trade mostly outside the group until it is stable."""
    partners: dict[str, list[str]] = {}
    for j in jobs:
        h, w = j.hirer.lower(), j.worker.lower()
        partners.setdefault(h, []).append(w)
        partners.setdefault(w, []).append(h)
    group = {a for a, p in partners.items() if len(p) >= RING_MIN_JOBS}
    while True:
        keep = {a for a in group if sum(p in group for p in partners[a]) / len(partners[a]) >= RING_INSIDE_SHARE}
        if keep == group:
            break
        group = keep
    rings, seen = [], set()
    for start in group:
        if start in seen:
            continue
        component, stack = set(), [start]
        while stack:
            node = stack.pop()
            if node in component:
                continue
            component.add(node)
            stack.extend(p for p in partners[node] if p in group)
        seen |= component
        if len(component) >= RING_MIN_SIZE:
            rings.append(component)
    return rings


def risk_flags(agent: str, jobs: list[JobRecord]) -> list[RiskFlag]:
    flags = [f for f in (dispute_burst(agent, jobs), serial_disputer(agent, jobs)) if f]
    for ring in closed_rings(jobs):
        if agent.lower() in ring:
            flags.append(RiskFlag(
                kind="closed_ring", level="watch", label="Closed ring",
                reason=f"Does most of its work inside a group of {len(ring)} agents that mostly "
                       "transact with each other. Scores built this way may be self-dealt.",
            ))
    return flags


def agent_state(agent: PublishedAgent, jobs: list[JobRecord] | None = None) -> AgentState:
    bps = required_collateral_bps(agent.score)
    previous_bps = required_collateral_bps(agent.previous_score)
    return AgentState(
        address=agent.address,
        name=agent.name,
        score=agent.score,
        previous_score=agent.previous_score,
        score_delta=agent.score - agent.previous_score,
        band=score_band(agent.score),
        previous_band=score_band(agent.previous_score),
        required_collateral_bps=bps,
        required_collateral_pct=collateral_pct(bps),
        previous_required_collateral_bps=previous_bps,
        previous_required_collateral_pct=collateral_pct(previous_bps),
        top_factors=agent.top_factors,
        recent_events=agent.recent_events,
        risk_flags=risk_flags(agent.address, jobs or []),
    )


def agents_state() -> AgentsStateResponse:
    snapshot = ORACLE_STATE.snapshot
    if snapshot is None:
        return AgentsStateResponse(
            source="oracle",
            notice="No data from the oracle yet. Is oracle/watcher.py running?",
            oracle_live=False,
            updated_at=None,
            chain_id=None,
            block=None,
            agents=[],
        )

    silent_for = time.monotonic() - ORACLE_STATE.received_monotonic
    live = silent_for <= ORACLE_STALE_SECONDS
    return AgentsStateResponse(
        source="oracle",
        notice=None if live else (
            f"The oracle has not reported for {silent_for:.0f}s. Showing the last known state."
        ),
        oracle_live=live,
        updated_at=ORACLE_STATE.received_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        chain_id=snapshot.chain_id,
        block=snapshot.block,
        agents=[agent_state(agent, snapshot.jobs) for agent in snapshot.agents],
    )


# ---------------------------------------------------------------------------
# Chain-read state. Set AEGIS_STATE_CHAIN to a deployments/<name>.json (e.g. "base-sepolia") and
# /agents/state reads the current profiles from that chain's Registry -- one getProfile per
# agent, no event replay, no get_logs -- and scores them here. Unset, the oracle push is used.
# ---------------------------------------------------------------------------

STATE_CHAIN = os.environ.get("AEGIS_STATE_CHAIN") or None
CHAIN_CACHE_SECONDS = 5.0
GET_PROFILE_SELECTOR = "0x0f53a470"  # getProfile(address)
USDC_UNITS = 10**6  # SPEC.md section 5


def _rpc(url: str, method: str, params: list):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    # Public RPCs (sepolia.base.org) answer urllib's default User-Agent with 403.
    headers = {"Content-Type": "application/json", "User-Agent": "aegis-score-service"}
    request = urllib.request.Request(url, data=body, headers=headers)
    with urllib.request.urlopen(request, timeout=10) as reply:
        payload = json.loads(reply.read())
    if "error" in payload:
        raise RuntimeError(payload["error"])
    return payload["result"]


def read_profile(url: str, registry: str, agent: str) -> dict:
    """AgentProfile is all static fields, so the return data is seven 32-byte words in order."""
    data = GET_PROFILE_SELECTOR + agent.lower().removeprefix("0x").rjust(64, "0")
    words = _rpc(url, "eth_call", [{"to": registry, "data": data}, "latest"]).removeprefix("0x")
    w = [int(words[i * 64:(i + 1) * 64], 16) for i in range(7)]
    return {"score": w[1], "completed": w[2], "disputed": w[3], "defaults": w[4], "value": w[5], "exists": bool(w[6])}


def profile_events(profile: dict, as_of: datetime) -> list[JobEvent]:
    """An event list equivalent to the profile's counters. Only counts and the average value
    reach the features, so this scores the same as the full history would.

    Counters do not say whether a disputed job was won or lost; disputes are attributed to
    defaults first. Exact for what AegisEscrow records (a dispute is always a default) and for
    the seed (its one disputed job was delivered, with no defaults).
    """
    total = profile["completed"] + profile["defaults"]
    lost = min(profile["disputed"], profile["defaults"])
    won = profile["disputed"] - lost
    value = max(profile["value"] / USDC_UNITS / total, 1 / USDC_UNITS)
    kinds = ([(True, False)] * (profile["completed"] - won) + [(True, True)] * won
             + [(False, True)] * lost + [(False, False)] * (profile["defaults"] - lost))
    return [JobEvent(delivered=d, disputed=x, value_usd=value, timestamp=as_of) for d, x in kinds]


def chain_agents_state(as_of: datetime | None = None) -> AgentsStateResponse:
    deployment = json.loads((DEPLOYMENTS_DIR / f"{STATE_CHAIN}.json").read_text())
    url, registry = deployment["rpcUrl"], deployment["AegisRegistry"]
    as_of = as_of or datetime.now(timezone.utc)
    scoring_model = _require_model()
    # History is not replayed from this chain. The activity shown is the SEEDED history recorded
    # from a local run (docs/api_stub.json), labelled so on the dashboard. Live-demo jobs (those
    # with a job id) are dropped: this chain holds the seed only, so every row agrees with the
    # card above it. Scores are never taken from it.
    recorded = {
        agent["name"]: [event for event in agent["recent_events"] if event["job_id"] is None]
        for agent in json.loads(STUB_PATH.read_text())["agents"]
    }

    agents = []
    for name, entry in deployment.get("accounts", {}).items():
        profile = read_profile(url, registry, entry["address"])
        if not profile["exists"] or profile["completed"] + profile["defaults"] == 0:
            continue
        request = EventsRequest(
            events=profile_events(profile, as_of), as_of=as_of, registered_at=entry.get("registeredAt"))
        result = score_agent(derive_features(request), scoring_model)
        # No event replay, so no score movement to show: previous = current.
        agents.append(PublishedAgent(
            address=entry["address"], name=name, score=result.score, previous_score=result.score,
            top_factors=result.top_factors, recent_events=recorded.get(name, [])))

    return AgentsStateResponse(
        source="chain",
        notice=None,
        oracle_live=True,
        updated_at=as_of.strftime("%Y-%m-%dT%H:%M:%SZ"),
        chain_id=deployment["chainId"],
        block=int(_rpc(url, "eth_blockNumber", []), 16),
        agents=[agent_state(agent) for agent in agents],
    )


class _ChainCache:
    response: AgentsStateResponse | None = None
    fetched: float = float("-inf")
    lock = threading.Lock()


CHAIN_CACHE = _ChainCache()


def cached_chain_state() -> AgentsStateResponse:
    """At most one chain read per CHAIN_CACHE_SECONDS, failures included, so polling dashboards
    never hammer the RPC. A failed read keeps serving the last good state, flagged."""
    with CHAIN_CACHE.lock:
        if time.monotonic() - CHAIN_CACHE.fetched < CHAIN_CACHE_SECONDS and CHAIN_CACHE.response:
            return CHAIN_CACHE.response
        CHAIN_CACHE.fetched = time.monotonic()
        try:
            CHAIN_CACHE.response = chain_agents_state()
        except Exception as exc:  # noqa: BLE001 -- any RPC failure degrades, never 500s
            notice = f"Could not read {STATE_CHAIN}: {exc}"
            if CHAIN_CACHE.response is None:
                CHAIN_CACHE.response = AgentsStateResponse(
                    source="chain", notice=notice, oracle_live=False, updated_at=None,
                    chain_id=None, block=None, agents=[])
            else:
                CHAIN_CACHE.response = CHAIN_CACHE.response.model_copy(
                    update={"notice": notice + ". Showing the last good read.", "oracle_live": False})
        return CHAIN_CACHE.response


app = FastAPI(
    title="AEGIS score service",
    description=(
        "Credit scoring for the AI agent economy. Converts an agent's job history into a "
        "score, a band, and the collateral the chain will require from it."
    ),
    version="0.1.0",
)


# The dashboard is a browser app on another port and polls GET /agents/state.
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=["*"])


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    if SCORING_MODEL is None:
        return HealthResponse(status="degraded", model_loaded=False)
    return HealthResponse(
        status="ok",
        model_loaded=True,
        test_roc_auc=SCORING_MODEL.metrics.get("test_roc_auc"),
        features=SCORING_MODEL.feature_names,
    )


@app.post("/score", response_model=ScoreResponse)
def score(features: AgentFeatures) -> ScoreResponse:
    """Score an agent from its seven features."""
    return score_agent(features, _require_model())


@app.post("/score/from-events", response_model=EventsScoreResponse)
def score_from_events(request: EventsRequest) -> EventsScoreResponse:
    """Derive the features from raw job events, then score.

    Lets live chain events be fed straight in without the caller computing features itself.
    """
    scoring_model = _require_model()
    features = derive_features(request)
    result = score_agent(features, scoring_model)
    return EventsScoreResponse(**result.model_dump(), derived_features=features)


@app.get("/agents/state", response_model=AgentsStateResponse)
def get_agents_state() -> AgentsStateResponse:
    """Everything the dashboard renders, for every agent the oracle knows about.

    Served from the oracle's last pushed snapshot, or, with AEGIS_STATE_CHAIN set, from that
    chain's Registry directly. Poll it every 1-2s; the shape is fixed by docs/api_stub.json.
    """
    if STATE_CHAIN:
        return cached_chain_state()
    return agents_state()


@app.put("/internal/agents/state", status_code=204)
def put_agents_state(snapshot: OracleSnapshot) -> None:
    """Called by oracle/watcher.py after every rescore and on a heartbeat. Not for the dashboard."""
    ORACLE_STATE.snapshot = snapshot
    ORACLE_STATE.received_at = datetime.now(timezone.utc)
    ORACLE_STATE.received_monotonic = time.monotonic()
