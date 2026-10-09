// The dashboard's whole data contract: GET /agents/state, polled. Nothing is derived here.
const params = new URLSearchParams(window.location.search);

// Deployed builds set VITE_API_BASE (a URL, or a bare host from render.yaml); local runs fall
// back to the score service on this machine.
const configured = import.meta.env.VITE_API_BASE || "";
const deployed =
  configured && !/^https?:\/\//.test(configured) ? `https://${configured}` : configured;
export const API_BASE = (params.get("api") || deployed || "http://127.0.0.1:8000").replace(
  /\/$/,
  "",
);
export const STATE_URL = `${API_BASE}/agents/state`;
export const POLL_MS = 1500;

// ?stub=1 renders docs/api_stub.json instead of polling, for offline previews.
export const USE_STUB = params.get("stub") === "1";

// Write endpoints from the shared contract (person/README.md). In stub mode nothing is sent;
// the hook applies the change to its local copy so the buttons still do something visible.
async function postJson(path, body) {
  if (USE_STUB) return {};
  const response = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json().catch(() => ({}));
}

// verdict: "confirm" | "dismiss"
export const sendVerdict = (findingId, verdict) =>
  postJson(`/findings/${encodeURIComponent(findingId)}/verdict`, { verdict });

// decision: "approve" | "deny"
export const sendDecision = (editId, decision) =>
  postJson("/decisions", { edit_id: editId, decision });
