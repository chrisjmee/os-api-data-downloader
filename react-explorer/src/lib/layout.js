// Neat column layout: every box the same size, columns evenly spaced, rows evenly spaced and centred.
import dagre from "@dagrejs/dagre";

export const NODE_W = 250;
export const NODE_H = 64;
export const ROW = NODE_H + 22; // vertical pitch between boxes
export const COL = NODE_W + 190; // horizontal pitch between columns

/** Place columns of ids: column i at x = i * COL, each column centred on y = 0. Returns {id: {x, y}}. */
export function grid(cols) {
  const pos = {};
  cols.forEach((col, i) => {
    col.forEach((id, j) => {
      pos[id] = { x: i * COL, y: (j - (col.length - 1) / 2) * ROW - NODE_H / 2 };
    });
  });
  return pos;
}

/** Use dagre only to choose each box's column and order (fewest crossings), then snap to the grid. */
export function dagreColumns(ids, links) {
  const g = new dagre.graphlib.Graph({ multigraph: true });
  g.setGraph({ rankdir: "LR", nodesep: 20, ranksep: 100 });
  g.setDefaultEdgeLabel(() => ({}));
  ids.forEach((id) => g.setNode(id, { width: NODE_W, height: NODE_H }));
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
