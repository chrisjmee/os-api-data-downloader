// The data, and the lookups the app needs. It is read at start-up from two files that sit next to the page:
//   ngdhierarchy.json  - themes, collections, feature types and their relationships (the OS explorer's format)
//   ngdreference.json  - the linking keys explained, and the use cases
// Both are written by explorer/export_ngd_hierarchy.py from the OS relationship model: `npm run data`.

export const DATA = { themes: [], features: [], links: [], cases: [], keys: [], version: "", built: "" };
export const FEATURES = new Map();
export const KEYS = new Map();
export const LINKS = new Map();
export const CASES = new Map();
const OUT = new Map();
const IN = new Map();

// Theme colours, after OS map conventions (building salmon, vegetation green, water blue, road amber...).
// Kept lighter than the line colours below so a box's theme never reads as a linking key.
const THEME_COLORS = {
  buildings: "#d98b74", landuse: "#d6b56d", land: "#8fc165", address: "#e07a8a", structures: "#a39a8e",
  transport: "#f2b134", water: "#6cb4e0", administrative: "#b4a0d8", geographicalnames: "#5d5955",
  osreference: "#c9c5bf", external: "#e3dccf",
};
const THEME_COLOR_BY_LABEL = {};
export const themeColor = (theme) => THEME_COLOR_BY_LABEL[theme] ?? "#c9c5bf";

const STORAGE_OF = { attribute: "attribute", crossReference: "table", standaloneCrossReference: "related",
                     attributeAndCrossReference: "both" };

async function getJson(name) {
  const res = await fetch(`./${name}`);
  if (!res.ok) throw new Error(`${name} could not be loaded (${res.status}). Keep it in the same folder as the page.`);
  return res.json();
}

/** Read both files and build the lookups. Call once, before the app renders. */
export async function loadData() {
  const [hier, ref] = await Promise.all([getJson("ngdhierarchy.json"), getJson("ngdreference.json")]);
  const all = [];
  for (const [themeId, theme] of Object.entries(hier)) {
    const label = theme.label.replace(/^OS NGD /, "");
    THEME_COLOR_BY_LABEL[label] = THEME_COLORS[themeId] ?? "#c9c5bf";
    for (const col of Object.values(theme.collections)) {
      for (const ft of col.featureTypes) all.push({ ft, theme: label, group: col.label });
    }
  }
  for (const { ft } of all) {
    for (const rel of [...(ft.relationships ?? []), ...(ft.selfRelationships ?? [])]) {
      const joins = (rel.joins ?? []).map((j) => ({
        field: j.sourceField, targetField: j.targetField, key: j.key, storage: STORAGE_OF[j.storage] ?? "attribute",
        osType: j.osRelationshipType, purpose: j.purpose, sentence: j.sentence, meaning: j.meaning,
      }));
      const link = {
        id: rel.id, source: ft.id, target: rel.targetFeature,
        keys: rel.relationshipType?.keys ?? [...new Set(joins.map((j) => j.key))],
        storage: STORAGE_OF[rel.relationshipType?.type] ?? "attribute",
        meaning: [...new Set(joins.map((j) => j.meaning).filter(Boolean))],
        sentences: joins.length ? joins.map((j) => j.sentence) : [rel.relationshipType?.description ?? ""],
        joins,
      };
      DATA.links.push(link);
      LINKS.set(link.id, link);
      if (!OUT.has(link.source)) OUT.set(link.source, []);
      if (!IN.has(link.target)) IN.set(link.target, []);
      OUT.get(link.source).push(link);
      IN.get(link.target).push(link);
    }
  }
  // feature types that take part in at least one relationship
  const linked = new Set(DATA.links.flatMap((l) => [l.source, l.target]));
  for (const { ft, theme, group } of all) {
    if (!linked.has(ft.id)) continue;
    const f = { id: ft.id, title: ft.label, theme, group, org: ft.organisation ?? "Ordnance Survey",
                delivery: ft.delivery ?? "api", api: ft.apiCollection ?? "", about: ft.description ?? "" };
    DATA.features.push(f);
    FEATURES.set(f.id, f);
  }
  DATA.features.sort((a, b) => a.title.localeCompare(b.title));
  DATA.themes = [...new Set(all.map((x) => x.theme))].filter((t) => DATA.features.some((f) => f.theme === t));
  DATA.keys = ref.keys;
  ref.keys.forEach((k) => KEYS.set(k.id, k));
  DATA.cases = ref.useCases.map((c) => ({ ...c, links: c.relationships.filter((id) => LINKS.has(id)) }));
  DATA.cases.forEach((c) => CASES.set(c.id, c));
  DATA.version = ref.version;
  DATA.built = ref.built;
}

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
  for (const l of DATA.links) {
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
  for (const theme of DATA.themes) {
    const items = DATA.features.filter(
      (f) =>
        f.theme === theme &&
        (withExternal || f.delivery !== "external") &&
        (!q || f.title.toLowerCase().includes(q) || f.group.toLowerCase().includes(q) || f.org.toLowerCase().includes(q))
    );
    if (items.length) out.push({ theme, items });
  }
  return out;
}
