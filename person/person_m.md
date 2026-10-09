# Person M: engine backend

**No Gemma needed.** You own the engine: the service every edit goes through, the event log, the
score, the pattern checks, the call graph and the demo driver. Read the
[shared contract](README.md#the-shared-contract) first. You own `engine/models.py`.

**Branch:** `m/engine`. **Works in:** a new `engine/` folder, plus `demo/`.

Reuse what exists. `score/app.py` already does FastAPI, the `/agents/state` shape, CORS for the
dashboard, a log-odds score calibration, and reasons built from factor contributions. Copy
patterns from it rather than starting fresh. Don't break `score/`: its 66 tests must keep passing.

## Tasks

### 1. Skeleton serving the contract
- [ ] `engine/app.py`: FastAPI on port **8100** with CORS for `http://127.0.0.1:5173`.
- [ ] `engine/models.py`: Pydantic models for `Edit`, `Finding`, `Agent`, the graph and the state
      response, matching the contract exactly.
- [ ] `GET /agents/state` returns hard-coded data first, so A can switch from the stub early.
- [ ] `GET /health`.
- [ ] `engine/checks/gemma_checks.py` stub: `review(edit, timeout_s=8.0) -> []`. C replaces it.

### 2. Event log
- [ ] SQLite at `engine/data/viz_trust.db` (gitignored), **append-only**: prompts, edits, findings,
      verdicts, decisions, score changes, tier changes.
- [ ] Store diff stats, a hash of the content and the cited lines, **not whole files**.
- [ ] The state endpoint is built **from the log**. Wipe the in-memory state, rebuild it from the
      log, and you get the same answer.

### 3. Score and tiers
- [ ] v0 scoring as a clear points table with a reason for every change. For example: clean edit
      approved +14, clean edit allowed +8, confirmed medium finding −30, confirmed high finding −60,
      broken caller −20, dismissed finding +2. Clamp to 0–1000, start at 500.
- [ ] **Hard rule:** a confirmed secret leak resets the agent to probation (score capped at 550).
- [ ] **Anti-gaming:** gains are scaled by edit size and blast radius, so one-line edits barely count.
- [ ] Tiers: trusted at 800+, standard at 600–799, probation below 600.
- [ ] `top_factors` = the biggest point contributions, phrased like Aegis's reasons.
- [ ] Unit tests for every rule.

### 4. Decision flow
- [ ] `POST /edits`: run pattern checks, then `gemma_checks.review()`, then the graph diff, then
      decide.
  - Probation: hold everything.
  - Standard: hold if any high finding, otherwise allow.
  - Trusted: allow, but hold a high finding, and hold 1 in 5 edits at random for a spot check.
  - Deny straight away on a high-severity secret, whatever the tier.
- [ ] `GET /edits/{id}`, `POST /decisions`, `POST /findings/{id}/verdict`, each writing to the log.
- [ ] Held edits time out after 120 s and count as denied.

### 5. Pattern checks (no LLM): `engine/checks/patterns.py`
- [ ] **Hardcode Hunter:** known token formats (`xoxb-`, `ghp_`, `sk-`, AWS keys, private keys),
      high-entropy strings, credentialed URLs, absolute local paths, fixed ports.
- [ ] **Test Guardian (patterns):** `.only`, `skip`, `xit`, `@pytest.mark.skip`, deleted test
      functions, `assert True`.
- [ ] **Reality Check (exact part):** imports not in the repo, `requirements.txt` or
      `package.json`. Mark them as "not installed". C's Gemma check decides whether to flag them.
- [ ] **Scope Guard (exact part):** edits to lockfiles, `.env`, or CI files the prompt didn't mention.
- [ ] Every finding carries `file`, `line` and `evidence`.

### 6. Call graph and blast radius: `engine/graph.py`
- [ ] Parse Python files with the built-in `ast`: functions and methods as nodes, calls as edges.
      Python only is fine for the demo.
- [ ] On each edit, work out `touched` (functions whose lines changed) and `blast` (callers,
      walked upwards, up to depth 3).
- [ ] `heat` falls off over time, and goes up each time a function is edited.

### 7. Demo repo and driver
- [ ] `demo/sample_repo/`: a small Python app (signup, routes, notifications, about 15 functions
      across 4 files, plus a few tests).
- [ ] `demo/driver.py` posts a scripted series of edits to `POST /edits` so the demo runs the same
      way every time: a new agent, clean edits, promotion to standard, then the Slack-token edit.
      It waits on held edits so a person can click Approve in the dashboard.
- [ ] A `--fast` flag that auto-approves, to build up trust quickly for Scene 3.
- [ ] A `reset` command that wipes the log.

### 8. Stretch: the Claude Code hook
- [ ] A PreToolUse hook script that sends the proposed edit to `POST /edits`, polls `GET /edits/{id}`
      every 700 ms while held, and returns `permissionDecision: "deny"` on deny.
- [ ] If the engine is unreachable, exit 0 silently. Treat a dead engine as allow. Never hang.

## You depend on
- **C** for `gemma_checks.review()`. Until then, the stub returns `[]`, and that's fine.

## Done when
- [ ] `uvicorn engine.app:app --port 8100` serves the contract, and A's dashboard reads it.
- [ ] `python demo/driver.py` runs the four demo beats end to end, and the score and tier move.
- [ ] Restarting the engine rebuilds the same state from the log.
- [ ] `pytest engine` passes, and `score/` tests still pass.
- [ ] The engine still works with Ollama stopped (pattern checks only).
