// The data, and the lookups the app needs. ngd-links.json is written by explorer/export_react_data.py from the
// OS relationship model in this repository - run `npm run data` to refresh it.
import raw from "../data/ngd-links.json";

export const DATA = raw;
export const FEATURES = new Map(raw.features.map((f) => [f.id, f]));
export const KEYS = new Map(raw.keys.map((k) => [k.id, k]));
export const LINKS = new Map(raw.links.map((l) => [l.id, l]));
export const CASES = new Map(raw.cases.map((c) => [c.id, c]));

// Colour for each linking key. The five keys most links use get their own colour; the rest share grey.
export const KEY_STYLE = {
  osid: { label: "OSID", color: "#005eb8" },
  uprn: { label: "UPRN", color: "#007a33" },
  usrn: { label: "USRN", color: "#c45200" },
  gsscode: { label: "GSS code", color: "#7a3e9d" },
  postcode: { label: "Postcode", color: "#0e7c86" },
};
export const OTHER_KEY = "#8a8580";
export function keyStyle(id) {
  return KEY_STYLE[id] ?? { label: KEYS.get(id)?.name ?? id, color: OTHER_KEY };
}

export const STORAGE = {
  attribute: { label: "Stored on the feature", dash: undefined },
  table: { label: "Listed in a reference table", dash: "7 5" },
  related: { label: "Related Entity table (Select+Build)", dash: "2 5" },
  both: { label: "On the feature and in a table", dash: undefined },
};

export const DELIVERY = {
  api: "OS NGD API - Features",
  sb: "OS Select+Build only",
  external: "Another organisation's data",
};

export const isExternal = (id) => FEATURES.get(id)?.delivery === "external";

// links, indexed both ways
const OUT = new Map();
const IN = new Map();
for (const l of raw.links) {
  if (!OUT.has(l.source)) OUT.set(l.source, []);
  if (!IN.has(l.target)) IN.set(l.target, []);
  OUT.get(l.source).push(l);
  IN.get(l.target).push(l);
}

const allowed = (l, withExternal) =>
  withExternal || (!isExternal(l.source) && !isExternal(l.target));

/** Links from and to one feature type, split by direction; self links listed separately. */
export function linksOf(id, withExternal) {
  const out = (OUT.get(id) ?? []).filter((l) => allowed(l, withExternal));
  const inn = (IN.get(id) ?? []).filter((l) => allowed(l, withExternal));
  return {
    out: out.filter((l) => l.target !== id),
    in: inn.filter((l) => l.source !== id),
    self: out.filter((l) => l.target === id),
  };
}

/** Every shortest chain of links between two feature types (direction ignored). Returns the features on
 *  those chains, each one's step number, and the links used. */
export function shortestRoutes(from, to, withExternal) {
  if (from === to) return null;
  const adj = new Map();
  const add = (a, b, l) => {
    if (!adj.has(a)) adj.set(a, []);
    adj.get(a).push({ next: b, link: l });
  };
  for (const l of raw.links) {
    if (l.source === l.target || !allowed(l, withExternal)) continue;
    add(l.source, l.target, l);
    add(l.target, l.source, l);
  }
  const dist = new Map([[from, 0]]);
  const parents = new Map();
  const queue = [from];
  while (queue.length) {
    const n = queue.shift();
    if (n === to) continue;
    for (const { next, link } of adj.get(n) ?? []) {
      if (!dist.has(next)) {
        dist.set(next, dist.get(n) + 1);
        parents.set(next, [{ prev: n, link }]);
        queue.push(next);
      } else if (dist.get(next) === dist.get(n) + 1) {
        parents.get(next).push({ prev: n, link });
      }
    }
  }
  if (!dist.has(to)) return { found: false };
  const nodes = new Map([[to, dist.get(to)]]);
  const links = new Map();
  const stack = [to];
  while (stack.length) {
    const n = stack.pop();
    for (const { prev, link } of parents.get(n) ?? []) {
      links.set(link.id, { link, prev, next: n });
      if (!nodes.has(prev)) {
        nodes.set(prev, dist.get(prev));
        stack.push(prev);
      }
    }
  }
  return { found: true, steps: dist.get(to), nodes, links: [...links.values()] };
}

/** Feature types grouped by theme, then by group, for the sidebar. */
export function featuresByTheme(filter, withExternal) {
  const q = filter.trim().toLowerCase();
  const out = [];
  for (const theme of raw.themes) {
    const items = raw.features.filter(
      (f) =>
        f.theme === theme &&
        (withExternal || f.delivery !== "external") &&
        (!q || f.title.toLowerCase().includes(q) || f.group.toLowerCase().includes(q) || f.org.toLowerCase().includes(q))
    );
    if (items.length) out.push({ theme, items });
  }
  return out;
}
