import { useCallback, useEffect, useMemo, useState } from "react";
import { Background, Controls, MarkerType, ReactFlow, ReactFlowProvider } from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import Sidebar from "./components/Sidebar";
import Details from "./components/Details";
import FeatureNode from "./components/FeatureNode";
import KeyEdge from "./components/KeyEdge";
import { CASES, FEATURES, isExternal, KEY_STYLE, LINKS, linksOf, shortestRoutes } from "./lib/data";
import { columns, layout } from "./lib/layout";

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
            external: f.delivery === "external", ...extra },
  };
}

/** One feature type in the middle, what it stores the IDs of on the right, what stores its ID on the left. */
function featureView(focus, withExternal) {
  const { out, in: inn } = linksOf(focus, withExternal);
  const ids = [...new Set([focus, ...out.map((l) => l.target), ...inn.map((l) => l.source)])];
  const items = ids.map((id) => ({ id, title: FEATURES.get(id).title }));
  // a feature linked both ways is laid out on the right only, so the picture stays left-to-right
  const right = new Set(out.map((l) => l.target));
  const order = [...out, ...inn.filter((l) => !right.has(l.source))];
  const pos = layout(items, order);
  const nodes = ids.map((id) => featureNode(id, pos[id], { focus: id === focus }));
  const arrow = { type: MarkerType.ArrowClosed, width: 16, height: 16, color: "#6a6664" };
  const edges = [
    ...out.map((l) => ({ id: l.id, source: l.source, target: l.target, type: "key", data: { link: l }, markerEnd: arrow })),
    // linked both ways: drawn along the same line, with the arrow at the other end
    ...inn.map((l) =>
      right.has(l.source)
        ? { id: l.id, source: focus, target: l.source, type: "key", data: { link: l }, markerStart: arrow }
        : { id: l.id, source: l.source, target: l.target, type: "key", data: { link: l }, markerEnd: arrow }
    ),
  ];
  return { nodes, edges: spreadBadges(edges) };
}

/** Every shortest chain of links between two feature types, one column per step. */
function routeView(route, withExternal) {
  const r = shortestRoutes(route.from, route.to, withExternal);
  if (!r?.found) return { nodes: [], edges: [], result: r };
  const items = [...r.nodes.keys()].map((id) => ({ id, title: FEATURES.get(id).title }));
  const pos = columns(items, Object.fromEntries(r.nodes));
  const nodes = items.map(({ id }) => featureNode(id, pos[id], { focus: id === route.from || id === route.to }));
  const arrow = { type: MarkerType.ArrowClosed, width: 16, height: 16, color: "#6a6664" };
  // drawn in route order (left to right); the arrow still points at the feature whose ID is stored
  const edges = r.links.map(({ link, prev, next }) => ({
    id: link.id,
    source: prev,
    target: next,
    type: "key",
    data: { link },
    ...(link.target === next ? { markerEnd: arrow } : { markerStart: arrow }),
  }));
  return { nodes, edges: spreadBadges(edges), result: r };
}

/** A use case: the feature types and links it follows, laid out left to right. */
function caseView(id) {
  const uc = CASES.get(id);
  const links = uc.links.map((l) => LINKS.get(l)).filter((l) => l.source !== l.target);
  const ids = [...new Set(links.flatMap((l) => [l.source, l.target]))];
  const items = ids.map((x) => ({ id: x, title: FEATURES.get(x).title }));
  const pos = layout(items, links);
  const nodes = ids.map((x) => featureNode(x, pos[x]));
  const arrow = { type: MarkerType.ArrowClosed, width: 16, height: 16, color: "#6a6664" };
  const seen = new Set();
  const edges = links.map((l) => {
    const back = seen.has(`${l.target}|${l.source}`); // the reverse link is already drawn: share its line
    seen.add(`${l.source}|${l.target}`);
    return back
      ? { id: l.id, source: l.target, target: l.source, type: "key", data: { link: l }, markerStart: arrow }
      : { id: l.id, source: l.source, target: l.target, type: "key", data: { link: l }, markerEnd: arrow };
  });
  return { nodes, edges: spreadBadges(edges) };
}

/** Two links drawn between the same pair of boxes would hide each other's badge: stack the badges instead. */
function spreadBadges(edges) {
  const groups = new Map();
  for (const e of edges) {
    const k = [e.source, e.target].sort().join("|");
    if (!groups.has(k)) groups.set(k, []);
    groups.get(k).push(e);
  }
  for (const g of groups.values()) g.forEach((e, i) => (e.data.offset = (i - (g.length - 1) / 2) * 22));
  return edges;
}

function Legend() {
  return (
    <div className="legend">
      <div className="legend__row">
        {Object.entries(KEY_STYLE).map(([id, k]) => (
          <span key={id} className="chip" style={{ background: k.color }}>{k.label}</span>
        ))}
        <span className="chip" style={{ background: "#6a6664" }}>Other keys</span>
      </div>
      <div className="legend__row small">
        <span><svg width="34" height="8"><line x1="0" y1="4" x2="34" y2="4" stroke="currentColor" strokeWidth="2" /></svg> ID stored on the feature</span>
        <span><svg width="34" height="8"><line x1="0" y1="4" x2="34" y2="4" stroke="currentColor" strokeWidth="2" strokeDasharray="7 5" /></svg> in a reference table ▤</span>
        <span><svg width="34" height="8"><line x1="0" y1="4" x2="34" y2="4" stroke="currentColor" strokeWidth="2" strokeDasharray="2 5" /></svg> Related Entity table (Select+Build)</span>
        <span>→ points to the feature whose ID is stored</span>
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
          fitViewOptions={{ padding: 0.15, maxZoom: 1.1 }}
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
