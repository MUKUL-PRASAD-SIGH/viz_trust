import { STATE_URL } from "../lib/api.js";

// Full-width warning, only for real problems: backend unreachable or oracle down.
export default function StatusBanner({ state, error }) {
  let message = null;
  if (error) {
    message = `Can't reach the score service at ${STATE_URL} (${error}). Is it running? Retrying.`;
  } else if (state && state.source !== "stub" && !state.oracle_live) {
    message = state.notice ?? "The oracle has stopped reporting. Showing the last known state.";
  }
  if (!message) return null;
  return <div className="banner">{message}</div>;
}
