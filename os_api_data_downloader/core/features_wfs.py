"""OS Features API (OGC WFS) - OS MasterMap Topography Layer, Highways and the
other WFS feature types, for an area of interest only.

* ``GET https://api.os.uk/features/v1/wfs`` with ``service=WFS&version=2.0.0``.
* ``GetFeature`` returns at most 100 features per request (``count``), paged
  with ``startIndex``; every request is one OS Data Hub transaction.
* Features are requested as GeoJSON in EPSG:27700.
* The area is sent as an OGC XML filter: ``BBOX`` for a rectangle (map view or
  a drawn window), ``Intersects`` with the polygon otherwise, on the feature
  types' ``SHAPE`` geometry property (as in OS's own examples). If the service
  rejects a polygon filter, the request falls back to the polygon's bounding
  box - exact clipping happens locally afterwards either way.
* Attribute filters (OGC Filter XML from ``filters.to_ogc``) are combined
  with the area filter inside ``ogc:And``; ``describe`` lists a feature
  type's attributes (DescribeFeatureType).
* ``resultType=hits`` gives the number of features before downloading, so the
  cost is known up front.
* ``/wfs/archive/{year}`` serves the annual snapshots.

The service is due to be replaced by OS NGD API - Features (end of life
expected in 2030); OS MasterMap Water Network and Detailed Path Network have
already been removed from it.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET

from .budget import Budget, BudgetExceeded
from .transport import HttpError, build_url, default_transport

WFS_BASE = "https://api.os.uk/features/v1/wfs"
PAGE = 100
GEOMETRY_PROPERTY = "SHAPE"

# Shown first in the picker - the OS MasterMap Topography Layer, then Highways
FEATURED = ("Topography_TopographicArea", "Topography_TopographicLine", "Topography_TopographicPoint",
            "Topography_CartographicText", "Topography_CartographicSymbol", "Topography_BoundaryLine",
            "Highways_RoadLink", "Highways_RoadNode", "Highways_Street")


class WfsError(Exception):
    pass


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def parse_capabilities(xml_text):
    """[{'id', 'title', 'description'}] from a WFS GetCapabilities document."""
    root = ET.fromstring(xml_text)
    out = []
    for ft in root.iter():
        if _local(ft.tag) != "FeatureType":
            continue
        rec = {}
        for child in ft:
            name = _local(child.tag)
            if name == "Name":
                rec["id"] = (child.text or "").split(":")[-1].strip()
            elif name == "Title":
                rec["title"] = (child.text or "").strip()
            elif name == "Abstract":
                rec["description"] = (child.text or "").strip()
        if rec.get("id"):
            out.append(rec)
    return out


def _ring_coords(ring):
    return " ".join(f"{x:.2f},{y:.2f}" for x, y in ring)


def _wrap(body, where=None):
    if where:
        body = f"<ogc:And>{body}{where}</ogc:And>"
    return f"<ogc:Filter>{body}</ogc:Filter>"


def bbox_filter(bbox, where=None):
    xmin, ymin, xmax, ymax = bbox
    return _wrap(f"<ogc:BBOX><ogc:PropertyName>{GEOMETRY_PROPERTY}</ogc:PropertyName>"
            f'<gml:Box srsName="urn:ogc:def:crs:EPSG::27700"><gml:coordinates>{xmin:.2f},{ymin:.2f} '
            f"{xmax:.2f},{ymax:.2f}</gml:coordinates></gml:Box></ogc:BBOX>", where)


def polygon_filter(rings, where=None):
    """``rings``: list of polygons, each [outer, *holes] as lists of (x, y). Several polygons
    become an ``ogc:Or`` of ``Intersects``."""
    parts = []
    for poly in rings:
        outer, holes = poly[0], poly[1:]
        gml = (f'<gml:Polygon srsName="urn:ogc:def:crs:EPSG::27700"><gml:outerBoundaryIs><gml:LinearRing>'
               f"<gml:coordinates>{_ring_coords(outer)}</gml:coordinates></gml:LinearRing></gml:outerBoundaryIs>")
        for h in holes:
            gml += (f"<gml:innerBoundaryIs><gml:LinearRing><gml:coordinates>{_ring_coords(h)}</gml:coordinates>"
                    f"</gml:LinearRing></gml:innerBoundaryIs>")
        gml += "</gml:Polygon>"
        parts.append(f"<ogc:Intersects><ogc:PropertyName>{GEOMETRY_PROPERTY}</ogc:PropertyName>{gml}"
                     f"</ogc:Intersects>")
    body = parts[0] if len(parts) == 1 else "<ogc:Or>" + "".join(parts) + "</ogc:Or>"
    return _wrap(body, where)


def rings_from_wkt(wkt):
    """Polygon / MultiPolygon WKT -> list of polygons of rings of (x, y)."""
    text = wkt.strip()
    body = text[text.index("("):]
    polys = re.findall(r"\(\((.*?)\)\)", body) if text.upper().startswith("MULTI") else [body.strip()[2:-2]]
    out = []
    for p in polys:
        rings = []
        for ring in re.split(r"\)\s*,\s*\(", p):
            pts = []
            for pair in ring.strip("() ").split(","):
                xs = pair.split()
                pts.append((float(xs[0]), float(xs[1])))
            rings.append(pts)
        out.append(rings)
    return out


def is_rectangle(rings, bbox):
    if len(rings) != 1 or len(rings[0]) != 1:
        return False
    xmin, ymin, xmax, ymax = bbox
    pts = rings[0][0]
    on_corners = all(abs(x - xmin) < 0.01 or abs(x - xmax) < 0.01 for x, _ in pts) and \
        all(abs(y - ymin) < 0.01 or abs(y - ymax) < 0.01 for _, y in pts)
    area = abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]))) / 2
    return on_corners and abs(area - (xmax - xmin) * (ymax - ymin)) < 0.01 * max(1.0, area)


class FeaturesWfsClient:
    def __init__(self, api_key, transport=None, budget=None, base=WFS_BASE, archive_year=None):
        if not api_key:
            raise WfsError("No OS Data Hub API key configured.")
        self.api_key = api_key
        self.transport = transport or default_transport()
        self.budget = budget or Budget()
        self.base = base + (f"/archive/{archive_year}" if archive_year else "")
        self.notes = []
        self._bbox_only = set()   # type names whose polygon filter was refused

    def _get(self, params, spend=True):
        q = {"service": "WFS", "version": "2.0.0", "key": self.api_key}
        q.update(params)
        url = build_url(self.base, q)
        if spend:
            self.budget.spend(1)
        status, content = self.transport.request("GET", url)
        text = content.decode("utf-8", "replace") if isinstance(content, bytes) else str(content)
        if status == 200:
            if "ExceptionReport" in text[:600]:
                raise HttpError(400, text, url)
            return text
        if status in (401, 403):
            raise WfsError("OS Features API rejected the key (HTTP %s) - add 'OS Features API' to the key's "
                           "OS Data Hub project." % status)
        raise HttpError(status, text, url)

    def collections(self):
        cols = parse_capabilities(self._get({"request": "GetCapabilities"}, spend=False))

        def rank(c):
            cid = c["id"]
            return (0 if cid in FEATURED else 1, FEATURED.index(cid) if cid in FEATURED else 0, cid)
        return sorted(cols, key=rank)

    def describe(self, type_name):
        """DescribeFeatureType XML schema for a feature type (no transaction)."""
        return self._get({"request": "DescribeFeatureType", "typeNames": type_name}, spend=False)

    # ---------------------------------------------------------------- area filters
    def _filter(self, type_name, bbox, filter_wkt, where=None):
        if filter_wkt and type_name not in self._bbox_only:
            rings = rings_from_wkt(filter_wkt)
            if not is_rectangle(rings, bbox):
                return polygon_filter(rings, where), True
        return bbox_filter(bbox, where), False

    def _request(self, type_name, bbox, filter_wkt, extra, where=None):
        flt, is_poly = self._filter(type_name, bbox, filter_wkt, where)
        params = dict(request="GetFeature", typeNames=type_name, srsName="EPSG:27700", filter=flt, **extra)
        try:
            return self._get(params)
        except HttpError as ex:
            if not is_poly or ex.status not in (400, 500):
                raise
            # polygon filter refused - use the bounding box; results are clipped locally anyway
            self._bbox_only.add(type_name)
            self.notes.append(f"{type_name}: the service refused the polygon filter, so its bounding box was "
                              "used (results are still clipped to your shape).")
            params["filter"] = bbox_filter(bbox, where)
            return self._get(params)

    # ---------------------------------------------------------------- count / download
    def estimate_count(self, type_name, bbox, filter_wkt=None, max_probes=40, where=None):
        """Returns (feature_count, transactions_used) using resultType=hits."""
        start = self.budget.used
        text = self._request(type_name, bbox, filter_wkt, {"resultType": "hits"}, where)
        n = None
        m = re.search(r'numberMatched="(\d+)"', text)
        if m:
            n = int(m.group(1))
        else:
            try:
                data = json.loads(text)
                n = data.get("numberMatched", data.get("totalFeatures"))
                n = int(n) if n is not None else None
            except ValueError:
                n = None
        if n is None:   # no count in the reply - find it with one-feature probes
            n = self._probe_count(type_name, bbox, filter_wkt, max_probes, where)
        return n, self.budget.used - start

    def _has_feature_at(self, type_name, bbox, filter_wkt, index, where=None):
        data = json.loads(self._request(type_name, bbox, filter_wkt,
                                        {"count": 1, "startIndex": index, "outputFormat": "GEOJSON"}, where))
        return bool(data.get("features"))

    def _probe_count(self, type_name, bbox, filter_wkt, max_probes, where=None):
        start = self.budget.used
        if not self._has_feature_at(type_name, bbox, filter_wkt, 0, where):
            return 0
        lo, hi = 0, PAGE
        while self._has_feature_at(type_name, bbox, filter_wkt, hi, where):
            lo, hi = hi, hi * 2
            if self.budget.used - start >= max_probes:
                return hi
        while hi - lo > PAGE and self.budget.used - start < max_probes:
            mid = (lo + hi) // 2
            if self._has_feature_at(type_name, bbox, filter_wkt, mid, where):
                lo = mid
            else:
                hi = mid
        return hi

    def iter_pages(self, type_name, bbox, filter_wkt=None, is_cancelled=None, where=None):
        index = 0
        while True:
            if is_cancelled and is_cancelled():
                return
            data = json.loads(self._request(type_name, bbox, filter_wkt,
                                            {"count": PAGE, "startIndex": index, "outputFormat": "GEOJSON"}, where))
            feats = data.get("features") or []
            if feats:
                yield feats
            if len(feats) < PAGE:
                return
            index += PAGE

    def download(self, type_name, bbox, out_path, filter_wkt=None, progress=None, is_cancelled=None,
                 expected=None, where=None):
        """Writes features to a GeoJSONSeq file. Returns dict(features, requests, truncated, cancelled)."""
        n, start, truncated = 0, self.budget.used, False
        with open(out_path, "w", encoding="utf-8") as fh:
            try:
                for feats in self.iter_pages(type_name, bbox, filter_wkt, is_cancelled, where):
                    for f in feats:
                        fh.write(json.dumps(f) + "\n")
                    n += len(feats)
                    if progress:
                        pct = 100.0 * n / expected if expected else 0
                        progress(min(99.0, pct), f"{type_name}: {n:,} features")
            except BudgetExceeded:
                truncated = True
        return {"features": n, "requests": self.budget.used - start, "truncated": truncated,
                "cancelled": bool(is_cancelled and is_cancelled())}
