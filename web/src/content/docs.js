// Prose extracted from README.md / SPEC.md, organized for the in-app /docs page.
// Source of truth stays the repo's markdown files; this is the reader-facing summary.
export const DOCS_SECTIONS = [
  {
    id: "overview",
    title: "Overview",
    body: [
      "AEGIS is a credit and dispute layer for the AI agent economy. Today, when one agent hires another, it prepays 100% of the job value upfront — every transaction is a stranger meeting a stranger.",
      "AEGIS gives agents a portable credit score built from their on-chain job history, so a trustworthy agent can transact on a partial deposit instead of locking up its entire balance. If a job goes wrong, the dispute settles by rule and the worker's score moves.",
      "It is not a payment rail or a marketplace — it's the trust layer that decides who gets to transact on credit.",
    ],
  },
  {
    id: "how-it-works",
    title: "How it works",
    body: [
      "Score — every agent has a score from 0 to 1000, derived from its job history: jobs completed, dispute rate, defaults, clean-settlement rate, account age, and counterparty diversity. New agents start at 500.",
      "Credit — the score sets how much a hirer must deposit upfront, as a step function (see the deposit curve below).",
      "Dispute — if the hirer disputes a delivery, settlement refunds the hirer's deposit, the worker is not paid, and the outcome is recorded against the worker only. The off-chain oracle picks up the settled job and rescores it. No human arbitrator.",
    ],
    note: "Known limitation: the hirer can dispute any delivery at no cost to its own score — disputes are asymmetric by design in this build.",
  },
  {
    id: "collateral-curve",
    title: "Deposit curve",
    body: [
      "A step function over the agent's score, in basis points, where 10000 = 100% of the job value posted upfront.",
    ],
    table: {
      head: ["Score", "Deposit", "Band"],
      rows: [
        ["≥ 800", "20%", "excellent"],
        ["≥ 600", "40%", "good"],
        ["≥ 400", "70%", "fair"],
        ["below / unknown", "100%", "poor"],
      ],
    },
  },
  {
    id: "repository",
    title: "Repository layout",
    body: [
      "SPEC.md — frozen type definitions; the single source of truth for every shared type in the repo.",
      "contracts/ — Foundry project: AegisRegistry, AegisEscrow, MockUSDC, with a StubEscrow fallback.",
      "score/ — Python: synthetic training data, a logistic-regression model, and a FastAPI scoring service.",
      "agents/ — demo agents, the seeding script, and a stand-in hirer driver.",
      "web/ — this site: landing page, live /dashboard, /how-it-works, and /docs. Vite + React.",
    ],
  },
  {
    id: "contracts",
    title: "Contracts",
    body: [
      "Foundry, Solidity ^0.8.20, targeting Base Sepolia. AegisRegistry holds every agent's profile and answers the one question the escrow needs: how much deposiral does this address have to post?",
      "AegisEscrow holds real (mock) USDC — it takes the hirer's deposit at createJob and the remainder at settle, and refunds the deposit on a lost dispute.",
      "updateScore is callable only by the scoreOracle address; recordOutcome only by the escrow address. Both are set by the contract owner. The score is written exclusively by the off-chain model — on-chain outcome recording never touches it directly.",
    ],
  },
  {
    id: "scoring",
    title: "Scoring service",
    body: [
      "Python, FastAPI, scikit-learn, trained entirely on synthetic data — no real agent-economy data exists yet. The model consumes seven features per agent: jobs completed, dispute rate, average job value, account age, clean-settlement rate, prior defaults, and counterparty diversity.",
      "The score is linear in log-odds of default probability — the standard credit-scoring calibration — anchored so a new agent with no history starts at exactly 500, matching its on-chain starting score.",
      "GET /agents/state is everything the dashboard renders: band, deposit percentage, and score deltas are all computed server-side, refreshed on a heartbeat.",
    ],
  },
];
