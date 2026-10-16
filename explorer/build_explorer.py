"""Builds the OS NGD Data Linkages Explorer: one self-contained web page (no downloads, no API key).

    python explorer/build_explorer.py            -> docs/ngd-links/index.html

The relationships come from OS's relationship model (explorer/data/os_relationships.csv); the written
content - linking keys, API vs Select+Build, use cases - from explorer/content.py; which feature types the
OS NGD API - Features serves, from the plugin's own list. Run from the repository root; needs only Python 3."""
import csv
import datetime as dt
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import content as C  # noqa: E402

REL_CSV = os.path.join(HERE, "data", "os_relationships.csv")
API_CSV = os.path.join(ROOT, "os_api_data_downloader", "data", "ngd_feature_types.csv")
TEMPLATE = os.path.join(HERE, "template.html")
OUT = os.path.join(ROOT, "docs", "ngd-links", "index.html")       # the full web page (GitHub Pages, email)
FRAGMENT = os.path.join(HERE, "dist", "explorer.html")            # the same page without the document shell


def norm(s):
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def title_of(name):
    if name in C.FEATURE_TITLES:
        return C.FEATURE_TITLES[name]
    t = re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", " ", name)
    return re.sub(r"\bOr\b", "or", re.sub(r"\bAnd\b", "and", re.sub(r"\bOf\b", "of", t)))


def version_major(v):
    m = re.match(r"\s*v?(\d+)", str(v))
    return int(m.group(1)) if m else None


def version_num(v):
    m = re.match(r"\s*v?(\d+(?:\.\d+)?)\s*$", str(v))
    return float(m.group(1)) if m else None


def api_collections():
    out = {}
    with open(API_CSV, encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            out[norm(r["base_id"].rsplit("-", 1)[-1])] = r["cid"]
    return out


def key_id(field):
    last = field.split(".")[-1].lower()
    return C.KEY_OF.get(last, "other")


def build():
    with open(REL_CSV, encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    api = api_collections()
    feats, edges, seen = {}, [], {}
    fixes = []

    def feature(r, side):
        name = r[f"{side}Feature"].strip()
        name = C.FEATURE_ALIASES.get(name, name)
        org = r[f"{side}Organisation"].strip()
        f = feats.setdefault(name, {"id": name, "title": title_of(name), "org": org,
                                    "theme": r[f"{side}Theme"].strip(), "subtheme": r[f"{side}SubTheme"].strip(),
                                    "pk": "", "versions": set()})
        pk = C.KEY_ALIASES.get(r[f"{side}PrimaryKey"].strip(), r[f"{side}PrimaryKey"].strip())
        if pk and pk != "tbc" and not f["pk"]:
            f["pk"] = pk
        v = r[f"{side}Version"].strip()
        if v:
            f["versions"].add(v)
        return name

    for r in rows:
        s, t = feature(r, "Source"), feature(r, "Target")
        sf = r["sourcejoinkey"].strip()
        tf = C.KEY_ALIASES.get(r["targetjoinkey"].strip(), r["targetjoinkey"].strip())
        if r["targetjoinkey"].strip() != tf or r["TargetFeature"].strip() != t or r["SourceFeature"].strip() != s:
            fixes.append(f"{r['SourceFeature']}.{sf} -> {r['TargetFeature']}.{r['targetjoinkey']}")
        rtype = r["RelationshipType"].strip()
        owner = C.OWNER_ALIASES.get(r["RelationshipOwner"].strip(), r["RelationshipOwner"].strip())
        jt = r["JoinType"].strip()
        jt = jt[:1].upper() + jt[1:]
        k = (s, sf, t, tf, rtype)
        purpose = r["PurposeOfRelationship"].strip()
        if k in seen:                       # the same relationship recorded twice (e.g. by two owners)
            e = seen[k]
            if owner and owner not in e["owners"]:
                e["owners"].append(owner)
            continue
        e = {"id": f"r{len(edges)}", "s": s, "t": t, "sf": sf, "tf": tf, "key": key_id(tf), "type": rtype,
             "family": C.TYPE_FAMILY.get(rtype, "within"), "join": jt, "owners": [owner] if owner else [],
             "freq": r["RelationshipUpdateFrequency"].strip(), "sv": r["SourceVersion"].strip(),
             "tv": r["TargetVersion"].strip(), "purpose": "" if purpose.lower() == "tbc" else purpose}
        seen[k] = e
        edges.append(e)

    # joins worked out from location (not supplied by OS) - shown only when asked for
    for name, info in C.SPATIAL_FEATURES.items():
        feats.setdefault(name, dict(info, id=name, versions=set()))
    for s, t, method, test, note in C.SPATIAL:
        for f in (s, t):
            if f not in feats:
                raise SystemExit(f"Spatial join {s} -> {t}: no feature {f}")
        edges.append({"id": f"r{len(edges)}", "s": s, "t": t, "sf": "geometry", "tf": "geometry", "key": "location",
                      "type": "Worked out from location", "family": "spatial", "join": method,
                      "owners": [], "freq": "When you run it", "sv": "", "tv": "", "purpose": note,
                      "test": test, "spatial": True})

    # older schema versions: a relationship from an earlier major version of its source feature
    for f in feats.values():
        nums = [version_num(v) for v in f["versions"] if version_num(v) is not None]
        f["latest"] = max(f["versions"], key=lambda v: version_num(v) or -1) if nums else ""
        f["versions"] = sorted(f["versions"], key=lambda v: (version_num(v) is None, version_num(v) or 0, v))
    for e in edges:
        latest = version_major(feats[e["s"]]["latest"])
        mine = version_major(e["sv"]) if e["sv"] else None
        e["old"] = bool(latest is not None and mine is not None and mine < latest)
    missing = [n for n in feats if n not in C.FEATURE_INFO]
    if missing:
        print("No description yet for:", ", ".join(missing))
    for f in feats.values():
        f["about"] = C.FEATURE_INFO.get(f["id"], "")
        cid = api.get(norm(f["id"])) if f["org"] == "Ordnance Survey" else None
        f["api"] = cid or ""
        f["route"] = "api" if cid else ("sb" if f["org"] == "Ordnance Survey" else "external")

    # use cases: every step must be a relationship in the file
    by_step = {}
    for e in edges:
        by_step.setdefault((e["s"], e["sf"], e["t"]), []).append(e)
    cases = []
    for uc in C.USE_CASES:
        ids = []
        for s, sf, t in uc["steps"]:
            s, t = C.FEATURE_ALIASES.get(s, s), C.FEATURE_ALIASES.get(t, t)
            hit = by_step.get((s, sf, t))
            if not hit:
                raise SystemExit(f"Use case '{uc['id']}': no relationship {s}.{sf} -> {t} in the file")
            ids.append(hit[0]["id"])
        cases.append({k: v for k, v in uc.items() if k != "steps"} | {"steps": ids})

    keys = []
    for k in C.KEYS:
        n = sum(1 for e in edges if e["key"] == k["id"])
        if n:
            keys.append(dict(k, count=n))

    data = {"built": dt.date.today().isoformat(), "features": feats, "edges": edges, "keys": keys,
            "families": C.FAMILIES, "delivery": C.DELIVERY, "cases": cases,
            "source": {"file": "UK Geospatial Entity Relationships (OS)", "rows": len(rows)}}
    with open(TEMPLATE, encoding="utf-8") as fh:
        page = fh.read()
    blob = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    page = page.replace("/*__DATA__*/null", blob)
    full = ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
            + page.replace("<header", "</head>\n<body>\n<header", 1) + "\n</body>\n</html>\n")
    for path, text in ((OUT, full), (FRAGMENT, page)):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
    print(f"Wrote {OUT}: {len(feats)} feature types, {len(edges)} relationships (from {len(rows)} rows), "
          f"{len(keys)} linking keys, {len(cases)} use cases, {len(page) // 1024} KB")
    if fixes:
        print("Tidied names in:", *fixes, sep="\n  ")


if __name__ == "__main__":
    build()
