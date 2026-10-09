import BandPill from "./BandPill.jsx";
import MicroLabel from "./MicroLabel.jsx";

// Static agent card for the landing page: name, band tag, address path, labelled values, scale.
export default function SpecCard({ name, band, path, fields, footer }) {
  return (
    <article className="card spec-card">
      <header className="spec-head">
        <div>
          <h3 className="spec-name">{name}</h3>
          <div className="spec-path">agent/{path}</div>
        </div>
        <BandPill band={band} />
      </header>
      <dl className="spec-fields">
        {fields.map(([label, value], index) => (
          <div key={label} className="spec-field">
            <dt>
              <MicroLabel>{label}</MicroLabel>
            </dt>
            <dd className={index === 0 ? "spec-score" : "mono-value"}>{value}</dd>
          </div>
        ))}
      </dl>
      <footer className="spec-foot">{footer}</footer>
    </article>
  );
}
