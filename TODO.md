# viz_trust: work split

Two people work **independently**, then merge and validate together. There is no cross-checking
before the merge, so the only thing that keeps the halves compatible is the contract below.
**Freeze it before anyone starts. Changing it later breaks the merge.**

| Part | Owner | Folders | Works against |
| --- | --- | --- | --- |
| **A. Credit scoring** | Person 1 | `score/` | Synthetic data and its own benchmarks |
| **B. Visualisation and review** | Person 2 | `engine/`, `hook/`, `web/` (all new or reworked) | A fake score server and a real Claude Code agent |

Decisions already made: the halves talk over **HTTP**, the engine is **Python**, the real agent is
**Claude Code** (PreToolUse hook), and the **on-chain part is out of scope**.

---

## 0. The contract (do this first, together, then freeze)

Put these files in `docs/contract/` so both people build against the same thing:
`edit_event.example.json`, `agent_standing.example.json`, `contract.md`.

### B → A: one review result per edit

`POST /edits`

```json
{
  "edit_id": "e_123",
  "timestamp": "2026-10-09T12:00:00Z",
  "agent_id": "claude-code",
  "model": "claude-sonnet-5-5",
  "repo": "viz_trust",
  "file": "src/auth/login.py",
  "area": "auth",
  "lines_changed": 14,
  "findings": [
    {"check": "hardcode_hunter", "severity": "high", "evidence": "API key on line 8"}
  ],
  "callers_broken": 0
}
```

### A → B: the agent's standing

`GET /agents/{agent_id}`

```json
{
  "agent_id": "claude-code",
  "score": 640,
  "tier": "standard",
  "spot_check": false,
  "reasons": [{"factor": "high_severity_findings", "points": -35}]
}
```

### Fixed vocabularies (both sides use exactly these strings)

- `check`: `reality_check`, `hardcode_hunter`, `scope_guard`, `test_guardian`, `impact_analyst`
- `severity`: `low`, `medium`, `high`, `critical`
- `tier`: `trusted` (800+), `standard` (600–799), `probation` (under 600 or new)
- `area`: `auth`, `payments`, `migrations`, `api`, `ui`, `tests`, `config`, `other`

### Rules everyone must follow

- The only signals A can use are: **findings (check and severity), `callers_broken`, `lines_changed`,
  `area`, `agent_id`, `model`, `timestamp`**. Nothing else crosses the wire.
- There is **no user feedback** (confirmed or dismissed) in this version. A can't score on false alarms.
- A `critical` `hardcode_hunter` finding means a confirmed secret leak, so A resets the agent to probation.
- New or unknown agents: A returns `score: 500`, `tier: "probation"`. It never returns a 404.
- `GET /agents/{id}/areas` returns per-area scores: `{"areas": {"auth": 720, "payments": 410}}`.
- The base URL comes from the `SCORE_API_URL` environment variable (default `http://127.0.0.1:8000`).
- Unknown fields are ignored, and missing optional fields get defaults. No crashes either way.

- [ ] Both people agree the contract and commit `docs/contract/`
- [ ] Both people confirm the fixed vocabularies above, especially the `area` list

---

## Part A: Credit scoring (Person 1)

Goal: a trustworthy 0–1000 score with reasons, a tier, and benchmarks that show it behaves well.
You never need the visualisation side. Build against the sample JSON in `docs/contract/`.

### A1. Redefine the features
- [ ] Define features computable only from contract fields, for example: clean-edit rate,
  findings per edit by severity, findings per check, broken callers per edit, average edit size,
  edits seen (experience), account age, and share of edits in risky areas
- [ ] Update the feature definitions in `SPEC.md` (the Aegis features and loan terms go away)
- [ ] Rewrite `score/generate_data.py` to simulate agents with these features, including
  agent archetypes: careful, sloppy, improving, degrading, and gaming
- [ ] Keep the AUC band check (0.80–0.88) and the 500 anchor in `score/train.py`, re-tuned to the new target
- [ ] Retrain, and replace the Aegis tests in `score/tests/`

### A2. Score service
- [ ] `POST /edits` validates against the contract, stores the edit, updates the agent, returns the new standing
- [ ] `GET /agents/{id}` returns score, tier, `spot_check` and reasons (unknown agent gives 500 and probation)
- [ ] `GET /agents/{id}/areas` returns per-area scores
- [ ] `GET /agents/{id}/history` returns score over time (for the UI chart)
- [ ] `GET /agents` lists all agents with score and tier (for the model comparison view)
- [ ] Trust ledger: persistent SQLite storage of every edit and every score change
- [ ] Reasons built from per-feature contributions, as in the current model
- [ ] Reject bad input with clear 4xx errors, and ignore unknown fields
- [ ] CORS enabled so the web UI can call it from the browser

### A3. Tier and rule logic
- [ ] Tiers: trusted 800+, standard 600–799, probation under 600 or new
- [ ] `spot_check` is true for about 1 in 5 edits from trusted agents (seeded so tests are stable)
- [ ] A `critical` `hardcode_hunter` finding resets the agent straight to probation
- [ ] Score rises with clean edits and falls with high-severity findings and broken callers

### A4. Anti-gaming
- [ ] Cap how much trivial one-line edits can raise the score
- [ ] A fresh `agent_id` can't skip probation, and cheap identity-hopping doesn't help
- [ ] Scores don't all bunch into one band (keep the existing distribution check, updated)
- [ ] A dedicated test for each of these

### A5. Per-model and per-area scoring, and the router
- [ ] Score per model and per area from the same ledger
- [ ] `GET /route?area=auth` returns the model with the best record in that area
- [ ] Model comparison data from the stored edits

### A6. Benchmarks and tests (this is your validation, since nobody checks you before the merge)
- [ ] Unit tests for every rule in A3 and A4
- [ ] Archetype benchmark: careful agents end up trusted, sloppy ones on probation, within N edits
- [ ] Sensitivity test: one critical finding drops a trusted agent by a measurable amount
- [ ] Score distribution report across 5,000 synthetic agents
- [ ] Contract test: every example in `docs/contract/` is accepted and returns the documented shape
- [ ] Load test: 100 edits per second don't corrupt the ledger
- [ ] `pytest` passes, and the benchmark results are written to `score/BENCHMARKS.md`

### A7. Cleanup (on-chain is out of scope)
- [ ] Remove `contracts/`, `oracle/`, `deployments/`, `render.yaml` entries and `agents/` demo scripts
  that depend on them, and the web components that show escrow and collateral. Do this last, and
  coordinate with Person 2 on `web/` so you don't both edit the same files.

### A8. Done when
- [ ] The service runs with `uvicorn app:app` and answers every contract endpoint with the documented shapes
- [ ] Benchmarks are written up and pass

---

## Part B: Visualisation and review (Person 2)

Goal: review each Claude Code edit before it's written, and show what it did on a live graph.
You never need the real score service. Run the fake one from B1 and keep tiers switchable.

### B1. Fake score server (build this first so you're never blocked)
- [ ] `engine/fake_score_server.py` serves the contract endpoints from fixed data
- [ ] Switchable tier through an environment variable or query, so you can test trusted, standard and probation
- [ ] Saves every `POST /edits` it receives to a file, so you can inspect what you send
- [ ] Reads the same example files as `docs/contract/`

### B2. Gemma 4 through Ollama
- [ ] Ollama installed, and `gemma4:e4b` pulled and answering
- [ ] Client wrapper using the local API, model name from `VIZ_TRUST_MODEL`
- [ ] Timeouts, retries, and a clear error when Ollama is down
- [ ] Structured JSON output from the model, validated before use

### B3. The five checks (`engine/`)
- [ ] **Reality Check:** imports and APIs that don't exist, wrong signatures
- [ ] **Hardcode Hunter:** secrets, credentialed URLs, local paths, fixed ports, placeholders. A real secret is `critical`
- [ ] **Scope Guard:** edits unrelated to the prompt, unrequested lockfile, `.env` or CI changes
- [ ] **Test Guardian:** skipped, `.only`, always-true or deleted tests
- [ ] **Impact Analyst:** blast radius and `callers_broken`
- [ ] Pattern checks first, Gemma 4 only for the judgement parts
- [ ] Output only the contract's `check` and `severity` values
- [ ] A test set of good and bad edits for each check, and a precision and recall report

### B4. Call graph and blast radius
- [ ] Parse a repo into a call graph (functions, files, callers)
- [ ] Compute the blast radius of each edit and `callers_broken`
- [ ] Update incrementally when a file changes
- [ ] Port what's reusable from Blast Radius Live

### B5. Claude Code hook (the real agent)
- [ ] PreToolUse hook for Edit and Write: build the event, run the checks, post to `SCORE_API_URL`, read the tier
- [ ] Apply the tier: trusted allows, standard holds on `high` or `critical` findings, probation holds everything
- [ ] Honour `spot_check`: when true, run the full review even for a trusted agent
- [ ] Fail safe: no server means silent allow, a dead server means allow, and the hook times out instead of freezing
- [ ] Held edits show a clear reason, and the user can approve or reject
- [ ] MCP server with `impact`, `hotspots`, `findings` and `trust` tools
- [ ] Map each edited file to an `area` using path rules

### B6. Web UI (`web/`)
- [ ] Remove the Aegis pages and copy (escrow, collateral)
- [ ] Live graph with 3D, 2D and heat-map views, lighting up as edits land
- [ ] Colour nodes by blast radius, with a toggle for the trust of the agent that made the change
- [ ] Findings panel with evidence
- [ ] Agent view: score, tier, reasons and history, read from `SCORE_API_URL`
- [ ] Edit timeline, held-edits queue and model comparison view
- [ ] Works with the fake server and shows a clear message when the score service is unreachable

### B7. Screenshot review
- [ ] Capture before and after screenshots for frontend changes
- [ ] Send both to Gemma 4 and report visual regressions as `findings`

### B8. Testing with the real agent (this is your validation before the merge)
- [ ] A scripted set of edits Claude Code should make: a clean one, a hardcoded key, a deleted test, a hallucinated import, an edit that breaks a caller
- [ ] Each produces the expected finding, tier decision and graph update
- [ ] Kill the fake server and Ollama in turn and confirm the hook never blocks work
- [ ] Event files saved by the fake server pass validation against `docs/contract/`

### B9. Done when
- [ ] A real Claude Code session is reviewed locally, findings and graph update live, and tier decisions follow the fake server's tier

---

## Benchmarks (what we measure, and who builds each one)

Nobody validates the other half before the merge, so each person ships their own benchmark and
a written result. Numbers go in `score/BENCHMARKS.md` (Person 1) and `engine/BENCHMARKS.md`
(Person 2), and the merge benchmark goes in `docs/BENCHMARKS.md`.

### Benchmark 1: Does the score behave? (Person 1, uses synthetic agents)
- [ ] **Separation:** careful agents reach `trusted` and sloppy agents stay `probation`. Report how many edits it takes
- [ ] **Speed of drop:** edits for a trusted agent to fall to `standard` after a run of bad edits
- [ ] **Leak response:** a `critical` `hardcode_hunter` finding sends a trusted agent to `probation` in one step
- [ ] **Gaming resistance:** an agent making only one-line edits, and an agent that changes `agent_id`, do not reach `trusted`
- [ ] **Distribution:** score spread across 5,000 synthetic agents, with no single band holding most of them
- [ ] **Model quality:** AUC stays in the 0.80–0.88 band, and the per-feature reasons add up to the score
- [ ] **Throughput:** 100 edits per second without corrupting the ledger

### Benchmark 2: Do the checks catch the right things? (Person 2, uses labelled edits)
- [ ] Build a labelled set of edits in `engine/benchmark/`: at least 20 good and 20 bad per check, each with the expected finding and severity
- [ ] **Precision and recall** for each of the five checks
- [ ] **False-block rate:** how often a good edit would be held. This is the number that decides whether anyone keeps the tool switched on
- [ ] **Pattern checks vs Gemma 4:** how much Gemma 4 adds over patterns alone
- [ ] **Model size:** `gemma4:e2b` vs `gemma4:e4b` on accuracy and time per edit
- [ ] **Latency:** review time per edit, and extra time added to a Claude Code edit by the hook
- [ ] **Safety:** the hook allows the edit within the timeout when the server or Ollama is down

### Benchmark 3: Does the whole thing work together? (both, at the merge)
- [ ] Replay the same scripted sequences through the real hook, engine and score service: a clean agent, a sloppy agent, an improving agent and a gaming agent
- [ ] **Bad edits held:** share of bad edits that are held or blocked
- [ ] **Good edits held:** share of good edits that are held, split by tier (a trusted agent should see almost none)
- [ ] **Time to tier:** edits for the sloppy agent to reach `probation`, and for the clean agent to reach `standard` and `trusted`
- [ ] **Compare with no tiers:** the same sequences reviewed with everything held, to show how much review work tiers save
- [ ] **Model comparison:** the model that wins per area in the UI matches the ledger

---

## Merge (together, after both halves are done)

Nobody validates before this, so this is where everything gets checked.

- [ ] Point `SCORE_API_URL` at the real score service and run the whole of B8 again
- [ ] Check that every event the hook sends passes A's validation (no 4xx)
- [ ] Check that every field A returns is read correctly by the hook and UI
- [ ] End-to-end demo: a sloppy session drops an agent to probation, and a clean one earns standard or trusted
- [ ] Check that the UI score history, tiers and model comparison match the ledger
- [ ] Fix mismatches in the contract, and update `docs/contract/` so both sides agree again
- [ ] Remove `fake_score_server.py` or keep it only as a test fixture
- [ ] Update the README Status table and `SETUP.md`
- [ ] Choose and add an open-source license
