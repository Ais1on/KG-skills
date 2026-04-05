"use client";

import { useEffect, useState } from "react";

type GraphEntity = {
  name: string;
  type?: string;
  properties?: Record<string, unknown>;
};

type GraphTriplet = {
  head: string;
  relation: string;
  tail: string;
  properties?: Record<string, unknown>;
};

type GraphSnapshot = {
  entities: GraphEntity[];
  triplets: GraphTriplet[];
};

type LayoutNode = GraphEntity & {
  x: number;
  y: number;
  vx: number;
  vy: number;
};

const WIDTH = 520;
const HEIGHT = 320;
const CENTER_X = WIDTH / 2;
const CENTER_Y = HEIGHT / 2;

function colorFromType(type?: string) {
  const value = String(type || "entity").toLowerCase();
  if (value.includes("cve") || value.includes("vuln")) return "#fb7185";
  if (value.includes("person")) return "#f59e0b";
  if (value.includes("org") || value.includes("company")) return "#60a5fa";
  if (value.includes("software") || value.includes("project")) return "#34d399";
  return "#a78bfa";
}

function truncate(text: string, max = 16) {
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

function buildInitialLayout(graph: GraphSnapshot): LayoutNode[] {
  const total = Math.max(graph.entities.length, 1);
  const radius = Math.min(WIDTH, HEIGHT) * 0.32;
  return graph.entities.map((entity, index) => {
    const angle = (Math.PI * 2 * index) / total;
    return {
      ...entity,
      x: CENTER_X + Math.cos(angle) * radius,
      y: CENTER_Y + Math.sin(angle) * radius,
      vx: 0,
      vy: 0,
    };
  });
}

function simulate(graph: GraphSnapshot): LayoutNode[] {
  const nodes = buildInitialLayout(graph);
  const indexByName = new Map(nodes.map((node, index) => [node.name, index]));

  for (let step = 0; step < 140; step += 1) {
    for (let i = 0; i < nodes.length; i += 1) {
      for (let j = i + 1; j < nodes.length; j += 1) {
        const a = nodes[i];
        const b = nodes[j];
        const dx = b.x - a.x;
        const dy = b.y - a.y;
        const distanceSq = Math.max(dx * dx + dy * dy, 0.01);
        const force = 2400 / distanceSq;
        const fx = (dx / Math.sqrt(distanceSq)) * force;
        const fy = (dy / Math.sqrt(distanceSq)) * force;
        a.vx -= fx;
        a.vy -= fy;
        b.vx += fx;
        b.vy += fy;
      }
    }

    for (const edge of graph.triplets) {
      const sourceIndex = indexByName.get(edge.head);
      const targetIndex = indexByName.get(edge.tail);
      if (sourceIndex == null || targetIndex == null) continue;
      const source = nodes[sourceIndex];
      const target = nodes[targetIndex];
      const dx = target.x - source.x;
      const dy = target.y - source.y;
      const distance = Math.max(Math.sqrt(dx * dx + dy * dy), 1);
      const desired = 130;
      const spring = (distance - desired) * 0.018;
      const fx = (dx / distance) * spring;
      const fy = (dy / distance) * spring;
      source.vx += fx;
      source.vy += fy;
      target.vx -= fx;
      target.vy -= fy;
    }

    for (const node of nodes) {
      const pullX = (CENTER_X - node.x) * 0.004;
      const pullY = (CENTER_Y - node.y) * 0.004;
      node.vx = (node.vx + pullX) * 0.84;
      node.vy = (node.vy + pullY) * 0.84;
      node.x = Math.min(WIDTH - 28, Math.max(28, node.x + node.vx));
      node.y = Math.min(HEIGHT - 28, Math.max(28, node.y + node.vy));
    }
  }

  return nodes;
}

export function GraphPanel({ graph }: { graph: GraphSnapshot }) {
  const [nodes, setNodes] = useState<LayoutNode[]>(() => buildInitialLayout(graph));
  const nodeByName = new Map(nodes.map((node) => [node.name, node]));

  useEffect(() => {
    setNodes(simulate(graph));
  }, [graph]);

  return (
    <div className="mt-3 rounded-2xl border border-[#2b313a] bg-[#141820] p-3">
      <div className="mb-3 flex items-center justify-between">
        <div className="text-xs uppercase tracking-[0.18em] text-[#8ea0b5]">Force Graph</div>
        <div className="text-xs text-[#9aa8b8]">
          {graph.entities.length} nodes / {graph.triplets.length} edges
        </div>
      </div>

      <div className="overflow-hidden rounded-xl border border-[#283140] bg-[radial-gradient(circle_at_top,_#182231,_#0f131a_70%)]">
        <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} className="h-[320px] w-full">
          <defs>
            <marker id="graph-arrow" markerWidth="10" markerHeight="10" refX="7" refY="3" orient="auto">
              <path d="M0,0 L0,6 L8,3 z" fill="#5b6677" />
            </marker>
          </defs>

          {graph.triplets.map((edge, index) => {
            const source = nodeByName.get(edge.head);
            const target = nodeByName.get(edge.tail);
            if (!source || !target) return null;
            const midX = (source.x + target.x) / 2;
            const midY = (source.y + target.y) / 2;
            return (
              <g key={`${edge.head}-${edge.relation}-${edge.tail}-${index}`}>
                <line
                  x1={source.x}
                  y1={source.y}
                  x2={target.x}
                  y2={target.y}
                  stroke="#5b6677"
                  strokeWidth="1.4"
                  markerEnd="url(#graph-arrow)"
                  opacity="0.9"
                />
                <rect x={midX - 42} y={midY - 11} width="84" height="22" rx="11" fill="#111722" stroke="#344256" />
                <text x={midX} y={midY + 4} textAnchor="middle" fontSize="10" fill="#dce7f6">
                  {truncate(edge.relation, 14)}
                </text>
              </g>
            );
          })}

          {nodes.map((node) => (
            <g key={node.name}>
              <circle cx={node.x} cy={node.y} r="20" fill={colorFromType(node.type)} fillOpacity="0.18" stroke={colorFromType(node.type)} strokeWidth="1.5" />
              <circle cx={node.x} cy={node.y} r="4.5" fill={colorFromType(node.type)} />
              <text x={node.x} y={node.y - 28} textAnchor="middle" fontSize="11" fill="#eef4fb">
                {truncate(node.name)}
              </text>
              {node.type && (
                <text x={node.x} y={node.y + 34} textAnchor="middle" fontSize="9" fill="#8ea0b5">
                  {truncate(node.type, 12)}
                </text>
              )}
            </g>
          ))}
        </svg>
      </div>

      <div className="mt-3 grid gap-3 md:grid-cols-2">
        <div className="rounded-xl border border-[#283140] bg-[#10141b] p-3">
          <div className="mb-2 text-sm font-medium text-[#e5edf7]">Nodes</div>
          <div className="space-y-2">
            {graph.entities.map((entity) => (
              <div key={entity.name} className="rounded-lg border border-[#243041] bg-[#151b24] px-3 py-2">
                <div className="text-sm text-[#f2f6fb]">{entity.name}</div>
                {entity.type && <div className="mt-1 text-xs text-[#8ea0b5]">{entity.type}</div>}
              </div>
            ))}
          </div>
        </div>

        <div className="rounded-xl border border-[#283140] bg-[#10141b] p-3">
          <div className="mb-2 text-sm font-medium text-[#e5edf7]">Edges</div>
          <div className="space-y-2">
            {graph.triplets.map((triplet, index) => (
              <div key={`${triplet.head}-${triplet.relation}-${triplet.tail}-${index}`} className="rounded-lg border border-[#243041] bg-[#151b24] px-3 py-2">
                <div className="text-sm text-[#f2f6fb]">
                  <span className="font-medium">{triplet.head}</span>
                  <span className="mx-2 text-[#7bc6ff]">[{triplet.relation}]</span>
                  <span className="font-medium">{triplet.tail}</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
