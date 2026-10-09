import { useMemo, useState } from "react";
import { forceCollide, forceLink, forceManyBody, forceSimulation, forceX, forceY } from "d3-force";

const W = 900;
const H = 520;
const PAD = 56;

// Callers of the touched nodes, by distance: depth 1 calls a touched node directly, depth 2 calls
// that, and so on. The ripple on the graph spreads outward by this depth.
function blastDepths(edges, touched) {
  const callers = new Map();
  for (const { source, target } of edges) {
    if (!callers.has(target)) callers.set(target, []);
    callers.get(target).push(source);
  }
  const depth = new Map();
  let frontier = touched;
  for (let d = 1; frontier.length > 0; d += 1) {
    const next = [];
    for (const id of frontier) {
      for (const caller of callers.get(id) ?? []) {
        if (!depth.has(caller) && !touched.includes(caller)) {
          depth.set(caller, d);
          next.push(caller);
        }
      }
    }
    frontier = next;
  }
  return depth;
}

// A static, repeatable layout: run the force simulation to rest before drawing, and pull each
// file's functions together so files read as clusters. Heat and ownership changes don't move
// anything; only a change in the call structure does.
function layout(nodes, edges) {
  const files = [...new Set(nodes.map((n) => n.file))];
  const anchor = new Map(
    files.map((file, i) => {
      const angle = (i / files.length) * Math.PI * 2 - Math.PI / 2;
      return [file, { x: W / 2 + Math.cos(angle) * 320, y: H / 2 + Math.sin(angle) * 190 }];
    }),
  );
  const simNodes = nodes.map((n) => ({ id: n.id, file: n.file }));
  const simulation = forceSimulation(simNodes)
    .force(
      "link",
      forceLink(edges.map((e) => ({ ...e })))
        .id((d) => d.id)
        .distance(46)
        .strength(0.15),
    )
    .force("charge", forceManyBody().strength(-90))
    .force("collide", forceCollide(24))
    .force("x", forceX((d) => anchor.get(d.file).x).strength(0.3))
    .force("y", forceY((d) => anchor.get(d.file).y).strength(0.3))
    .stop();
  for (let i = 0; i < 300; i += 1) simulation.tick();

  // Fit the result to the canvas so the graph is centred and uses the space it has.
  const xs = simNodes.map((n) => n.x);
  const ys = simNodes.map((n) => n.y);
  const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  const fit = (v, lo, hi, size) =>
    hi === lo ? size / 2 : PAD + ((v - lo) / (hi - lo)) * (size - PAD * 2);
  return new Map(simNodes.map((n) => [n.id, { x: fit(n.x, x0, x1, W), y: fit(n.y, y0, y1, H) }]));
}

function fileBoxes(nodes, positions) {
  const byFile = new Map();
  for (const n of nodes) {
    const p = positions.get(n.id);
    const box = byFile.get(n.file) ?? { x0: Infinity, y0: Infinity, x1: -Infinity, y1: -Infinity };
    box.x0 = Math.min(box.x0, p.x);
    box.y0 = Math.min(box.y0, p.y);
    box.x1 = Math.max(box.x1, p.x);
    box.y1 = Math.max(box.y1, p.y);
    byFile.set(n.file, box);
  }
  const pad = 26;
  return [...byFile].map(([file, b]) => ({
    file,
    x: b.x0 - pad,
    y: b.y0 - pad,
    w: b.x1 - b.x0 + pad * 2,
    h: b.y1 - b.y0 + pad * 2,
  }));
}

// 2D call graph. Nodes are functions, an edge runs from a caller to what it calls. Touched nodes
// glow and are filled by the trust tier of the agent that edited them; their callers ripple
// outward by distance. `selected` is a node id to ring (used by the findings panel).
export default function BlastGraph({ graph, agents = [], selected = null }) {
  const [hovered, setHovered] = useState(null);
  const { nodes, edges, last_edit: lastEdit } = graph;

  const structureKey = useMemo(
    () =>
      nodes.map((n) => n.id).join("|") +
      "#" +
      edges.map((e) => `${e.source}>${e.target}`).join("|"),
    [nodes, edges],
  );
  // eslint-disable-next-line react-hooks/exhaustive-deps -- layout depends on structure only
  const positions = useMemo(() => layout(nodes, edges), [structureKey]);
  const boxes = useMemo(() => fileBoxes(nodes, positions), [nodes, positions]);

  const touched = lastEdit?.touched ?? [];
  const depths = useMemo(() => blastDepths(edges, touched), [edges, touched]);
  const agentByAddress = new Map(agents.map((a) => [a.address, a]));
  const involved = new Set([...touched, ...depths.keys()]);
  const hoveredNode = nodes.find((n) => n.id === hovered);

  return (
    <div className="blast-graph">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-label={`Call graph with ${nodes.length} functions. ${touched.length} edited, ${depths.size} callers in the blast radius.`}
      >
        {boxes.map((box) => (
          <g key={box.file}>
            <rect className="file-box" x={box.x} y={box.y} width={box.w} height={box.h} rx="8" />
            <text className="file-label" x={box.x + 8} y={box.y - 6}>
              {box.file}
            </text>
          </g>
        ))}

        {edges.map((edge) => {
          const a = positions.get(edge.source);
          const b = positions.get(edge.target);
          const on = involved.has(edge.source) && involved.has(edge.target);
          return (
            <line
              key={`${edge.source}>${edge.target}`}
              className={`graph-edge ${on ? "on" : ""}`}
              x1={a.x}
              y1={a.y}
              x2={b.x}
              y2={b.y}
            />
          );
        })}

        {nodes.map((node) => {
          const { x, y } = positions.get(node.id);
          const isTouched = touched.includes(node.id);
          const depth = depths.get(node.id);
          const radius = 5 + node.heat * 6;
          const tier = agentByAddress.get(node.last_agent)?.tier;
          const state = isTouched ? "touched" : depth ? "blast" : "idle";
          return (
            <g
              key={node.id}
              className={`graph-node ${state} ${tier ? `tier-${tier}` : ""}`}
              transform={`translate(${x} ${y})`}
              onMouseEnter={() => setHovered(node.id)}
              onMouseLeave={() => setHovered(null)}
            >
              {/* keyed by edit so the ripple plays again for each new edit */}
              {isTouched && <circle key={lastEdit.edit_id} className="glow" r={radius + 6} />}
              {depth && (
                <circle
                  key={lastEdit.edit_id}
                  className="ripple"
                  r={radius + 4}
                  style={{ animationDelay: `${depth * 280}ms` }}
                />
              )}
              {node.id === selected && <circle className="selected-ring" r={radius + 9} />}
              <circle
                className="dot"
                r={radius}
                style={state === "idle" ? { opacity: 0.35 + node.heat * 0.5 } : undefined}
              />
              <text className="node-label" y={radius + 13} textAnchor="middle">
                {node.label}
              </text>
            </g>
          );
        })}
      </svg>

      {hoveredNode && (
        <div
          className="graph-tip"
          style={{
            left: `${(positions.get(hoveredNode.id).x / W) * 100}%`,
            top: `${(positions.get(hoveredNode.id).y / H) * 100}%`,
          }}
        >
          <strong>{hoveredNode.label}</strong>
          <span>{hoveredNode.file}</span>
          <span>
            last edited by{" "}
            {agentByAddress.get(hoveredNode.last_agent)?.name ??
              hoveredNode.last_agent ??
              "nobody yet"}
          </span>
        </div>
      )}

      <ul className="graph-legend">
        <li>
          <i className="swatch touched" /> edited
        </li>
        <li>
          <i className="swatch blast" /> in the blast radius
        </li>
        <li>
          <i className="swatch tier-trusted" /> trusted
        </li>
        <li>
          <i className="swatch tier-standard" /> standard
        </li>
        <li>
          <i className="swatch tier-probation" /> probation
        </li>
        <li className="muted-small">size follows how often it changes</li>
      </ul>
    </div>
  );
}
