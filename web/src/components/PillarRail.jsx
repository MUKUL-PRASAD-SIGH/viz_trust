// A connecting line behind the pillar grid: purely decorative SVG, drawn in by CSS off the
// same `.reveal-stagger.in-view` class the pillar cards themselves already use, so the rail
// and the cards animate on one trigger instead of a second IntersectionObserver.
export default function PillarRail({ count }) {
  const nodeAt = (i) => (count === 1 ? 50 : (i / (count - 1)) * 100);
  return (
    <svg className="pillar-rail" viewBox="0 0 100 1" preserveAspectRatio="none" aria-hidden="true">
      <line
        className="pillar-rail-line"
        x1="0"
        y1="0.5"
        x2="100"
        y2="0.5"
        vectorEffect="non-scaling-stroke"
      />
      {Array.from({ length: count }, (_, i) => (
        <circle
          key={i}
          className="pillar-rail-node"
          cx={nodeAt(i)}
          cy="0.5"
          r="1.6"
          style={{ transitionDelay: `${i * 60 + 120}ms` }}
        />
      ))}
    </svg>
  );
}
