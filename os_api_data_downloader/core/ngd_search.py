"""Find a feature type: the OS Labs prototyping tool that searches OS NGD feature-type *descriptions* for a
word, e.g. "bridge" -> every feature type whose description values include something like "Footbridge" or
"Cable Bridge". Handy because OS NGD has around 70 feature types with technical names (``str-fts-structure``)
that don't obviously say what they contain.

    https://labs.os.uk/prototyping/osngd/os-ngd-api-features/search/description/contains/{term}

This is a public OS Labs prototype, not an OS Data Hub API product: no API key, and it doesn't spend the
user's transaction budget. It returns one entry per *version* of a feature type (``str-fts-structure-1``,
``-2``, ``-3``...); ``latest_only`` keeps just the highest version of each so old, superseded versions don't
clutter the results.

OS NGD doesn't publish the geometry type (point/line/polygon) of a feature type anywhere machine-readable,
so ``classify_geometry`` looks at one real feature (see ``NgdFeaturesClient.probe_one``); ``guess_geometry``
is the fallback when that isn't possible (no API key yet, or nothing in the area), based on the OS NGD naming
convention - a type's "Line"/"Link" suffix means line geometry, "Point" means point geometry, anything else
is a polygon (the large majority of OS NGD feature types are areas).
"""

from __future__ import annotations

import json
import re
import urllib.parse

from .transport import default_transport

LABS_BASE = "https://labs.os.uk/prototyping/osngd/os-ngd-api-features/search/description/contains"

POINT, LINE, POLYGON = "point", "line", "polygon"
GEOM_ORDER = (POLYGON, LINE, POINT)   # the order the user wants results grouped in

_VERSION_RE = re.compile(r"^(.*)-(\d+)$")
_LINE_HINTS = ("line", "link")
_POINT_HINTS = ("point",)


class NgdSearchError(Exception):
    pass


class NgdSearchClient:
    """No API key needed - this is a public OS Labs prototype, not an OS Data Hub API product."""

    def __init__(self, transport=None):
        self.transport = transport or default_transport()

    def search(self, term):
        """Returns the raw ``{collection_id: {"enum": [...], "code-lists-overview": url}}`` mapping, or {}
        for a blank search term."""
        term = (term or "").strip()
        if not term:
            return {}
        url = f"{LABS_BASE}/{urllib.parse.quote(term)}"
        status, content = self.transport.request("GET", url)
        text = content.decode("utf-8", "replace") if isinstance(content, bytes) else str(content)
        if status != 200:
            raise NgdSearchError(f"The OS Labs search tool returned HTTP {status} - it may be down; try again "
                                 "shortly, or browse the full OS NGD list on the OS NGD tab instead.")
        try:
            data = json.loads(text) if text else {}
        except ValueError as ex:
            raise NgdSearchError(f"The OS Labs search tool returned something unexpected ({ex}).") from ex
        return data if isinstance(data, dict) else {}


def split_version(collection_id):
    """'str-fts-compoundstructure-3' -> ('str-fts-compoundstructure', 3). No trailing number -> version 0."""
    m = _VERSION_RE.match(collection_id or "")
    return (m.group(1), int(m.group(2))) if m else (collection_id, 0)


def latest_only(results):
    """Keeps only the highest-versioned collection id for each base feature type, so superseded versions
    don't appear twice. Returns {base_id: (full_id, version, enum_values, code_lists_overview_url)}."""
    best = {}
    for cid, info in (results or {}).items():
        base, ver = split_version(cid)
        if base not in best or ver > best[base][1]:
            best[base] = (cid, ver, list((info or {}).get("enum") or []), (info or {}).get("code-lists-overview") or "")
    return best


def reconcile_latest(latest, collections):
    """Cross-checks OS Labs's search results against the real OS NGD ``/collections`` list, so a feature
    type is always downloaded from its true most recent version even if the Labs prototype's own version
    number lags behind the live API. ``collections``: an iterable of real collection ids, or dicts with an
    "id" key, e.g. from ``NgdFeaturesClient.collections()``. Same shape as ``latest_only``'s result."""
    real_ids = [c["id"] if isinstance(c, dict) else c for c in collections or []]
    real_best = {}
    for rid in real_ids:
        base, ver = split_version(rid)
        if base not in real_best or ver > real_best[base][1]:
            real_best[base] = (rid, ver)
    out = {}
    for base, (cid, ver, enum, url) in (latest or {}).items():
        rid, rver = real_best.get(base, (cid, ver))
        out[base] = (rid, rver, enum, url) if rver >= ver else (cid, ver, enum, url)
    return out


def guess_geometry(base_id):
    """A geometry type guessed from the OS NGD naming convention. Only used as a fallback when a feature
    type can't be checked directly (see ``classify_geometry``)."""
    name = (base_id or "").lower()
    if any(name.endswith(h) or f"-{h}" in name for h in _POINT_HINTS):
        return POINT
    if any(name.endswith(h) or f"-{h}" in name for h in _LINE_HINTS):
        return LINE
    return POLYGON


def find_attribute(attrs, values):
    """A feature type's description search only tells you it *has* features described as e.g. "Weir" -
    downloading the whole feature type would also bring back every other kind it holds (bridges, culverts,
    sluices...). This finds which of the feature type's filterable attributes (as parsed by
    ``core.filters.parse_queryables``) actually carries those values - usually a "...description" field,
    but the attribute name varies (``formofway`` for road/path links, for instance). Returns that
    attribute's dict (name/type/enum/...), or None if nothing fits - in which case the whole feature type
    would have to be downloaded (the caller should say so), and there is nothing to narrow with a drop-down
    either."""
    wanted = {v for v in (values or []) if v}
    if not wanted:
        return None
    best = None
    for a in attrs or []:
        enum = set(a.get("enum") or [])
        if not enum:
            continue
        if wanted <= enum:                     # every matched value is a real allowed value of this attribute
            return a
        if best is None and wanted & enum:     # partial match - keep as a fallback if nothing better turns up
            best = a
    return best


def attribute_for(client, collection_id, values):
    """Fetches the collection's queryables and returns ``find_attribute``'s match for the searched values,
    or None if the attributes can't be read or none fit."""
    from . import filters as F

    try:
        attrs = F.parse_queryables(client.queryables(collection_id))
    except Exception:
        return None
    return find_attribute(attrs, values)


def cql_for_values(attr, values):
    """CQL restricting ``attr`` (a ``parse_queryables`` entry, as found by ``find_attribute``) to just
    ``values`` - e.g. ``description IN ('Weir')``. None if there's nothing to filter on or no values."""
    from . import filters as F

    vals = sorted({v for v in (values or []) if v})
    if not attr or not vals:
        return None
    rule = {"attr": attr["name"], "op": "IN", "value": vals}      # a list: values can contain commas
    return F.to_cql({"join": "AND", "items": [rule]}, {attr["name"]: attr.get("type") or "string"})


def classify_geometry(client, collection_id, bbox=None, wkt=None):
    """The exact geometry type (point/line/polygon), read from one real feature of the collection
    (optionally within an area) via ``client.probe_one``. Returns None if that can't be determined (no
    feature in the area, or the request failed) - callers should fall back to ``guess_geometry`` then."""
    try:
        feat = client.probe_one(collection_id, bbox, wkt)
    except Exception:
        return None
    if not feat:
        return None
    t = (feat.get("geometry") or {}).get("type", "") or ""
    if t.startswith("Point") or t.startswith("MultiPoint"):
        return POINT
    if t.startswith("LineString") or t.startswith("MultiLineString"):
        return LINE
    if t.startswith("Polygon") or t.startswith("MultiPolygon"):
        return POLYGON
    return None
