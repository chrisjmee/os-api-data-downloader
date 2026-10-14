"""Find an OS NGD Named Area to use as the area of interest.

OS NGD API - Features, Geographic Names theme: the *Named Area* collection
(``gnm-fts-namedarea-*``) has the real boundary polygon of each named area
(settlements, landforms, woods...). Searched with a CQL
``name1_text LIKE 'Chorley%'`` filter; each search is one OS Data Hub transaction.
"""

from __future__ import annotations

import json

from .budget import Budget
from .transport import HttpError, build_url, default_transport

NGD_BASE = "https://api.os.uk/features/ngd/ofa/v1"
CRS_27700 = "http://www.opengis.net/def/crs/EPSG/0/27700"


class NamesError(Exception):
    pass


def _get(transport, url, budget, what, spend=True):
    if spend:
        budget.spend(1)
    status, content = transport.request("GET", url)
    text = content.decode("utf-8", "replace") if isinstance(content, bytes) else str(content)
    if status == 200:
        return json.loads(text) if text else {}
    if status in (401, 403):
        raise NamesError(f"{what} rejected the key (HTTP {status}) - add it to the key's OS Data Hub project.")
    raise HttpError(status, text, url)


class NgdNamesClient:
    """OS NGD Geographic Names - named areas with their boundary polygons."""

    def __init__(self, api_key, transport=None, budget=None, base=NGD_BASE):
        if not api_key:
            raise NamesError("No OS Data Hub API key configured.")
        self.api_key, self.transport, self.budget, self.base = api_key, transport or default_transport(), \
            budget or Budget(), base
        self._collection = None

    def collection(self):
        if self._collection is None:
            url = build_url(f"{self.base}/collections", {"key": self.api_key})
            data = _get(self.transport, url, self.budget, "OS NGD API", spend=False)  # the list is free
            ids = [c.get("id", "") for c in data.get("collections") or []]
            named = sorted((i for i in ids if i.startswith("gnm-fts-namedarea")),
                           key=lambda i: int(i.rsplit("-", 1)[-1]) if i.rsplit("-", 1)[-1].isdigit() else 0)
            if not named:
                raise NamesError("OS NGD API has no Named Area collection for this key.")
            self._collection = named[-1]   # the latest version
        return self._collection

    def find(self, text, maxresults=20):
        t = text.strip().replace("'", "''")
        variants = {t, t.title(), t.upper()}
        cql = " OR ".join(f"name1_text LIKE '{v}%'" for v in sorted(variants))
        params = {"filter": cql, "filter-lang": "cql-text", "crs": CRS_27700, "limit": min(100, maxresults),
                  "key": self.api_key}
        url = build_url(f"{self.base}/collections/{self.collection()}/items", params)
        data = _get(self.transport, url, self.budget, "OS NGD API")
        out = []
        for f in data.get("features") or []:
            p = f.get("properties") or {}
            geom = f.get("geometry")
            area = p.get("geometry_area")
            try:
                area = float(area)
            except (TypeError, ValueError):
                area = polygon_area(geom)
            out.append({"name": p.get("name1_text") or "", "kind": p.get("description") or p.get("descriptiongroup")
                        or "Named area", "where": p.get("name2_text") or "", "bbox": None, "point": None,
                        "id": p.get("osid"), "geometry": geom, "area_m2": area})
        out.sort(key=lambda r: -(r["area_m2"] or 0))      # largest areas first
        return out


def _ring_area(ring):
    return sum(x1 * y2 - x2 * y1 for (x1, y1, *_), (x2, y2, *_) in zip(ring, ring[1:] + ring[:1])) / 2


def polygon_area(geom):
    """Area in m² of a GeoJSON Polygon / MultiPolygon in British National Grid (holes subtracted)."""
    if not geom:
        return 0.0
    polys = [geom["coordinates"]] if geom.get("type") == "Polygon" else geom.get("coordinates") or []
    total = 0.0
    for rings in polys:
        if rings:
            total += abs(_ring_area(rings[0])) - sum(abs(_ring_area(h)) for h in rings[1:])
    return total


def size_text(m2):
    """'12.3 km²' / '45 ha' / '800 m²'."""
    if not m2:
        return ""
    if m2 >= 1_000_000:
        return f"{m2 / 1e6:,.1f} km²" if m2 < 100e6 else f"{m2 / 1e6:,.0f} km²"
    if m2 >= 10_000:
        return f"{m2 / 1e4:,.1f} ha"
    return f"{m2:,.0f} m²"
