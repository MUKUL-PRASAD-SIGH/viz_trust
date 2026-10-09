# viz_trust: Progress and Plan

> Companion file: [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md) explains the whole project.
> Status as of **2026-10-09**, based on reading the repository (tests were not executed while writing this).

Legend: ✅ done · 🟡 exists but needs rework for viz_trust · ⬜ not started

## Where we are in one line

The **Aegis foundation (scoring, oracle, contracts, UI, deployment) is built**. The **viz_trust-specific
product (local Gemma 4 review, call graph, agent hooks, autonomy tiers, routing) is not started**. The repo
also still carries Aegis naming in code, `SPEC.md` and the web copy.

---

## Part A. What has been made

### A1. Project scaffolding and docs
- ✅ A1.1 Repo, `.gitignore` (secrets, Foundry output, model files, venvs), MIT `LICENSE`
- ✅ A1.2 `README.md` describing viz_trust vision plus a status table
- ✅ A1.3 `SETUP.md` machine setup guide (Ollama, Gemma 4 sizing, Python 3.12, Node 20, troubleshooting)
- 🟡 A1.4 `SPEC.md`: thorough, but it specifies **Aegis** types, not viz_trust
- ✅ A1.5 `docs/architecture.svg`, `docs/api_stub.json`

### A2. Trust scoring service (`score/`) 🟡
- ✅ A2.1 Synthetic dataset generator (`generate_data.py`, 5,000 agents)
- ✅ A2.2 Logistic-regression trainer with calibration artifacts (`train.py`, AUC target band 0.80–0.88)
- ✅ A2.3 Score distribution checker (`check_distribution.py`)
- ✅ A2.4 FastAPI service: `/health`, `/score`, `/score/from-events`, `/agents/state`, `/internal/agents/state`
- ✅ A2.5 Per-feature explanations (top 3 factors with point impact and text)
- ✅ A2.6 Advisory risk flags (dispute burst, serial disputer, closed ring)
- ✅ A2.7 Two state sources: oracle push or direct on-chain read, with caching and staleness notice
- ✅ A2.8 Tests: `test_scoring.py` (34 test functions), `test_agents_state.py` (13)
- 🟡 A2.9 **Features are Aegis features** (jobs, disputes, payment rate…). They must be replaced with edit-review signals.

### A3. On-chain registry and escrow (`contracts/`) 🟡 (optional in viz_trust)
- ✅ A3.1 `AegisRegistry` with oracle-only `updateScore`, escrow-only `recordOutcome`, collateral curve
- ✅ A3.2 `AegisEscrow` with real token flow and the job state machine
- ✅ A3.3 `MockUSDC`, `StubEscrow` fallback, interfaces
- ✅ A3.4 Foundry tests (71 test functions: Registry 42, Escrow 23, Stub 6)
- ✅ A3.5 Deploy scripts for Anvil and Base Sepolia, `Makefile`
- ✅ A3.6 Deployed to Base Sepolia (`deployments/base-sepolia.json`)
- 🟡 A3.7 Semantics are "jobs and collateral", not "edits and tiers". Only useful as optional score anchoring.

### A4. Oracle (`oracle/`) ✅/🟡
- ✅ A4.1 Polling watcher with chain-reset recovery and block-hash checks
- ✅ A4.2 History builder, reason strings, score writer, dashboard publisher with heartbeat
- 🟡 A4.3 Tied to `OutcomeRecorded` events. For viz_trust the evidence source becomes **edit-review results**, with the chain only an optional sink.

### A5. Demo agents and drivers (`agents/`) 🟡
- ✅ A5.1 `HonestAgent` / `SloppyAgent` plus shared `worker.py`
- ✅ A5.2 `demo_driver.py`, `multi_driver.py` (parallel and swarm beats), `seed_demo.py`, `seed_sepolia.py`, `select_escrow.py`
- 🟡 A5.3 These are simulated *job* agents. viz_trust needs adapters for **real coding agents**.

### A6. Web UI (`web/`) 🟡
- ✅ A6.1 Landing, How it works, Docs, 404 and Dashboard pages; design system in `global.css`
- ✅ A6.2 Live dashboard: agent cards, animated score, collateral curve, activity feed, risk flags, status banner
- 🟡 A6.3 Aegis branding and links (`links.js` → `Santhosh121805/Aegis_new`, `aegis-web`)
- 🟡 A6.4 Shows agent-credit data, not a call graph, findings or tier decisions

### A7. Deployment and demo tooling
- ✅ A7.1 `render.yaml` (API in chain mode + static site)
- ✅ A7.2 PowerShell multi-window demo (`scripts/demo*.ps1`)
- 🟡 A7.3 Render service names are `aegis-api` / `aegis-web`

---

## Part B. What is left (step-by-step plan)

Order follows dependencies: get the review loop working first, then trust, then visuals, then extras.
Effort is a rough guess (S ≤ 1 day, M ≈ 2–4 days, L ≈ 1+ week) for one person.

### Phase 0. Decide and clean up (S)
1. ⬜ **Decide the repo layout.** Recommended: add `engine/` (review engine + trust ledger), keep `score/` as the model service, keep `contracts/` + `oracle/` as the optional anchoring module, rework `web/`.
2. ⬜ Rewrite `SPEC.md` for viz_trust (types: `Edit`, `Finding`, `AgentIdentity`, `TrustRecord`, `Tier`, `Decision`) or split into `SPEC_AEGIS.md` and a new `SPEC.md`. Do this *before* writing code, since the old file says every file must match it.
3. ⬜ Rename leftover Aegis strings in `web/` (`links.js`, `docs.js`, `package.json`, `render.yaml`) once the new UI direction is set.
4. ⬜ Confirm baseline works on a clean machine: follow `SETUP.md`, run `pytest` and `forge test`, record the results here.

### Phase 1. Local model plumbing (S–M)
5. ⬜ Ollama client wrapper in `engine/`: health check, model name from `VIZ_TRUST_MODEL` (default `gemma4:e4b`), timeouts, retries, structured (JSON) output parsing.
6. ⬜ Prompt templates and a tiny eval set (10–20 labelled snippets) so prompt changes can be measured.
7. ⬜ Latency budget test on the demo machine (6 GB GPU, `e4b`); fall back to `e2b` if too slow.

### Phase 2. The five checks (L)
8. ⬜ Shared types and runner: input = diff plus file context plus the agent's prompt; output = list of `Finding` (check, severity, evidence, suggested fix).
9. ⬜ **Hardcode Hunter** (pattern-first: secrets, URLs with credentials, absolute paths, ports). Easiest; build first.
10. ⬜ **Test Guardian** (skipped/`.only`/always-true/deleted tests; patterns, then a model pass).
11. ⬜ **Scope Guard** (compare diff to task prompt; flag lockfile, `.env`, CI edits; model judgement).
12. ⬜ **Reality Check** (resolve imports against installed packages/lockfile and repo symbols, then model for API existence).
13. ⬜ **Impact Analyst** (needs the call graph from Phase 4; stub with simple import-based callers until then).
14. ⬜ Per-check unit tests plus a false-positive pass on a real repo.
15. ⬜ Finding actions: Fix it, Ask, Copy prompt for AI, Dismiss. Dismiss and confirm feed the trust ledger.

### Phase 3. Trust ledger and tiers (M–L)
16. ⬜ Define the new evidence signals and replace the seven Aegis features, e.g. clean-edit rate, confirmed-finding rate, false-alarm rate, broken-caller count, test-integrity events, out-of-scope rate, edit size/complexity, history length.
17. ⬜ Storage: local SQLite ledger keyed by (agent, model, repo area) with full event history and reasons.
18. ⬜ Retrain or redesign the model in `score/`. Options: keep the interpretable logistic regression on new features (needs synthetic or recorded data) **or** start with a transparent rules-plus-weights scorer and learn weights later. Keep ANCHOR = 500 for new agents.
19. ⬜ Tier logic: ≥ 800 Trusted (about 1 in 5 sampled for full review), 600–799 Standard, < 600 or new Probation. Confirmed secret leak resets to probation.
20. ⬜ **Anti-gaming**: weight edits by size/complexity (no farming on one-line edits); identity binding so a fresh agent ID cannot skip probation; reuse the Aegis lessons (band bunching, farmed top score).
21. ⬜ Cold-start smoothing (empirical-Bayes shrinkage, already on the Aegis roadmap in `SPEC.md` §10) so one early finding does not zero a thin-history agent.
22. ⬜ Port the score tests to the new features; add tier-boundary and reset tests.

### Phase 4. Call graph and blast radius (L)
23. ⬜ Port the graph builder from Blast Radius Live (language support decision: start with Python and JS/TS).
24. ⬜ Blast-radius computation (callers, transitive reach) feeding Impact Analyst.
25. ⬜ Graph API: nodes, edges, per-node trust colour, "last edit" highlight, live updates (SSE or WebSocket).

### Phase 5. Agent adapters (M–L)
26. ⬜ Engine HTTP API: `POST /review` returning `allow | hold | deny` plus findings; hold-and-approve flow.
27. ⬜ **Claude Code**: PreToolUse hook (silent if no server; dead server = allow; timeout) and an MCP server with `impact`, `hotspots`, `findings`, `fix`, `trust` tools.
28. ⬜ Open-source adapters: Aider, Cline, OpenHands behind the same adapter contract.
29. ⬜ Adapter failure-mode tests (server down, slow model, malformed response).

### Phase 6. Web UI rework (L)
30. ⬜ Live call graph (3D / 2D / heat-map toggle), edits lighting up as they land.
31. ⬜ Findings panel with the four actions and evidence.
32. ⬜ Trust view: per-agent / per-model scores, tier badge, reasons, timeline (reuse `AgentCard`, `ScoreBar`, `FactorList`, `ActivityFeed`).
33. ⬜ Hold queue for Probation edits (approve / reject).
34. ⬜ Update landing, How it works and Docs copy to viz_trust; remove or relocate the Aegis-only pages.

### Phase 7. Extras from the README (M each)
35. ⬜ **Model routing**: per-area scores, recommend a model for a task, comparison view.
36. ⬜ **Screenshot review** with Gemma 4 vision: before/after capture, diff prompt, finding output.
37. ⬜ **Optional on-chain anchoring**: adapt the oracle to publish the trust score (only if the team still wants it; it is the least central feature).

### Phase 8. Hardening and ship (M)
38. ⬜ End-to-end demo script: a "clean" agent and a "sloppy" agent editing a real repo, tiers changing live (the viz_trust equivalent of the HonestAgent/SloppyAgent demo).
39. ⬜ CI (pytest, forge test if kept, web build), pre-commit secret scan (viz_trust should pass its own Hardcode Hunter).
40. ⬜ Update `SETUP.md` "Run it" section and README Status table as each phase lands.
41. ⬜ Update deployment: decide whether anything is hosted publicly (the engine is local-first), update `render.yaml` accordingly.
42. ⬜ Demo rehearsal on the target hardware with `gemma4:e4b`.

---

## Part C. Status table (mirrors the README)

| Part | Status |
| --- | --- |
| Score service and reasons (`score/`) | 🟡 Built for Aegis; retrain on edit-review signals |
| Web UI shell and style (`web/`) | 🟡 Built for Aegis; rework for graph and trust views |
| On-chain registry and oracle (`contracts/`, `oracle/`) | 🟡 Built; optional anchoring only |
| Five checks on local Gemma 4 | ⬜ Planned (Phase 1–2) |
| Live call graph (3D / 2D / heat map) | ⬜ Planned (Phase 4, 6) |
| Claude Code hook and MCP server | ⬜ Planned (Phase 5) |
| Open-source agent adapters | ⬜ Planned (Phase 5) |
| Autonomy tiers and routing | ⬜ Planned (Phase 3, 7) |
| Screenshot review | ⬜ Planned (Phase 7) |

## Part D. Suggested critical path

`Phase 0 → 1 → 2 (checks 9–12) → 5 (steps 26–27) → 3 (16–19) → 6 (30–33) → 4 → 7`

That gives, as early as possible, a minimal end-to-end loop: Claude Code edit → hook → local review → trust
score update → tier decision → visible in the UI. The graph (Phase 4) can start as a simple import graph and be
upgraded, which is why it is later on the path despite being a headline feature.

## Part E. Risks and open questions

- **Scope of the merge:** the Blast Radius Live code is not in this repo. Is it being copied in, or rewritten? This decides how big Phases 2, 4 and 5 are.
- **Training data:** the Aegis model is trained on synthetic data only. Edit-review trust has no existing dataset, so decide between synthetic generation and a transparent hand-weighted scorer first.
- **Local model latency and accuracy:** a 6 GB GPU running `e4b` partly in RAM may be too slow for per-edit review. Measure early (step 7).
- **Blockchain relevance:** the contracts are the most self-contained part but the least tied to the new idea. Keep them optional or cut them to reduce demo risk.
- **Naming drift:** `SPEC.md`, web copy and Render service names still say Aegis.
