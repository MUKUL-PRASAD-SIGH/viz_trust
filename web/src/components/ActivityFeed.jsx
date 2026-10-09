import MicroLabel from "./MicroLabel.jsx";
import { chainStamp, direction, signed } from "../lib/format.js";

const SHOWN = 12;

// Every agent's recent events in one stream, newest first. Reasons are never truncated.
// `recorded`: the events are a recorded local run, not this chain's history (chain mode).
export default function ActivityFeed({ agents, recorded = false }) {
  const events = agents
    .flatMap((agent) => agent.recent_events.map((event) => ({ ...event, agent: agent.name })))
    .sort((a, b) => b.timestamp.localeCompare(a.timestamp));
  const shown = events.slice(0, SHOWN);

  return (
    <section className="feed">
      <div className="section-head">
        <MicroLabel>
          {recorded
            ? "Seeded history / recorded from a local run, not this chain"
            : "Live activity"}
        </MicroLabel>
      </div>
      <div className="feed-rows">
        <div className="feed-row feed-header">
          <span className="micro">Time</span>
          <span className="micro">Agent</span>
          <span className="micro">Reason</span>
          <span className="micro num">Delta</span>
        </div>
        {shown.map((event) => (
          <div key={`${event.agent}|${event.timestamp}|${event.reason}`} className="feed-row">
            <span className="feed-time">{chainStamp(event.timestamp)}</span>
            <span className="feed-agent">{event.agent}</span>
            <span className="feed-reason">{event.reason}</span>
            <span className={`feed-delta num ${direction(event.delta)}`}>
              {signed(event.delta)}
            </span>
          </div>
        ))}
      </div>
      <div className="table-foot">
        {shown.length} of {events.length} recent events
      </div>
    </section>
  );
}
