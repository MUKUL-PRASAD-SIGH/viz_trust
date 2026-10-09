// Right side of the nav on /dashboard. Stub data gets a quiet tag here instead of a banner.
export default function LiveStatus({ state, error }) {
  if (state?.source === "stub") {
    return (
      <div className="live-status">
        <span className="tag">[STUB DATA]</span>
        <span className="muted-pill">sample from docs/api_stub.json</span>
      </div>
    );
  }
  const live = !error && state?.oracle_live;
  // source "chain": the score service read the Registry itself; no oracle is involved.
  const chain = state?.source === "chain";
  const label = live
    ? chain
      ? state.chain_id === 84532
        ? "BASE SEPOLIA"
        : "CHAIN READ"
      : "ORACLE LIVE"
    : error
      ? "DISCONNECTED"
      : state
        ? chain
          ? "CHAIN UNREACHABLE"
          : "ORACLE SILENT"
        : "CONNECTING";
  return (
    <div className="live-status">
      <span className={`live-dot ${live ? "on" : "off"}`} />
      <span className="mono-small">{label}</span>
      {state?.block != null && <span className="mono-small muted">block/{state.block}</span>}
    </div>
  );
}
