import { useEffect, useState } from "react";
import stub from "../../../docs/api_stub.json";
import { POLL_MS, STATE_URL, USE_STUB } from "../lib/api.js";

// Polls GET /agents/state every POLL_MS. Returns the body untouched, plus the last fetch error.
export default function useAgentsState() {
  const [state, setState] = useState(USE_STUB ? stub : null);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (USE_STUB) return undefined;
    let cancelled = false;
    let timer;

    const poll = async () => {
      try {
        const response = await fetch(STATE_URL, { cache: "no-store" });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const body = await response.json();
        if (!cancelled) {
          setState(body);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) setError(err.message || "unreachable");
      } finally {
        if (!cancelled) timer = setTimeout(poll, POLL_MS);
      }
    };

    poll();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, []);

  return { state, error };
}
