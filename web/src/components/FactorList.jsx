import { FEATURE_LABELS } from "../lib/format.js";

// Top factors as bars from a centre line: accent raises the score, danger lowers it.
export default function FactorList({ factors }) {
  const scale = Math.max(100, ...factors.map((f) => Math.abs(f.impact)));
  return (
    <ul className="factors">
      {factors.map((factor) => {
        const width = (Math.abs(factor.impact) / scale) * 50;
        const helps = factor.impact >= 0;
        const position = helps
          ? { left: "50%", width: `${width}%` }
          : { left: `${50 - width}%`, width: `${width}%` };
        return (
          <li key={factor.feature} className="factor" title={factor.explanation}>
            <span className="factor-name">{FEATURE_LABELS[factor.feature] ?? factor.feature}</span>
            <span className="factor-track">
              <span className={`factor-bar ${helps ? "helps" : "hurts"}`} style={position} />
            </span>
            <span className={`factor-pts ${helps ? "up" : "down"}`}>
              {factor.impact > 0 ? "+" : ""}
              {factor.impact}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
