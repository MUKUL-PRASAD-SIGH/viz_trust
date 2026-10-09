import { useEffect, useRef, useState } from "react";
import MicroLabel from "./MicroLabel.jsx";

const lineKind = (line) =>
  line.startsWith("@@")
    ? "hunk"
    : line.startsWith("+")
      ? "add"
      : line.startsWith("-")
        ? "del"
        : "ctx";

// An edit waiting for you. Approving is deliberate: Esc hides the dialog without deciding, and
// nothing is focused when it opens, so a stray Enter can't approve. Only a click does.
export default function HeldEditDialog({ edit, agent, findings, queued, onDecide, onClose }) {
  const dialog = useRef(null);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(null);

  useEffect(() => {
    dialog.current?.focus();
  }, [edit.edit_id]);

  const decide = async (choice) => {
    setBusy(true);
    setFailed(null);
    try {
      await onDecide(edit.edit_id, choice);
    } catch (err) {
      setFailed(`Couldn't send that to the engine (${err.message}). Try again.`);
      setBusy(false);
    }
  };

  const linked = findings.filter((f) => (edit.finding_ids ?? []).includes(f.id));

  return (
    <div className="dialog-backdrop">
      <div
        ref={dialog}
        className="card held-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="held-title"
        tabIndex={-1}
        onKeyDown={(event) => {
          if (event.key === "Escape") onClose();
        }}
      >
        <header className="held-head">
          <div>
            <MicroLabel>
              Held / {edit.reason}
              {queued > 1 ? ` / ${queued} waiting` : ""}
            </MicroLabel>
            <h2 id="held-title" className="held-title">
              {agent?.name ?? edit.agent} wants to change {edit.file}
            </h2>
          </div>
          <button type="button" className="button-ghost" onClick={onClose}>
            Decide later
          </button>
        </header>

        <div className="held-facts">
          <span className="up">+{edit.added}</span>
          <span className="down">−{edit.removed}</span>
          <span className="muted-pill">area / {edit.area}</span>
          <span className="muted-pill">blast radius / {edit.blast_count}</span>
          <span className="muted-pill">findings / {linked.length}</span>
        </div>

        <pre className="diff" aria-label="Proposed change">
          {edit.diff.split("\n").map((line, i) => (
            <span key={i} className={`diff-line diff-${lineKind(line)}`}>
              {line || " "}
            </span>
          ))}
        </pre>

        {linked.length > 0 && (
          <ul className="held-findings">
            {linked.map((f) => (
              <li key={f.id}>
                <i className={`sev-dot sev-${f.severity}`} aria-hidden="true" /> {f.message}
              </li>
            ))}
          </ul>
        )}

        {failed && <p className="form-error">{failed}</p>}
        <footer className="held-actions">
          <button
            type="button"
            className="button-ghost danger"
            disabled={busy}
            onClick={() => decide("deny")}
          >
            Deny
          </button>
          <button
            type="button"
            className="button-accent"
            disabled={busy}
            onClick={() => decide("approve")}
          >
            Approve
          </button>
        </footer>
      </div>
    </div>
  );
}
