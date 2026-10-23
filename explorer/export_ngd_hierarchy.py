"""Exports the OS NGD Data Linkages Explorer's relationships as ``ngdhierarchy.json`` for OS's React Flow app,
the "OS NGD Relationship Explorer" (os_ngd_relationships_react.html).

    python explorer/export_ngd_hierarchy.py            -> explorer/dist/ngdhierarchy.json
                                                          docs/ngd-links/ngdhierarchy.json

The layout (themes, collections, feature type ids and labels) starts from that app's own file, kept in
explorer/data/ngdhierarchy_base.json, so its ids and wording are unchanged. Every relationship is then
regenerated from OS's relationship model, the same data the Explorer page uses, and feature types the
model mentions that the app doesn't yet have are added.

What is carried across, in the app's own format:
* one relationship per pair of feature types, with the app's badge type (attribute, cross-reference table,
  both, or standalone cross-reference table), a plain-English description and a direction;
* only current schema versions (relationships from superseded versions are left out);
* links to other organisations' datasets, under an extra "Other organisations' datasets" theme.

It also writes ngdreference.json alongside: the linking keys explained and the use cases, which the
React app (react-explorer/) reads with the hierarchy. Joins worked out from location are left out. Extra detail the app doesn't read yet is still written into each record (``joins``,
``availability``, ``organisation``, ``description``, ``selfRelationships``) so a later version of the app
can use it; the current app ignores those fields.
"""
import copy
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)
import build_explorer as B  # noqa: E402
import content as C  # noqa: E402

EXPORT_VERSION = "2.0.0"
BASE = os.path.join(HERE, "data", "ngdhierarchy_base.json")
# written next to each other in every place they're used: the React app (react-explorer/public) reads both
OUT_DIRS = [os.path.join(HERE, "dist"), os.path.join(ROOT, "docs", "ngd-links"),
            os.path.join(ROOT, "react-explorer", "public")]

OS = "Ordnance Survey"
# OS model theme -> the app's theme id
THEME_IDS = {"Building": "buildings", "Land": "land", "Address": "address",
             "Administrative and Statistical Unit": "administrative", "Geographical Names": "geographicalnames",
             "Land Use": "landuse", "Structures": "structures", "Transport": "transport", "Water": "water"}
# OS features the model files under a placeholder or outside OS NGD's themes: (theme id, collection id, label)
PLACE = {
    "BuiltUpArea": ("osreference", "built-up-areas", "Built Up Areas"),
    "Grid100m": ("osreference", "grids", "Grids"),
    "Grid1km": ("osreference", "grids", "Grids"),
    "WaterCatchment": ("water", "water-features", None),
}
EXTRA_THEMES = {"osreference": "OS reference data (outside OS NGD)", "external": "Other organisations' datasets"}
# OS model feature -> the app's id, where the labels differ
ID_ALIASES = {"RoadTrackOrPath": "road-track-path", "PrebuildAddress": "gb-pre-build-address",
              "NonAddressableObject": "gb-non-addressable-object",
              "GreaterLondonAuthorityAssemblyConstituency": "gla-assembly-constituency",
              "WaterBodyCatchment": "waterbody-catchment"}

KEY_NAMES = {"osid": "OSID", "uprn": "UPRN", "usrn": "USRN", "postcode": "postcode", "udprn": "UDPRN",
             "gsscode": "GSS code", "uarn": "UARN", "atcocode": "ATCO code", "waterbodyid": "water body ID",
             "grid": "grid square", "featureid": "feature ID", "other": "identifier"}
KEY_LABELS = {"osid": "OSID", "uprn": "UPRN", "usrn": "USRN", "postcode": "Postcode", "udprn": "UDPRN",
              "gsscode": "GSS code", "uarn": "UARN", "atcocode": "ATCO code", "waterbodyid": "Water body ID",
              "grid": "Grid square", "featureid": "Feature ID", "other": "Partner ID"}
TYPE_LABELS = {"attribute": "Feature ID stored as an attribute", "crossReference": "Cross Reference Table",
               "attributeAndCrossReference": "Attribute and Cross Reference Table",
               "standaloneCrossReference": "Standalone Cross Reference Table"}
TABLE_NAMES = {"relatedentity": "Related Entity", "uprnreference": "UPRN Reference",
               "sitetoaddressreference": "Site to Address Reference", "roadtrackorpathreference":
               "Road Track or Path Reference"}


def norm(s):
    return re.sub(r"[^a-z0-9]", "", str(s).lower().replace(" or ", " "))


def kebab(s):
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", str(s).lower())).strip("-")


def table_title(prefix):
    if prefix in TABLE_NAMES:
        return TABLE_NAMES[prefix]
    words = re.sub(r"reference$", "", prefix)
    for a in ("building", "site", "path", "road", "railway", "water"):          # e.g. buildingpart -> Building Part
        if words.startswith(a) and words != a:
            words = a + " " + words[len(a):]
    return " ".join(w.capitalize() for w in words.split()) + " Reference"


def storage(field):
    """How a join is stored: an attribute on the feature, a cross-reference table delivered with it, or the
    separate Related Entity cross-reference table (OS Select+Build)."""
    if "." not in field:
        return "attribute"
    return "standaloneCrossReference" if field.split(".")[0] == "relatedentity" else "crossReference"


def place_features(hier, feats):
    """Give every OS model feature an id in the app's hierarchy, adding the ones the app doesn't have."""
    index = {}                                   # (theme id, normalised label) -> (collection id, ft)
    for tid, theme in hier.items():
        for cid, col in theme["collections"].items():
            for ft in col["featureTypes"]:
                index.setdefault((tid, norm(ft["label"])), []).append((cid, col, ft))
    all_ids = {ft["id"] for t in hier.values() for c in t["collections"].values() for ft in c["featureTypes"]}

    def collection(tid, label, cid=None):
        theme = hier.setdefault(tid, {"label": EXTRA_THEMES.get(tid, tid), "collections": {}})
        cid = cid or kebab(label)
        for k, c in theme["collections"].items():
            if k == cid or norm(c["label"]) == norm(label):
                return c
        return theme["collections"].setdefault(cid, {"label": label, "featureTypes": []})

    ids, added = {}, []
    for name, f in sorted(feats.items()):
        if f.get("spatial_only"):
            continue
        if name in ID_ALIASES:
            ids[name] = ID_ALIASES[name]
            continue
        if f["org"] != OS:
            col = collection("external", f["org"])
        elif name in PLACE:
            tid, cid, label = PLACE[name]
            col = collection(tid, label, cid) if label else hier[tid]["collections"][cid]
        else:
            tid = THEME_IDS[f["theme"]]
            hits = index.get((tid, norm(f["title"])), [])
            sub = norm(f["subtheme"].replace("Sructure", "Structure"))
            hit = next((h for h in hits if norm(h[1]["label"]) == sub), hits[0] if hits else None)
            if hit:
                ids[name] = hit[2]["id"]
                continue
            col = next((c for c in hier[tid]["collections"].values() if norm(c["label"]) == sub), None)
            col = col or collection(tid, f["subtheme"])
        fid = kebab(f["title"])
        while fid in all_ids:
            fid += "-x"
        all_ids.add(fid)
        col["featureTypes"].append({"id": fid, "label": f["title"]})
        ids[name] = fid
        added.append(f["title"])
    return ids, added


def describe(src, tgt, joins, feats):
    parts = []
    for j in joins:
        key = KEY_NAMES.get(j["key"], j["key"])
        if j["storage"] == "attribute":
            parts.append(f"{src} stores the {tgt} {key} in the attribute {j['sourceField']}")
        else:
            prefix = j["sourceField"].split(".")[0]
            parts.append(f"the {table_title(prefix)} cross-reference table lists each {tgt} {key} "
                         f"({j['sourceField']})")
    text = "; ".join(parts)
    text = text[:1].upper() + text[1:] + "."
    kinds = sorted({j["osRelationshipType"] for j in joins})
    text += f" OS relationship type: {', '.join(kinds)}."
    purposes = sorted({j["purpose"] for j in joins if j["purpose"]})
    if purposes:
        text += " " + " ".join(purposes)
    return text


def sentence(src, tgt, j):
    """One join in plain English, e.g. 'Building stores the Site OSID in primarysiteid.'"""
    key = KEY_NAMES.get(j["key"], j["key"])
    if j["storage"] == "attribute":
        return f"{src} stores the {tgt} {key} in {j['sourceField']}."
    if j["storage"] == "standaloneCrossReference":
        return f"{src} lists every {tgt} {key} in the separate Related Entity table, OS Select+Build ({j['sourceField']})."
    return f"{src} lists every {tgt} {key} in its {table_title(j['sourceField'].split('.')[0])} table ({j['sourceField']})."


def direction(types, os_types):
    if os_types == {"Same As"}:
        return "one-to-one"
    if types & {"crossReference", "standaloneCrossReference"}:
        return "one-to-many"
    return "many-to-one"


def export():
    data, _ = B.collect()
    feats = data["features"]
    for f in feats.values():
        f["spatial_only"] = True
    edges = [e for e in data["edges"] if not e.get("spatial") and not e["old"]]
    for e in edges:
        feats[e["s"]]["spatial_only"] = feats[e["t"]]["spatial_only"] = False

    with open(BASE, encoding="utf-8") as fh:
        hier = json.load(fh)
    hier = copy.deepcopy(hier)
    for t in hier.values():                      # relationships are regenerated in full
        for c in t["collections"].values():
            for ft in c["featureTypes"]:
                ft.pop("relationships", None)
    ids, added = place_features(hier, feats)
    by_id = {ft["id"]: ft for t in hier.values() for c in t["collections"].values() for ft in c["featureTypes"]}

    for name, f in feats.items():               # extra detail the current app ignores
        if f["spatial_only"]:
            continue
        ft = by_id[ids[name]]
        ft["organisation"] = f["org"]
        ft["delivery"] = f["route"]             # api / sb / external
        ft["availability"] = {"api": "OS NGD API - Features", "sb": "OS Select+Build only"}.get(
            f["route"], "Another organisation's dataset")
        if f.get("api"):
            ft["apiCollection"] = f["api"]
        if f.get("about"):
            ft["description"] = f["about"]

    pairs = {}
    for e in edges:
        pairs.setdefault((e["s"], e["t"]), []).append(e)
    n_rel = n_self = 0
    for (s, t), es in sorted(pairs.items(), key=lambda kv: (ids[kv[0][0]], ids[kv[0][1]])):
        sft, tft = by_id[ids[s]], by_id[ids[t]]
        joins = [{"sourceField": e["sf"], "targetField": e["tf"], "key": e["key"], "storage": storage(e["sf"]),
                  "osRelationshipType": e["type"], "joinType": e["join"], "sourceVersion": e["sv"],
                  "owners": e["owners"], "updateFrequency": e["freq"], "purpose": e["purpose"],
                  "meaning": C.FAMILIES.get(e["family"], ("", ""))[0]} for e in es]
        for j in joins:
            j["sentence"] = sentence(sft["label"], tft["label"], j)
        types = {j["storage"] for j in joins}
        rtype = ("attributeAndCrossReference" if "attribute" in types and len(types) > 1 else
                 "standaloneCrossReference" if types == {"standaloneCrossReference"} else
                 "crossReference" if "attribute" not in types else "attribute")
        rel = {"id": f"{ids[s]}--{ids[t]}", "targetFeature": ids[t],
               "relationshipType": {"type": rtype, "label": TYPE_LABELS[rtype] + " · " + " / ".join(
                                        dict.fromkeys(KEY_LABELS.get(j["key"], j["key"]) for j in joins)),
                                    "keys": list(dict.fromkeys(j["key"] for j in joins)),
                                    "description": describe(sft["label"], tft["label"], joins, feats),
                                    "direction": direction(types, {j["osRelationshipType"] for j in joins})},
               "joins": joins}
        if s == t:                               # the app's graph can't draw a feature linked to itself
            rel["relationshipType"]["description"] = rel["relationshipType"]["description"].replace(
                f"the {tft['label']}", f"another {tft['label']}'s", 1)
            sft.setdefault("selfRelationships", []).append(rel)
            n_self += 1
        else:
            sft.setdefault("relationships", []).append(rel)
            n_rel += 1

    # ngdreference.json: the linking keys and the use cases, which have no place in the hierarchy itself
    by_edge = {e["id"]: e for e in data["edges"]}
    rel_ids = {r["id"] for ft in by_id.values() for r in ft.get("relationships", []) + ft.get("selfRelationships", [])}
    cases = []
    for c in data["cases"]:
        links = list(dict.fromkeys(f"{ids[by_edge[x]['s']]}--{ids[by_edge[x]['t']]}" for x in c["steps"]))
        missing = [x for x in links if x not in rel_ids]
        if missing:
            raise SystemExit(f"Use case '{c['id']}': relationships not in the hierarchy: {missing}")
        cases.append({"id": c["id"], "title": c["title"], "who": c.get("who", ""), "summary": c.get("summary", ""),
                      "answers": c.get("answers", []), "watch": c.get("watch", ""), "relationships": links})
    reference = {"version": EXPORT_VERSION, "built": data["built"],
                 "source": "OS relationship model (UK Geospatial Entity Relationships)",
                 "keys": [{"id": k["id"], "name": k["name"], "full": k["full"], "what": k["what"]}
                          for k in data["keys"] if k["id"] != "location"],
                 "useCases": cases}

    for d in OUT_DIRS:
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "ngdhierarchy.json"), "w", encoding="utf-8") as fh:
            json.dump(hier, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        with open(os.path.join(d, "ngdreference.json"), "w", encoding="utf-8") as fh:
            json.dump(reference, fh, indent=1, ensure_ascii=False)
            fh.write("\n")
    n_ft = sum(len(c["featureTypes"]) for t in hier.values() for c in t["collections"].values())
    print(f"ngdhierarchy.json v{EXPORT_VERSION}: {len(hier)} themes, {n_ft} feature types "
          f"({len(added)} added), {n_rel} relationships, {n_self} self-references kept aside, "
          f"from {len(edges)} OS relationships; ngdreference.json: {len(reference['keys'])} keys, "
          f"{len(cases)} use cases")
    if added:
        print("Added:", ", ".join(added))
    return hier


if __name__ == "__main__":
    export()
