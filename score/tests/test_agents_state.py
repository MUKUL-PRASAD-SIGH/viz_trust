"""GET /agents/state must stay shape-identical to docs/api_stub.json.

The dashboard is being built against the stub. If the live endpoint drifts from it -- a key
renamed, a number turned into a string -- the dashboard breaks on the day it swaps in.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app as score_app
from app import AgentEvent, AgentsStateResponse, app

STUB_PATH = Path(__file__).resolve().parents[2] / "docs" / "api_stub.json"
STUB = json.loads(STUB_PATH.read_text())

client = TestClient(app)


def _published_from_stub() -> dict:
    """The raw snapshot the oracle would push to produce the stub's agents."""
    return {
        "chain_id": STUB["chain_id"],
        "block": STUB["block"],
        "agents": [
            {
                "address": agent["address"],
                "name": agent["name"],
                "score": agent["score"],
                "previous_score": agent["previous_score"],
                "top_factors": agent["top_factors"],
                "recent_events": agent["recent_events"],
            }
            for agent in STUB["agents"]
        ],
    }


@pytest.fixture(autouse=True)
def _empty_oracle_state():
    score_app.ORACLE_STATE.snapshot = None
    score_app.ORACLE_STATE.received_at = None
    score_app.ORACLE_STATE.received_monotonic = 0.0
    yield


def _kind(value) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, (int, float)):
        return "number"  # JSON has one number type; 500 and 500.0 are the same to a dashboard
    return type(value).__name__


def assert_same_shape(live, stub, path: str = "$") -> None:
    """Same keys at every level, same JSON type at every leaf. Null matches either side, since
    a nullable field (job_id, notice) is legitimately null in one and set in the other."""
    if live is None or stub is None:
        return
    assert _kind(live) == _kind(stub), f"{path}: live is {_kind(live)}, stub is {_kind(stub)}"

    if isinstance(stub, dict):
        assert set(live) == set(stub), (
            f"{path}: keys differ. only live: {sorted(set(live) - set(stub))}, "
            f"only stub: {sorted(set(stub) - set(live))}"
        )
        for key in stub:
            assert_same_shape(live[key], stub[key], f"{path}.{key}")
    elif isinstance(stub, list):
        if not live and not stub:
            return  # e.g. risk_flags: empty is the normal state on both sides
        assert live and stub, f"{path}: need a non-empty list on both sides to compare"
        for i, item in enumerate(live):
            assert_same_shape(item, stub[0], f"{path}[{i}]")
        for i, item in enumerate(stub):
            assert_same_shape(live[0], item, f"{path}[{i}] (stub)")


def test_stub_is_a_valid_response():
    AgentsStateResponse.model_validate(STUB)


def test_live_endpoint_has_the_stubs_shape():
    assert client.put("/internal/agents/state", json=_published_from_stub()).status_code == 204

    live = client.get("/agents/state").json()

    assert live["source"] == "oracle"
    assert_same_shape(live, STUB)


def test_live_endpoint_derives_the_stubs_numbers():
    """Band, collateral and deltas are computed server-side and must match the stub exactly."""
    client.put("/internal/agents/state", json=_published_from_stub())

    live = client.get("/agents/state").json()

    assert live["agents"] == STUB["agents"]


def test_sloppy_agent_crosses_two_tiers():
    client.put("/internal/agents/state", json=_published_from_stub())
    sloppy = next(a for a in client.get("/agents/state").json()["agents"] if a["name"] == "SloppyAgent")

    assert (sloppy["previous_band"], sloppy["band"]) == ("good", "poor")
    assert (sloppy["previous_required_collateral_pct"], sloppy["required_collateral_pct"]) == ("40%", "100%")
    assert sloppy["score_delta"] == -231


def test_before_the_oracle_reports_the_response_says_so():
    body = client.get("/agents/state").json()

    assert body["agents"] == []
    assert body["oracle_live"] is False
    assert "oracle" in body["notice"]
    AgentsStateResponse.model_validate(body)


def test_a_silent_oracle_is_flagged_stale():
    client.put("/internal/agents/state", json=_published_from_stub())
    score_app.ORACLE_STATE.received_monotonic -= score_app.ORACLE_STALE_SECONDS + 1

    body = client.get("/agents/state").json()

    assert body["oracle_live"] is False
    assert body["notice"]
    assert len(body["agents"]) == 3


def test_unknown_fields_from_the_oracle_are_rejected():
    snapshot = _published_from_stub()
    snapshot["agents"][0]["band"] = "excellent"  # derived here, never accepted from outside

    assert client.put("/internal/agents/state", json=snapshot).status_code == 422


def test_chain_mode_scores_current_profiles_without_events(tmp_path, monkeypatch):
    """AEGIS_STATE_CHAIN: one getProfile per agent, scored here. The seeded counters and ages
    (729 / 379 / 729 days) must land exactly where the oracle path lands them."""
    from datetime import datetime, timedelta, timezone

    now = datetime(2026, 9, 19, 12, tzinfo=timezone.utc)
    profiles = {  # address -> (score, completed, disputed, defaults, value in USDC units)
        "0x" + "1" * 40: (0, 20, 0, 0, 10_500_000_000),
        "0x" + "2" * 40: (0, 15, 1, 0, 7_850_000_000),
        "0x" + "3" * 40: (0, 22, 0, 0, 11_570_000_000),
    }
    ages = {"HonestAgent": 729, "SloppyAgent": 379, "Hirer": 729}
    addresses = dict(zip(ages, profiles))
    (tmp_path / "fake.json").write_text(json.dumps({
        "chainId": 84532, "rpcUrl": "http://rpc.invalid", "AegisRegistry": "0x" + "9" * 40,
        "accounts": {
            name: {"address": addresses[name],
                   "registeredAt": (now - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")}
            for name, days in ages.items()
        },
    }))

    def fake_rpc(url, method, params):
        if method == "eth_blockNumber":
            return "0x10"
        agent = "0x" + params[0]["data"][-40:]
        words = [0, *profiles[agent], 1]
        return "0x" + "".join(f"{w:064x}" for w in words)

    monkeypatch.setattr(score_app, "STATE_CHAIN", "fake")
    monkeypatch.setattr(score_app, "DEPLOYMENTS_DIR", tmp_path)
    monkeypatch.setattr(score_app, "_rpc", fake_rpc)

    state = score_app.chain_agents_state(as_of=now + timedelta(hours=1))
    assert state.source == "chain" and state.block == 16
    assert [(a.name, a.score, a.required_collateral_pct) for a in state.agents] == [
        ("HonestAgent", 864, "20%"), ("SloppyAgent", 613, "40%"), ("Hirer", 877, "20%")]
    # Scores are live; the activity is the recorded seed history only, never used for a score.
    assert all(a.score_delta == 0 for a in state.agents)
    assert [a.recent_events for a in state.agents] == [
        [AgentEvent(**e) for e in agent["recent_events"] if e["job_id"] is None] for agent in STUB["agents"]]
    assert all(e.job_id is None for a in state.agents for e in a.recent_events)
    assert "lost dispute" not in " ".join(e.reason for a in state.agents for e in a.recent_events)


# ---------------------------------------------------------------------------
# Risk flags: advisory, from escrow job facts only
# ---------------------------------------------------------------------------

HIRER, HONEST, SLOPPY = "0x" + "a" * 40, "0x" + "b" * 40, "0x" + "c" * 40


def _job(n, hirer, worker, disputed=False, minute=0):
    return score_app.JobRecord(job_id=n, hirer=hirer, worker=worker, value_usd=500.0,
                               created_at=f"2026-09-19T10:{minute:02d}:00Z", disputed=disputed, settled=True)


def _demo_jobs(parallel=False, swarm=False):
    jobs = [_job(1, HIRER, HONEST), _job(2, HIRER, SLOPPY, disputed=True, minute=1)]
    if parallel:
        jobs += [_job(3 + i, HIRER, HONEST, minute=2) for i in range(5)]
    if swarm:
        jobs += [_job(8 + i, "0x" + f"{i + 1:040x}", HONEST, minute=3) for i in range(5)]
    return jobs


@pytest.mark.parametrize("parallel,swarm", [(False, False), (True, False), (True, True)])
def test_no_flag_fires_on_the_demo(parallel, swarm):
    jobs = _demo_jobs(parallel, swarm)
    for agent in (HIRER, HONEST, SLOPPY):
        assert score_app.risk_flags(agent, jobs) == []


def test_dispute_burst_flags_a_griefed_worker():
    jobs = [_job(1, HIRER, HONEST)] + [_job(2 + i, "0x" + f"{i + 1:040x}", HONEST, disputed=True, minute=5) for i in range(3)]
    [flag] = score_app.risk_flags(HONEST, jobs)
    assert (flag.kind, flag.level) == ("dispute_burst", "alert")


def test_serial_disputer_flags_a_hirer_that_disputes_everything():
    jobs = [_job(i, HIRER, "0x" + f"{i:040x}", disputed=i % 2 == 0) for i in range(1, 7)]
    flags = {f.kind: f.level for f in score_app.risk_flags(HIRER, jobs)}
    assert flags == {"serial_disputer": "alert"}


def test_closed_ring_flags_agents_that_only_trade_with_each_other():
    ring = [HIRER, HONEST, SLOPPY]
    jobs = [_job(n, ring[n % 3], ring[(n + 1) % 3]) for n in range(9)]
    assert all([f.kind for f in score_app.risk_flags(a, jobs)] == ["closed_ring"] for a in ring)


def test_flags_never_change_the_score():
    snapshot = _published_from_stub()
    snapshot["jobs"] = [j.model_dump() for j in [_job(i, HIRER, "0x" + f"{i:040x}", disputed=True) for i in range(1, 7)]]
    assert client.put("/internal/agents/state", json=snapshot).status_code == 204
    live = client.get("/agents/state").json()
    assert [a["score"] for a in live["agents"]] == [a["score"] for a in STUB["agents"]]
