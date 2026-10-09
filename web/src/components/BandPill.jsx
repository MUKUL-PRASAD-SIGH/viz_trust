// `label` lets a tier name wear a band's colour (see tierBand in lib/format.js).
export default function BandPill({ band, label }) {
  return <span className={`band-pill band-${band}`}>[{label ?? band}]</span>;
}
