# viz_trust: work split

Three people work in parallel against one shared contract, then integrate and validate together.
The detailed task lists are in [`person/`](person/README.md). This file is the summary, the rules,
the benchmarks and the integration checklist.

| Person | Part | Folders | Uses Gemma? | Works against until integration | Details |
| --- | --- | --- | --- | --- | --- |
| **A** | Frontend and visualisation | `web/`, `docs/api_stub.json` | No | The stub (`?stub=1`) | [person_a.md](person/person_a.md) |
| **M** | Engine: events, score, tiers, pattern checks, graph, demo driver | `engine/`, `demo/` | No | A stubbed `gemma_checks.review()` that returns `[]` | [person_m.md](person/person_m.md) |
| **C** | Gemma checks and evaluation | `engine/checks/gemma_checks.py`, `engine/llm/`, `eval/` | **Yes** | The contract's `Edit` and `Finding` types, tested from `eval/run.py` | [person_c.md](person/person_c.md) |

**Decisions already made**

- Everything talks over **HTTP**. The engine is **Python + FastAPI** on port **8100**.
- The model is **Gemma 4 through Ollama**, `gemma4:e4b` by default.
- The demo agent is a **scripted driver** first. The **Claude Code PreToolUse hook** is the stretch goal.
- **Don't redesign the existing UI.** Only `/dashboard` changes, and only by adding panels.
- **The on-chain part is out of the demo.** `contracts/` and `oracle/` stay in the repo untouched,
  and nothing new depends on them.

---

## 0. The contract (agree it first, then freeze it)

The full contract is in [person/README.md](person/README.md#the-shared-contract). It is the source
of truth. Change it there first, in its own commit, and tell the other two.

- [ ] A, M and C read the contract and agree it
- [ ] M commits `engine/models.py` matching it, and A commits the extended `docs/api_stub.json`

### Fixed vocabularies (everyone uses exactly these strings)

- `check`: `reality_check`, `hardcode_hunter`, `scope_guard`, `test_guardian`, `impact_analyst`
- `severity`: `low`, `medium`, `high`, `critical`
- `source`: `pattern`, `gemma`
- `tier`: `trusted` (800+), `standard` (600–799), `probation` (under 600 or new)
- `area`: `auth`, `payments`, `migrations`, `api`, `ui`, `tests`, `config`, `other`
- `decision`: `allow`, `hold`, `deny`

### Rules everyone follows

- A **`critical` `hardcode_hunter`** finding means a real secret. The edit is denied whatever the
  tier, and the agent resets to probation.
- An unknown agent gets `score: 500` and `tier: "probation"`. Never a 404.
- Unknown fields are ignored and missing optional fields get defaults. No crashes either way.
- Each edited file maps to an `area` by path rules (M owns the rules).
- Trusted agents get `spot_check: true` on about 1 in 5 edits, seeded so tests are stable.
- Gemma only ever **adds** findings. Allow, hold and deny are decided by the engine's rules.
- Confirm and dismiss verdicts from the dashboard are part of this version (Arjit's draft left them
  out). They count, but objective signals (tests, reverts, broken callers) count more.

---

## A: Frontend and visualisation

Full list: [person_a.md](person/person_a.md).

- [ ] Extend `docs/api_stub.json` with `tier`, `model`, `graph`, `findings` and `pending`
- [ ] `BlastGraph`: a 2D call graph where touched nodes glow and callers ripple out
- [ ] `FindingsPanel`: evidence, a pattern or gemma tag, Confirm and Dismiss
- [ ] `HeldEditDialog`: the diff, the reason, the blast count, Approve and Deny
- [ ] Add a "Blast radius / live" section to `/dashboard` between the agents and the activity feed
- [ ] Small wording changes on `AgentCard` (tier, model, "Edits reviewed")
- [ ] A clear message when the engine is unreachable (reuse `StatusBanner`)
- [ ] Stretch: 3D view, heat-map view, a model comparison view, a score history chart

## M: Engine

Full list: [person_m.md](person/person_m.md).

- [ ] Engine skeleton on `:8100` serving the contract, starting with fake data, so A can switch early
- [ ] Append-only SQLite event log, with the state rebuilt from the log
- [ ] v0 score as a points table with reasons, plus the tiers, `spot_check` and the critical-leak reset
- [ ] Anti-gaming: gains scaled by edit size and blast radius; a fresh agent id can't skip probation
- [ ] Decision flow: `POST /edits`, `GET /edits/{id}`, `POST /decisions`, `POST /findings/{id}/verdict`
- [ ] Pattern checks: Hardcode Hunter, Test Guardian, and the exact parts of Reality Check and Scope Guard
- [ ] Call graph and blast radius with Python's `ast`, plus `area` mapping
- [ ] `demo/sample_repo/` and `demo/driver.py` (with `--fast` and `reset`)
- [ ] Stretch: Claude Code PreToolUse hook (silent if the engine is down, dead engine means allow, never hangs)
- [ ] Stretch: `GET /agents/{id}/history`, `GET /agents/{id}/areas`, `GET /route?area=auth`
- [ ] Later: retrain `score/`'s logistic regression on edit features, with archetypes (careful,
      sloppy, improving, degrading, gaming), keeping the 0.80–0.88 AUC band and the 500 anchor

## C: Gemma checks and evaluation

Full list: [person_c.md](person/person_c.md).

- [ ] Gemma client: JSON-schema output, a timeout, one retry, Pydantic validation, per-call logging, a warm-up call
- [ ] Judgement checks: Scope Guard, Reality Check (with a PyPI or npm lookup done in code), Test Guardian, Hardcode Hunter
- [ ] `review(edit)`: merge findings, drop any that cite missing lines, never raise, never hang
- [ ] Fix-it prompts for each finding
- [ ] Evaluation set in `eval/`, with clean controls and prompt-injection cases
- [ ] Stretch: screenshot review with Gemma 4 image input

---

## Benchmarks (what we measure, and who owns each one)

Results go in `engine/BENCHMARKS.md` (M), `eval/results.md` (C) and `docs/BENCHMARKS.md`
(integration).

### Benchmark 1: Does the score behave? (M)
- [ ] **Separation:** a careful scripted agent reaches `trusted` and a sloppy one stays on `probation`. Report how many edits it takes
- [ ] **Speed of drop:** edits for a trusted agent to fall to `standard` after a run of bad edits
- [ ] **Leak response:** one `critical` `hardcode_hunter` finding sends a trusted agent to `probation`
- [ ] **Gaming resistance:** one-line-edit farming and changing `agent_id` don't reach `trusted`
- [ ] **Replay:** the score rebuilt from the log matches the live score

### Benchmark 2: Do the checks catch the right things? (C, with M's pattern checks)
- [ ] A labelled set in `eval/`: at least 40 cases across all five checks, including clean controls and prompt-injection cases
- [ ] **Precision and recall** for each check
- [ ] **False-block rate:** how often a good edit would be held. This decides whether anyone keeps the tool switched on
- [ ] **Patterns only vs patterns + Gemma 4:** how much Gemma adds
- [ ] **Model size:** `gemma4:e2b` vs `e4b` (and `12b` if the VRAM allows) on accuracy and time per edit
- [ ] **Latency:** p50 and p95 review time per edit
- [ ] **Safety:** with Ollama stopped, `review()` returns `[]` within its timeout

### Benchmark 3: Does it work together? (everyone, at integration)
- [ ] Replay scripted sessions through the driver, engine and dashboard: a clean agent, a sloppy one, an improving one and a gaming one
- [ ] **Bad edits held:** the share of bad edits that are held or blocked
- [ ] **Good edits held:** the share of good edits held, split by tier (a trusted agent should see almost none)
- [ ] **Compare with no tiers:** the same sessions with everything held, to show how much review work the tiers save. **This is the headline number for the pitch**
- [ ] **UI matches the log:** scores, tiers and findings on the dashboard match the event log

---

## Integration (together, after the three parts work alone)

- [ ] C's `review()` replaces M's stub, and the engine still works with Ollama stopped
- [ ] A switches from `?stub=1` to `?api=http://127.0.0.1:8100`, and every panel updates live
- [ ] Approve, Deny, Confirm and Dismiss from the dashboard reach the engine and move the score
- [ ] The four demo beats run end to end: new agent held, clean edits earn Standard, the Slack-token edit is blocked, back to probation
- [ ] Fix contract mismatches in `person/README.md` first, then in code
- [ ] Update the README Status table and the "Run it" section of `SETUP.md`
- [ ] Rehearse on the demo machine with `gemma4:e4b`

## Later (after the demo works)

- [ ] Rename leftover Aegis strings in `web/` (`links.js`, `docs.js`, `package.json`) and `render.yaml`
- [ ] Rewrite `SPEC.md` for viz_trust, or move it to `SPEC_AEGIS.md`
- [ ] Decide whether to remove `contracts/`, `oracle/`, `deployments/` and the `agents/` demo scripts
- [ ] Open-source agent adapters (Aider, Cline, OpenHands) and an MCP server
- [x] MIT license
