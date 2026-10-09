<div align="center">

# viz_trust

**Coding agents earn their autonomy.**<br/>
A local, open-weight review layer that scores every AI coding agent on what its edits actually did,
and decides how much of its work you need to look at.

</div>

> **Status: in development.** This README describes what we are building. The
> [Status](#status) table shows what works today and what is still planned.

## The problem

AI coding agents edit code faster than anyone can review it. They import packages that don't
exist, hardcode keys and ports, touch files unrelated to the task, skip or delete tests, and
break callers elsewhere in the repo.

Today every agent gets the same treatment no matter what it has done before. You either review
everything, which doesn't scale, or you review nothing, which isn't safe. A model that has made
200 clean edits in your repo gets no more freedom than one you installed five minutes ago, and
one that just leaked a token gets no less.

## What viz_trust does

viz_trust sits beside the agent and does three things on every edit.

1. **Reviews it locally with Gemma 4.** Five checks run on the new lines before they are written
   to disk. The model runs on your machine through Ollama or llama.cpp, so your code never leaves it.
2. **Updates the agent's trust score.** Each agent and model has a 0–1000 score built from its
   record in your repo, with the reasons behind it.
3. **Applies the agent's autonomy tier.** The score decides whether the edit goes straight
   through, gets spot-checked, or is held for you.

All of this shows up on a live call graph that lights up as edits land, coloured by blast radius
and by the trust of the agent that made each change.

### The five checks

| Check | Catches |
| --- | --- |
| **Reality Check** | Imports, APIs and functions that don't exist; mismatched call signatures |
| **Hardcode Hunter** | Secrets, credentialed URLs, local paths, fixed ports, placeholder data |
| **Scope Guard** | Edits unrelated to the prompt; unrequested lockfile, `.env` or CI changes |
| **Test Guardian** | Skipped, `.only`, always-true or deleted tests |
| **Impact Analyst** | The blast radius of each change and the callers it breaks |

Fast pattern checks run first, and Gemma 4 handles the parts that need judgement: is this import
real, is this edit in scope, does this test still test anything. Each finding comes with evidence and
four actions: **Fix it**, **Ask**, **Copy prompt for AI** and **Dismiss**.

### Trust score and autonomy tiers

The score works like a credit score. A good record earns a lighter touch, an unknown or bad
record means full review.

| Tier | Score | What happens to an edit |
| --- | --- | --- |
| **Trusted** | 800+ | Applied straight away. Every check still runs, and about 1 in 5 edits gets a full review |
| **Standard** | 600–799 | Applied unless a check finds something high-severity, which is held for you |
| **Probation** | below 600, or new | Every edit is held until you approve it |

New agents start at 500, on probation. The score moves on evidence:

- **Up:** clean edits that stay clean, tests that keep passing, findings that turn out to be false alarms.
- **Down:** findings you confirm, broken callers, deleted or skipped tests, edits outside the task.
- **Reset:** a confirmed secret leak drops the agent straight to probation.

Every score comes with its reasons, so you can see *why* an agent is on probation. The design
also defends against gaming the score. Trust can't be farmed on trivial one-line edits, and
fresh agent identities can't skip probation. See [Prior work](#prior-work) for where those
lessons come from.

### Model routing

Because every model has a score in every part of the repo, viz_trust can recommend which model
gets a task. Risky areas such as auth, payments and migrations go to the model with the best
record there. This also gives you a model comparison drawn from real edits in your own codebase
rather than from a benchmark.

### Visual review

Gemma 4 takes images as well as text. For frontend changes, viz_trust compares before and after
screenshots, so the review covers what the change looks like as well as what the code says.

## How it works

```
 coding agent ──► adapter / hook ──► viz_trust engine ──► allow · hold · deny
 (Claude Code,    (PreToolUse,        │
  Aider, Cline,    MCP server)        ├─ call graph + blast radius
  OpenHands…)                         ├─ five checks (patterns + Gemma 4, local)
                                      ├─ trust ledger (per agent / per model)
                                      └─ router
                                             │
                                             ▼
                                   web UI: live 3D / 2D / heat-map graph,
                                   findings, trust scores, timeline
```

- **Adapters.** Each agent connects through a small adapter. For Claude Code that's a PreToolUse
  hook that reviews an edit *before* it reaches disk, plus an MCP server with `impact`, `hotspots`,
  `findings`, `fix` and `trust` tools. Adapters for open-source agents follow the same contract.
- **Failure handling.** The hook stays silent when no server is running, treats a dead server as
  "allow" so it never blocks work, and times out instead of freezing the session.
- **Trust ledger.** Stored locally by default. Optionally, scores can be anchored on-chain so an
  agent's record goes with it from one repo or team to the next.

## Status

| Part | Status |
| --- | --- |
| Score service and reasons (`score/`) | Exists, from Aegis. To be retrained on edit-review signals |
| Web UI shell and style (`web/`) | Exists, from Aegis. To be reworked for the graph and trust views |
| On-chain trust registry (`contracts/`, `oracle/`) | Exists, from Aegis. Optional anchoring only |
| Five checks on local Gemma 4 | Planned |
| Live call graph (3D / 2D / heat map) | Planned, porting from Blast Radius |
| Claude Code hook and MCP server | Planned, porting from Blast Radius |
| Open-source agent adapters (Aider, Cline, OpenHands) | Planned |
| Autonomy tiers and routing | Planned |
| Screenshot review | Planned |

## Run it

Setup instructions will be added as each part lands. The planned requirements are:

- [Ollama](https://ollama.com) with a Gemma 4 model pulled
- Python 3.11+ for the engine and score service
- Node 20+ for the web UI

## Models and key dependencies

- **Gemma 4** (open-weight), served locally through Ollama or llama.cpp, for the review checks and screenshot review
- Python · FastAPI · scikit-learn for the engine and trust scoring
- React · Vite for the web UI
- Solidity · Foundry · web3.py for the optional on-chain registry

## Prior work

viz_trust combines two earlier projects by the same team.

- **Aegis** was a credit score for AI agents that hire and pay each other. A good score meant a
  20% deposit, an unknown one meant 100%, and scores lived on-chain. viz_trust reuses its scoring
  approach, its UI style, and the anti-gaming lessons it taught us: scores that bunched into one band
  until we changed the risk mapping, and a fresh wallet that farmed a top score on tiny jobs until we
  blocked it.
- **Blast Radius Live** was a live call-graph reviewer for coding agents, with five checks and a
  Claude Code plugin. viz_trust reuses its checks, graph and hook design, and moves the reasoning onto
  a local open-weight model.

**New in viz_trust:** trust scores for coding agents, autonomy tiers, model routing, local Gemma 4
review, screenshot review, and support for open-source agents.

## Presented to you by <3

Charithra G | Santhosh S | Sharmily H

## License

To be added: an OSI-approved open-source license.
