import { useState } from "react";
import MicroLabel from "./MicroLabel.jsx";
import { CHECK_LABELS } from "../lib/format.js";

const SEVERITY_ORDER = { critical: 0, high: 1, medium: 2, low: 3 };

// Newest edit first, and within an edit the most severe first.
const byNewest = (a, b) =>
  b.edit_id.localeCompare(a.edit_id) || SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity];

// What the checks found. Clicking a finding highlights its function on the graph; Confirm and
// Dismiss go to the engine, which moves the agent's score.
export default function FindingsPanel({ findings, selectedId, onSelect, onVerdict }) {
  const [busy, setBusy] = useState(null);
  const [failed, setFailed] = useState(null);
  const sorted = [...findings].sort(byNewest);

  const answer = async (finding, choice) => {
    setBusy(finding.id);
    setFailed(null);
    try {
      await onVerdict(finding.id, choice);
    } catch (err) {
      setFailed(`Couldn't send that to the engine (${err.message}). Try again.`);
    } finally {
      setBusy(null);
    }
  };

  return (
    <section className="card findings-panel">
      <div className="section-head">
        <MicroLabel>Findings</MicroLabel>
        <span className="muted-small">
          {findings.filter((f) => f.status === "open").length} open
        </span>
      </div>
      {failed && <p className="form-error">{failed}</p>}
      {sorted.length === 0 ? (
        <p className="empty">No findings yet. Every edit so far has been clean.</p>
      ) : (
        <ul className="finding-list">
          {sorted.map((finding) => (
            <li
              key={finding.id}
              className={`finding ${finding.id === selectedId ? "is-selected" : ""} status-${finding.status}`}
            >
              <button
                type="button"
                className="finding-main"
                aria-pressed={finding.id === selectedId}
                onClick={() => onSelect(finding.id === selectedId ? null : finding.id)}
              >
                <span className="finding-top">
                  <i className={`sev-dot sev-${finding.severity}`} aria-hidden="true" />
                  <span className="finding-check">
                    {CHECK_LABELS[finding.check] ?? finding.check}
                  </span>
                  <span className="sev-text">{finding.severity}</span>
                  <span className="tag">{finding.source}</span>
                </span>
                <span className="finding-where">
                  {finding.file}:{finding.line}
                </span>
                <span className="finding-message">{finding.message}</span>
                <code className="finding-evidence">{finding.evidence}</code>
              </button>
              <div className="finding-actions">
                {finding.status === "open" ? (
                  <>
                    <button
                      type="button"
                      className="button-ghost"
                      disabled={busy === finding.id}
                      onClick={() => answer(finding, "confirm")}
                    >
                      Confirm
                    </button>
                    <button
                      type="button"
                      className="button-ghost"
                      disabled={busy === finding.id}
                      onClick={() => answer(finding, "dismiss")}
                    >
                      Dismiss
                    </button>
                  </>
                ) : (
                  <span className="muted-pill">{finding.status}</span>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
