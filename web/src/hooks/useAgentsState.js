import { useCallback, useEffect, useState } from "react";
import stub from "../../../docs/api_stub.json";
import { POLL_MS, STATE_URL, USE_STUB, sendDecision, sendVerdict } from "../lib/api.js";

const VERDICT_STATUS = { confirm: "confirmed", dismiss: "dismissed" };

// Polls GET /agents/state every POLL_MS. Returns the body untouched, plus the last fetch error.
// `verdict` and `decide` send the dashboard's answers to the engine and update the local copy at
// once, so the panel reacts before the next poll confirms it. They throw if the engine refuses.
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

  const verdict = useCallback(async (findingId, choice) => {
    await sendVerdict(findingId, choice);
    setState((s) => ({
      ...s,
      findings: (s.findings ?? []).map((f) =>
        f.id === findingId ? { ...f, status: VERDICT_STATUS[choice] } : f,
      ),
    }));
  }, []);

  const decide = useCallback(async (editId, choice) => {
    await sendDecision(editId, choice);
    setState((s) => ({ ...s, pending: (s.pending ?? []).filter((p) => p.edit_id !== editId) }));
  }, []);

  return { state, error, verdict, decide };
}
