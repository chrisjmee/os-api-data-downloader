"""Builds the NGD Data Linkages explorer: one self-contained web page (no downloads, no API key) from the
plugin's own link registry, so the page and the plugin always agree.

    python explorer/build_explorer.py            -> docs/ngd-links/index.html

Run from the repository root. Needs only Python 3 (the registry is plain Python)."""
import csv
import datetime as dt
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from os_api_data_downloader.core import ngd_links as NL  # noqa: E402

PLUGIN = os.path.join(ROOT, "os_api_data_downloader")
OUT = os.path.join(ROOT, "docs", "ngd-links", "index.html")       # the full web page (GitHub Pages, email)
FRAGMENT = os.path.join(ROOT, "explorer", "dist", "explorer.html")  # the same page without the document shell
TEMPLATE = os.path.join(ROOT, "explorer", "template.html")

HOW = {"attr": "value", "list": "list", "count": "count", "breakdown": "breakdown", "agg": "calculated",
       "=": "worked out"}
CLASS_TEXT = {
    "A": ("Stored ID", "OS records the other feature's identifier in the data."),
    "B": ("Network connection", "Part of how a network is joined together (links, nodes, junctions)."),
    "C": ("Sits within", "OS records what the feature lies inside, such as its smallest and largest Site."),
    "D": ("Worked out from location", "Not supplied by OS: calculated from where the features are, so "
                                      "treat it as a best guess."),
}


def version():
    with open(os.path.join(PLUGIN, "metadata.txt"), encoding="utf-8") as fh:
        m = re.search(r"^version=(.+)$", fh.read(), re.M)
    return m.group(1).strip() if m else ""


def schema():
    out = {}
    with open(os.path.join(PLUGIN, "data", "ngd_feature_types.csv"), encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            out[r["base_id"]] = {"collection": r["cid"], "geom": r["geom"], "attr": r["attr"],
                                 "values": [v for v in r["values"].split("|") if v]}
    return out


def column(subject, col):
    name, alias, path, how, _attrs = col
    if how == "=":
        return {"name": name, "label": alias, "how": "worked out", "from": "other columns", "steps": []}
    steps, end = NL.path_types(subject, path or [])
    kind = "percentage" if how.startswith("pct:") else HOW.get(how, how)
    return {"name": name, "label": alias, "how": kind, "steps": [lk["id"] for lk, _ in steps],
            "from": NL.title(end)}


def recipe(r, group):
    a = r.get("answer")
    return {
        "group": group, "name": r["name"], "question": r.get("question", ""), "path": r.get("path", ""),
        "answers": r.get("answers", ""), "note": r.get("note", ""), "types": r["types"], "links": r["links"],
        "filters": {k: list(v) for k, v in (r.get("filters") or {}).items()},
        "answer": None if not a else {"subject": a["subject"], "title": a["title"],
                                      "columns": [column(a["subject"], c) for c in a["columns"]]},
    }


def build():
    sch = schema()
    themes = [{"name": t, "types": [b for b, _, _ in items]} for t, items in NL.THEMES]
    types = {}
    for b, info in NL.TYPES.items():
        s = sch.get(b, {})
        types[b] = {"title": info["title"], "theme": info["theme"], "note": info["note"],
                    "available": info["available"], "legacy": info["legacy"], "geom": s.get("geom", ""),
                    "collection": s.get("collection", ""), "attr": s.get("attr", ""), "values": s.get("values", [])}
    types[NL.PLACES_ADDRESS]["geom"] = "point"
    fallback = {lid: sp for lid, (sp, _) in NL.FALLBACK.items()}
    links = []
    for lk in NL.LINKS:
        links.append({
            "id": lk["id"], "holder": lk["holder"], "target": lk["target"], "kind": lk["kind"], "cls": lk["cls"],
            "card": lk["card"], "fwd": NL.say(lk), "back": NL.say(lk, "in"), "sentence": NL.card_sentence(lk),
            "fields": lk["fields"] if lk["kind"] == "id" else [], "key": lk["key"] if lk["kind"] == "id" else "",
            "op": lk.get("op") or "", "tol": lk.get("tol") or 0, "note": lk["note"] or "",
            "fallback": fallback.get(lk["id"], ""),
        })
    recipes = ([recipe(r, "showcase") for r in NL.SHOWCASE_RECIPES] + [recipe(r, "question") for r in NL.RECIPES]
               + [recipe(r, "engineer") for r in NL.ENGINEER_RECIPES])
    data = {"version": version(), "built": dt.date.today().isoformat(), "themes": themes, "types": types,
            "links": links, "recipes": recipes, "classes": CLASS_TEXT}
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
    print(f"Wrote {OUT} - {len(types)} feature types, {len(links)} links, {len(recipes)} quick picks, "
          f"{len(page) // 1024} KB")


if __name__ == "__main__":
    build()
