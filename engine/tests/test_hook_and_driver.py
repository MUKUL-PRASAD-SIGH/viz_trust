"""The Claude Code hook and the demo driver, against a real engine served over HTTP."""

from __future__ import annotations

import io
import json
import socket
import sys
import threading
import time
from pathlib import Path

import pytest
import uvicorn

from demo import edits as script
from engine.app import create_app
from engine.checks.patterns import run_patterns
from engine.hook import claude_code_hook as hook
from engine.models import Edit
from engine.tests.conftest import REPO

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def server(engine):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    config = uvicorn.Config(create_app(engine), host="127.0.0.1", port=port, log_level="warning")
    instance = uvicorn.Server(config)
    thread = threading.Thread(target=instance.run, daemon=True)
    thread.start()
    for _ in range(100):
        if instance.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}", engine
    instance.should_exit = True
    thread.join(timeout=5)


# -- the scripted edits ------------------------------------------------------------


def test_every_scripted_clean_edit_is_valid_python_and_trips_no_check():
    import ast
    for edit in script.clean_edits():
        ast.parse(edit.after)
        found = run_patterns(Edit(agent="a", file=edit.file, before=edit.before, after=edit.after, prompt=edit.prompt), REPO)
        assert found == [], (edit.prompt, found)


def test_scripted_slack_edit_has_both_findings():
    edit = script.slack_edit()
    found = run_patterns(Edit(agent="a", file=edit.file, before=edit.before, after=edit.after), REPO)
    assert {(f.check, f.severity) for f in found} == {("hardcode_hunter", "high"), ("reality_check", "medium")}


def test_sample_repo_is_never_modified_by_the_script():
    before = {p: p.read_text() for p in REPO.rglob("*.py")}
    script.clean_edits(), script.slack_edit()
    assert before == {p: p.read_text() for p in REPO.rglob("*.py")}


# -- the driver, end to end ---------------------------------------------------------


def test_driver_runs_the_four_beats(server, capsys):
    url, engine = server
    sys.path.insert(0, str(ROOT / "demo"))
    import driver

    assert driver.main(["run", "--fast", "--pace", "0", "--url", url]) == 0
    out = capsys.readouterr().out
    for beat in ("Beat 1", "Beat 2", "Beat 3", "Beat 4"):
        assert beat in out
    assert "promoted" in out and "DENY" in out and "no click needed" in out
    agent = engine.state_response().agents[0]
    assert agent.tier == "probation" and agent.score <= 550
    kinds = {e.type for e in agent.recent_events}
    assert {"tier_changed", "finding_confirmed", "edit_blocked"} <= kinds

    # A second run refuses to pile onto existing state; reset makes it runnable again.
    assert driver.main(["run", "--fast", "--pace", "0", "--url", url]) == 1
    assert driver.main(["reset", "--url", url]) == 0
    assert engine.state_response().agents == []


def test_driver_reports_a_dead_engine(capsys):
    sys.path.insert(0, str(ROOT / "demo"))
    import driver
    assert driver.main(["run", "--url", "http://127.0.0.1:1"]) == 1
    assert "Cannot reach the engine" in capsys.readouterr().out


# -- the hook -------------------------------------------------------------------------


def run_hook(monkeypatch, capsys, payload, url, tmp_cwd=None):
    monkeypatch.setenv("VIZ_TRUST_URL", url)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload)))
    code = hook.main()
    return code, capsys.readouterr().out


def edit_payload(tmp_path, old, new, content=None):
    target = tmp_path / "app" / "signup.py"
    target.parent.mkdir(exist_ok=True)
    target.write_text("USERS = {}\n\ndef f():\n    return 1\n")
    if content is not None:
        return {"cwd": str(tmp_path), "tool_name": "Write", "tool_input": {"file_path": str(target), "content": content}}
    return {"cwd": str(tmp_path), "tool_name": "Edit",
            "tool_input": {"file_path": str(target), "old_string": old, "new_string": new}}


def test_hook_denies_a_secret_with_the_deny_decision(server, monkeypatch, capsys, tmp_path):
    url, _ = server
    token = "xo" + "xb-123456789012-abcdefghijklmnopqrstuvwx"
    code, out = run_hook(monkeypatch, capsys, edit_payload(tmp_path, "USERS = {}", f'USERS = {{}}\nT = "{token}"'), url)
    assert code == 0
    reply = json.loads(out)["hookSpecificOutput"]
    assert reply["permissionDecision"] == "deny" and reply["hookEventName"] == "PreToolUse"


def test_hook_waits_on_a_held_edit_and_allows_after_approval(server, monkeypatch, capsys, tmp_path):
    url, engine = server
    monkeypatch.setattr(hook, "POLL_S", 0.05)

    def approve_when_held():
        for _ in range(200):
            pending = engine.state_response().pending
            if pending:
                engine.decide(pending[0].edit_id, "approve")
                return
            time.sleep(0.05)

    threading.Thread(target=approve_when_held, daemon=True).start()
    code, out = run_hook(monkeypatch, capsys, edit_payload(tmp_path, "return 1", "return 2"), url)
    assert code == 0 and out == ""          # approved: silent, Claude Code carries on
    assert engine.state.agents["claude-code:claude"].score > 500


def test_hook_denies_when_the_reviewer_denies(server, monkeypatch, capsys, tmp_path):
    url, engine = server
    monkeypatch.setattr(hook, "POLL_S", 0.05)

    def deny_when_held():
        for _ in range(200):
            pending = engine.state_response().pending
            if pending:
                engine.decide(pending[0].edit_id, "deny")
                return
            time.sleep(0.05)

    threading.Thread(target=deny_when_held, daemon=True).start()
    _, out = run_hook(monkeypatch, capsys, edit_payload(tmp_path, "return 1", "return 2"), url)
    assert json.loads(out)["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_dead_engine_means_allow_and_never_hangs(monkeypatch, capsys, tmp_path):
    started = time.monotonic()
    code, out = run_hook(monkeypatch, capsys, edit_payload(tmp_path, "return 1", "return 2"), "http://127.0.0.1:1")
    assert (code, out) == (0, "") and time.monotonic() - started < 5


@pytest.mark.parametrize("payload", [
    {"tool_name": "Bash", "tool_input": {"command": "ls"}},
    {"tool_name": "Read", "tool_input": {"file_path": "x"}},
    {"tool_name": "Edit", "tool_input": {}},
])
def test_other_tools_are_ignored(monkeypatch, capsys, payload):
    assert run_hook(monkeypatch, capsys, payload, "http://127.0.0.1:1") == (0, "")


def test_garbage_on_stdin_is_ignored(monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", io.StringIO("not json"))
    assert hook.main() == 0 and capsys.readouterr().out == ""


def test_edit_payloads_become_before_and_after(tmp_path):
    payload = edit_payload(tmp_path, "return 1", "return 2")
    request = hook.build_request(payload)
    assert request["file"] == "app/signup.py" and "return 2" in request["after"] and "return 1" in request["before"]

    multi = {"cwd": str(tmp_path), "tool_name": "MultiEdit", "tool_input": {
        "file_path": str(tmp_path / "app" / "signup.py"),
        "edits": [{"old_string": "return 1", "new_string": "return 5"}, {"old_string": "USERS", "new_string": "ALL"}]}}
    assert "return 5" in hook.build_request(multi)["after"] and "ALL = {}" in hook.build_request(multi)["after"]

    missing = edit_payload(tmp_path, "text that is not there", "x")
    assert hook.build_request(missing) is None


def test_prompt_comes_from_the_transcript(tmp_path):
    transcript = tmp_path / "t.jsonl"
    transcript.write_text("\n".join(json.dumps(e) for e in [
        {"type": "user", "message": {"role": "user", "content": "first ask"}},
        {"type": "assistant", "message": {"role": "assistant", "content": "ok"}},
        {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": "rename the helper"}]}},
    ]))
    assert hook.last_user_prompt(str(transcript)) == "rename the helper"
    assert hook.last_user_prompt(str(tmp_path / "missing.jsonl")) == ""
