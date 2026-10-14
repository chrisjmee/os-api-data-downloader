"""OS NGD API - Features: download only the features inside an area of interest.

* ``GET /features/ngd/ofa/v1/collections/{id}/items`` - max 100 features per
  request (``limit``), paged with ``offset``; each request is one OS Data Hub
  transaction. Results are requested in EPSG:27700.
* The area is sent as ``bbox`` plus a CQL ``INTERSECTS(geometry, <polygon>)``
  filter, so only features touching the shape come back; exact clipping is
  done locally afterwards.
* Attribute filters (see ``filters.py``) are CQL text and are ANDed with the
  area filter: ``INTERSECTS(geometry, …) AND (<attribute filter>)``.
  ``queryables`` lists a feature type's filterable attributes.
* The API has no feature count, so ``estimate_count`` finds one with a few
  one-feature probe requests (exponential then binary search on ``offset``) -
  about 2*log2(N/100) transactions - before committing to a full download.
"""

from __future__ import annotations

import json
import re

from .budget import Budget, BudgetExceeded  # noqa: F401  (re-exported for callers)
from .transport import HttpError, build_url, default_transport

NGD_BASE = "https://api.os.uk/features/ngd/ofa/v1"
CRS_27700 = "http://www.opengis.net/def/crs/EPSG/0/27700"
PAGE = 100

# Shown first in the picker - commonly wanted for an area of interest
FEATURED = ("lnd-fts-land", "bld-fts-building", "lus-fts-site", "trn-fts-roadlink", "wtr-fts-waterlink",
            "str-fts-structure", "lnd-fts-landpoint", "gnm-fts-namedpoint")


MAX_FILTER_CHARS = 6000     # URL-encoded filter length that keeps the whole request well under 8 kB


def _encoded_len(text):
    import urllib.parse
    return len(urllib.parse.quote_plus(text or ""))


class NgdError(Exception):
    pass


class NgdFeaturesClient:
    def __init__(self, api_key, transport=None, budget=None, base=NGD_BASE):
        if not api_key:
            raise NgdError("No OS Data Hub API key configured.")
        self.api_key = api_key
        self.transport = transport or default_transport()
        self.budget = budget or Budget()
        self.base = base

    def _get(self, path, params=None, spend=True):
        params = dict(params or {})
        params["key"] = self.api_key
        url = build_url(f"{self.base}{path}", params)
        if spend:
            self.budget.spend(1)
        status, content = self.transport.request("GET", url)
        text = content.decode("utf-8", "replace") if isinstance(content, bytes) else str(content)
        if status == 200:
            return json.loads(text)
        if status in (401, 403):
            raise NgdError("OS NGD API rejected the key (HTTP %s) - add 'OS NGD API - Features' to the key's "
                           "OS Data Hub project." % status)
        raise HttpError(status, text, url)

    def collections(self):
        data = self._get("/collections", spend=False)
        cols = data.get("collections", data if isinstance(data, list) else [])

        def rank(c):
            cid = c.get("id", "")
            base = cid.rsplit("-", 1)[0]
            return (0 if base in FEATURED else 1, FEATURED.index(base) if base in FEATURED else 0,
                    cid.split("-")[0], cid)
        return sorted(cols, key=rank)

    def queryables(self, collection):
        """The feature type's filterable attributes (JSON Schema). Not a data request - no transaction."""
        return self._get(f"/collections/{collection}/queryables", spend=False)

    @staticmethod
    def area_params(bbox, filter_wkt=None, where=None):
        p = {"bbox": ",".join(f"{v:.1f}" for v in bbox), "bbox-crs": CRS_27700, "crs": CRS_27700}
        parts = []
        if filter_wkt and where and _encoded_len(filter_wkt) + _encoded_len(where) > MAX_FILTER_CHARS:
            # OS's server turns away requests over about 8 kB (HTTP 400). A long list of ticked values plus a
            # detailed area outline can go over that, so send the area as its bounding box only - features
            # are clipped to the exact shape locally anyway.
            filter_wkt = None
        if filter_wkt:
            # CQL examples use upper-case WKT type names; QGIS writes "Polygon"/"MultiPolygon"
            wkt = re.sub(r"^\s*([A-Za-z]+)", lambda m: m.group(1).upper(), filter_wkt)
            parts.append(f"INTERSECTS(geometry, {wkt})")
            p["filter-crs"] = CRS_27700
        if where and where.strip():
            parts.append(f"({where.strip()})" if parts else where.strip())
        if parts:
            p["filter"] = " AND ".join(parts)
            p["filter-lang"] = "cql-text"
        return p

    def probe_one(self, collection, bbox=None, wkt=None):
        """Returns one feature from the collection (optionally within an area), or None if there isn't one.
        Doesn't spend the user's transaction budget - used to inspect a feature type (e.g. its geometry
        type) rather than to download data."""
        params = self.area_params(bbox, wkt) if bbox is not None else {}
        data = self._get(f"/collections/{collection}/items", dict(params, limit=1), spend=False)
        feats = data.get("features") or []
        return feats[0] if feats else None

    def _has_feature_at(self, collection, params, offset):
        data = self._get(f"/collections/{collection}/items", dict(params, limit=1, offset=offset))
        return bool(data.get("features"))

    def estimate_count(self, collection, bbox, filter_wkt=None, max_probes=40, where=None):
        """Returns (approx_feature_count, probes_used). Exact to within one page (100)."""
        params = self.area_params(bbox, filter_wkt, where)
        start = self.budget.used
        if not self._has_feature_at(collection, params, 0):
            return 0, self.budget.used - start
        lo, hi = 0, PAGE                       # lo: known to exist; hi: probe
        while self._has_feature_at(collection, params, hi):
            lo, hi = hi, hi * 2
            if self.budget.used - start >= max_probes:
                return hi, self.budget.used - start   # "at least"
        while hi - lo > PAGE and self.budget.used - start < max_probes:
            mid = (lo + hi) // 2
            if self._has_feature_at(collection, params, mid):
                lo = mid
            else:
                hi = mid
        return hi, self.budget.used - start

    def iter_pages(self, collection, bbox, filter_wkt=None, is_cancelled=None, where=None):
        """Yields lists of GeoJSON features (EPSG:27700), one list per transaction."""
        params = self.area_params(bbox, filter_wkt, where)
        offset = 0
        while True:
            if is_cancelled and is_cancelled():
                return
            data = self._get(f"/collections/{collection}/items", dict(params, limit=PAGE, offset=offset))
            feats = data.get("features") or []
            if feats:
                yield feats
            has_next = any(link.get("rel") == "next" for link in data.get("links") or [])
            if len(feats) < PAGE and not has_next:
                return
            if not feats:
                return
            offset += PAGE

    def download(self, collection, bbox, out_path, filter_wkt=None, progress=None, is_cancelled=None,
                 expected=None, where=None):
        """Writes features to a GeoJSONSeq file. Returns dict(features, requests, truncated, cancelled)."""
        n, start, truncated = 0, self.budget.used, False
        with open(out_path, "w", encoding="utf-8") as fh:
            try:
                for feats in self.iter_pages(collection, bbox, filter_wkt, is_cancelled, where):
                    for f in feats:
                        fh.write(json.dumps(f) + "\n")
                    n += len(feats)
                    if progress:
                        pct = 100.0 * n / expected if expected else 0
                        progress(min(99.0, pct), f"{collection}: {n:,} features")
            except BudgetExceeded:
                truncated = True
        return {"features": n, "requests": self.budget.used - start, "truncated": truncated,
                "cancelled": bool(is_cancelled and is_cancelled())}
