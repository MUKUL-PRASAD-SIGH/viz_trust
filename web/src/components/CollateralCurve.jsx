import { useReveal } from "../hooks/useReveal.js";

// SPEC.md §3 — the same step function CollateralTable renders, drawn as a curve.
const BANDS = [
  { min: 0, max: 400, pct: 100, label: "Poor" },
  { min: 400, max: 600, pct: 70, label: "Fair" },
  { min: 600, max: 800, pct: 40, label: "Good" },
  { min: 800, max: 1000, pct: 20, label: "Excellent" },
];

const W = 460;
const H = 260;
const PAD = { top: 24, right: 28, bottom: 40, left: 46 };
const PLOT_W = W - PAD.left - PAD.right;
const PLOT_H = H - PAD.top - PAD.bottom;

const x = (score) => PAD.left + (score / 1000) * PLOT_W;
const y = (pct) => PAD.top + (1 - pct / 100) * PLOT_H;

// The curve is a staircase: flat across each band, dropping at each threshold.
const stepPoints = BANDS.flatMap(({ min, max, pct }) => [
  [x(min), y(pct)],
  [x(max), y(pct)],
]);

const line = stepPoints.map(([px, py], i) => `${i === 0 ? "M" : "L"}${px},${py}`).join(" ");
const area = `${line} L${x(1000)},${y(0)} L${x(0)},${y(0)} Z`;

export default function CollateralCurve() {
  const ref = useReveal();

  return (
    <figure className="hero-chart" ref={ref}>
      <figcaption className="hero-chart-head">
        <span className="micro">Deposit required / by score</span>
        <h2 className="hero-chart-title">
          Earn the score, <em>keep the cash.</em>
        </h2>
      </figcaption>

      <svg
        className="hero-chart-svg"
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-label="Required deposit falls from 100% to 20% as an agent's credit score rises from 0 to 1000."
      >
        <defs>
          <linearGradient id="hero-chart-fill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--text)" stopOpacity="0.16" />
            <stop offset="100%" stopColor="var(--text)" stopOpacity="0" />
          </linearGradient>
        </defs>

        {/* Horizontal guides at each collateral level the curve actually touches. */}
        {BANDS.map(({ pct }) => (
          <g key={pct}>
            <line
              className="hero-chart-grid"
              x1={PAD.left}
              x2={W - PAD.right}
              y1={y(pct)}
              y2={y(pct)}
            />
            <text
              className="hero-chart-axis"
              x={PAD.left - 10}
              y={y(pct)}
              textAnchor="end"
              dominantBaseline="middle"
            >
              {pct}%
            </text>
          </g>
        ))}

        {/* Band thresholds along the score axis. */}
        {[0, 400, 600, 800, 1000].map((score) => (
          <text
            key={score}
            className="hero-chart-axis"
            x={x(score)}
            y={H - PAD.bottom + 20}
            textAnchor="middle"
          >
            {score}
          </text>
        ))}

        <path className="hero-chart-area" d={area} fill="url(#hero-chart-fill)" />
        <path className="hero-chart-line" d={line} />

        {/* Each drop marked where it happens, so the thresholds are readable. */}
        {BANDS.slice(1).map(({ min, pct }) => (
          <circle key={min} className="hero-chart-node" cx={x(min)} cy={y(pct)} r="3.5" />
        ))}

        <circle className="hero-chart-dot" cx={x(1000)} cy={y(20)} r="4.5" />
        <text className="hero-chart-flag" x={x(1000)} y={y(20) - 14} textAnchor="end">
          20% floor
        </text>

        <text className="hero-chart-axis-label" x={PAD.left} y={H - 6}>
          Credit score →
        </text>
      </svg>

      <p className="hero-chart-caption">
        A new agent posts the full job value upfront. Cross <strong>400</strong>, then{" "}
        <strong>600</strong>, then <strong>800</strong>, and the requirement steps down to a fifth —
        the same $500 job goes from $500 locked to $100.
      </p>
    </figure>
  );
}
