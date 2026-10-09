# Person M: final report (engine backend)

**Branch:** `m/engine` (not committed or pushed yet). **Task file:** [person_m.md](person_m.md).
**Status:** every task 1–8 is built, including the stretch hook. `pytest engine` passes (129 tests),
and `score/` still passes (66 tests, run after generating its model files).

## What was built

All paths are new. Nothing under `score/`, `web/`, `contracts/` or `oracle/` was changed. The only edit to an existing file is two lines in `.gitignore` (`engine/data/`).

| Task | Where | Notes |
| --- | --- | --- |
| 1. Skeleton | `engine/app.py`, `engine/models.py`, `engine/checks/gemma_checks.py` | FastAPI on **:8100**, CORS for `http://127.0.0.1:5173` (and `localhost:5173`), `/health`, `/agents/state`. Gemma stub is `review(edit, timeout_s=8.0) -> []` |
| 2. Event log | `engine/eventlog.py`, `engine/state.py` | SQLite at `engine/data/viz_trust.db` (gitignored). **Append-only**: update and delete are blocked by triggers. State is a pure replay of the log |
| 3. Score and tiers | `engine/scoring.py` | Points table below. 500 start, 0–1000, tiers at 600 / 800 |
| 4. Decision flow | `engine/core.py` | `POST /edits`, `GET /edits/{id}`, `POST /decisions`, `POST /findings/{id}/verdict`, 120 s hold timeout |
| 5. Pattern checks | `engine/checks/patterns.py` | Hardcode Hunter, Test Guardian, Reality Check (exact half), Scope Guard (exact half) |
| 6. Call graph | `engine/graph.py` | `ast`-based, Python only. `touched`, `blast` (depth 3), heat with decay |
| 7. Demo | `demo/sample_repo/`, `demo/edits.py`, `demo/driver.py` | 8 Python files (4 app modules, 2 test files, 2 `__init__`), 12 app functions plus 7 test functions, `--fast`, `reset` |
| 8. Hook (stretch) | `engine/hook/claude_code_hook.py` | PreToolUse for Edit / Write / MultiEdit. Dead engine = allow, never hangs |

Also added: `engine/requirements.txt`, `engine/diffing.py`, `POST /admin/reset` (what the driver's `reset` calls).

## How to run it

```bash
pip install -r engine/requirements.txt          # or the venv from SETUP.md
uvicorn engine.app:app --port 8100              # from the repo root
python demo/driver.py run                       # waits for you to click Approve in the dashboard
python demo/driver.py run --fast                # auto-approves beats 1-2
python demo/driver.py reset                     # wipe the log
pytest engine                                   # 129 tests
```

Dashboard: `http://127.0.0.1:5173/dashboard?api=http://127.0.0.1:8100`.
Environment: `VIZ_TRUST_REPO` (repo the graph is built from, default `demo/sample_repo`),
`VIZ_TRUST_DB`, `VIZ_TRUST_SEED` (fixes the 1-in-5 spot check), `VIZ_TRUST_HOLD_TIMEOUT_S`.

**Hook setup** (project `.claude/settings.json`): matcher `Edit|Write|MultiEdit`, command
`python <repo>/engine/hook/claude_code_hook.py`, and **`"timeout": 150`**. Claude Code's default hook
timeout is shorter than a held edit can wait. Set `VIZ_TRUST_REPO` on the engine to the project you are editing.

## Scoring rules (v0)

| Event | Points | Factor label |
| --- | --- | --- |
| Clean edit approved | +14 | `clean_edit_approved` |
| Clean edit allowed (standard / trusted) | +8 | `clean_edit_allowed` |
| Finding dismissed (false alarm) | +2 | `finding_dismissed` |
| Confirmed finding: high / medium / low | −60 / −30 / −10 | `confirmed_high` / `_medium` / `_low` |
| Confirmed broken caller (Impact Analyst) | −20 | `broken_caller` |
| Confirmed secret leak (high Hardcode Hunter) | −60 **and score capped at 550** | `secret_leak` |

- **Anti-gaming:** gains (not penalties) are multiplied by `clamp(0.10 + 0.07 × changed lines + 0.10 × blast callers, 0, 1)`, minimum 1 point. A one-line edit with no callers earns 2 of the 14. About 10 changed lines, or 3 callers, earns the full amount.
- **Decisions:** secret → deny (any tier). Probation → hold all. Standard → hold on a high finding, else allow. Trusted → hold on a high finding, else hold 1 in 5 at random, else allow.
- **Demo path with the shipped script:** 500 → 514 → … → 612 after 8 approvals (promoted to standard), two more edits auto-allowed (620, 628), then the Slack edit is denied and the score drops to **550, probation**.

## Notes for A (frontend) and C (Gemma)

**For A. Things that follow the contract but need a decision on the card:**
- `required_collateral_pct` is a string per tier: trusted `"20%"`, probation `"100%"`, but standard is `"high severity"`. Standard has no honest percentage (every edit is checked, only high-severity ones are held). The card prints `[<pct>]`, so A may want wording like "edits reviewed". `required_collateral_bps` is 2000 / 4000 / 10000 for trusted / standard / probation.
- `band` uses the Aegis breakpoints (800 / 600 / 400), so probation agents are `fair` above 400 and `poor` below.
- `address` is `"<agent>:<model>"` (e.g. `aider:gemma4:e4b`); `name` is `aider·e4b`.
- Feed keys are `agent|timestamp|reason`. Every reason includes the edit id, so rows stay unique.
- `recent_events[].job_id` is the edit number (1, 2, …), `value_usd` is 0. `delta` is 0 for held / blocked / tier-change rows.
- `findings` is newest first, capped at 100. `pending` is oldest first. `pending[].diff` starts at `@@` and is capped at 4000 chars.
- `graph.nodes[].heat` is 0–1 and is computed on every read. It rises only when an edit **lands** (allowed or approved). `last_edit` is set as soon as an edit **arrives**, so the touched node can glow while the edit is still held. `last_edit` is `null` before the first edit.
- `notice` is set (and `agents` is empty) before the first edit. `StatusBanner` may show it.
- Errors: 404 unknown id, 409 edit already decided or finding already confirmed or dismissed.

**For C. Interface details:**
- `gemma_checks.review(edit, timeout_s=8.0) -> list[Finding]`. Leave `id` and `edit_id` empty (they default to `""`); the engine assigns them. Set `source="gemma"`.
- The engine calls it **outside** its lock, wraps it in `try/except`, ignores anything that is not a `Finding`, de-duplicates on (check, file, line, message), and redacts evidence.
- Reality Check hand-off: the pattern half **already emits** a `medium` finding for an import that is not stdlib, not in the repo, and not in `requirements.txt` / `package.json`. There is no separate "not installed" list. To judge them, use `RepoContext(root).requirements() / .node_deps() / .python_modules()` from `engine/checks/patterns.py`, or call `reality_check(...)`. If Gemma decides an import is real, it cannot currently retract the pattern finding; the person dismissing it does (+2).
- Test Guardian deleted tests are `high`; skips / `.only` / `assert True` are `medium`. Scope Guard findings are `medium`. Hardcode Hunter: known token formats, private keys and credentialed URLs are `high`; password-style assignments and high-entropy strings are `medium`; local paths and fixed ports are `low`.

## Decisions I made that the task file did not specify

1. **A secret that gets denied is confirmed automatically.** The task says a confirmed leak resets the agent, and the demo needs the drop at the moment of the block. So the engine confirms the high Hardcode Hunter finding itself (`by: "engine"`). Downside: a human cannot dismiss it afterwards (409). Only known-format secrets are `high`, so false positives should be rare, but they are possible.
2. **Reality Check is `medium`, not `high`.** The mock in `person/README.md` shows it as HIGH, but a missing `requirements.txt` entry is not proof of a hallucinated package. At medium it never holds a standard agent by itself. In the demo the edit is blocked by the token anyway. Change `severity` in `reality_check` if you want it high.
3. **Held, blocked and allowed-with-findings events are `activity` rows** in the log with delta 0; only real movements are `score_change` rows. Both show in the feed.
4. **Approving with unresolved findings earns nothing.** Approve counts as a clean edit only if the edit has no open or confirmed findings (dismissed ones are fine).
5. **Secrets are redacted before storage.** Evidence, the diff and the log keep only a short prefix (`xoxb-…`). Whole files are never stored, only a 16-hex hash of the new content, diff stats and a hash of each cited line.
6. **The engine never writes the repo.** Functions added by an edit are not on disk, so they are kept in the graph from the log (touched / blast ids). The demo edits are all built from the pristine sample repo, so replays are identical.
7. **Impact Analyst is mine.** The five checks list it as the graph's job. It raises a `medium` finding when a changed signature adds a required parameter or drops / renames one, or when a removed function still has callers. A confirmed one costs −20 (the "broken caller" row).

## Done when (from the task file)

- [x] `uvicorn engine.app:app --port 8100` serves the contract. **Not yet verified against A's dashboard**: `web/` has no engine integration yet, so only the JSON shape (tested) and CORS were checked.
- [x] `python demo/driver.py run` runs the four beats end to end; verified live against a real server and in `test_driver_runs_the_four_beats`.
- [x] Restarting the engine rebuilds the same state from the log (`test_state_is_rebuilt_identically_from_the_log`; only `updated_at`, the read-time clock, differs).
- [x] `pytest engine` passes (129); `score/` tests pass (66, after `python generate_data.py && python train.py`).
- [x] Works with Ollama stopped: nothing on the path needs it (`test_engine_works_with_ollama_stopped`).

## Known limits and untested areas

- **Python only** for the graph, as allowed. JS / TS files get pattern checks but no touched / blast.
- **Call resolution is name-based.** It over-approximates unique method names and misses dynamic calls and decorators.
- **The trusted tier was not seen live.** The shipped script goes to standard and back. Trusted behaviour (holds, 1-in-5 spot check) is covered by unit tests only.
- **The hook was tested with simulated Claude Code payloads, not a real session.** The PreToolUse input shape and the deny output follow Claude Code's documented format, but a real run is still worth doing before the demo.
- **The prompt is best-effort** in the hook (last user message from the transcript, or `VIZ_TRUST_PROMPT`). Without it, Scope Guard treats the prompt as empty and flags lockfile / `.env` / CI edits.
- **The hold sweeper** runs every 5 s and every API call also checks timeouts, so a lapsed hold is denied on the next call at the latest.
- **Single process.** One engine, one SQLite file; not built for concurrent writers across processes.
- **Tested on Python 3.10.11**; SETUP.md recommends 3.12. `sys.stdlib_module_names` needs 3.10+.
- **Two plans in the repo disagree.** `TODO.md` (two people, `POST /edits` with a different body, a score server on another side) conflicts with `person/README.md`. I followed `person/` as instructed. The shared contract needs the team's decision before merge.

## Pull request checklist

- [ ] Commit on `m/engine` and open the PR into `main` (one commit per area works well: models + log, checks + graph, flow + API, demo, hook).
- [ ] Tell A about the card wording question above, and C about the `Finding` defaults.
- [ ] Paste the "Done when" list into the PR description.
