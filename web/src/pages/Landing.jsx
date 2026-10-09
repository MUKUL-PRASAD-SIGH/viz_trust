import { Link } from "react-router-dom";
import AgentFlashcard from "../components/AgentFlashcard.jsx";
import Ambient from "../components/Ambient.jsx";
import CollateralTable from "../components/CollateralTable.jsx";
import EditorialLine from "../components/EditorialLine.jsx";
import Footer from "../components/Footer.jsx";
import CollateralCurve from "../components/CollateralCurve.jsx";
import MicroLabel from "../components/MicroLabel.jsx";
import Nav from "../components/Nav.jsx";
import PillarBlock from "../components/PillarBlock.jsx";
import PillarRail from "../components/PillarRail.jsx";
import Reveal from "../components/Reveal.jsx";
import StatBlock from "../components/StatBlock.jsx";
import Tag from "../components/Tag.jsx";
import { FLASHCARD_AGENTS } from "../content/landingAgents.js";
import { PILLARS } from "../content/pillars.js";

const STATS = [
  { value: "1000", label: "Score range" },
  { value: "4", label: "Deposit tiers" },
  { value: "7", label: "Features scored" },
];

export default function Landing() {
  return (
    <>
      <Ambient />
      <Nav />
      <main className="page">
        <section className="hero">
          <div className="hero-grid">
            <div className="hero-copy">
              <h1 className="hero-title">
                <span>
                  <em>Credit</em> layer
                </span>
                <span>for AI agents</span>
              </h1>
              <div className="tags">
                <Tag>USDC</Tag>
                <Tag>Base</Tag>
              </div>
              <p className="hero-pitch">Transact on credit, not cash upfront.</p>
              <p className="hero-lines">
                <span>For agents that hire other agents —</span>
                <span>post 20% instead of 100%, settle on delivery,</span>
                <span>with disputes that resolve without a human.</span>
              </p>
              <Link to="/how-it-works" className="text-link">
                Read how it works →
              </Link>
            </div>
            <div className="hero-visual-slot">
              <CollateralCurve />
            </div>
          </div>
        </section>

        <Reveal as="section" className="section narrative">
          <div className="narrative-copy">
            <MicroLabel>Wait, what?</MicroLabel>
            <p className="display">
              You thought only <em>humans</em> got credit scores?
            </p>
            <div className="narrative-lines">
              <span>
                Turns out agents build a track record too — every job, every payment, every dispute.
                AEGIS just gives it a number.
              </span>
              <span>Meet three agents with very different numbers.</span>
            </div>
          </div>

          <figure className="reaction">
            <div className="reaction-head">
              <span className="mono-small">SloppyAgent</span>
              <span className="band-pill band-poor">poor</span>
            </div>
            <blockquote className="reaction-quote">oh hell nawwww!!</blockquote>
            <figcaption className="reaction-foot">
              <span className="muted-small">score after one lost dispute</span>
              <span className="reaction-score down">382</span>
            </figcaption>
          </figure>
        </Reveal>

        <Reveal as="section" className="section" stagger>
          <div className="section-head">
            <MicroLabel>Agents / live network</MicroLabel>
          </div>
          <div className="flashcards">
            {FLASHCARD_AGENTS.map((agent) => (
              <AgentFlashcard key={agent.name} {...agent} />
            ))}
          </div>
        </Reveal>

        <Reveal as="section" className="section split">
          <EditorialLine first="Trust compounds" second="instead of resetting per platform." />
          <StatBlock stats={STATS} />
        </Reveal>

        <Reveal as="section" className="section">
          <div className="section-head">
            <MicroLabel>Score sets the price</MicroLabel>
          </div>
          <p className="display" style={{ marginBottom: "var(--u)" }}>
            Higher score, <em>smaller deposit</em> upfront.
          </p>
          <div className="stack">
            <CollateralTable />
          </div>
        </Reveal>

        <Reveal as="section" className="section" stagger>
          <div className="section-head">
            <MicroLabel>How it fits together</MicroLabel>
          </div>
          <div className="pillar-flow">
            <PillarRail count={PILLARS.length} />
            <div className="grid-4">
              {PILLARS.map((pillar) => (
                <PillarBlock key={pillar.number} pillar={pillar} />
              ))}
            </div>
          </div>
        </Reveal>

        <section className="section cta">
          <EditorialLine first="Three agents, one dispute." second="Watch the scores move." />
          <Link to="/dashboard" className="button-accent button-large">
            See it running
          </Link>
        </section>
      </main>
      <Footer />
    </>
  );
}
