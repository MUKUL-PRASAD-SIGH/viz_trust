# viz_trust: Project Overview

> Companion file: [PROGRESS_PLAN.md](PROGRESS_PLAN.md) has the step-by-step record of what is built and what is left.

## 1. One-paragraph summary

**viz_trust** is a local review layer for AI coding agents. It sits beside an agent (Claude Code, Aider,
Cline, OpenHands…), reviews every edit with an open-weight model (Gemma 4 via Ollama) before it reaches
disk, keeps a **0–1000 trust score** per agent and per model, and uses that score to decide how much of
the agent's work a human must look at (**autonomy tiers**). Everything is shown on a live call graph
coloured by blast radius and trust.

The idea comes from merging two earlier projects by the same team:

| Earlier project | What it was | What viz_trust takes from it |
| --- | --- | --- |
| **Aegis** | A credit score for AI agents that hire and pay each other (on-chain registry + escrow, off-chain ML score, React dashboard) | The scoring approach, score service, oracle, web UI style, anti-gaming lessons |
| **Blast Radius Live** | A live call-graph reviewer for coding agents with five checks and a Claude Code plugin | The five checks, the graph, the hook / MCP design |

## 2. The most important thing to know about the current repo

**The code in this repository today is the Aegis codebase.** The README, SETUP.md and landing text were
rewritten for viz_trust, but the code under `contracts/`, `oracle/`, `score/`, `agents/`, `web/`, and the
`SPEC.md` file are all still Aegis (credit scoring for agents that *hire each other for jobs*). The
viz_trust-specific parts (Gemma 4 checks, call graph, hooks, autonomy tiers, routing) are described in the
README as **planned** and are **not yet in the repo**. There is no `engine/` directory yet.

So when reading this project, keep two layers apart:

- **Exists (inherited from Aegis):** a working-looking scoring pipeline, contracts, oracle, demo agents, website.
- **Vision (viz_trust proper):** the coding-agent review engine that will reuse and adapt the above.

## 3. The problem viz_trust solves

AI coding agents write code faster than people can review it. Typical failures: importing packages that
don't exist, hardcoding keys/ports, touching unrelated files, skipping or deleting tests, breaking callers
elsewhere in the repo. Today all agents get identical treatment, so you either review everything (doesn't
scale) or nothing (unsafe). A model with 200 clean edits gets no more freedom than one installed five
minutes ago.

## 4. The product vision (what viz_trust will do)

On every edit it does three things:

1. **Review locally with Gemma 4.** Five checks run on the new lines before they're written. The model runs
   on the user's machine (Ollama / llama.cpp), so code never leaves it.
2. **Update the agent's trust score** (0–1000, with reasons).
3. **Apply the autonomy tier** that the score implies.

### The five checks

| Check | Catches |
| --- | --- |
| Reality Check | Imports/APIs/functions that don't exist; wrong call signatures |
| Hardcode Hunter | Secrets, credentialed URLs, local paths, fixed ports, placeholder data |
| Scope Guard | Edits unrelated to the prompt; unrequested lockfile / `.env` / CI changes |
| Test Guardian | Skipped, `.only`, always-true or deleted tests |
| Impact Analyst | Blast radius of the change and the callers it breaks |

Cheap pattern checks run first; Gemma 4 handles the judgement calls. Each finding carries evidence and four
actions: **Fix it, Ask, Copy prompt for AI, Dismiss**.

### Autonomy tiers

| Tier | Score | Behaviour |
| --- | --- | --- |
| Trusted | 800+ | Applied immediately; all checks still run; ~1 in 5 edits gets a full review |
| Standard | 600–799 | Applied unless a high-severity finding appears, then held |
| Probation | < 600 or new | Every edit held until the human approves |

New agents start at 500 (probation). Score goes **up** on clean edits that stay clean, passing tests, and
false-alarm findings; **down** on confirmed findings, broken callers, deleted/skipped tests, out-of-scope
edits; and **resets to probation** on a confirmed secret leak.

### Other planned features

- **Model routing:** because each model has a per-area score, risky areas (auth, payments, migrations) go to
  the model with the best record there. Doubles as a model comparison based on real edits in the user's repo.
- **Visual review:** Gemma 4 is multimodal, so frontend changes are reviewed from before/after screenshots.
- **Optional on-chain anchoring:** a score can be written to a registry so an agent's record travels between repos/teams.
- **Anti-gaming:** trust can't be farmed on trivial one-line edits; fresh identities can't skip probation.

### Planned architecture

```
coding agent ─► adapter / hook ─► viz_trust engine ─► allow · hold · deny
(Claude Code,    (PreToolUse,       ├─ call graph + blast radius
 Aider, Cline…)   MCP server)       ├─ five checks (patterns + Gemma 4, local)
                                    ├─ trust ledger (per agent / per model)
                                    └─ router
                                            ▼
                                web UI: live 3D / 2D / heat-map graph,
                                findings, trust scores, timeline
```

Adapter failure rules: silent when no server runs, a dead server means "allow" (never block work), and
timeouts instead of freezing the session.

## 5. What actually exists today (the Aegis foundation)

### 5.1 The Aegis idea in brief

Aegis is a credit and dispute layer for an agent economy. Agents carry a portable score built from on-chain
job history. A high-score agent hiring another posts only partial collateral; an unknown agent prepays 100%.
If the hirer disputes a delivery, the escrow settles by a fixed rule (hirer refunded, worker unpaid, outcome
recorded against the worker) and the off-chain oracle rescores the worker. This is the machinery viz_trust
intends to reuse: *evidence in → score out → score decides how much freedom/scrutiny*.

Collateral curve (the template for the viz_trust tiers):

| Score | Upfront collateral | Band |
| --- | --- | --- |
| ≥ 800 | 20% | excellent |
| ≥ 600 | 40% | good |
| ≥ 400 | 70% | fair |
| < 400 / unknown | 100% | poor |

### 5.2 Repository map

| Path | What it is |
| --- | --- |
| `README.md` | viz_trust description and status table (rewritten for the new project) |
| `SETUP.md` | Machine setup: Ollama, Gemma 4 sizes, Python 3.12, Node 20, env files, training and running |
| `SPEC.md` | **Aegis** single source of truth for shared types, score calibration, collateral curve, roadmap. Not yet adapted to viz_trust |
| `contracts/` | Foundry project (Solidity ^0.8.20, OpenZeppelin): `AegisRegistry`, `AegisEscrow`, `MockUSDC`, `StubEscrow`, interfaces, deploy scripts, 71 Solidity test functions across 3 test files |
| `score/` | Python FastAPI scoring service, synthetic data generator, trainer, distribution checker, pytest suite |
| `oracle/` | Event watcher that bridges chain → score service → chain (`watcher.py`, `history.py`, `publisher.py`, `reasons.py`, `writer.py`, `config.py`) |
| `agents/` | Demo agents (`honest_agent.py`, `sloppy_agent.py`), shared `worker.py`, drivers (`demo_driver.py`, `multi_driver.py`), seeders (`seed_demo.py`, `seed_sepolia.py`), `select_escrow.py`, `chain.py`, `escrow.py` |
| `web/` | Vite + React site: Landing, Dashboard (`/dashboard`), How it works, Docs, 404; 30+ components; IBM Plex fonts |
| `deployments/base-sepolia.json` | Deployed Base Sepolia addresses and ABIs (chain 84532) |
| `docs/` | `architecture.svg`, `api_stub.json` (sample `/agents/state` response) |
| `scripts/` | PowerShell demo launchers (`demo.ps1`, `demo_control.ps1`, `demo_window.ps1`) |
| `render.yaml` | Render blueprint: `aegis-api` (score service in chain mode) + `aegis-web` (static site) |
| `LICENSE` | MIT |

### 5.3 Component detail

**Score service (`score/`)**
- Synthetic data (5,000 agents) → logistic regression on seven standardized features → score.
- Features: `jobs_completed`, `dispute_rate`, `avg_job_value_usd`, `account_age_days`,
  `on_time_payment_rate` (really a clean-settlement proxy), `prior_defaults`, `counterparty_diversity`
  (estimated as `0.6 × jobs` when unlabeled).
- Score is **linear in log-odds**: `score = clamp(round(500 − 144.3 × (logit − median_logit)), 0, 1000)`.
  `ANCHOR = 500` deliberately equals the starting score. The raw probability is *not* used, because it
  bunched 79% of agents into the top band.
- Explainability for free: each feature's point impact = `−FACTOR × coefficient × standardized_value`; the
  top 3 factors are returned with human-readable text.
- Reported (SPEC.md, not re-run here): test ROC AUC ≈ 0.82; band split 4.6 / 18.5 / 47.3 / 29.6 %.
- Endpoints: `GET /health`, `POST /score`, `POST /score/from-events`, `GET /agents/state`,
  `PUT /internal/agents/state` (oracle-only).
- Advisory **risk flags** (never change the score): `dispute_burst`, `serial_disputer`, `closed_ring`.
- Two data sources for `/agents/state`: the oracle's pushed snapshot, or (with `AEGIS_STATE_CHAIN`) a direct
  read of the on-chain registry with a 5 s cache. Stale-oracle detection after 10 s.
- Model files (`score/models/`, `score/data/`) are gitignored; run `generate_data.py` then `train.py`.

**Contracts (`contracts/`)**
- `AegisRegistry`: agent profiles (`score`, `jobsCompleted`, `jobsDisputed`, `defaults`, `totalValueHandled`,
  `exists`); `updateScore` only by the score oracle; `recordOutcome` only by the escrow; `requiredCollateralBps`.
- `AegisEscrow`: real USDC-style token movement; job born `Funded`; state machine
  `Funded → Delivered → Accepted → Settled` or `Delivered → Disputed → Settled`; a lost dispute refunds the hirer
  and records a default against the worker.
- Known, documented limitation: disputes are asymmetric (hirer always wins, pays nothing, isn't scored).
- `StubEscrow`: token-free fallback with the same interface.

**Oracle (`oracle/`)**
- Plain polling loop (no websockets) that survives Anvil restarts: on any reset it replays history from block 0
  and rescores any agent whose latest outcome is newer than its latest score update. The chain is the only store.
- Flow: `OutcomeRecorded` → rebuild agent history → `POST /score/from-events` → `updateScore(agent, score, reason)`
  → push a snapshot to the score service for the dashboard.

**Demo agents (`agents/`)**
- `HonestAgent` works for 3 s then delivers. `SloppyAgent` marks delivered instantly without working. The hirer
  disputes the sloppy one, its score falls, and the collateral band changes live. `multi_driver.py` adds
  `parallel` (5 jobs at once) and `swarm` (5 fresh hirers) beats. `seed_demo.py` / `seed_sepolia.py` give the
  agents prior history so scores start in sensible places.

**Web (`web/`)**
- React 18 + react-router + Vite 5. Pages: `/` (landing), `/dashboard` (polls `/agents/state`, shows agent cards,
  score animation, collateral curve, activity feed, risk flags), `/how-it-works`, `/docs`.
- Still branded Aegis: `src/content/links.js` points to `github.com/Santhosh121805/Aegis_new`, `docs.js` text,
  `package.json` name `aegis-web`.

**Deployment**
- Public read-only side on Render (`render.yaml`), reading the Base Sepolia registry
  (chain 84532; registry `0x449d…490c`, escrow `0x6626…a9c4`). The live demo (Anvil + oracle + agents) is local-only.

## 6. Tech stack

| Layer | Technology |
| --- | --- |
| Local LLM (planned) | Gemma 4 via Ollama / llama.cpp (`gemma4:e2b`, `e4b` team default, `12b`) |
| Engine / score service | Python 3.12, FastAPI, scikit-learn 1.7.2, pandas, numpy 2.2.6, pydantic |
| Chain | Solidity ^0.8.20, Foundry, OpenZeppelin, web3.py, Anvil (local), Base Sepolia (testnet) |
| Web | React 18, Vite 5, react-router-dom 6, IBM Plex fonts |
| Hosting | Render (blueprint), PowerShell scripts for the local demo |

## 7. How to run what exists

From `SETUP.md`: clone → install Ollama and pull `gemma4:e4b` → create a Python 3.12 venv and install the three
`requirements.txt` files → `cd web && npm ci` → copy `.env.example` files → `cd score && python generate_data.py && python train.py && pytest`
→ `uvicorn app:app --reload` (port 8000) and `npm run dev` (port 5173). The full chain demo uses
`scripts\demo.ps1` (needs Foundry/Anvil).

## 8. Team and license

Charithra G · Santhosh S · Sharmily H. MIT licensed. Git history: 10 commits, all on 2026-10-09 (the repo was
assembled from the Aegis work in one day).

## 9. Caveats

- This overview is from reading the code and docs. **I did not run the test suites, the model training or the
  contracts**, so statements about test counts and score metrics are taken from file contents and `SPEC.md`.
- `SPEC.md` is explicitly the "single source of truth" but describes Aegis, so it conflicts in spirit with the
  viz_trust README until it is rewritten.
