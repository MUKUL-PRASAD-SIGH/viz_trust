import { useEffect, useRef, useState } from "react";
import AnimatedNumber from "./AnimatedNumber.jsx";
import BandPill from "./BandPill.jsx";
import Crossfade from "./Crossfade.jsx";
import FactorList from "./FactorList.jsx";
import MicroLabel from "./MicroLabel.jsx";
import ScoreBar from "./ScoreBar.jsx";
import { direction, shortAddress, signed } from "../lib/format.js";

const HIGHLIGHT_MS = 1200;

// Live agent card, framed like the landing page's spec cards. Renders the API's fields as-is.
export default function AgentCard({ agent, position, total }) {
  const [changed, setChanged] = useState(false);
  const lastScore = useRef(agent.score);

  useEffect(() => {
    if (lastScore.current === agent.score) return undefined;
    lastScore.current = agent.score;
    setChanged(true);
    const off = setTimeout(() => setChanged(false), HIGHLIGHT_MS);
    return () => clearTimeout(off);
  }, [agent.score]);

  const collateralMoved = agent.previous_required_collateral_pct !== agent.required_collateral_pct;

  return (
    <article className={`card agent-card ${changed ? "is-changed" : ""}`}>
      <header className="spec-head">
        <div>
          <h3 className="spec-name">{agent.name}</h3>
          <div className="spec-path">agent/{shortAddress(agent.address)}</div>
        </div>
        <span className="spec-path">score/{agent.score}</span>
      </header>

      <div>
        <MicroLabel>Credit score</MicroLabel>
        <div className="score-line">
          <span className="value-large">
            <AnimatedNumber value={agent.score} from={agent.previous_score} />
          </span>
          <span className={`delta ${direction(agent.score_delta)}`}>
            {signed(agent.score_delta)}
          </span>
          <span className="muted-small">from {agent.previous_score}</span>
        </div>
        <ScoreBar score={agent.score} band={agent.band} />
        <div className="band-row">
          <Crossfade value={agent.band} render={(band) => <BandPill band={band} />} />
          {agent.previous_band !== agent.band && (
            <span className="muted-small">was {agent.previous_band}</span>
          )}
        </div>
        {(agent.risk_flags ?? []).length > 0 && (
          // Advisory only: the score and collateral above are unaffected.
          <ul className="risk-flags">
            {agent.risk_flags.map((flag) => (
              <li key={flag.kind} className={`risk-flag risk-${flag.level}`} title={flag.reason}>
                <span className="risk-pill">
                  {flag.level === "alert" ? "Alert" : "Watch"} / {flag.label}
                </span>
                <span className="risk-reason">{flag.reason}</span>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div>
        <MicroLabel>Deposit upfront</MicroLabel>
        <div className="mono-value collateral-value">
          [<Crossfade value={agent.required_collateral_pct} render={(pct) => pct} />
          {collateralMoved ? ` / was ${agent.previous_required_collateral_pct}` : ""}]
        </div>
      </div>

      <div>
        <MicroLabel>Why this score</MicroLabel>
        <FactorList factors={agent.top_factors} />
      </div>

      <footer className="spec-foot">
        {position} of {total} agents on the live network
      </footer>
    </article>
  );
}
