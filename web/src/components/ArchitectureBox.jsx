import MicroLabel from "./MicroLabel.jsx";

export default function ArchitectureBox({ label, title, line }) {
  return (
    <div className="card arch-box">
      <MicroLabel>{label}</MicroLabel>
      <div className="arch-title">{title}</div>
      <p>{line}</p>
    </div>
  );
}
