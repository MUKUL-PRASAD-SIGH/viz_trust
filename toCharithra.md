# To Charithra: frontend status and what I need from you

**From:** A (frontend and visualisation). **Branch:** `a/frontend`, not pushed or committed yet.
**Date:** 2026-10-09.

I'm writing this to you because you wrote the three-person plan and the shared contract in
`person/README.md`, so I'm assuming you own the contract. If someone else does, please pass it on.
The line-by-line contract requests are in [`update.md`](update.md). This file is the summary, and
tells you what to do.

## 1. What is done

All six of A's tasks from `person/person_a.md` are built, and they work against the stub.

| Task | Done | Where |
| --- | --- | --- |
| 1. Stub data | Three agents (probation, standard, trusted), a 16-node graph in 5 files, three findings, one held edit | `docs/api_stub.json` |
| 2. Graph panel | 2D call graph. The edited function glows in its agent's tier colour, callers ripple outward by distance, files are clustered, size follows heat, hover shows details. Respects reduced motion | `web/src/components/BlastGraph.jsx` |
| 3. Findings panel | Newest first, severity, check, `file:line`, evidence, pattern/gemma tag. Clicking highlights the node. Confirm and Dismiss call the engine | `FindingsPanel.jsx` |
| 4. Held-edit dialog | Diff with coloured lines, reason, blast count, linked findings. Approve and Deny need a click. Enter does not approve. Esc hides it and the edit stays pending | `HeldEditDialog.jsx` |
| 5. Wiring | New **`/blast-radius` page with a "Blast radius" link right after Overview in the nav**, holding the graph, findings and dialog. POST helpers in `lib/api.js`. A clear message when the engine is unreachable | `pages/BlastRadius.jsx`, `Nav.jsx`, `App.jsx`, `lib/api.js`, `hooks/useAgentsState.js` |
| 6. Card wording | Model under the agent name, tier pill, "Trust score", "Edits reviewed", "was standard" when the tier changes, labels for the new factor names, `ENGINE LIVE` status | `AgentCard.jsx`, `BandPill.jsx`, `LiveStatus.jsx`, `StatusBanner.jsx`, `format.js` |

Not done from A's stretch list: the 3D view, the heat-map view, the model comparison view and the
score history chart.

**One decision I made that changes the plan.** You wrote "don't redesign the UI, only `/dashboard`
changes". On Arjit's instruction I added a **new page and a new nav link**, and put the graph,
findings and held-edit dialog there instead of on `/dashboard`. `/dashboard` only got wording
changes. `TODO.md` and `person/README.md` still say the old thing, so please update them (section 3).

**How I checked it.** `npm run build` passes. I ran the pages in a simulated browser (jsdom): 23
checks pass, covering the graph, Esc and Enter on the dialog, Approve, Confirm, finding selection,
the new card wording and the nav order. I also drew the graph to an image and checked the layout.
**I have not seen it in a real browser**, so hover, the animations and the overall look still need
someone to open it.

## 2. How to see it

```bash
cd web
npm ci            # picks up the new d3-force dependency
npm run dev
```

- <http://127.0.0.1:5173/blast-radius?stub=1> is the new page.
- <http://127.0.0.1:5173/dashboard?stub=1> is the dashboard with the new card wording.
- In stub mode the buttons update the screen locally but send nothing.

When the engine exists, use `?api=http://127.0.0.1:8100` instead of `?stub=1`.

## 3. What you need to do

### a. Decide the contract changes (about 15 minutes)

`update.md` lists 13 numbered changes with a reason and a suggestion for each. The ones that block
integration:

- **Findings get an optional `node`** (the graph node id), or clicking a finding can't highlight anything.
- **`oracle_live: true`** must come from the engine, or the status banner shows a false warning.
- **Edge direction is caller to callee**, and **`last_edit.blast` lists all transitive callers.** My
  ripple depends on both.
- **`previous_tier`** on each agent, and **zero-padded `edit_id` and finding `id`**.
- **CORS must allow `POST` with a JSON body** from `http://127.0.0.1:5173`.
- **Your call:** what `required_collateral_pct` says for the standard tier. I used `"high-severity only"`.
- **Your call:** the final names for `top_factors[].feature`. I used `secret_leak`,
  `high_severity_findings`, `clean_edit_rate`, `edits_reviewed`, `broken_callers`.

Please commit the agreed contract to `person/README.md` in its own commit, as its own rule says, and
tell me what changed.

### b. Update the plan documents

- `TODO.md` and `person/README.md`: replace "only `/dashboard` changes" with the new page and link.
- `person/README.md`: redraw the dashboard layout section. The Blast radius panel is now its own page.
- `person/person_a.md`: tick off the finished tasks and note the new page.

### c. Build your own part

The frontend only needs three things from the engine, and `docs/api_stub.json` is the exact shape:

1. **`GET /agents/state`** returns the stub's shape, with `source: "engine"`. It can serve hard-coded
   data first, so I can switch from `?stub=1` early.
2. **`POST /findings/{id}/verdict`** with `{"verdict": "confirm" | "dismiss"}` and
   **`POST /decisions`** with `{"edit_id": "...", "decision": "approve" | "deny"}`. After either one,
   the next `/agents/state` must show the change (the finding's `status`, or the edit leaving
   `pending`). Otherwise the next poll undoes what the user just did.
3. Keep `graph.nodes[].last_agent` equal to an agent's `address`, and `pending[].agent` too.

Beyond that, your task list is unchanged. If you are **M**, that means the engine, event log, score,
tiers, pattern checks, call graph and demo driver. If you are **C**, it is the Gemma checks and the
evaluation set.

### d. Integration, when the engine serves real data

1. Open `/blast-radius?api=http://127.0.0.1:8100` while the demo driver runs.
2. Check that the graph updates and the four demo beats play: new agent held, clean edits earn
   Standard, the Slack-token edit is blocked, the agent drops back to probation.
3. Click Approve, Deny, Confirm and Dismiss, and check each moves the score.
4. Tell me what looks wrong. The data flow is already in place, so most fixes should be small.

## 4. Things to know

- **Merging:** my changes are in `docs/api_stub.json`, `web/` (new files plus edits to six existing
  files), `update.md` and this file. Please keep `web/` and `docs/api_stub.json` to me, so we don't
  conflict. The `web/package.json` change is one new dependency, `d3-force`.
- **No new design system:** I reused the existing colour tokens, fonts and card styles. The graph
  is drawn in plain SVG.
- **Held edits only show on `/blast-radius`.** If someone is on `/dashboard` when one arrives, nothing
  tells them. A nav badge would fix that if you want it.
- **Gemma:** the frontend never calls Gemma. The `ollama pull gemma4:e4b` download of 9.5 GB failed
  once on a network error and was restarted. I have not confirmed it finished, so check with
  `ollama list`. (`SETUP.md` says 6.6 GB, which is out of date.)
- **Leftover Aegis strings** in `web/` (`links.js`, `docs.js`, `package.json`, the AEGIS nav brand)
  are untouched. They are in the "Later" list.
