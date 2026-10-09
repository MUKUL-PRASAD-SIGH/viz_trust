import MicroLabel from "./MicroLabel.jsx";

// One numbered block. `expanded` shows the long-form sentences used on /how-it-works.
export default function PillarBlock({ pillar, expanded = false }) {
  return (
    <article className={`card pillar ${expanded ? "pillar-expanded" : ""}`}>
      <div className="pillar-head">
        <span className="pillar-number">{pillar.number}</span>
        <MicroLabel>{pillar.title}</MicroLabel>
        {expanded && (
          <div className="pillar-metric">
            <span className="pillar-metric-value">{pillar.metric}</span>
            <span className="pillar-metric-label">{pillar.metricLabel}</span>
          </div>
        )}
      </div>

      {expanded ? (
        <div className="pillar-body">
          <h2 className="pillar-hook">{pillar.hook}</h2>
          {pillar.long.map((sentence) => (
            <p key={sentence}>{sentence}</p>
          ))}
        </div>
      ) : (
        <>
          <p className="pillar-hook-short">{pillar.hook}</p>
          <p className="pillar-short">{pillar.short}</p>
          <div className="pillar-metric">
            <span className="pillar-metric-value">{pillar.metric}</span>
            <span className="pillar-metric-label">{pillar.metricLabel}</span>
          </div>
        </>
      )}
    </article>
  );
}
