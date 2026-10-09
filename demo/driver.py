"""Scripted demo: a new agent earns trust, then leaks a token.

    python demo/driver.py run   [--fast] [--reset] [--url http://127.0.0.1:8100]
    python demo/driver.py reset [--url ...]

Start the engine first (`uvicorn engine.app:app --port 8100`) and open
    http://127.0.0.1:5173/dashboard?api=http://127.0.0.1:8100

The four beats (person/README.md, "What the demo shows"):
    1  a new agent starts at 500 on probation; its first edit is held for you to Approve
    2  clean edits, each held until you Approve, raise the score to Standard (600+)
    3  now clean edits go through by themselves
    4  an edit with a hardcoded Slack token and a package that does not exist is blocked,
       two findings appear, and the agent falls back to Probation

`--fast` approves held edits for you in beats 1-2, to build up trust quickly (Scene 3).
Without it the driver waits for you to click Approve in the dashboard. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import edits as script  # noqa: E402

DEFAULT_URL = "http://127.0.0.1:8100"
AGENT, MODEL = "aider", "gemma4:e4b"
AFTER_PROMOTION = 2  # clean edits shown going straight through in beat 3
POLL_S = 0.7
DB_PATH = Path(__file__).resolve().parent.parent / "engine" / "data" / "viz_trust.db"


class Engine:
    def __init__(self, url: str) -> None:
        self.url = url.rstrip("/")

    def call(self, method: str, path: str, body: dict | None = None):
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(
            self.url + path, data=data, method=method, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=30) as reply:
            raw = reply.read()
        return json.loads(raw) if raw else None

    def state(self) -> dict:
        return self.call("GET", "/agents/state")

    def agent(self) -> dict | None:
        return next((a for a in self.state()["agents"] if a["model"] == MODEL), None)


def say(text: str = "") -> None:
    print(text, flush=True)


def describe(agent: dict | None) -> str:
    return "no score yet" if agent is None else f"score {agent['score']}, {agent['tier']}"


def send(engine: Engine, edit: script.ScriptedEdit) -> dict:
    return engine.call("POST", "/edits", {
        "agent": AGENT, "model": MODEL, "prompt": edit.prompt,
        "file": edit.file, "before": edit.before, "after": edit.after})


def settle(engine: Engine, result: dict, auto_approve: bool) -> str:
    """Return the final decision, approving (--fast) or waiting for the person at the dashboard."""
    if result["decision"] != "hold":
        return result["decision"]
    edit_id = result["edit_id"]
    if auto_approve:
        time.sleep(0.3)
        engine.call("POST", "/decisions", {"edit_id": edit_id, "decision": "approve"})
        return "allow"
    say(f"    waiting for you to click Approve or Deny on {edit_id} in the dashboard...")
    while True:
        time.sleep(POLL_S)
        decision = engine.call("GET", f"/edits/{edit_id}")["decision"]
        if decision != "hold":
            return decision


def run(engine: Engine, fast: bool, pace: float) -> int:
    existing = engine.agent()
    if existing is not None:
        say(f"The engine already knows {AGENT} ({MODEL}) ({describe(existing)}).")
        say("Run `python demo/driver.py reset` first for a clean demo, or pass --reset.")
        return 1

    clean = script.clean_edits()
    say("Beat 1: a new agent appears")
    first = send(engine, clean[0])
    say(f"  {AGENT} ({MODEL}) edits {clean[0].file}: {first['decision'].upper()} (probation tier holds every edit)")
    if settle(engine, first, fast) != "allow":
        say("  The first edit was not approved, so the agent stays on probation. Stopping here.")
        return 0
    say(f"  approved -> {describe(engine.agent())}")
    time.sleep(pace)

    say("")
    say("Beat 2: clean edits earn trust")
    used = 1
    while used < len(clean) and engine.agent()["tier"] == "probation":
        edit = clean[used]
        used += 1
        result = send(engine, edit)
        decision = settle(engine, result, fast)
        say(f"  {edit.file}: {edit.prompt} -> {decision} -> {describe(engine.agent())}")
        time.sleep(pace)
    if engine.agent()["tier"] == "probation":
        say("  The agent did not reach Standard with the scripted edits. Approve edits faster, or reset and rerun.")
        return 1
    say(f"  promoted: {describe(engine.agent())}")

    say("")
    say("Beat 3: standard tier, clean edits go straight through")
    for edit in clean[used:used + AFTER_PROMOTION]:
        result = send(engine, edit)
        say(f"  {edit.file}: {edit.prompt} -> {result['decision']} (no click needed) -> {describe(engine.agent())}")
        time.sleep(pace)

    say("")
    say("Beat 4: the Slack token")
    bad = script.slack_edit()
    result = send(engine, bad)
    say(f"  {AGENT} edits {bad.file}: {bad.prompt} -> {result['decision'].upper()}")
    state = engine.state()
    for finding in state["findings"]:
        if finding["edit_id"] == result["edit_id"]:
            say(f"    {finding['severity'].upper():6} {finding['check']:16} {finding['file']}:{finding['line']}  "
                f"{finding['message']}   [{finding['status']}]")
    say(f"  after the edit: {describe(engine.agent())}")
    return 0


def reset(engine: Engine) -> int:
    try:
        engine.call("POST", "/admin/reset")
        say("Event log wiped through the running engine.")
    except (urllib.error.URLError, OSError):
        if DB_PATH.exists():
            DB_PATH.unlink()
            say(f"Engine not running; deleted {DB_PATH}.")
        else:
            say("Engine not running and no event log to delete. Nothing to reset.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", nargs="?", choices=["run", "reset"], default="run")
    parser.add_argument("--url", default=DEFAULT_URL, help="engine URL (default %(default)s)")
    parser.add_argument("--fast", action="store_true", help="auto-approve held edits in beats 1-2")
    parser.add_argument("--reset", action="store_true", help="wipe the log before running")
    parser.add_argument("--pace", type=float, default=None, help="seconds between steps (default 2, or 0.2 with --fast)")
    args = parser.parse_args(argv)
    engine = Engine(args.url)

    if args.command == "reset":
        return reset(engine)
    try:
        engine.call("GET", "/health")
    except (urllib.error.URLError, OSError):
        say(f"Cannot reach the engine at {args.url}. Start it with: uvicorn engine.app:app --port 8100")
        return 1
    if args.reset:
        reset(engine)
    return run(engine, args.fast, args.pace if args.pace is not None else (0.2 if args.fast else 2.0))


if __name__ == "__main__":
    sys.exit(main())
