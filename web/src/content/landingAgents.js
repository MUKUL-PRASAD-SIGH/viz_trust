// The landing page's agent cards. Static on purpose -- the live version is /dashboard -- but
// read from docs/api_stub.json at build time so the numbers can never drift from the demo.
import stub from "../../../docs/api_stub.json";
import { EVENT_LABELS, shortAddress, signed } from "../lib/format.js";
import { FLASHCARD_QUOTES } from "./flashcards.js";

const JOB_USD = 500;
const byName = Object.fromEntries(stub.agents.map((agent) => [agent.name, agent]));

function collateral(agent) {
  if (agent.required_collateral_bps === 10000) return `[100% / full $${JOB_USD} upfront]`;
  const dollars = (JOB_USD * agent.required_collateral_bps) / 10000;
  return `[${agent.required_collateral_pct} / $${dollars} on a $${JOB_USD} job]`;
}

function lastJob(agent) {
  const event = agent.recent_events[0];
  return `[${signed(event.delta)} / ${EVENT_LABELS[event.type]}]`;
}

function card(name, fields) {
  const agent = byName[name];
  return {
    name,
    band: agent.band,
    path: shortAddress(agent.address),
    fields: [["Credit score", String(agent.score)], ...fields(agent)],
    footer: `1 of ${stub.agents.length} agents on the live network`,
  };
}

export const LANDING_AGENTS = [
  card("Hirer", (a) => [
    ["Deposit", collateral(a)],
    ["Settlement", "[USDC/BASE]"],
  ]),
  card("HonestAgent", (a) => [
    ["Last job", lastJob(a)],
    ["Deposit", collateral(a)],
  ]),
  card("SloppyAgent", (a) => [
    ["Last job", lastJob(a)],
    ["Deposit", collateral(a)],
  ]),
];

// Same three agents, shaped for the flashcard section: real score/band/delta plus a quote.
export const FLASHCARD_AGENTS = ["Hirer", "HonestAgent", "SloppyAgent"].map((name) => {
  const agent = byName[name];
  return {
    name,
    band: agent.band,
    path: shortAddress(agent.address),
    score: agent.score,
    delta: agent.recent_events[0].delta,
    quote: FLASHCARD_QUOTES[name],
  };
});
