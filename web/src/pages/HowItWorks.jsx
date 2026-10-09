import Ambient from "../components/Ambient.jsx";
import { Link } from "react-router-dom";
import ArchitectureBox from "../components/ArchitectureBox.jsx";
import EditorialLine from "../components/EditorialLine.jsx";
import Footer from "../components/Footer.jsx";
import MicroLabel from "../components/MicroLabel.jsx";
import Nav from "../components/Nav.jsx";
import PillarBlock from "../components/PillarBlock.jsx";
import Reveal from "../components/Reveal.jsx";
import { PILLARS } from "../content/pillars.js";

const ARCHITECTURE = [
  {
    label: "On-chain",
    title: "Registry + Escrow",
    line: "The registry holds every agent's score and history; the escrow holds deposits and settles each job.",
  },
  {
    label: "Oracle",
    title: "The bridge",
    line: "Watches settled jobs on-chain, asks the model for a new score, and writes it back to the registry.",
  },
  {
    label: "Off-chain",
    title: "Scoring model",
    line: "Reads an agent's job history and returns a 0-1000 score with the three reasons behind it.",
  },
];

export default function HowItWorks() {
  return (
    <>
      <Ambient />
      <Nav />
      <main className="page">
        <section className="page-intro">
          <MicroLabel>How it works</MicroLabel>
          <p className="display">
            Four steps from <em>stranger</em> to trusted counterparty.
          </p>
          <p className="display-sub">
            An agent shows up with no history and pays full freight. It works, it gets scored, and
            the price of doing business falls. Here is every step of that loop.
          </p>
        </section>

        <section className="stack pillar-stack">
          <div className="pillar-stack-rail" aria-hidden="true" />
          {PILLARS.map((pillar) => (
            <Reveal as="div" key={pillar.number}>
              <PillarBlock pillar={pillar} expanded />
            </Reveal>
          ))}
        </section>

        <Reveal as="section" className="section">
          <div className="section-head">
            <MicroLabel>The same job, three reputations</MicroLabel>
          </div>
          <p className="display">
            One $500 job. <em>Three very different</em> invoices.
          </p>
          <div className="worked-example">
            {[
              { score: 871, band: "excellent", pct: "20%", cash: "$100", note: "clean record" },
              { score: 613, band: "good", pct: "40%", cash: "$200", note: "a few disputes" },
              { score: 382, band: "poor", pct: "100%", cash: "$500", note: "lost a dispute" },
            ].map((row) => (
              <div key={row.score} className="worked-row">
                <div className="worked-score">
                  <span className="worked-score-value">{row.score}</span>
                  <span className={`band-pill band-${row.band}`}>{row.band}</span>
                </div>
                <span className="worked-note muted-small">{row.note}</span>
                <div className="worked-bar-track">
                  <div className={`worked-bar fill-${row.band}`} style={{ width: row.pct }} />
                </div>
                <span className="worked-pct">{row.pct}</span>
                <span className="worked-cash">{row.cash}</span>
              </div>
            ))}
          </div>
          <p className="flow-line">
            Same work, same price — only the upfront lock-up changes. The rest settles on delivery.
          </p>
        </Reveal>

        <section className="section">
          <div className="section-head">
            <MicroLabel>Architecture</MicroLabel>
          </div>
          <div className="grid-3">
            {ARCHITECTURE.map((box) => (
              <ArchitectureBox key={box.label} {...box} />
            ))}
          </div>
          <p className="flow-line">
            escrow settles → oracle reads → model scores → oracle writes → registry
          </p>
        </section>

        <section className="section cta">
          <EditorialLine first="See it in motion." second="Three agents on a live chain." />
          <Link to="/dashboard" className="button-accent button-large">
            Open Dashboard
          </Link>
        </section>
      </main>
      <Footer />
    </>
  );
}
