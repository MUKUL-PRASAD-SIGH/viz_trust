import MicroLabel from "./MicroLabel.jsx";

export default function StatBlock({ stats }) {
  return (
    <div className="stat-block">
      {stats.map(({ value, label }) => (
        <div key={label} className="stat">
          <div className="stat-number">{value}</div>
          <MicroLabel>{label}</MicroLabel>
        </div>
      ))}
    </div>
  );
}
