"""Claude Code PreToolUse hook: send every Edit / Write / MultiEdit to the viz_trust engine first.

    .claude/settings.json (project or user):
    {
      "hooks": {
        "PreToolUse": [{
          "matcher": "Edit|Write|MultiEdit",
          "hooks": [{
            "type": "command",
            "command": "python /path/to/viz_trust/engine/hook/claude_code_hook.py",
            "timeout": 150
          }]
        }]
      }
    }

Behaviour:
    allow   prints nothing and exits 0, so Claude Code carries on as normal
    hold    polls GET /edits/{id} every 700 ms until someone clicks Approve or Deny (the
            engine denies on its own after 120 s)
    deny    prints permissionDecision "deny" with the reason, so the edit never reaches disk
    engine unreachable, slow or broken: exits 0 silently. A dead engine means "allow";
            the hook never blocks work and never hangs.

Environment: VIZ_TRUST_URL (default http://127.0.0.1:8100), VIZ_TRUST_AGENT (claude-code),
VIZ_TRUST_AGENT_MODEL (claude), VIZ_TRUST_PROMPT (overrides the prompt read from the transcript).
Point the engine at the project with VIZ_TRUST_REPO so the call graph covers it.
Standard library only.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

POLL_S = 0.7
POST_TIMEOUT_S = 20.0
GET_TIMEOUT_S = 5.0
MAX_WAIT_S = 135.0  # just over the engine's own 120 s hold timeout
TRANSCRIPT_TAIL_BYTES = 200_000


def apply_edits(before: str, edits: list[dict]) -> str | None:
    """Apply Edit / MultiEdit replacements in order. None if one does not apply cleanly."""
    text = before
    for item in edits:
        old, new = item.get("old_string", ""), item.get("new_string", "")
        if old not in text:
            return None  # Claude Code will reject this edit itself; nothing to review
        text = text.replace(old, new) if item.get("replace_all") else text.replace(old, new, 1)
    return text


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def relative_path(file_path: str, cwd: str) -> str:
    path = Path(file_path)
    try:
        return path.resolve().relative_to(Path(cwd).resolve()).as_posix()
    except (ValueError, OSError):
        return path.as_posix()


def last_user_prompt(transcript_path: str | None) -> str:
    """Best effort: the most recent user message in the session transcript."""
    if not transcript_path:
        return ""
    try:
        with open(transcript_path, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            handle.seek(max(0, handle.tell() - TRANSCRIPT_TAIL_BYTES))
            lines = handle.read().decode("utf-8", "replace").splitlines()
        for line in reversed(lines):
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            message = entry.get("message") or {}
            if entry.get("type") != "user" or message.get("role") != "user":
                continue
            content = message.get("content")
            if isinstance(content, str):
                return content[:500]
            if isinstance(content, list):
                texts = [b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
                if texts:
                    return " ".join(texts)[:500]
    except OSError:
        pass
    return ""


def build_request(payload: dict) -> dict | None:
    """The POST /edits body for this tool call, or None if it is not an edit we review."""
    tool, args = payload.get("tool_name"), payload.get("tool_input") or {}
    file_path = args.get("file_path")
    if tool not in ("Edit", "Write", "MultiEdit") or not file_path:
        return None
    cwd = payload.get("cwd") or os.getcwd()
    absolute = Path(file_path) if Path(file_path).is_absolute() else Path(cwd) / file_path
    before = read_text(absolute)

    if tool == "Write":
        after: str | None = args.get("content", "")
    elif tool == "Edit":
        after = apply_edits(before, [args])
    else:
        after = apply_edits(before, args.get("edits") or [])
    if after is None:
        return None

    return {
        "agent": os.environ.get("VIZ_TRUST_AGENT", "claude-code"),
        "model": os.environ.get("VIZ_TRUST_AGENT_MODEL", "claude"),
        "prompt": os.environ.get("VIZ_TRUST_PROMPT") or last_user_prompt(payload.get("transcript_path")),
        "file": relative_path(str(absolute), cwd),
        "before": before,
        "after": after,
    }


def call(url: str, method: str, body: dict | None, timeout: float) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as reply:
        return json.loads(reply.read())


def deny(reason: str) -> None:
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason,
    }}))


def review(payload: dict, base_url: str) -> str | None:
    """Return a denial reason, or None to allow. Any failure raises and the caller allows."""
    body = build_request(payload)
    if body is None:
        return None
    result = call(f"{base_url}/edits", "POST", body, POST_TIMEOUT_S)
    decision, edit_id = result["decision"], result["edit_id"]
    deadline = time.monotonic() + MAX_WAIT_S
    while decision == "hold" and time.monotonic() < deadline:
        time.sleep(POLL_S)
        decision = call(f"{base_url}/edits/{edit_id}", "GET", None, GET_TIMEOUT_S)["decision"]
    if decision == "deny":
        return f"viz_trust blocked this edit ({edit_id}). Open the dashboard for the findings."
    return None


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        reason = review(payload, os.environ.get("VIZ_TRUST_URL", "http://127.0.0.1:8100").rstrip("/"))
    except Exception:  # noqa: BLE001 -- unreachable, slow or broken engine, bad input: fail open
        return 0
    if reason:
        deny(reason)
    return 0


if __name__ == "__main__":
    sys.exit(main())
