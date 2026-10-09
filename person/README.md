# Prototype plan: who builds what

The goal is a working demo of the core idea. A coding agent makes edits, viz_trust reviews each
one, the agent's trust score moves, and the dashboard shows it all live on a call graph.

| Person | Area | Uses Gemma? | Task file |
| --- | --- | --- | --- |
| **A** | Frontend and visualisation | No | [person_a.md](person_a.md) |
| **M** | Engine backend: events, scoring, pattern checks, demo driver | No | [person_m.md](person_m.md) |
| **C** | Gemma checks and evaluation | **Yes** | [person_c.md](person_c.md) |

Machine setup for everyone: [SETUP.md](../SETUP.md).

---

## The end goal

### What the demo shows

1. A new agent starts at **500, Probation**. Every edit it makes is held for approval.
2. It makes a clean edit. The touched function lights up on the graph, its callers ripple out, and
   the edit waits for **Approve**. Approving raises the score, with a reason.
3. After more clean edits it reaches **Standard** (600+), and clean edits go through by themselves.
4. It writes a hardcoded Slack token and imports a package that doesn't exist. The edit is
   **blocked**, two findings appear with the exact lines, and the agent drops back to **Probation**.

### The one UI rule

**Don't redesign the existing UI.** The landing page, How it works, Docs, the nav, the styles and the
existing components stay as they are. The only page that changes is **`/dashboard`**, and it changes
by *adding* a panel, not by restyling.

### Dashboard layout

```
┌────────────────────────────────────────────────────────────────────────┐
│ Nav                                              ● live (LiveStatus)   │  unchanged
├────────────────────────────────────────────────────────────────────────┤
│ StatusBanner                                                           │  unchanged
├────────────────────────────────────────────────────────────────────────┤
│ Agents / live network                                                  │
│ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐                     │  AgentCard, reused:
│ │ aider·e4b    │ │ claude-code  │ │ ...          │                     │  score + tier +
│ │ 500 PROBATION│ │ 812 TRUSTED  │ │              │                     │  reasons + "edits
│ │ review 100%  │ │ review 20%   │ │              │                     │  reviewed" %
│ └──────────────┘ └──────────────┘ └──────────────┘                     │
├────────────────────────────────────────────────────────────────────────┤
│ NEW: Blast radius / live                                               │
│ ┌──────────────────────────────────────────┐ ┌───────────────────────┐ │
│ │                                          │ │ Findings              │ │
│ │     call graph (2D)                      │ │ ● HIGH Hardcode Hunter│ │
│ │     touched node = glows                 │ │   signup.py:14 xoxb-… │ │
│ │     callers = ripple, coloured by        │ │   [Confirm] [Dismiss] │ │
│ │     the trust of the agent that edited   │ │ ● HIGH Reality Check  │ │
│ │                                          │ │   slack_notify_pro    │ │
│ └──────────────────────────────────────────┘ └───────────────────────┘ │
├────────────────────────────────────────────────────────────────────────┤
│ Live activity (ActivityFeed, reused: edit events with reasons)         │  unchanged
└────────────────────────────────────────────────────────────────────────┘

 NEW: held-edit dialog, shown over the page when an edit is waiting:
 ┌─────────────────────────────────────────────┐
 │ Held · probation tier · aider·e4b           │
 │ app/signup.py  +12 −3   blast radius: 3     │
 │ (diff)                                      │
 │ findings: 0                                 │
 │              [Deny]  [Approve]              │
 └─────────────────────────────────────────────┘
```

How the tiers fit the existing card:

| Tier | Score | Shown in the card's existing % field | Card band colour |
| --- | --- | --- | --- |
| Trusted | 800+ | "20% of edits reviewed" | excellent |
| Standard | 600–799 | "high-severity edits held" | good |
| Probation | below 600 | "100% of edits reviewed" | fair / poor |

### How the pieces connect

```
 demo driver / Claude Code hook ──POST /edits──►  engine (FastAPI, :8100)  ◄── Gemma checks (C)
                                                   │  SQLite event log
                                                   │  pattern checks, graph, score, tier (M)
 dashboard (:5173) ──GET /agents/state (poll)────► │
                   ──POST /decisions, /verdicts──► │
```

The dashboard already polls `GET /agents/state`, and `?api=` already changes the server it polls.
So the engine serves **the same endpoint in the same shape, plus three new fields**, and the
existing components keep working unchanged. Open the demo at:

```
http://127.0.0.1:5173/dashboard?api=http://127.0.0.1:8100
```

---

## The shared contract

**This section is the source of truth between A, M and C.** If it needs to change, change it here
first, in its own commit, and tell the other two.

### `GET /agents/state`

Same fields as today (see `docs/api_stub.json`), so `AgentCard`, `ActivityFeed`, `LiveStatus` and
`StatusBanner` keep working. What changes:

- `source` is `"engine"`.
- Each agent gains `tier` (`"probation" | "standard" | "trusted"`), `model` (e.g. `"gemma4:e4b"`)
  and `spot_check` (true when the next edit from a trusted agent gets a full review).
- `address` is a stable agent id string, e.g. `"aider:gemma4:e4b"`.
- `required_collateral_pct` now means the **share of edits reviewed**.
- `recent_events[].type` is one of `edit_clean`, `edit_held`, `edit_blocked`, `finding_confirmed`,
  `finding_dismissed`, `tier_changed`. `reason` and `delta` work as before.
- `top_factors` lists the reasons behind the score, as before.

New top-level fields:

```jsonc
{
  "graph": {
    "nodes": [
      { "id": "app/signup.py::handle_signup", "file": "app/signup.py", "label": "handle_signup",
        "heat": 0.8,                         // 0–1, how recently and how often it was edited
        "last_agent": "aider:gemma4:e4b" }
    ],
    "edges": [ { "source": "app/routes.py::signup", "target": "app/signup.py::handle_signup" } ],
    "last_edit": {
      "edit_id": "e_0007",
      "touched": ["app/signup.py::handle_signup"],   // functions the edit changed
      "blast":   ["app/routes.py::signup"]           // their callers, direct and indirect
    }
  },
  "findings": [
    { "id": "f_0003", "edit_id": "e_0007",
      "check": "hardcode_hunter",            // reality_check | hardcode_hunter | scope_guard
                                             // | test_guardian | impact_analyst
      "severity": "high",                    // critical | high | medium | low
                                             // critical hardcode_hunter = real secret
      "source": "pattern",                   // pattern | gemma
      "file": "app/signup.py", "line": 14,
      "area": "auth",                        // see the area list in TODO.md
      "message": "Slack bot token hardcoded",
      "evidence": "token = \"xoxb-…\"",
      "status": "open" }                     // open | confirmed | dismissed
  ],
  "pending": [
    { "edit_id": "e_0008", "agent": "aider:gemma4:e4b",
      "file": "app/signup.py", "area": "auth", "added": 12, "removed": 3,
      "diff": "@@ -10,3 +10,12 @@ …",
      "reason": "probation tier",            // why it was held
      "blast_count": 3,
      "finding_ids": [] }
  ]
}
```

### Write endpoints

| Endpoint | Body | Who calls it |
| --- | --- | --- |
| `POST /edits` | `{agent, model, prompt, file, before, after}` → `{edit_id, decision: "allow"\|"hold"\|"deny", finding_ids}` | demo driver, hook |
| `GET /edits/{edit_id}` | → `{decision}` (the hook polls this while an edit is held) | hook |
| `POST /decisions` | `{edit_id, decision: "approve"\|"deny"}` | dashboard dialog |
| `POST /findings/{id}/verdict` | `{verdict: "confirm"\|"dismiss"}` | dashboard findings panel |

### The Gemma check interface (between M and C)

C writes this function and M calls it. Until C's version lands, M uses a stub that returns `[]`.

```python
# engine/checks/gemma_checks.py
def review(edit: Edit, timeout_s: float = 8.0) -> list[Finding]:
    """Gemma judgement checks. Never raises: on any failure returns [] and logs why."""
```

`Edit` and `Finding` are defined in `engine/models.py` (M owns it) and match the JSON above.

The fixed vocabularies (`check`, `severity`, `source`, `tier`, `area`, `decision`) and the shared
rules are listed in [TODO.md](../TODO.md#fixed-vocabularies-everyone-uses-exactly-these-strings).

---

## Order of work

| Step | A | M | C |
| --- | --- | --- | --- |
| 1 | Extend `docs/api_stub.json` with the new fields; build against `?stub=1` | Engine skeleton serving the contract with fake data | Gemma client: structured output, timeout, retry |
| 2 | Graph panel | Event log, scoring, tiers | Scope Guard + Reality Check judgement |
| 3 | Findings panel, held-edit dialog | Pattern checks, graph builder, blast radius | Test Guardian, Fix-it prompts |
| 4 | Card and feed wording for tiers | Demo driver | Evaluation set, precision / recall / latency |
| 5 | **Integration:** all three run the demo end to end on one machine | | |
| 6 | Stretch: 3D view | Stretch: Claude Code hook | Stretch: screenshot review |

Because A works against the stub and M works against a stubbed Gemma, **nobody waits on anyone**
until step 5.

## Working rules

- One branch per person: `a/frontend`, `m/engine`, `c/gemma`. Open pull requests into `main`.
- Never commit `.env`, keys, `.venv/`, `node_modules/` or model files.
- Each task file ends with a **Done when** list. Tick it off in the PR description.
