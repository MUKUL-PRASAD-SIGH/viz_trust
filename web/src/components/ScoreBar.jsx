const TICKS = [400, 600, 800];
const SCALE = [0, 400, 600, 800, 1000];

// 0-1000 bar. The ticks are gaps cut through the fill, so crossing a tier is visible.
export default function ScoreBar({ score, band }) {
  return (
    <div className="scorebar">
      <div className="scorebar-track">
        <div className={`scorebar-fill fill-${band}`} style={{ width: `${score / 10}%` }} />
        {TICKS.map((tick) => (
          <span key={tick} className="scorebar-tick" style={{ left: `${tick / 10}%` }} />
        ))}
      </div>
      <div className="scorebar-scale">
        {SCALE.map((mark) => (
          <span key={mark} style={{ left: `${mark / 10}%` }}>
            {mark}
          </span>
        ))}
      </div>
    </div>
  );
}
