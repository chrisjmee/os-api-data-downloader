"""A local index of every OS NGD feature type's description-style attribute and its allowed values, kept
as a CSV, so the "Find an NGD Feature Type" tab's search is a local string match with no network calls at
all - instead of a live OS Labs lookup (plus, previously, a live attribute check for every match).

Two copies can exist, in priority order:

* a **user-built** one in the QGIS profile folder (``user_path``) - built from your own OS Data Hub API key
  via the tab's "Rebuild index" button, so it reflects OS NGD exactly as it is right now;
* a **bundled** one shipped inside the plugin (``BUNDLED_PATH``) - so a fresh install has instant search
  from the first run, without anyone needing an API key or a one-off build first.

Checking every feature type's queryables (~100 API calls) is the only genuinely slow part, and it only
happens when a user explicitly rebuilds the index - never on an ordinary search, and never just from
installing or opening the plugin.

OS NGD's convention is one primary enumerated attribute per feature type (usually literally called
"description", sometimes e.g. "formofway") that lists every value that type of feature can be described
as - ``pick_description_attribute`` picks it out from a feature type's queryables without needing to
already know a search term (unlike ``core.ngd_search.find_attribute``, which matches specific values).
"""

from __future__ import annotations

import csv
import datetime as _dt
import os

from .ngd_search import guess_geometry, split_version

HERE = os.path.dirname(os.path.abspath(__file__))
BUNDLED_PATH = os.path.join(os.path.dirname(HERE), "data", "ngd_feature_types.csv")
FIELDS = ("base_id", "cid", "version", "attr", "geom", "values")
VALUE_SEP = "|"   # separates a feature type's values within one CSV cell (none of OS NGD's own values use it)


def pick_description_attribute(attrs):
    """The attribute that carries a feature type's 'kind': the enum-bearing string attribute with the most
    allowed values (ties broken in favour of a name containing "description"). None if nothing fits."""
    best = None
    for a in attrs or []:
        if a.get("type") != "string" or not a.get("enum"):
            continue
        if best is None or len(a["enum"]) > len(best["enum"]) or (
                len(a["enum"]) == len(best["enum"])
                and "description" in a["name"] and "description" not in best["name"]):
            best = a
    return best


def build(client, progress=None, is_cancelled=None):
    """Fetches every OS NGD feature type's queryables once. Returns {base_id: {"cid", "version", "attr"
    (name or None), "values" ([...]), "geom" ("polygon"/"line"/"point")}}. ``progress(pct, msg)`` and
    ``is_cancelled()`` behave like a ``FunctionTask``'s (see gui/tasks.py)."""
    from . import filters as F

    cols = client.collections()
    ids = [c["id"] if isinstance(c, dict) else c for c in (cols or [])]
    latest = {}
    for cid in ids:
        base, ver = split_version(cid)
        if base not in latest or ver > latest[base][1]:
            latest[base] = (cid, ver)
    out = {}
    items = sorted(latest.items())
    for i, (base, (cid, ver)) in enumerate(items):
        if is_cancelled and is_cancelled():
            break
        if progress:
            progress(100 * i / len(items), f"Indexing {cid}")
        try:
            attrs = F.parse_queryables(client.queryables(cid))
        except Exception:
            attrs = []
        attr = pick_description_attribute(attrs)
        out[base] = {"cid": cid, "version": ver, "attr": attr["name"] if attr else None,
                     "values": attr["enum"] if attr else [], "geom": guess_geometry(base)}
    return out


def user_path():
    from qgis.core import QgsApplication
    d = os.path.join(QgsApplication.qgisSettingsDirPath(), "os_api_data_downloader")
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, "ngd_feature_types.csv")


def write_csv(index, path):
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(FIELDS)
        for base, info in sorted(index.items()):
            w.writerow([base, info["cid"], info["version"], info.get("attr") or "", info["geom"],
                       VALUE_SEP.join(info.get("values") or [])])


def read_csv(path):
    """The index from a CSV file (see ``write_csv``'s columns), or None if it doesn't exist or can't be
    read/parsed - a bad or missing file should never stop the tab working, just fall back to the next one
    (or to "no index yet")."""
    try:
        with open(path, encoding="utf-8", newline="") as fh:
            rows = list(csv.DictReader(fh))
    except (OSError, csv.Error):
        return None
    out = {}
    try:
        for r in rows:
            out[r["base_id"]] = {"cid": r["cid"], "version": int(r["version"]), "attr": r["attr"] or None,
                                 "geom": r["geom"], "values": r["values"].split(VALUE_SEP) if r["values"] else []}
    except (KeyError, ValueError):
        return None
    return out or None


def save(index):
    """Saves a freshly built index as the user's own copy - takes priority over the bundled one from then on."""
    write_csv(index, user_path())


def load():
    """The index to search: your own rebuilt copy if you have one, otherwise the one bundled with the
    plugin, otherwise None (nothing to search - the tab should offer to build one)."""
    return read_csv(user_path()) or read_csv(BUNDLED_PATH)


def source():
    """Where the index currently in use came from, for the tab's status line."""
    if read_csv(user_path()) is not None:
        return "your own", _dt.datetime.fromtimestamp(os.path.getmtime(user_path()))
    if read_csv(BUNDLED_PATH) is not None:
        return "bundled with the plugin", None
    return None, None


def search(index, term):
    """{base_id: [matching values]} for every feature type in the index described as ``term`` (a
    case-insensitive substring match - the same test OS Labs's own prototype search tool uses)."""
    term = (term or "").strip().lower()
    if not term or not index:
        return {}
    out = {}
    for base, info in index.items():
        hits = [v for v in (info.get("values") or []) if term in v.lower()]
        if hits:
            out[base] = hits
    return out
