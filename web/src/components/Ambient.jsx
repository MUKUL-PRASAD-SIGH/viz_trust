// Fixed, decorative, behind everything. Two blobs drift via CSS keyframes (transform-only),
// with the AEGIS mark held faintly behind the page as a standing watermark.
export default function Ambient() {
  return (
    <div className="ambient" aria-hidden="true">
      <div className="ambient-blob ambient-blob-a" />
      <div className="ambient-blob ambient-blob-b" />
      <div className="ambient-mark" />
    </div>
  );
}
