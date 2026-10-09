export default function BandPill({ band }) {
  return <span className={`band-pill band-${band}`}>[{band}]</span>;
}
