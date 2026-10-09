# Person A: frontend and visualisation

**No Gemma needed.** You own everything the user sees on `/dashboard`. Read the
[shared contract](README.md#the-shared-contract) first.

**Branch:** `a/frontend`. **Works in:** `web/`, `docs/api_stub.json`.

## The rule

Don't redesign anything. Landing, How it works, Docs, the nav, `global.css` tokens and the existing
components stay as they are. You **add** to `/dashboard`, and new components reuse the existing
look: `card`, `spec-head`, `MicroLabel`, `BandPill`, IBM Plex Mono and the colour tokens
(`--accent`, `--danger`, `--warning`). No new fonts, no new colour palette, no UI library.

## Tasks

### 1. Stub data, so you can start now
- [ ] Extend `docs/api_stub.json` with the contract's new fields: `tier` and `model` on each agent,
      plus `graph`, `findings` and `pending`. Write it as a believable demo: three agents (one each in
      probation, standard and trusted), about 15 graph nodes in 3–4 files, two findings, and one
      pending edit.
- [ ] Check the current components still render with `?stub=1`.

### 2. Graph panel: `components/BlastGraph.jsx`
- [ ] A 2D force-directed call graph built from `graph.nodes` and `graph.edges`. Use
      `react-force-graph-2d`, or `d3-force` drawn in SVG. Pick one and note why in the PR.
- [ ] Group nodes by file: a colour per file, or a light cluster outline.
- [ ] `last_edit.touched` nodes glow in `--accent`. `last_edit.blast` nodes pulse once, in a ripple
      outward by caller depth.
- [ ] Node size or brightness follows `heat`.
- [ ] Colour the touched node by the trust tier of `last_agent`.
- [ ] Hover shows the function name, file and who last edited it.
- [ ] Respect `prefers-reduced-motion`: no pulse animation, just a static highlight.

### 3. Findings panel: `components/FindingsPanel.jsx`
- [ ] Lists `findings`, newest first: severity dot, check name, `file:line`, message, evidence in mono.
- [ ] A small "pattern" or "gemma" tag from `source`.
- [ ] **Confirm** and **Dismiss** buttons call `POST /findings/{id}/verdict`.
- [ ] Clicking a finding highlights its node on the graph.

### 4. Held-edit dialog: `components/HeldEditDialog.jsx`
- [ ] Opens when `pending` isn't empty. Shows the agent, file, `+added −removed`, the reason, the
      blast count, the diff (monospace, coloured `+` and `−` lines) and any linked findings.
- [ ] **Approve** and **Deny** call `POST /decisions`. Close when the edit leaves `pending`.
- [ ] Keyboard: Esc doesn't approve. Enter doesn't approve either, because approving must be a
      deliberate click.

### 5. Wire it into the dashboard
- [ ] In `pages/Dashboard.jsx`, add a "Blast radius / live" section between the agent grid and the
      activity feed, with the graph on the left and findings on the right. Stack them on narrow
      screens.
- [ ] Add `web/src/lib/api.js` helpers for the three POST endpoints, next to the existing `STATE_URL`.

### 6. Tier wording on the existing card (small text changes only)
- [ ] `AgentCard`: show `tier` next to the score, relabel "Collateral" as "Edits reviewed", and show
      `model` under the agent name.
- [ ] `ActivityFeed`: no layout change. Just make sure the new event types read well.
- [ ] Map tiers to the existing band colours (see the README's tier table).

### 7. Stretch
- [ ] A 3D toggle using `react-force-graph-3d`, with the same data.
- [ ] A heat-map toggle: a file × function grid coloured by `heat`.

## You depend on
- **M** for the real engine at `:8100`. Until then, use `?stub=1`.

## Done when
- [ ] `/dashboard?stub=1` shows all three new panels with the stub data, and nothing else on the
      site looks different.
- [ ] `/dashboard?api=http://127.0.0.1:8100` updates live while M's demo driver runs.
- [ ] Approve, Deny, Confirm and Dismiss all work against the real engine.
- [ ] `npm run build` passes.
