// Left-to-right layout with dagre. Node widths follow their titles so long names never overflow.
import dagre from "@dagrejs/dagre";

const ctx = typeof document !== "undefined" ? document.createElement("canvas").getContext("2d") : null;
export const NODE_HEIGHT = 58;

export function nodeWidth(title) {
  if (!ctx) return 200;
  ctx.font = "600 14px system-ui, -apple-system, 'Segoe UI', sans-serif";
  return Math.max(150, Math.min(300, Math.ceil(ctx.measureText(title).width) + 40));
}

/**
 * @param {{id: string, title: string}[]} items  nodes to place
 * @param {{source: string, target: string}[]} order  edges in the left-to-right order to lay out by
 * @param {object} [opts]  rank: fixed column per node id (used for routes)
 */
export function layout(items, order) {
  const g = new dagre.graphlib.Graph({ multigraph: true });
  g.setGraph({ rankdir: "LR", nodesep: 18, ranksep: 150, marginx: 20, marginy: 20 });
  g.setDefaultEdgeLabel(() => ({}));
  for (const n of items) g.setNode(n.id, { width: nodeWidth(n.title), height: NODE_HEIGHT });
  order.forEach((e, i) => g.setEdge(e.source, e.target, { minlen: 1 }, `e${i}`));
  dagre.layout(g);
  const pos = {};
  for (const n of items) {
    const p = g.node(n.id);
    pos[n.id] = { x: p.x - p.width / 2, y: p.y - p.height / 2, width: p.width };
  }
  return pos;
}

/** Routes: one column per step from the start, each column centred vertically. */
export function columns(items, stepOf) {
  const cols = new Map();
  for (const n of items) {
    const s = stepOf[n.id];
    if (!cols.has(s)) cols.set(s, []);
    cols.get(s).push(n);
  }
  const pos = {};
  for (const [s, col] of cols) {
    col.sort((a, b) => a.title.localeCompare(b.title));
    const top = -((col.length - 1) * (NODE_HEIGHT + 28)) / 2;
    col.forEach((n, i) => {
      const w = nodeWidth(n.title);
      pos[n.id] = { x: s * 340 + (300 - w) / 2, y: top + i * (NODE_HEIGHT + 28), width: w };
    });
  }
  return pos;
}
