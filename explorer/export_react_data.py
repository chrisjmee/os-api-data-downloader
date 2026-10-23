"""Exports the OS NGD Data Linkages Explorer's data as one simple JSON file for the React app (react-explorer/).

    python explorer/export_react_data.py            -> react-explorer/src/data/ngd-links.json

Same source as the Explorer page: OS's relationship model (os_api_data_downloader/data/os_relationships.csv)
and the written content in explorer/content.py. Kept simple on purpose:
* current schema versions only (relationships from superseded versions are left out);
* one link per pair of feature types, listing every attribute that joins them;
* no joins worked out from location;
* the use cases, each listing the links it follows.

Run it again whenever the relationship model changes; GitHub Actions does this before building the app.
"""
import datetime as dt
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)
import build_explorer as B  # noqa: E402
import content as C  # noqa: E402
from export_ngd_hierarchy import KEY_NAMES, storage, table_title  # noqa: E402

DATA_VERSION = "1.1.0"
OUT = os.path.join(ROOT, "react-explorer", "src", "data", "ngd-links.json")
OS = "Ordnance Survey"
THEME_ORDER = ["Building", "Land Use", "Land", "Address", "Structures", "Transport", "Water",
               "Administrative and Statistical Unit", "Geographical Names", "Global Geodetic Reference Frame",
               "Other organisations"]
THEME_TITLES = {"Building": "Buildings", "Administrative and Statistical Unit": "Administrative and statistical units",
                "Global Geodetic Reference Frame": "Grids", "Structures": "Structures"}
SUBTHEME_FIX = {"Sructure Features": "Structure Features", "tbc": "Other"}
STORAGE = {"attribute": "attribute", "crossReference": "table", "standaloneCrossReference": "related"}


def sentence(src, tgt, j):
    key = KEY_NAMES.get(j["key"], j["key"])
    if j["storage"] == "attribute":
        return f"{src} stores the {tgt} {key} in {j['field']}."
    table = table_title(j["field"].split(".")[0])
    where = "the separate Related Entity table (OS Select+Build)" if j["storage"] == "related" else \
        f"its {table} table"
    return f"{src} lists every {tgt} {key} in {where} ({j['field']})."


def export():
    data, _ = B.collect()
    feats, edges = data["features"], [e for e in data["edges"] if not e.get("spatial") and not e["old"]]
    used = {e["s"] for e in edges} | {e["t"] for e in edges}

    features = []
    for name in sorted(used, key=lambda n: feats[n]["title"]):
        f = feats[name]
        theme = f["theme"] if f["org"] == OS else "Other organisations"
        group = SUBTHEME_FIX.get(f["subtheme"], f["subtheme"]) if f["org"] == OS else f["org"]
        features.append({"id": name, "title": f["title"], "theme": THEME_TITLES.get(theme, theme), "group": group,
                         "org": f["org"], "delivery": f["route"], "api": f.get("api", ""),
                         "about": f.get("about", "")})

    pairs = {}
    for e in edges:
        pairs.setdefault((e["s"], e["t"]), []).append(e)
    links = []
    for (s, t), es in sorted(pairs.items()):
        joins = [{"field": e["sf"], "targetField": e["tf"], "key": e["key"],
                  "storage": STORAGE[storage(e["sf"])], "osType": e["type"],
                  "meaning": C.FAMILIES.get(e["family"], ("", ""))[0],
                  "purpose": e["purpose"]} for e in es]
        kinds = {j["storage"] for j in joins}
        links.append({
            "id": f"{s}->{t}", "source": s, "target": t,
            "keys": list(dict.fromkeys(j["key"] for j in joins)),
            "storage": "both" if "attribute" in kinds and len(kinds) > 1 else kinds.pop() if len(kinds) == 1 else "table",
            "meaning": list(dict.fromkeys(j["meaning"] for j in joins if j["meaning"])),
            "sentences": [sentence(feats[s]["title"], feats[t]["title"], j) for j in joins],
            "joins": joins,
        })

    by_edge = {e["id"]: e for e in data["edges"]}
    link_ids = {l["id"] for l in links}
    cases = []
    for c in data["cases"]:
        ids = list(dict.fromkeys(f"{by_edge[s]['s']}->{by_edge[s]['t']}" for s in c["steps"]))
        missing = [i for i in ids if i not in link_ids]
        if missing:
            raise SystemExit(f"Use case '{c['id']}': links not in the current data: {missing}")
        cases.append({"id": c["id"], "title": c["title"], "who": c.get("who", ""), "summary": c.get("summary", ""),
                      "answers": c.get("answers", []), "watch": c.get("watch", ""), "links": ids})

    keys = [{"id": k["id"], "name": k["name"], "full": k["full"], "what": k["what"]}
            for k in data["keys"] if k["id"] != "location"]
    themes = sorted({f["theme"] for f in features},
                    key=lambda th: next((i for i, o in enumerate(THEME_ORDER) if THEME_TITLES.get(o, o) == th), 99))
    out = {"version": DATA_VERSION, "built": dt.date.today().isoformat(),
           "source": "OS relationship model (UK Geospatial Entity Relationships), via github.com/chrisjmee/"
                     "os-api-data-downloader",
           "themes": themes, "keys": keys, "features": features, "links": links, "cases": cases}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    print(f"ngd-links.json v{DATA_VERSION}: {len(features)} feature types, {len(links)} links, "
          f"{len(keys)} keys, {len(cases)} use cases, themes: {', '.join(themes)}")


if __name__ == "__main__":
    export()
