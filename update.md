# Update from A (frontend) to M (contract holder)

**To:** M, who owns `engine/models.py` and the shared contract in `person/README.md`.
**From:** A. **Branch:** `a/frontend`. **Date:** 2026-10-09.

I haven't edited `person/README.md` or `TODO.md`. The contract rule says changes go there first, in
their own commit, so the changes below are for you to make. Reply in this file, or commit the
contract change and I'll match it.

## 1. What I changed (so you know what the UI now expects)

- **`docs/api_stub.json`** now has the full contract shape: `tier`, `model` and `spot_check` on each
  agent, plus `graph`, `findings` and `pending`. **It is the best reference for the exact JSON I read.**
  Please make the engine's `/agents/state` match it.
- **New page `/blast-radius`**, with a **"Blast radius" link in the nav, right after Overview.** It
  holds the call graph, and soon the findings panel and held-edit dialog. This goes beyond the rule
  "only `/dashboard` changes" in `TODO.md` and `person/README.md`. It was agreed with Arjit, so
  please update that rule and the dashboard layout section.
- **New component `BlastGraph.jsx`** (2D call graph, drawn with `d3-force`, a new dependency in
  `web/package.json`).
- `/dashboard` is unchanged for now. The only planned change is the tier wording on `AgentCard`.

## 2. Contract changes I need (please decide and commit)

| # | Change | Why | My suggestion |
| --- | --- | --- | --- |
| 1 | Add an optional **`node`** to each finding: the id of the graph node it sits in, e.g. `"app/signup.py::handle_signup"`. `null` when the finding is about the whole file. | Clicking a finding must highlight its node. With only `file` and `line` I can't tell which function it belongs to. | Pattern checks already know the line, so find the function that encloses it with `ast`. Unknown fields are ignored, so this is safe for anyone not using it. |
| 2 | Say what **`required_collateral_pct`** holds for the **standard** tier. | The contract says "share of edits reviewed", but standard only holds high-severity edits, so there is no honest percentage. | Use the text `"high-severity only"` for standard, with `required_collateral_bps` at `4000`. I used this in the stub. Probation is `"100%"` and trusted is `"20%"`. |
| 3 | Send **`oracle_live: true`** from the engine. | `StatusBanner` shows a warning whenever `source` isn't `"stub"` and `oracle_live` is falsy. | Keep sending `true` while the engine is up. Otherwise tell me and I'll change the banner. |
| 4 | Fix the **edge direction**: `source` is the **caller**, `target` is the function it calls. | I work out the ripple depth from this direction. Reversed edges would send the ripple to callees instead of callers. | Write it into the contract. The stub follows it. |
| 5 | **`last_edit.blast`** must be the **complete list of transitive callers** of `touched`, not only direct ones. | I compute the ripple depth from `edges`, and I draw blast nodes from this list. | The stub's blast list matches what the graph gives. I checked it in code. |
| 6 | **`graph.nodes[].last_agent`** must equal an agent's **`address`**, or be `null`. | I look the agent up by address to get its tier and name. | Same ids the engine uses in `/agents/state`. |
| 7 | Give me the **final list of `top_factors[].feature` names**. | `FactorList` turns a feature name into a label. Unknown names show raw, like `secret_leak`. | The stub uses `secret_leak`, `high_severity_findings`, `clean_edit_rate`, `edits_reviewed`, `broken_callers`. Send me the real list and I'll add the labels. |

### Added after building the findings panel, held-edit dialog and card wording

| # | Change | Why | My suggestion |
| --- | --- | --- | --- |
| 8 | Add **`previous_tier`** to each agent, next to `previous_score` and `previous_band`. | The card shows "was standard" when a tier changes. Guessing it from `previous_band` is wrong: probation and standard can share a band. | Same three values as `tier`. If it is missing I fall back to `previous_band`. |
| 9 | Make **`edit_id`** and finding **`id`** **zero-padded and fixed width** (`e_0007`, `f_0003`). | The findings panel sorts newest first by comparing `edit_id` as text. `e_10` would sort before `e_9`. | Pad to at least 4 digits, as in the contract examples. |
| 10 | **CORS must allow `POST` with a JSON `Content-Type`** from `http://127.0.0.1:5173`. | `POST /decisions` and `POST /findings/{id}/verdict` send `Content-Type: application/json`, so the browser sends a preflight `OPTIONS` first. | `allow_methods=["GET","POST"]`, `allow_headers=["Content-Type"]`. |
| 11 | **`pending[].agent`** is the agent's **`address`**, the same id as in `agents[]`. | I look the agent up by it to show its name. | The stub follows this. |
| 12 | After **`POST /decisions`**, the edit must **leave `pending`**, and after **`POST /findings/{id}/verdict`** the finding's **`status`** must change. | I update the screen at once, but the next 1.5 s poll replaces it with what the engine says. If the engine hasn't changed, the panel flips back. | Write to the log first, then respond. |
| 13 | **Optional: `pending[].expires_at`** (ISO time). | Held edits time out after 120 s and count as denied. Without it I can't show a countdown, and the dialog may show an edit that is already gone. | Nice to have. Not needed for the first demo. |

What the UI does with those endpoints, so you can test against it:
`POST /findings/{id}/verdict` body `{"verdict": "confirm" | "dismiss"}`, and `POST /decisions`
body `{"edit_id": "...", "decision": "approve" | "deny"}`. A non-2xx response shows
"Couldn't send that to the engine" and leaves the item on screen so you can retry.

## 3. Smaller notes, no decision needed

- **Agent ids.** The stub uses `address: "aider:gemma4:e4b"`, `name: "Aider"` and `model: "gemma4:e4b"`.
  The card currently shortens the id to `aider:…:e4b`, and I'll change that to show `name` and `model`.
  Please keep `name` and `model` as separate fields.
- **Event types.** I read `edit_clean`, `edit_held`, `edit_blocked`, `finding_confirmed`,
  `finding_dismissed` and `tier_changed`, as the contract lists. `ActivityFeed` also reads
  `reason`, `delta` and `timestamp` (ISO 8601). I added an optional `edit_id` to events in the stub.
- **Removed from the stub:** `chain_id` and `block`. `LiveStatus` only shows them when present.
- **Polling.** The dashboard polls `/agents/state` every 1.5 s and the page now carries the whole
  graph. That is fine for the sample repo. Tell me if it grows large and we can add a separate
  `/graph` endpoint.
- **Held edits and findings** are on `/blast-radius`, not `/dashboard`. The dialog opens when `pending` is
  not empty. Esc or "Decide later" hides it, a banner brings it back, and the edit stays pending.
- **`/dashboard` changes so far:** wording only. The card shows the model, the tier pill, "Trust
  score" and "Edits reviewed". The live label reads `ENGINE LIVE` when `source` is `"engine"`.

## 4. What I need from you

1. Make the contract changes in section 2 (or tell me which ones you disagree with).
2. Say when the engine can serve `/agents/state` with fake data, so I can switch from `?stub=1` to
   `?api=http://127.0.0.1:8100`.
3. Confirm the findings panel and held-edit dialog stay on `/blast-radius`. That is what I built.
