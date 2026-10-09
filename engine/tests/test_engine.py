from __future__ import annotations

import random

import pytest
from fastapi.testclient import TestClient

from engine.app import create_app
from engine.checks import gemma_checks
from engine.core import Conflict, Engine, NotFound
from engine.eventlog import EventLog
from engine.models import Edit, Finding
from engine.state import State
from engine.tests.conftest import REPO, clean_signup_edit, make_edit, promote, source

SLACK = 'TOKEN = "xo' 'xb-123456789012-abcdefghijklmnopqrstuvwx"'


def slack_edit() -> Edit:
    before = source("app/signup.py")
    return make_edit(before=before, after=before.replace("USERS = {}", f"USERS = {{}}\n{SLACK}\nimport slack_notify_pro"))


def agent(engine: Engine, agent_id="aider:gemma4:e4b"):
    return engine.state.agents[agent_id]


# -- decision flow --------------------------------------------------------------


def test_new_agent_is_held_on_probation(engine):
    result = engine.submit_edit(clean_signup_edit())
    assert result.decision == "hold"
    [pending] = engine.state_response().pending
    assert pending.reason == "probation tier" and pending.edit_id == result.edit_id
    assert agent(engine).score == 500


def test_approving_a_clean_edit_raises_the_score_with_a_reason(engine):
    result = engine.submit_edit(clean_signup_edit())
    assert engine.decide(result.edit_id, "approve") == "allow"
    assert agent(engine).score == 514
    event = engine.state_response().agents[0].recent_events[0]
    assert event.type == "edit_clean" and event.delta == 14 and "approved" in event.reason


def test_denying_a_held_edit_changes_no_score(engine):
    result = engine.submit_edit(clean_signup_edit())
    engine.decide(result.edit_id, "deny")
    assert agent(engine).score == 500 and engine.get_edit_decision(result.edit_id) == "deny"


def test_a_decided_edit_cannot_be_decided_again(engine):
    result = engine.submit_edit(clean_signup_edit())
    engine.decide(result.edit_id, "approve")
    with pytest.raises(Conflict):
        engine.decide(result.edit_id, "deny")
    with pytest.raises(NotFound):
        engine.decide("e_9999", "approve")


def test_clean_agent_reaches_standard_and_edits_then_go_straight_through(engine):
    promote(engine, 600)
    assert agent(engine).score >= 600
    result = engine.submit_edit(clean_signup_edit())
    assert result.decision == "allow"
    assert engine.state_response().agents[0].tier == "standard"


def test_standard_agent_is_held_on_a_high_finding(engine):
    promote(engine, 600)
    before = source("tests/test_signup.py")
    result = engine.submit_edit(make_edit("tests/test_signup.py", before=before, after=before.split("def test_profile_lookup")[0]))
    assert result.decision == "hold"
    assert any(f.message.startswith("Test deleted") for f in engine.state.findings.values())


def test_medium_finding_is_allowed_but_earns_nothing_for_a_standard_agent(engine):
    promote(engine, 600)
    score = agent(engine).score
    before = source("app/signup.py")
    result = engine.submit_edit(make_edit(before=before, after="import slack_notify_pro\n" + before))
    assert result.decision == "allow" and len(result.finding_ids) == 1
    assert agent(engine).score == score


def test_secret_edit_is_denied_in_any_tier_and_resets_to_probation(engine):
    promote(engine, 600)
    result = engine.submit_edit(slack_edit())
    assert result.decision == "deny" and len(result.finding_ids) == 2
    state = engine.state_response()
    assert state.agents[0].tier == "probation" and state.agents[0].score <= 550
    leak = next(f for f in state.findings if f.check == "hardcode_hunter")
    assert leak.status == "confirmed" and leak.line == 7 and "xoxb-" in leak.evidence
    assert "abcdefghijklmnopqrstuvwx" not in leak.evidence
    kinds = [e.type for e in state.agents[0].recent_events]
    assert "edit_blocked" in kinds and "finding_confirmed" in kinds and "tier_changed" in kinds


def test_secret_is_denied_even_for_a_trusted_agent(engine):
    promote(engine, 800)
    assert agent(engine).score >= 800
    assert engine.submit_edit(slack_edit()).decision == "deny"
    assert agent(engine).score <= 550


def test_secret_never_reaches_the_log_or_the_diff(engine):
    engine.submit_edit(slack_edit())
    dump = " ".join(str(e.data) for e in engine.log.all())
    assert "abcdefghijklmnopqrstuvwx" not in dump
    assert "xoxb-" in dump


def test_trusted_spot_check_holds_about_one_in_five(tmp_path, clock):
    eng = Engine(tmp_path / "t.db", REPO, clock=clock, rng=random.Random(7))
    promote(eng, 800)
    decisions = []
    for _ in range(100):
        result = eng.submit_edit(clean_signup_edit())
        decisions.append(result.decision)
        if result.decision == "hold":
            eng.decide(result.edit_id, "approve")
    held = decisions.count("hold")
    assert 8 <= held <= 35 and set(decisions) == {"allow", "hold"}


def test_trusted_agent_with_a_high_finding_is_held_not_spot_checked(engine):
    promote(engine, 800)
    before = source("tests/test_validators.py")
    result = engine.submit_edit(make_edit("tests/test_validators.py", before=before, after=before.split("def test_clean_name")[0]))
    assert result.decision == "hold"
    [pending] = engine.state_response().pending
    assert pending.reason == "high-severity finding"


def test_held_edit_times_out_as_denied(engine, clock):
    result = engine.submit_edit(clean_signup_edit())
    clock.advance(100)
    assert engine.get_edit_decision(result.edit_id) == "hold"
    clock.advance(30)
    assert engine.get_edit_decision(result.edit_id) == "deny"
    assert engine.state_response().pending == []
    assert "timed out" in engine.state_response().agents[0].recent_events[0].reason
    assert agent(engine).score == 500


# -- verdicts ---------------------------------------------------------------------


def test_confirming_a_finding_costs_points_and_dismissing_gains_two(engine):
    promote(engine, 600)
    before = source("app/signup.py")
    first = engine.submit_edit(make_edit(before=before, after="import slack_notify_pro\n" + before))
    second = engine.submit_edit(make_edit(before=before, after="import other_missing_pkg\n" + before))
    score = agent(engine).score
    engine.verdict(first.finding_ids[0], "confirm")
    assert agent(engine).score == score - 30
    engine.verdict(second.finding_ids[0], "dismiss")
    assert agent(engine).score == score - 30 + 2
    with pytest.raises(Conflict):
        engine.verdict(first.finding_ids[0], "dismiss")
    with pytest.raises(NotFound):
        engine.verdict("f_9999", "confirm")


def test_approving_with_an_unresolved_finding_earns_no_clean_gain(engine):
    before = source("app/signup.py")
    result = engine.submit_edit(make_edit(before=before, after="import slack_notify_pro\n" + before))
    engine.decide(result.edit_id, "approve")
    assert agent(engine).score == 500


def test_dismissed_findings_then_approval_counts_as_clean(engine):
    before = source("app/signup.py")
    result = engine.submit_edit(make_edit(before=before, after="import slack_notify_pro\n" + before))
    engine.verdict(result.finding_ids[0], "dismiss")
    engine.decide(result.edit_id, "approve")
    assert agent(engine).score > 502


def test_broken_caller_penalty(engine):
    before = source("app/signup.py")
    result = engine.submit_edit(make_edit(before=before, after=before.replace("def find_user(email):", "def find_user(email, tenant):")))
    [fid] = [f for f in result.finding_ids if engine.state.findings[f].check == "impact_analyst"]
    engine.verdict(fid, "confirm")
    assert agent(engine).score == 480


# -- gemma hook-in -----------------------------------------------------------------


def test_gemma_findings_are_merged_and_get_ids(engine, monkeypatch):
    def fake(edit, timeout_s=8.0):
        return [Finding(check="scope_guard", severity="low", source="gemma", file=edit.file, line=3, message="off topic")]
    monkeypatch.setattr(gemma_checks, "review", fake)
    result = engine.submit_edit(clean_signup_edit())
    gemma = [f for f in engine.state.findings.values() if f.source == "gemma"]
    assert len(gemma) == 1 and gemma[0].id in result.finding_ids and gemma[0].edit_id == result.edit_id


def test_a_crashing_gemma_check_does_not_break_the_engine(engine, monkeypatch):
    def boom(edit, timeout_s=8.0):
        raise RuntimeError("ollama is down")
    monkeypatch.setattr(gemma_checks, "review", boom)
    assert engine.submit_edit(clean_signup_edit()).decision == "hold"


# -- the log -----------------------------------------------------------------------


def test_state_is_rebuilt_identically_from_the_log(tmp_path, clock):
    path = tmp_path / "log.db"
    eng = Engine(path, REPO, clock=clock, rng=random.Random(3))
    promote(eng, 600)
    eng.submit_edit(slack_edit())
    pending = eng.submit_edit(clean_signup_edit())
    live = eng.state_response()

    reborn = Engine(path, REPO, clock=clock, rng=random.Random(3))
    # updated_at is the wall clock at read time, so it is the one field that may differ.
    assert {**reborn.state_response().model_dump(), "updated_at": None} == {**live.model_dump(), "updated_at": None}
    assert reborn.state_response().pending[0].edit_id == pending.edit_id


def test_replay_of_raw_events_matches_live_state(engine):
    promote(engine, 600)
    engine.submit_edit(slack_edit())
    replayed = State.from_events(engine.log.all())
    assert [a.model_dump() for a in replayed.agent_states()] == [a.model_dump() for a in engine.state.agent_states()]
    assert {k: v.status for k, v in replayed.findings.items()} == {k: v.status for k, v in engine.state.findings.items()}


def test_log_is_append_only(tmp_path):
    import sqlite3
    log = EventLog(tmp_path / "x.db")
    log.append("activity", {"a": 1}, 1.0)
    with pytest.raises(sqlite3.DatabaseError):
        log._db.execute("DELETE FROM events")
    with pytest.raises(sqlite3.DatabaseError):
        log._db.execute("UPDATE events SET kind='x'")


def test_log_stores_hashes_and_stats_not_whole_files(engine):
    engine.submit_edit(clean_signup_edit())
    received = next(e for e in engine.log.all() if e.kind == "edit_received").data
    assert len(received["content_hash"]) == 16 and received["added"] == 9
    assert source("app/signup.py") not in " ".join(str(e.data) for e in engine.log.all())


def test_reset_wipes_the_log(engine):
    engine.submit_edit(clean_signup_edit())
    engine.reset()
    assert engine.log.all() == [] and engine.state_response().agents == []


# -- graph in the response ------------------------------------------------------------


def test_state_carries_the_graph_and_last_edit(engine):
    result = engine.submit_edit(clean_signup_edit())
    graph = engine.state_response().graph
    assert graph.last_edit.edit_id == result.edit_id
    assert graph.last_edit.touched == ["app/signup.py::handle_signup"]
    assert "app/routes.py::signup_route" in graph.last_edit.blast
    assert len(graph.nodes) >= 15 and len(graph.edges) >= 10
    assert all(n.heat == 0 for n in graph.nodes)          # held, not landed yet


def test_heat_rises_when_an_edit_lands_and_falls_over_time(engine, clock):
    result = engine.submit_edit(clean_signup_edit())
    engine.decide(result.edit_id, "approve")
    node = lambda: next(n for n in engine.state_response().graph.nodes if n.id == "app/signup.py::handle_signup")
    hot = node()
    assert hot.heat > 0.4 and hot.last_agent == "aider:gemma4:e4b"
    clock.advance(600)
    assert node().heat < hot.heat / 2
    again = engine.submit_edit(clean_signup_edit())
    engine.decide(again.edit_id, "approve")
    assert node().heat > hot.heat / 2


# -- HTTP ------------------------------------------------------------------------------


@pytest.fixture
def client(engine):
    return TestClient(create_app(engine))


def body(edit: Edit) -> dict:
    return edit.model_dump()


def test_state_contract_shape(client):
    client.post("/edits", json=body(clean_signup_edit()))
    data = client.get("/agents/state").json()
    assert data["source"] == "engine" and data["oracle_live"] is True
    agent_json = data["agents"][0]
    for key in ("address", "name", "model", "tier", "score", "previous_score", "score_delta", "band",
                "required_collateral_pct", "top_factors", "recent_events", "risk_flags"):
        assert key in agent_json
    assert set(data) >= {"graph", "findings", "pending", "agents"}
    assert set(data["graph"]) == {"nodes", "edges", "last_edit"}
    assert set(data["pending"][0]) == {"edit_id", "agent", "file", "added", "removed", "diff", "reason", "blast_count", "finding_ids"}
    assert data["pending"][0]["diff"].startswith("@@")


def test_finding_shape(client):
    client.post("/edits", json=body(slack_edit()))
    finding = next(f for f in client.get("/agents/state").json()["findings"] if f["check"] == "hardcode_hunter")
    assert set(finding) == {
        "id", "edit_id", "check", "severity", "source", "file", "line", "message", "evidence", "status", "fix_prompt",
    }
    assert finding["source"] == "pattern" and finding["severity"] == "high"


def test_write_endpoints_round_trip(client):
    posted = client.post("/edits", json=body(clean_signup_edit())).json()
    assert posted["decision"] == "hold" and posted["edit_id"] == "e_0001"
    assert client.get("/edits/e_0001").json() == {"edit_id": "e_0001", "decision": "hold"}
    assert client.post("/decisions", json={"edit_id": "e_0001", "decision": "approve"}).json()["decision"] == "allow"
    assert client.get("/edits/e_0001").json()["decision"] == "allow"


def test_verdict_endpoint(client):
    client.post("/edits", json=body(slack_edit()))
    fid = next(f["id"] for f in client.get("/agents/state").json()["findings"] if f["check"] == "reality_check")
    assert client.post(f"/findings/{fid}/verdict", json={"verdict": "dismiss"}).json()["status"] == "dismissed"
    assert client.post(f"/findings/{fid}/verdict", json={"verdict": "confirm"}).status_code == 409


def test_errors(client):
    assert client.get("/edits/e_0404").status_code == 404
    assert client.post("/decisions", json={"edit_id": "e_0404", "decision": "approve"}).status_code == 404
    assert client.post("/edits", json={"agent": "a"}).status_code == 422


def test_health_and_cors(client):
    assert client.get("/health").json()["status"] == "ok"
    reply = client.get("/agents/state", headers={"Origin": "http://127.0.0.1:5173"})
    assert reply.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"


def test_engine_works_with_ollama_stopped(client):
    """No Gemma anywhere on this path: the stub returns [] and everything still decides."""
    assert client.post("/edits", json=body(slack_edit())).json()["decision"] == "deny"
