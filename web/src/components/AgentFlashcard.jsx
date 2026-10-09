import BandPill from "./BandPill.jsx";
import MicroLabel from "./MicroLabel.jsx";
import { direction, signed } from "../lib/format.js";

// The landing page's agent flashcard: identity + a first-person quote, with a small
// floating stat chip that drifts gently (desktop, motion allowed) — decorative only.
export default function AgentFlashcard({ name, band, path, score, delta, quote }) {
  return (
    <article className="card flashcard">
      <span className={`flashcard-chip ${direction(delta)}`}>{signed(delta)} last job</span>
      <header className="spec-head">
        <div>
          <h3 className="spec-name">{name}</h3>
          <div className="spec-path">agent/{path}</div>
        </div>
        <BandPill band={band} />
      </header>
      <div>
        <MicroLabel>Credit score</MicroLabel>
        <div className="spec-score">{score}</div>
      </div>
      <p className="flashcard-quote">{quote}</p>
    </article>
  );
}
