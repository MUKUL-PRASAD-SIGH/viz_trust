import Ambient from "../components/Ambient.jsx";
import ActivityFeed from "../components/ActivityFeed.jsx";
import AgentCard from "../components/AgentCard.jsx";
import Footer from "../components/Footer.jsx";
import LiveStatus from "../components/LiveStatus.jsx";
import MicroLabel from "../components/MicroLabel.jsx";
import Nav from "../components/Nav.jsx";
import StatusBanner from "../components/StatusBanner.jsx";
import useAgentsState from "../hooks/useAgentsState.js";

// The live instrument. Everything shown comes from GET /agents/state as-is.
export default function Dashboard() {
  const { state, error } = useAgentsState();
  const agents = state?.agents ?? [];

  return (
    <>
      <Ambient />
      <Nav status={<LiveStatus state={state} error={error} />} />
      <main className="page page-dashboard">
        <StatusBanner state={state} error={error} />
        <div className="section-head">
          <MicroLabel>Agents / live network</MicroLabel>
        </div>
        {agents.length === 0 ? (
          <p className="empty">Waiting for the oracle to report agents…</p>
        ) : (
          <div className="grid-3">
            {agents.map((agent, index) => (
              <AgentCard
                key={agent.address}
                agent={agent}
                position={index + 1}
                total={agents.length}
              />
            ))}
          </div>
        )}
        {agents.length > 0 && <ActivityFeed agents={agents} recorded={state?.source === "chain"} />}
      </main>
      <Footer />
    </>
  );
}
