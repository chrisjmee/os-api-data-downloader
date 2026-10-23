// Neat column layout: boxes sized to their names, left edges lined up in each column, rows evenly spaced and centred.
import dagre from "@dagrejs/dagre";

export const NODE_H = 52;
export const ROW = NODE_H + 18; // vertical pitch between boxes
export const GAP = 150; // space between columns, for the lines

// Boxes are sized to their names, like the original OS explorer
const ctx = typeof document !== "undefined" ? document.createElement("canvas").getContext("2d") : null;
export function nodeWidth(title) {
  if (!ctx) return 180;
  ctx.font = "600 14px system-ui, -apple-system, 'Segoe UI', sans-serif";
  return Math.max(140, Math.ceil(ctx.measureText(title).width) + 32);
}

/** Place columns of {id, title}: every box in a column starts at the same left edge, columns are spaced by
 *  their widest box, rows are evenly spaced and each column is centred on y = 0. Returns {id: {x, y, width}}. */
export function grid(cols) {
  const pos = {};
  let x = 0;
  for (const col of cols) {
    const widths = col.map((n) => nodeWidth(n.title));
    col.forEach((n, j) => {
      pos[n.id] = { x, y: (j - (col.length - 1) / 2) * ROW - NODE_H / 2, width: widths[j] };
    });
    x += (widths.length ? Math.max(...widths) : 0) + GAP;
  }
  return pos;
}

/** Use dagre only to choose each box's column and order (fewest crossings), then snap to the grid. */
export function dagreColumns(ids, links) {
  const g = new dagre.graphlib.Graph({ multigraph: true });
  g.setGraph({ rankdir: "LR", nodesep: 20, ranksep: 100 });
  g.setDefaultEdgeLabel(() => ({}));
  ids.forEach((id) => g.setNode(id, { width: 200, height: NODE_H }));
  links.forEach((l, i) => g.setEdge(l.source, l.target, {}, `e${i}`));
  dagre.layout(g);
  const xs = [...new Set(ids.map((id) => Math.round(g.node(id).x)))].sort((a, b) => a - b);
  const cols = xs.map(() => []);
  ids.forEach((id) => cols[xs.indexOf(Math.round(g.node(id).x))].push(id));
  cols.forEach((c) => c.sort((a, b) => g.node(a).y - g.node(b).y));
  return cols;
}

/** Order each column by the average row of the boxes it links to in the column before (fewer crossings). */
export function orderByNeighbours(cols, links) {
  for (let i = 1; i < cols.length; i++) {
    const prevRow = new Map(cols[i - 1].map((id, j) => [id, j]));
    const score = (id) => {
      const rows = links
        .filter((l) => (l.source === id && prevRow.has(l.target)) || (l.target === id && prevRow.has(l.source)))
        .map((l) => prevRow.get(l.source === id ? l.target : l.source));
      return rows.length ? rows.reduce((a, b) => a + b, 0) / rows.length : 0;
    };
    cols[i].sort((a, b) => score(a) - score(b));
  }
  return cols;
}
