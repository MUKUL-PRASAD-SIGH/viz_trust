// A single AEGIS wordmark band, drifting left to right. The track holds two identical halves
// so the loop is seamless; the second half is hidden from screen readers.
const WORDS = Array.from({ length: 8 }, (_, i) => i);

function Half({ hidden = false }) {
  return (
    <div className="marquee-half" aria-hidden={hidden || undefined}>
      {WORDS.map((i) => (
        <span key={i} className="marquee-word">
          AEGIS
        </span>
      ))}
    </div>
  );
}

export default function Footer() {
  return (
    <footer className="footer" aria-label="AEGIS">
      <div className="marquee">
        <div className="marquee-track">
          <Half />
          <Half hidden />
        </div>
      </div>
    </footer>
  );
}
