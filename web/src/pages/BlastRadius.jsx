import { useState } from "react";
import Ambient from "../components/Ambient.jsx";
import BlastGraph from "../components/BlastGraph.jsx";
import FindingsPanel from "../components/FindingsPanel.jsx";
import Footer from "../components/Footer.jsx";
import HeldEditDialog from "../components/HeldEditDialog.jsx";
import LiveStatus from "../components/LiveStatus.jsx";
import MicroLabel from "../components/MicroLabel.jsx";
import Nav from "../components/Nav.jsx";
import StatusBanner from "../components/StatusBanner.jsx";
import useAgentsState from "../hooks/useAgentsState.js";

// The live call graph, the findings behind it, and edits waiting for you. Everything comes from
// GET /agents/state; the engine works out what each edit touched and which callers could break.
export default function BlastRadius() {
  const { state, error, verdict, decide } = useAgentsState();
  const [selectedId, setSelectedId] = useState(null);
  // Held edits you chose to decide later (Esc or "Decide later"). They stay in the queue.
  const [snoozed, setSnoozed] = useState([]);

  const agents = state?.agents ?? [];
  const graph = state?.graph;
  const findings = state?.findings ?? [];
  const pending = state?.pending ?? [];
  const lastEdit = graph?.last_edit;
  const editor = agents.find(
    (a) => a.address === graph?.nodes.find((n) => n.id === lastEdit?.touched[0])?.last_agent,
  );

  const waiting = pending.filter((p) => !snoozed.includes(p.edit_id));
  const current = waiting[0];
  const selectedNode = findings.find((f) => f.id === selectedId)?.node ?? null;

  return (
    <>
      <Ambient />
      <Nav status={<LiveStatus state={state} error={error} />} />
      <main className="page page-dashboard">
        <StatusBanner state={state} error={error} />
        <section className="page-intro blast-hero">
          <MicroLabel>Blast radius / live</MicroLabel>
          <p className="display">
            See what an edit <em>could break</em> before it lands.
          </p>
          <p className="blast-sub">
            Every function is a node and every call is a line. The edited function glows in the
            colour of its agent's trust tier, and its callers ripple outward.
          </p>
        </section>

        {pending.length > 0 && !current && (
          <div className="held-banner">
            <span>
              {pending.length} held {pending.length === 1 ? "edit is" : "edits are"} waiting for
              you.
            </span>
            <button type="button" className="button-ghost" onClick={() => setSnoozed([])}>
              Review
            </button>
          </div>
        )}

        {!graph || graph.nodes.length === 0 ? (
          <p className="empty">
            {state && !graph
              ? "This server doesn't report a call graph yet. Point ?api= at the engine."
              : "Waiting for the engine to report a call graph…"}
          </p>
        ) : (
          <>
            {lastEdit && (
              <div className="blast-stats">
                <div>
                  <MicroLabel>Last edit</MicroLabel>
                  <div className="mono-value">{lastEdit.edit_id}</div>
                </div>
                <div>
                  <MicroLabel>By</MicroLabel>
                  <div className="mono-value">{editor?.name ?? "unknown"}</div>
                </div>
                <div>
                  <MicroLabel>Edited</MicroLabel>
                  <div className="mono-value">{lastEdit.touched.length}</div>
                </div>
                <div>
                  <MicroLabel>Callers at risk</MicroLabel>
                  <div className="mono-value">{lastEdit.blast.length}</div>
                </div>
              </div>
            )}
            <div className="blast-layout">
              <div className="card blast-card">
                <BlastGraph graph={graph} agents={agents} selected={selectedNode} />
              </div>
              <FindingsPanel
                findings={findings}
                selectedId={selectedId}
                onSelect={setSelectedId}
                onVerdict={verdict}
              />
            </div>
          </>
        )}
      </main>
      <Footer />
      {current && (
        <HeldEditDialog
          edit={current}
          agent={agents.find((a) => a.address === current.agent)}
          findings={findings}
          queued={waiting.length}
          onDecide={decide}
          onClose={() => setSnoozed((ids) => [...ids, current.edit_id])}
        />
      )}
    </>
  );
}
