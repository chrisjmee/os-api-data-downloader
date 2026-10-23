import { useCallback, useEffect, useMemo, useState } from "react";
import { Background, Controls, ReactFlow, ReactFlowProvider } from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import Sidebar from "./components/Sidebar";
import Details from "./components/Details";
import FeatureNode from "./components/FeatureNode";
import KeyEdge from "./components/KeyEdge";
import { CASES, DATA, FEATURES, themeColor, isExternal, KEY_STYLE, LINKS, linksOf, OTHER_KEY, shortestRoutes, STORAGE } from "./lib/data";
import { dagreColumns, grid, NODE_H, orderByNeighbours } from "./lib/layout";

const nodeTypes = { feature: FeatureNode };
const edgeTypes = { key: KeyEdge };
const START = "Building";

// What's on screen: one feature, a route between two, or a use case. It's kept in the address bar
// (#Building, #route=Building,Ward, #case=property) so a view can be bookmarked or shared.
function readHash() {
  const h = decodeURIComponent(window.location.hash.slice(1));
  if (h.startsWith("route=")) {
    const [from, to] = h.slice(6).split(",");
    if (FEATURES.has(from) && FEATURES.has(to)) return { kind: "route", from, to };
  }
  if (h.startsWith("case=") && CASES.has(h.slice(5))) return { kind: "case", id: h.slice(5) };
  return { kind: "feature", id: FEATURES.has(h) ? h : START };
}
const hashOf = (v) => (v.kind === "route" ? `route=${v.from},${v.to}` : v.kind === "case" ? `case=${v.id}` : v.id);

function featureNode(id, pos, extra = {}) {
  const f = FEATURES.get(id);
  return {
    id,
    type: "feature",
    position: { x: pos.x, y: pos.y },
    data: { title: f.title, sub: f.delivery === "external" ? f.org : f.group, about: f.about, width: pos.width,
            height: NODE_H, external: f.delivery === "external", themeColor: themeColor(f.theme), ...extra },
  };
}

// lines of the same key sit together: keys in legend order, then alphabetical
const KEY_ORDER = Object.keys(KEY_STYLE);
const keyRank = (l) => {
  const i = KEY_ORDER.indexOf(l.keys[0]);
  return i < 0 ? KEY_ORDER.length : i;
};
const byKeyThenTitle = (linkOf) => (a, b) =>
  keyRank(linkOf(a)) - keyRank(linkOf(b)) || FEATURES.get(a).title.localeCompare(FEATURES.get(b).title);

function edge(link, source, target, { sourceHandle = "out", targetHandle = "in" } = {}) {
  // no arrows: a join works both ways; which side holds the ID is in the details panel
  return { id: link.id, source, target, sourceHandle, targetHandle, type: "key", data: { link } };
}

const item = (id) => ({ id, title: FEATURES.get(id).title });

/** One feature type in the middle, what stores its ID on the left, what it stores the IDs of on the right. */
function featureView(focus, withExternal) {
  const { out, in: inn } = linksOf(focus, withExternal);
  const outOf = new Map(out.map((l) => [l.target, l]));
  const inOf = new Map(inn.map((l) => [l.source, l]));
  // a feature linked both ways goes on the right only
  const right = [...outOf.keys()].sort(byKeyThenTitle((id) => outOf.get(id)));
  const left = [...inOf.keys()].filter((id) => !outOf.has(id)).sort(byKeyThenTitle((id) => inOf.get(id)));
  const pos = grid([left.map(item), [item(focus)], right.map(item)]);
  const nodes = [focus, ...left, ...right].map((id) => featureNode(id, pos[id], { focus: id === focus }));
  const edges = [
    ...out.map((l) => edge(l, focus, l.target)),
    ...inn.map((l) => (outOf.has(l.source) ? edge(l, focus, l.source) : edge(l, l.source, focus))),
  ];
  return { nodes, edges };
}

/** Every shortest chain of links between two feature types, one column per step. */
function routeView(route, withExternal) {
  const r = shortestRoutes(route.from, route.to, withExternal);
  if (!r?.found) return { nodes: [], edges: [], result: r };
  const cols = Array.from({ length: r.steps + 1 }, () => []);
  for (const [id, step] of r.nodes) cols[step].push(id);
  const links = r.links.map((x) => x.link);
  const pos = grid(orderByNeighbours(cols, links).map((c) => c.map(item)));
  const nodes = [...r.nodes.keys()].map((id) => featureNode(id, pos[id], { focus: id === route.from || id === route.to }));
  // drawn in route order (left to right)
  const edges = r.links.map(({ link, prev, next }) => edge(link, prev, next));
  return { nodes, edges, result: r };
}

/** A use case: the feature types and links it follows, in tidy columns. */
function caseView(id) {
  const uc = CASES.get(id);
  const links = uc.links.map((l) => LINKS.get(l)).filter((l) => l.source !== l.target);
  const ids = [...new Set(links.flatMap((l) => [l.source, l.target]))];
  const cols = dagreColumns(ids, links);
  const colOf = new Map(cols.flatMap((c, i) => c.map((x) => [x, i])));
  const pos = grid(cols.map((c) => c.map(item)));
  const nodes = ids.map((x) => featureNode(x, pos[x]));
  // always drawn left to right; the arrow shows which way the ID is stored
  const edges = links.map((l) =>
    colOf.get(l.source) <= colOf.get(l.target) ? edge(l, l.source, l.target) : edge(l, l.target, l.source)
  );
  return { nodes, edges };
}

function LineSample({ color = "currentColor", dash }) {
  return (
    <svg width="36" height="10" aria-hidden="true">
      <line x1="1" y1="5" x2="35" y2="5" stroke={color} strokeWidth="3" strokeDasharray={dash} />
    </svg>
  );
}

function Legend() {
  return (
    <div className="legend">
      <div className="legend__row">
        <strong>Linking key</strong>
        {Object.entries(KEY_STYLE).map(([id, k]) => (
          <span key={id}><LineSample color={k.color} /> {k.label}</span>
        ))}
        <span><LineSample color={OTHER_KEY} /> Other</span>
      </div>
      <div className="legend__row">
        <strong>Stored</strong>
        <span><LineSample /> on the feature</span>
        <span><LineSample dash={STORAGE.table.dash} /> in a reference table</span>
        <span><LineSample dash={STORAGE.related.dash} /> Related Entity table</span>
        <span className="muted">Click a line for the attributes to join on.</span>
      </div>
      <div className="legend__row">
        <strong>Theme</strong>
        {DATA.themes.map((t) => (
          <span key={t}><i className="swatch" style={{ background: themeColor(t) }} /> {t}</span>
        ))}
      </div>
    </div>
  );
}

function Explorer() {
  const [view, setView] = useState(readHash);
  // the feature shown in the right-hand panel; on a use case nothing until a box is clicked
  const [focus, setFocus] = useState(() => (view.kind === "feature" ? view.id : view.kind === "route" ? view.from : null));
  const [selectedId, setSelectedId] = useState(null);
  const [withExternal, setWithExternal] = useState(true);

  // keep the address bar in step, and follow the browser's back and forward buttons
  useEffect(() => {
    const h = hashOf(view);
    if (decodeURIComponent(window.location.hash.slice(1)) !== h) window.history.pushState(null, "", `#${h}`);
  }, [view]);
  useEffect(() => {
    const onPop = () => {
      const v = readHash();
      setView(v);
      setFocus(v.kind === "feature" ? v.id : v.kind === "route" ? v.from : null);
      setSelectedId(null);
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const goFeature = useCallback((id) => {
    setView({ kind: "feature", id });
    setFocus(id);
    setSelectedId(null);
  }, []);
  const goRoute = useCallback(({ from, to }) => {
    setView({ kind: "route", from, to });
    setFocus(from);
    setSelectedId(null);
  }, []);
  const goCase = useCallback((id) => {
    setView({ kind: "case", id });
    setFocus(null);
    setSelectedId(null);
  }, []);
  // a feature hidden by the "other organisations" switch can't stay in view (use cases always show all their links)
  useEffect(() => {
    if (withExternal) return;
    if (view.kind === "feature" && isExternal(view.id)) goFeature(START);
    if (view.kind === "route" && (isExternal(view.from) || isExternal(view.to))) goFeature(view.from);
  }, [withExternal, view, goFeature]);

  const shown = useMemo(
    () =>
      view.kind === "route"
        ? routeView(view, withExternal)
        : view.kind === "case"
          ? caseView(view.id)
          : featureView(view.id, withExternal),
    [view, withExternal]
  );
  const selected = selectedId ? LINKS.get(selectedId) : null;
  const edges = useMemo(
    () =>
      shown.edges.map((e) => ({
        ...e,
        data: { ...e.data, selected: e.id === selectedId, dim: !!selectedId && e.id !== selectedId, onSelect: setSelectedId },
      })),
    [shown, selectedId]
  );
  const nodes = useMemo(
    () => shown.nodes.map((n) => (view.kind === "case" ? { ...n, data: { ...n.data, focus: n.id === focus } } : n)),
    [shown, view.kind, focus]
  );

  const viewKey = `${hashOf(view)}:${withExternal}`;
  const fromT = view.kind === "route" && FEATURES.get(view.from).title;
  const toT = view.kind === "route" && FEATURES.get(view.to).title;
  const uc = view.kind === "case" && CASES.get(view.id);

  return (
    <div className="app">
      <header className="header">
        <h1>OS NGD Links</h1>
        <p>How OS NGD feature types join: which key, which attribute, and the route between any two.</p>
      </header>
      <Sidebar
        view={view}
        onFocus={goFeature}
        onRoute={goRoute}
        onCase={goCase}
        withExternal={withExternal}
        onExternal={setWithExternal}
      />
      <main className="canvas">
        {view.kind === "route" && (
          <div className="banner">
            {shown.result?.found ? (
              <span>
                <strong>{fromT}</strong> to <strong>{toT}</strong>: {shown.result.steps} link{shown.result.steps > 1 ? "s" : ""}
                {shown.edges.length > shown.result.steps ? " (every shortest route shown)" : ""}
              </span>
            ) : (
              <span>
                No chain of links joins <strong>{fromT}</strong> and <strong>{toT}</strong>
                {withExternal ? "." : " without other organisations' datasets."}
              </span>
            )}
            <button type="button" onClick={() => goFeature(view.from)}>Close route</button>
          </div>
        )}
        {uc && (
          <div className="banner">
            <span>
              <strong>{uc.title}</strong>
            </span>
            <button type="button" onClick={() => goFeature(START)}>Close</button>
          </div>
        )}
        <ReactFlow
          key={viewKey}
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          onNodeClick={(_, n) => {
            if (view.kind === "feature") goFeature(n.id);
            else {
              // on a route or use case, a click shows that feature's details without leaving the view
              setSelectedId(null);
              setFocus(n.id);
            }
          }}
          onEdgeClick={(_, e) => setSelectedId(e.id)}
          onPaneClick={() => setSelectedId(null)}
          nodesConnectable={false}
          fitView
          fitViewOptions={{ padding: { top: "90px", bottom: "150px", left: "30px", right: "30px" }, maxZoom: 1 }}
          minZoom={0.15}
          colorMode="system"
          proOptions={{ hideAttribution: true }}
        >
          <Background gap={28} size={1} />
          <Controls showInteractive={false} position="bottom-right" />
        </ReactFlow>
        <Legend />
      </main>
      <Details
        focus={focus}
        useCase={uc || null}
        selected={selected}
        withExternal={withExternal}
        onSelect={setSelectedId}
        onFocus={goFeature}
        onBack={() => (selected ? setSelectedId(null) : setFocus(null))}
      />
    </div>
  );
}

export default function App() {
  return (
    <ReactFlowProvider>
      <Explorer />
    </ReactFlowProvider>
  );
}
