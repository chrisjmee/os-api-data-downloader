"""The work behind the 'NGD Data Linkages' tab: download the ticked OS NGD feature types (and OS Places
addresses) for the area, find the ticked links between them, fetch linked features that lie outside the
area by their identifier, and write one GeoPackage holding

* one layer per feature type (``ngd_in_area`` = 1 inside the area, 0 for a linked feature fetched from
  outside it),
* one ``link_<link id>`` table per link: ``from_key`` -> ``to_key``, the attribute it came from
  (``via_field``) and whether the linked feature was found,
* ``ngd_link_register``: every ticked link in plain English, with its class, cardinality, the attribute
  actually used and counts (the provenance the NGD Relationship Specification asks for),
* optionally ``<layer>_joined`` copies with the linked features' key attributes written in (1:N links as a
  count and a list).

Relations between the layers are then added to the QGIS project on the main thread (``add_relations``).

Speed: the API is the slow part, so requests run several at a time (``PARALLEL``, kept under the OS Data
Hub rate limit by ``RateLimited``) - every page of every feature type at once when the cost estimate has
already said how many pages there are, and likewise the fetches by ID and the address lookups. Writing is
done by GDAL and SQLite (C++), not feature by feature in Python: layers with ``gdal.VectorTranslate``, the
joined copies with one SQL query each, link tables in a single transaction.

``run`` is safe to call from a ``QgsTask`` worker thread: layers are opened privately, never added to the
project. Worker threads only make requests; all progress reporting happens on the task's own thread.
"""

from __future__ import annotations

import copy
import datetime as _dt
import json
import os
import re
import threading
import time

from qgis.core import (
    QgsFeature, QgsField, QgsFields, QgsGeometry, QgsPointXY, QgsProject, QgsRelation, QgsSpatialIndex,
    QgsVectorLayer, QgsWkbTypes,
)
from qgis.PyQt.QtCore import QRunnable, QThreadPool, QVariant

from ..core import ngd_links as NL
from ..core import places as P
from ..core.budget import BudgetExceeded
from ..core.ngd_features import CRS_27700, PAGE
from ..core.transport import HttpError
from . import clipping as C

PARALLEL = 10           # requests in flight at once (each OS NGD page takes ~0.5-1 s to come back)
MAX_PER_SECOND = 9.5    # OS Data Hub allows 600 a minute per project - stay under it on average
BURST = 40              # ...but let a short burst through at full speed
ADDRESS_MARGIN = 100.0  # addresses are read in bulk this far beyond the area too, so buildings at the edge find
                        # theirs without one-by-one lookups
MAX_UPRN_LOOKUPS = 60  # one-by-one address lookups cost a transaction each - never more than this
NEAR = (500.0, 5000.0)  # linked features are looked for within 500 m of the area, then 5 km (never all of GB)
COLLECTIONS_TTL = 3600  # the list of feature types is asked for once an hour, not on every click
ID_BATCH = 25           # identifiers per 'fetch by id' request (small enough for the server to answer quickly)
MAX_ROUNDS = 2          # follow links from fetched features once more, then stop
SPEC = "OS NGD Relationship Knowledge Specification v2"

try:
    _STR, _INT, _DBL = QVariant.String, QVariant.Int, QVariant.Double
except AttributeError:  # pragma: no cover - Qt6 builds without QVariant types
    from qgis.PyQt.QtCore import QMetaType
    _STR, _INT, _DBL = QMetaType.Type.QString, QMetaType.Type.Int, QMetaType.Type.Double


def layer_name(base):
    return C._safe_name(NL.title(base).split(" (")[0]) if base != NL.PLACES_ADDRESS else "Address"


def own_key(base):
    return "uprn" if base == NL.PLACES_ADDRESS else "osid"


_COLLECTIONS = {}


def latest_collections(client):
    """{base id: newest collection id} from the live API (not a data request, so no transaction). Kept for
    an hour, so estimating and then downloading don't both wait for it."""
    hit = _COLLECTIONS.get(client.base)
    if hit and time.monotonic() - hit[0] < COLLECTIONS_TTL:
        return dict(hit[1])
    out = {}
    for c in client.collections():
        cid = c.get("id", "")
        base, _, ver = cid.rpartition("-")
        if not base or not ver.isdigit():
            continue
        if base not in out or int(ver) > int(out[base].rpartition("-")[2]):
            out[base] = cid
    _COLLECTIONS[client.base] = (time.monotonic(), dict(out))
    return out


# ---------------------------------------------------------------------------------------------- parallel requests
class _Bucket:
    """A token bucket shared by every request of a download: short bursts go straight through, a long run
    averages ``per_second`` (the OS Data Hub allows 600 a minute per project)."""

    def __init__(self, per_second=MAX_PER_SECOND, burst=BURST):
        self.rate, self.burst = float(per_second), float(burst)
        self._tokens, self._last = float(burst), time.monotonic()
        self._lock = threading.Lock()

    def take(self):
        while True:
            with self._lock:
                now = time.monotonic()
                self._tokens = min(self.burst, self._tokens + (now - self._last) * self.rate)
                self._last = now
                if self._tokens >= 1:
                    self._tokens -= 1
                    return
                wait = (1 - self._tokens) / self.rate
            time.sleep(wait)


class RateLimited:
    """Wraps a transport so requests from several threads stay under the rate limit. ``retries`` (optional)
    caps how often a busy server is retried - lookups that are nice-to-have fail fast instead of waiting
    minutes on retries."""

    def __init__(self, inner, bucket=None, retries=None):
        self.inner = inner
        self.bucket = bucket or _Bucket()
        self.retries = retries

    def request(self, *a, **kw):
        self.bucket.take()
        if self.retries is not None:
            try:
                return self.inner.request(*a, retries=self.retries, **kw)
            except TypeError:       # a transport without the option
                pass
        return self.inner.request(*a, **kw)

    def fail_fast(self, retries=1):
        return RateLimited(self.inner, self.bucket, retries)

    def __getattr__(self, name):
        return getattr(self.inner, name)


def _limit(client, bucket=None):
    """Rate-limits a client. Pass the same ``bucket`` for clients that share the OS Data Hub project's
    limit (OS NGD and OS Places in one download)."""
    if client is not None and not isinstance(client.transport, RateLimited):
        client.transport = RateLimited(client.transport, bucket)
    return client


class _Job(QRunnable):
    def __init__(self, fn, results, i, done):
        super().__init__()
        self.fn, self.results, self.i, self.done = fn, results, i, done
        self.setAutoDelete(False)     # Python keeps the reference (see ``parallel``)

    def run(self):
        try:
            self.results[self.i] = self.fn()
        except Exception as ex:   # noqa: BLE001 - handed back to the caller
            self.results[self.i] = ex
        finally:
            self.done.append(self.i)


def parallel(jobs, task=None, label="", lo=0.0, hi=100.0):
    """Runs ``jobs`` (no-argument callables) ``PARALLEL`` at a time on Qt worker threads (QGIS's network
    requests need real QThreads - their time-outs use Qt timers). Returns their results in order (an
    exception is returned in place of a result). Progress is reported from the calling thread only."""
    results = [None] * len(jobs)
    if not jobs:
        return results
    pool = QThreadPool()
    pool.setMaxThreadCount(min(PARALLEL, len(jobs)))
    done = []
    runnables = [_Job(j, results, i, done) for i, j in enumerate(jobs)]
    for r in runnables:
        pool.start(r)
    reported = -1
    while not pool.waitForDone(100):
        if task is not None and len(done) != reported:
            reported = len(done)
            task.report(lo + (hi - lo) * reported / len(jobs), f"{label} ({reported:,}/{len(jobs):,})")
    if task is not None:
        task.report(hi, f"{label} ({len(jobs):,}/{len(jobs):,})")
    del runnables
    return results


def estimate_counts(ngd, cids, types, bbox, wkt, wheres, task=None, first_pages=None, quick=False):
    """{base: feature count in the area} for several feature types at once. The first request for each
    asks for a whole page (100), which is kept in ``first_pages`` for the download to reuse. In a small
    area that page *is* everything, so the count is exact. Feature types with more than a page are then
    counted with a few probe requests - unless ``quick``, when they're just marked None ('more than 100')
    and counted as they download: much faster with many feature types ticked, and cheaper."""
    _limit(ngd)
    types = [t for t in types if t in cids]
    cancelled = task.isCanceled if task is not None else (lambda: False)

    def job(t):
        def run_():
            if cancelled():
                return None
            params = ngd.area_params(bbox, wkt, wheres.get(t))
            page = _page_job(ngd, cids[t], params, 0, cancelled)()
            if len(page) < PAGE:
                return len(page), page
            if quick:
                return None, page
            return ngd.estimate_count(cids[t], bbox, wkt, where=wheres.get(t))[0], page
        return run_
    res = parallel([job(t) for t in types], task, "Counting features")
    out = {}
    for t, r in zip(types, res):
        if isinstance(r, Exception):
            raise r
        if r is None:
            continue
        out[t] = r[0]
        if r[1] is not None and first_pages is not None:
            first_pages[t] = r[1]
    return out


def _page_job(ngd, cid, params, offset, cancelled):
    def job():
        if cancelled():
            return []
        data = ngd._get(f"/collections/{cid}/items", dict(params, limit=PAGE, offset=offset))
        return data.get("features") or []
    return job


def download_area(ngd, cids, types, bbox, wkt, wheres, expected, tmp, task, lo, hi, first_pages=None):
    """Every ticked feature type in the area, written to one GeoJSONSeq file each. With a count from the
    estimate, every page is requested at once; without one, each feature type is read page by page (but
    the feature types side by side). Returns ({base: path}, {base: features}, truncated)."""
    cancelled = task.isCanceled
    jobs, owners = [], []
    first_pages = first_pages or {}
    for t in types:
        params = ngd.area_params(bbox, wkt, wheres.get(t))
        n = expected.get(t)
        if n == 0:
            continue
        start_at = 0
        if t in first_pages:            # the estimate already read the first page (in a small area: all of it)
            page = first_pages[t]
            jobs.append(lambda page=page: page)
            owners.append((t, 0))
            if len(page) < PAGE:
                continue
            start_at = PAGE
        if n is None:
            def chain(t=t, params=params, start_at=start_at):
                """Size unknown: read ahead in growing waves (2, 4, then 8 pages at once) until a short
                page - fast for big feature types, and at most a few empty requests wasted."""
                out, offset, wave = [], start_at, 2
                while not cancelled():
                    got = parallel([_page_job(ngd, cids[t], params, offset + i * PAGE, cancelled)
                                    for i in range(wave)])
                    for r in got:
                        if isinstance(r, Exception):
                            raise r
                    for r in got:
                        out.extend(r)
                    if any(len(r) < PAGE for r in got):
                        break
                    offset += wave * PAGE
                    wave = min(wave * 2, 8)
                return out
            jobs.append(chain)
            owners.append((t, None))
        else:
            for k in range(start_at // PAGE, -(-int(n) // PAGE)):
                jobs.append(_page_job(ngd, cids[t], params, k * PAGE, cancelled))
                owners.append((t, k * PAGE))
    res = parallel(jobs, task, "Downloading the area", lo, hi)
    feats, truncated, last_full = {}, False, {}
    for (t, offset), r in zip(owners, res):
        if isinstance(r, BudgetExceeded):
            truncated = True
            continue
        if isinstance(r, Exception):
            raise r
        feats.setdefault(t, []).append((offset or 0, r))
        if (offset is not None and expected.get(t) is not None and len(r) == PAGE
                and offset + PAGE >= int(expected[t])):
            last_full[t] = offset + PAGE     # the estimate was low: carry on from here
    for t, offset in last_full.items():
        if truncated or cancelled():
            break
        params = ngd.area_params(bbox, wkt, wheres.get(t))
        try:
            while not cancelled():
                page = _page_job(ngd, cids[t], params, offset, cancelled)()
                feats[t].append((offset, page))
                if len(page) < PAGE:
                    break
                offset += PAGE
        except BudgetExceeded:
            truncated = True
    paths, counts = {}, {}
    for t, pages in feats.items():
        path = os.path.join(tmp, f"{C._safe_name(t)}.geojsons")
        n = 0
        with open(path, "w", encoding="utf-8") as fh:
            for _, page in sorted(pages, key=lambda p: p[0]):
                for f in page:
                    fh.write(json.dumps(f) + "\n")
                n += len(page)
        paths[t], counts[t] = path, n
    return paths, counts, truncated


# ---------------------------------------------------------------------------------------------- store
class Store:
    """Properties of every feature read so far, per feature type, keyed by the type's own key, plus which
    were inside the area. Indexes on other keys (USRN, postcode) are built on demand and cached."""

    def __init__(self):
        self.props = {}       # base -> {own key: properties}
        self.in_area = {}     # base -> set(own keys)
        self._idx = {}

    def add(self, base, props, inside):
        k = NL.key_of(props, own_key(base))
        if not k:
            return None
        bucket = self.props.setdefault(base, {})
        new = k not in bucket
        bucket[k] = props
        if inside:
            self.in_area.setdefault(base, set()).add(k)
        if new:
            self._idx.pop(base, None)
        return k if new else None

    def index(self, base, key):
        """{normalised value of ``key``: own key} for a feature type (cached until features are added)."""
        cache = self._idx.setdefault(base, {})
        if key not in cache:
            if key == own_key(base):
                cache[key] = {k: k for k in self.props.get(base, {})}
            else:
                cache[key] = {}
                for k, p in self.props.get(base, {}).items():
                    v = NL.norm(p.get(key), key)
                    if v and v not in cache[key]:
                        cache[key][v] = k
        return cache[key]


def read_seq(path, base, store, inside):
    new = []
    if not path or not os.path.exists(path):
        return new
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            f = json.loads(line)
            props = dict(f.get("properties") or {})
            if "osid" not in props and f.get("id"):
                props["osid"] = f["id"]
            k = store.add(base, props, inside)
            if k:
                new.append(k)
    return new


# ---------------------------------------------------------------------------------------------- links
def resolve_links(link_ids, store, detected):
    """Finds each ticked identifier link in the features read so far. ``detected`` keeps, per link, the
    attribute(s) found to carry it - worked out once from a sample, then reused. Returns
    {link id: [(holder key, target key, via field)]}."""
    out = {}
    for lid in link_ids:
        lk = NL.LINK_BY_ID[lid]
        if lk["kind"] != "id":
            continue
        holders = store.props.get(lk["holder"], {})
        targets = store.props.get(lk["target"], {})
        d = detected.get(lid)
        if d is None or d["how"] == "not found":     # (again, if more features have arrived since)
            fields, how = NL.detect_field(lk, list(holders.values())[:400])
            rev, rhow = ([], None)
            if not fields and lk["rev"]:
                rev, rhow = NL.detect_field(lk, list(targets.values())[:400], reverse=True)
            d = {"fields": fields, "rev": rev, "how": how or (rhow and "reverse") or "not found"}
            detected[lid] = d
        out[lid] = NL.pairs_for(lk, holders, targets, d["fields"], d["rev"])
    return out


def missing_targets(link_ids, pairs, store):
    """{feature type: {key name: set(normalised values not yet read)}} - what to fetch by identifier."""
    want = {}
    for lid in link_ids:
        lk = NL.LINK_BY_ID[lid]
        if lk["kind"] != "id":
            continue
        idx = store.index(lk["target"], lk["key"])
        held = store.props.get(lk["holder"], {})
        for hk, tk, f in pairs.get(lid, ()):
            if tk not in idx:
                want.setdefault(lk["target"], {}).setdefault(lk["key"], set()).add(tk)
            # a reversed link (stored on the target) points back at holders that may be outside the area
            if f in lk["rev"] and hk not in held:
                want.setdefault(lk["holder"], {}).setdefault(own_key(lk["holder"]), set()).add(hk)
    return want


def _by_key_job(ngd, cid, key, chunk, cancelled, failed, near, where=None):
    """Features of ``cid`` whose ``key`` is in ``chunk``, looked for only within the box ``near`` - with
    the box the API answers from its spatial index in about a second; asking all of GB for an ID can take
    minutes. If the server fails on a batch, the batch is split in half and tried again, so one awkward ID
    doesn't lose the rest; IDs that still fail are counted in ``failed``."""
    numeric = key in ("usrn", "uprn")

    def dead():
        f = failed.get(cid, {})
        # four failures without a single success (or a dozen in all): OS can't answer for this feature
        # type - stop asking, as each failure can take up to a minute
        return (f.get("errors", 0) >= 4 and not f.get("ok")) or f.get("errors", 0) >= 12

    def fetch(ids, depth=0):
        if cancelled() or dead():
            return []
        flt = NL.cql_in(key, ids, quote=not numeric)
        if where:          # a filtered feature type (e.g. only School sites) stays filtered
            flt = f"({flt}) AND ({where})"
        params = {"filter": flt, "filter-lang": "cql-text",
                  "crs": CRS_27700, "limit": PAGE, "bbox": ",".join(f"{v:.1f}" for v in near),
                  "bbox-crs": CRS_27700}
        out, offset = [], 0
        while True:
            try:
                data = ngd._get(f"/collections/{cid}/items", dict(params, offset=offset))
            except (HttpError, OSError, ConnectionError) as ex:
                status = getattr(ex, "status", None)
                f = failed.setdefault(cid, {"status": status or "no answer", "ids": 0, "errors": 0})
                f["errors"] += 1
                # split (up to three times) in case the batch was too big or one awkward ID upset it
                if len(ids) > 1 and depth < 3 and not dead() and (status is None or status >= 500):
                    half = len(ids) // 2
                    return out + fetch(ids[:half], depth + 1) + fetch(ids[half:], depth + 1)
                f["ids"] += len(ids)
                return out
            failed.setdefault(cid, {"status": None, "ids": 0, "errors": 0})["ok"] = True
            feats = data.get("features") or []
            out.extend(feats)
            if len(feats) < PAGE:
                return out
            offset += PAGE
    return lambda: fetch(list(chunk))


def fetch_outside(ngd, places, cids, want, store, outside_files, tmp, task, lo, hi, notes, near=None,
                  filters=None, pool=None, lookups=None):
    """Fetches everything in ``want`` by identifier, several requests at once. Adds the features to the
    store (marked outside the area) and to per-type GeoJSONSeq files. Returns ({base: new features},
    [address rows], truncated)."""
    cancelled = task.isCanceled
    jobs, owners, failed = [], [], {}
    for t, keys in want.items():
        for key, vals in keys.items():
            if t == NL.PLACES_ADDRESS:
                if places is None:
                    continue
                vals = sorted(vals)
                if lookups is not None:           # one transaction each: keep to the cap
                    room = max(0, MAX_UPRN_LOOKUPS - lookups["done"])
                    lookups["skipped"] += max(0, len(vals) - room)
                    vals = vals[:room]
                    lookups["done"] += len(vals)
                for u in vals:
                    def look(u=u):
                        if cancelled():
                            return []
                        try:
                            data = places._call("uprn", {"uprn": u, "dataset": places.dataset})
                        except (HttpError, OSError, ConnectionError) as ex:
                            f = failed.setdefault("OS Places", {"status": getattr(ex, "status", None) or
                                                                "no answer", "ids": 0})
                            f["ids"] += 1
                            return []
                        return _rows_from(places, data.get("results") or [])
                    jobs.append(look)
                    owners.append(t)
                continue
            if t not in cids:
                continue
            numeric = key in ("usrn", "uprn")
            vals = [v for v in vals if not numeric or str(v).isdigit()]
            for chunk in NL.batches(vals, ID_BATCH):
                jobs.append(_by_key_job(ngd, cids[t], key, chunk, cancelled, failed, near, (filters or {}).get(t)))
                owners.append(t)
    res = parallel(jobs, task, "Fetching linked features outside the area", lo, hi)
    fetched, rows, truncated = {}, [], False
    by_type = {}
    for t, r in zip(owners, res):
        if isinstance(r, BudgetExceeded):
            truncated = True
            continue
        if isinstance(r, Exception):     # an optional lookup that failed - note it, keep everything else
            f = failed.setdefault(NL.noun(t), {"status": getattr(r, "status", None) or "no answer", "ids": 0})
            f["ids"] += 1
            continue
        by_type.setdefault(t, []).extend(r)
    for t, items in by_type.items():
        if t == NL.PLACES_ADDRESS:
            for row in merge_address_rows(items):
                if store.add(t, row, False):
                    rows.append(row)
                    fetched[t] = fetched.get(t, 0) + 1
            continue
        path = outside_files.setdefault(t, os.path.join(tmp, f"{C._safe_name(t)}_outside.geojsons"))
        with open(path, "a", encoding="utf-8") as fh:
            for f in items:
                props = dict(f.get("properties") or {})
                if "osid" not in props and f.get("id"):
                    props["osid"] = f["id"]
                if store.add(t, props, False):
                    fh.write(json.dumps(f) + "\n")
                    fetched[t] = fetched.get(t, 0) + 1
    for what, f in failed.items():
        if not f.get("errors") and not f.get("ids"):
            continue
        base = what.rsplit("-", 1)[0]
        name = NL.plural(base) if base in NL.TYPES else ("addresses" if what == "OS Places" else what)
        why = ("OS's rate limit was hit (429)" if f["status"] == 429 else
               f"OS's server had a problem ({f['status']})" if isinstance(f["status"], int) else "OS didn't answer")
        retry = (" Running the download again usually fills them in." if f["status"] == 429 else
                 " This is on OS's side; it was given up on quickly rather than retried.")
        notes.append(f"{why} when fetching linked {name} - those links are left unresolved.{retry}")
    return fetched, rows, truncated


def _rows_from(places, results):
    rows = []
    for r in results:
        if places.include_dpa and r.get("DPA"):
            rows.append(P.to_row(r["DPA"], "DPA"))
        if places.include_lpi and r.get("LPI"):
            rows.append(P.to_row(r["LPI"], "LPI"))
    return rows


def merge_address_rows(rows):
    """One row per UPRN: the Royal Mail (DPA) record preferred, with blanks (e.g. USRN, which only the
    LPI record has) filled from the other record."""
    out = {}
    for r in rows:
        u = r.get("uprn")
        if not u:
            continue
        if u not in out:
            out[u] = dict(r, has_dpa=r["dataset"] == "DPA")
            continue
        out[u]["has_dpa"] = out[u].get("has_dpa") or r["dataset"] == "DPA"
        cur = out[u]
        if r["dataset"] == "DPA" and cur["dataset"] != "DPA":
            r = dict(r, has_dpa=True)
            for k, v in cur.items():
                if r.get(k) in (None, ""):
                    r[k] = v
            out[u] = r
        else:
            for k, v in r.items():
                if cur.get(k) in (None, ""):
                    cur[k] = v
    return list(out.values())


def tiles(xmin, ymin, xmax, ymax, size=P.CELL):
    """The box cut into the fewest equal tiles of at most ``size`` x ``size`` (OS Places' 1 km² limit) -
    not aligned to the National Grid, so a margin round the area doesn't spill into extra squares."""
    import math
    nx = max(1, math.ceil((xmax - xmin) / size - 1e-9))
    ny = max(1, math.ceil((ymax - ymin) / size - 1e-9))
    w, h = (xmax - xmin) / nx, (ymax - ymin) / ny
    return [(xmin + i * w, ymin + j * h, xmin + (i + 1) * w, ymin + (j + 1) * h) for j in range(ny) for i in range(nx)]


def fetch_addresses(places, bbox, aoi, task, lo, hi, cancelled=None):
    """OS Places addresses for the area, read in bulk (1 km squares, 100 addresses a transaction, several
    at once) over the area plus ``ADDRESS_MARGIN``. Returns (area rows, pool, truncated): area rows are the
    postal addresses inside the area; the pool holds everything else read - addresses just beyond the edge
    and non-postal UPRNs (parent shells, non-addressable objects, from the LPI records) - so links to them
    resolve without a transaction each."""
    engine = QgsGeometry.createGeometryEngine(aoi.constGet())
    engine.prepareGeometry()
    cancelled = cancelled or task.isCanceled
    m = ADDRESS_MARGIN
    cells = tiles(bbox[0] - m, bbox[1] - m, bbox[2] + m, bbox[3] + m)
    res = parallel([lambda c=c: [] if cancelled() else places.bbox(*c) for c in cells], task,
                   "Reading addresses", lo, hi)
    rows, truncated = [], False
    for r in res:
        if isinstance(r, BudgetExceeded):
            truncated = True
            continue
        if isinstance(r, Exception):
            raise r
        rows.extend(r)
    area, pool = [], {}
    for row in merge_address_rows(rows):
        x, y = row["easting"], row["northing"]
        if x is None or y is None:
            continue
        g = QgsGeometry.fromPointXY(QgsPointXY(x, y))     # keep a reference while GEOS reads it
        if row.get("has_dpa", row["dataset"] == "DPA") and engine.intersects(g.constGet()):
            area.append(row)
        else:
            pool[row["uprn"]] = row
    return area, pool, truncated


# ---------------------------------------------------------------------------------------------- writing (GDAL)
def _sql_name(name):
    return '"' + name.replace('"', '""') + '"'


def write_ngd_layer(area_seq, outside_seq, aoi, out_path, name, mode):
    """One GeoPackage layer from the area download and the features fetched from outside it, written by
    GDAL. Area features are clipped as chosen; outside ones are kept whole. Adds ``ngd_in_area``.
    Returns the number of features written."""
    gdal, ogr, osr = C._gdal()
    srcs = [(p, inside) for p, inside in ((area_seq, 1), (outside_seq, 0))
            if p and os.path.exists(p) and os.path.getsize(p)]
    if not srcs:
        return 0
    aoi_ogr = C._aoi_for(aoi, None, ogr, osr)
    created = False
    for path, inside in srcs:
        opts = dict(format="GPKG", layerName=name, geometryType="PROMOTE_TO_MULTI", dstSRS="EPSG:27700",
                    reproject=False, transactionSize=100000)
        if inside and mode == "clip":
            opts["clipSrc"] = aoi_ogr.ExportToWkt()
        if created:
            opts.update(accessMode="append", addFields=True)
        elif os.path.exists(out_path):
            opts["accessMode"] = "update"
        gdal.VectorTranslate(out_path, path, **opts)
        ds = gdal.OpenEx(out_path, gdal.OF_VECTOR | gdal.OF_UPDATE)
        tbl = _sql_name(name)
        if not created:
            ds.ExecuteSQL(f"ALTER TABLE {tbl} ADD COLUMN ngd_in_area INTEGER")
            created = True
        ds.ExecuteSQL(f"UPDATE {tbl} SET ngd_in_area = {inside} WHERE ngd_in_area IS NULL")
        if inside and mode != "clip" and not C._is_rect(aoi_ogr):
            # the area filter sent to the API is simplified outwards: anything that doesn't touch the
            # real shape is kept, but marked as outside the area
            lyr = ds.GetLayerByName(name)
            fid_col = lyr.GetFIDColumn() or "fid"
            lyr.SetSpatialFilter(aoi_ogr)
            keep = {f.GetFID() for f in lyr}
            lyr.SetSpatialFilter(None)
            lyr.SetAttributeFilter("ngd_in_area = 1")
            drop = [f.GetFID() for f in lyr if f.GetFID() not in keep]
            lyr.SetAttributeFilter(None)
            for i in range(0, len(drop), 500):
                ds.ExecuteSQL(f"UPDATE {tbl} SET ngd_in_area = 0 WHERE {_sql_name(fid_col)} IN "
                              f"({','.join(str(x) for x in drop[i:i + 500])})")
        ds = None
    ds = gdal.OpenEx(out_path, gdal.OF_VECTOR | gdal.OF_UPDATE)
    lyr = ds.GetLayerByName(name)
    n = lyr.GetFeatureCount() if lyr is not None else 0
    if lyr is not None:
        _add_measure(ds, lyr, ogr)
    ds = None
    return n


def _add_measure(ds, lyr, ogr):
    """``ngd_area_m2`` (polygons) or ``ngd_length_m`` (lines) worked out from the geometry as written - a
    fallback for the answers when OS's own geometry_area_m2 / geometry_length_m isn't in the data."""
    gt = ogr.GT_Flatten(lyr.GetGeomType())
    if gt in (ogr.wkbPolygon, ogr.wkbMultiPolygon):
        col, fn = "ngd_area_m2", "GetArea"
    elif gt in (ogr.wkbLineString, ogr.wkbMultiLineString):
        col, fn = "ngd_length_m", "Length"
    else:
        return
    if lyr.GetLayerDefn().GetFieldIndex(col) < 0:
        lyr.CreateField(ogr.FieldDefn(col, ogr.OFTReal))
    lyr.StartTransaction()
    for f in lyr:
        g = f.GetGeometryRef()
        if g is not None:
            f.SetField(col, round(getattr(g, fn)(), 1))
            lyr.SetFeature(f)
    lyr.CommitTransaction()


ADDRESS_FIELDS = ("uprn", "address", "postcode", "organisation", "classification", "classification_desc",
                  "class_group", "dataset", "status", "logical_status", "parent_uprn", "usrn", "udprn", "toid",
                  "local_custodian", "easting", "northing")


def write_address_layer(rows, store, out_path):
    fields = QgsFields()
    for k in ADDRESS_FIELDS:
        fields.append(QgsField(k, _DBL if k in ("easting", "northing") else _STR))
    fields.append(QgsField("ngd_in_area", _INT))
    writer = C._writer(out_path, "Address", fields, QgsWkbTypes.Point, C.BNG)
    inside = store.in_area.get(NL.PLACES_ADDRESS, set())
    n = 0
    try:
        for r in rows:
            if r.get("easting") is None or r.get("northing") is None:
                continue
            f = QgsFeature(fields)
            for k in ADDRESS_FIELDS:
                f[k] = r.get(k)
            f["ngd_in_area"] = 1 if r["uprn"] in inside else 0
            f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(r["easting"], r["northing"])))
            writer.addFeature(f)
            n += 1
    finally:
        del writer
    return n


def write_table(out_path, name, columns, rows, index=(), ds=None):
    """A non-spatial GeoPackage table, in one transaction. ``columns``: [(name, 'str'|'int')]. Pass an open
    ``ds`` to write many tables without reopening the file each time."""
    gdal, ogr, _ = C._gdal()
    own = ds is None
    if own:
        ds = gdal.OpenEx(out_path, gdal.OF_VECTOR | gdal.OF_UPDATE) if os.path.exists(out_path) else \
            ogr.GetDriverByName("GPKG").CreateDataSource(out_path)
    lyr = ds.CreateLayer(name, geom_type=ogr.wkbNone, options=["OVERWRITE=YES"])
    for c, t in columns:
        lyr.CreateField(ogr.FieldDefn(c, ogr.OFTInteger if t == "int" else ogr.OFTString))
    defn = lyr.GetLayerDefn()
    lyr.StartTransaction()
    for r in rows:
        f = ogr.Feature(defn)
        for i, v in enumerate(r):
            if v is not None:
                f.SetField(i, v)
        lyr.CreateFeature(f)
    lyr.CommitTransaction()
    for col in index:
        ds.ExecuteSQL(f"CREATE INDEX IF NOT EXISTS {_sql_name(f'idx_{name}_{col}')} ON {_sql_name(name)} "
                      f"({_sql_name(col)})")
    if own:
        ds = None
    return len(rows)


def written_keys(out_path, name, key, ds=None):
    """{normalised key: (key as stored, in the area?)} for one written layer - so link tables carry the
    exact stored values (QGIS relations then match) and say truthfully what was written."""
    gdal, _, _ = C._gdal()
    own = ds is None
    if own:
        ds = gdal.OpenEx(out_path, gdal.OF_VECTOR | gdal.OF_UPDATE)
    lyr = ds.GetLayerByName(name)
    out = {}
    if lyr is not None and lyr.GetLayerDefn().GetFieldIndex(key) >= 0:
        ds.ExecuteSQL(f"CREATE INDEX IF NOT EXISTS {_sql_name(f'idx_{name}_{key}')} ON {_sql_name(name)} "
                      f"({_sql_name(key)})")
        res = ds.ExecuteSQL(f"SELECT {_sql_name(key)}, ngd_in_area FROM {_sql_name(name)}")
        for f in res:
            raw = f.GetField(0)
            k = NL.norm(raw, key)
            if k and (k not in out or f.GetField(1)):
                out[k] = (raw, bool(f.GetField(1)))
        ds.ReleaseResultSet(res)
    if own:
        ds = None
    return out


def gpkg_layer(out_path, name):
    lyr = QgsVectorLayer(f"{out_path}|layername={name}", name, "ogr")
    return lyr if lyr.isValid() else None


# ---------------------------------------------------------------------------------------------- spatial
def spatial_pairs(lk, holder_layer, target_layer, is_cancelled=None):
    """(holder key, target osid, op) pairs from geometry: 'within' - the holder's point on surface lies in
    the target polygon; 'nearest' - the closest target within ``tol`` metres."""
    hkey, tkey = own_key(lk["holder"]), "osid"
    geoms = {f.id(): (f.geometry(), f[tkey]) for f in target_layer.getFeatures()}
    index = QgsSpatialIndex()
    for fid, (g, _) in geoms.items():
        if g is not None and not g.isEmpty():
            index.addFeature(fid, g.boundingBox())
    out = []
    for f in holder_layer.getFeatures():
        if is_cancelled and is_cancelled():
            break
        g = f.geometry()
        if g is None or g.isEmpty():
            continue
        pt = g if QgsWkbTypes.geometryType(g.wkbType()) == C._POINT else g.pointOnSurface()
        hk = f[hkey]
        if lk["op"] == "nearest":
            p = pt.asPoint() if not pt.isMultipart() else pt.centroid().asPoint()
            for fid in index.nearestNeighbor(p, 1, lk["tol"] or 0):
                tg, tk = geoms[fid]
                if tg.distance(g) <= (lk["tol"] or 0):
                    out.append((hk, tk, "nearest"))
        else:
            for fid in index.intersects(pt.boundingBox()):
                tg, tk = geoms[fid]
                if tg.intersects(pt):
                    out.append((hk, tk, "within"))
    return out


# ---------------------------------------------------------------------------------------------- joined copies (SQL)
def joined_sql(base, link_ids, tables, columns, attrs):
    """The SQL for ``<layer>_joined``: the layer plus, for each link it holds, ``<prefix>key`` (first linked
    identifier), ``<prefix>n`` (how many), ``<prefix>keys`` (all, comma-separated, for one-to-many links) and
    up to two descriptive attributes of the first linked feature; for each link pointing at it, a count
    such as ``n_building_primary_site``. ``tables``: {link id: link table}; ``columns``: {layer: set(columns)};
    ``attrs``: {base: [descriptive attributes]}. None if there's nothing to add."""
    name = layer_name(base)
    selects, joins, used = ["t.*"], [], {c.lower() for c in columns.get(name, ())}

    def col(nm):
        nm2, i = nm, 2
        while nm2.lower() in used:
            nm2, i = f"{nm}_{i}", i + 1
        used.add(nm2.lower())
        return _sql_name(nm2)

    hkey = own_key(base)
    for j, lid in enumerate(link_ids):
        lk = NL.LINK_BY_ID[lid]
        tbl = tables.get(lid)
        if not tbl:
            continue
        if lk["holder"] == base:
            pre = NL.field_prefix(lk)
            a = f"o{j}"
            joins.append(f"LEFT JOIN (SELECT from_key AS fk, MIN(to_key) AS k, COUNT(DISTINCT to_key) AS n, "
                         f"GROUP_CONCAT(DISTINCT to_key) AS ks FROM {_sql_name(tbl)} GROUP BY from_key) {a} "
                         f"ON {a}.fk = t.{_sql_name(hkey)}")
            selects.append(f"{a}.k AS {col(pre + 'key')}")
            selects.append(f"COALESCE({a}.n, 0) AS {col(pre + 'n')}")
            if not lk["card"].startswith("N:1") and lk["card"] != "1:1":
                selects.append(f"{a}.ks AS {col(pre + 'keys')}")
            tname = layer_name(lk["target"])
            tkey = lk["key"] if lk["kind"] == "id" else "osid"
            if tname in columns and tkey in columns[tname]:
                for at in attrs.get(lk["target"], []):
                    if at in columns[tname]:
                        selects.append(f"(SELECT {_sql_name(at)} FROM {_sql_name(tname)} x WHERE "
                                       f"x.{_sql_name(tkey)} = {a}.k LIMIT 1) AS {col(pre + at[:30])}")
        if lk["target"] == base and lk["holder"] != base:
            a = f"i{j}"
            tkey = lk["key"] if lk["kind"] == "id" else "osid"
            if tkey not in columns.get(name, ()):
                continue
            joins.append(f"LEFT JOIN (SELECT to_key AS tk, COUNT(DISTINCT from_key) AS n FROM {_sql_name(tbl)} GROUP BY to_key) "
                         f"{a} ON {a}.tk = t.{_sql_name(tkey)}")
            selects.append(f"COALESCE({a}.n, 0) AS {col(NL.count_field(lk))}")
    if len(selects) == 1:
        return None
    return f"SELECT {', '.join(selects)} FROM {_sql_name(name)} t {' '.join(joins)}"


def write_joined(out_path, tmp, base, sql, dest=None):
    """Runs ``joined_sql`` inside the GeoPackage (SQLite does the joining) and stores the result as
    ``<layer>_joined`` - in the same GeoPackage, or in ``dest`` (a file of just the joined layers).
    Returns the new layer's name."""
    gdal, _, _ = C._gdal()
    jname = f"{layer_name(base)}_joined"
    tmp_gpkg = os.path.join(tmp, f"{jname}.gpkg")
    gdal.VectorTranslate(tmp_gpkg, out_path, format="GPKG", SQLStatement=sql, SQLDialect="SQLITE",
                         layerName=jname)
    dest = dest or out_path
    gdal.VectorTranslate(dest, tmp_gpkg, format="GPKG", accessMode="update" if os.path.exists(dest) else None,
                         layers=[jname], layerName=jname, transactionSize=100000)
    return jname


def layer_columns(out_path):
    gdal, _, _ = C._gdal()
    ds = gdal.OpenEx(out_path, gdal.OF_VECTOR)
    out = {}
    for i in range(ds.GetLayerCount()):
        lyr = ds.GetLayerByIndex(i)
        d = lyr.GetLayerDefn()
        out[lyr.GetName()] = {d.GetFieldDefn(k).GetName() for k in range(d.GetFieldCount())}
    ds = None
    return out


# ---------------------------------------------------------------------------------------------- the simple answer (SQL)
def geometry_column(out_path, name):
    gdal, _, _ = C._gdal()
    ds = gdal.OpenEx(out_path, gdal.OF_VECTOR)
    lyr = ds.GetLayerByName(name)
    g = (lyr.GetGeometryColumn() or "geom") if lyr is not None else None
    ds = None
    return g


MIXED = "Dual use (residential and commercial)"     # OS Places' name for mixed-use addresses


def _clean(expr, attr):
    """OS delivers some attributes as JSON lists (e.g. oslandusetierb = '["Primary Education"]'): show
    them as plain text."""
    if attr.endswith("tierb"):
        return f"TRIM(REPLACE(REPLACE(REPLACE({expr}, '[', ''), ']', ''), '\"', ''))"
    return expr


def _fill(template, use, cols, alias):
    """Fills {placeholders} in an aggregate's expression with the first attribute present for each - or
    returns None if a required one is missing. ``{name?}`` is optional and becomes NULL when missing."""
    out = template or ""
    for name, cands in use.items():
        a = next((c for c in cands if c in cols), None)
        col = f"{alias}.{_sql_name(a)}" if a else None
        if "{" + name + "}" in out:
            if col is None:
                return None
            out = out.replace("{" + name + "}", col)
        out = out.replace("{" + name + "?}", col or "NULL")
    return out


def answer_sql(ans, tables, columns, geom):
    """One row per subject feature (e.g. per address), with the answer's friendly columns gathered along
    the link tables by SQLite. A column whose link wasn't ticked or found comes out empty (counts: 0).

    Column kinds: 'attr' (first value), 'list' (all values), 'count', 'breakdown' (address types with %),
    'pct:<class>', 'agg' (SUM / MAX / MIN / COUNT of an expression over the linked features, optionally
    filtered) and '=' (worked out from other columns, e.g. floor area = footprint x floors)."""
    subj = ans["subject"]
    name = layer_name(subj)
    if name not in columns or not geom:
        return None
    key = own_key(subj)
    sel = [f"t.{_sql_name(geom)} AS geom"]
    derived = []
    for col, _alias, path, how, attrs in ans["columns"]:
        if how == "=":
            derived.append((col, attrs))
            continue
        steps, end = NL.path_types(subj, path)
        expr = "NULL"
        if not steps:
            if how == "agg":
                filled = _fill(attrs["expr"], attrs["use"], columns[name], "t")
                expr = f"({filled})" if filled else "NULL"
            else:
                a = next((a for a in attrs if a in columns[name]), None)
                if a:
                    expr = _clean(f"t.{_sql_name(a)}", a)
        else:
            prev, ok = f"t.{_sql_name(key)}", True
            for lk, side in steps:
                tbl = tables.get(lk["id"])
                if not tbl:
                    ok = False
                    break
                if side == "out":
                    prev = f"SELECT to_key AS k FROM {_sql_name(tbl)} WHERE from_key IN ({prev})"
                else:
                    prev = f"SELECT from_key AS k FROM {_sql_name(tbl)} WHERE to_key IN ({prev})"
            if not ok and how == "count":
                expr = "0"
            if not ok and how == "breakdown":
                expr = "'No addresses'"          # the link was looked for and none were found
            if ok:
                last, side = steps[-1]
                end_key = ((last["key"] if last["kind"] == "id" else "osid") if side == "out"
                           else own_key(last["holder"]))
                ename = layer_name(end)
                ecols = columns.get(ename, set())
                found = ename in columns and end_key in ecols
                if how == "count":
                    expr = f"(SELECT COUNT(DISTINCT k) FROM ({prev}))"
                elif how == "agg" and found:
                    a = attrs
                    body = "*" if a["expr"] == "*" else _fill(a["expr"], a["use"], ecols, "x")
                    cond = _fill(a["where"], a["use"], ecols, "x") if a.get("where") else ""
                    if body is not None and cond is not None:
                        expr = (f"(SELECT {a['fn']}({body}) FROM {_sql_name(ename)} x WHERE x.{_sql_name(end_key)} "
                                f"IN ({prev})" + (f" AND ({cond})" if cond else "") + ")")
                        if a["fn"] in ("SUM", "COUNT"):
                            expr = f"COALESCE({expr}, 0)"
                elif how == "breakdown" and attrs[0] in ecols and found:
                    # e.g. '34 Residential (72%) / 12 Commercial (26%) / 1 Mixed use (2%)'
                    a, kk, tbl = _sql_name(attrs[0]), _sql_name(end_key), _sql_name(ename)
                    label = f"COALESCE(NULLIF(REPLACE(x.{a}, '{MIXED}', 'Mixed use'), ''), 'Unclassified')"
                    expr = (f"(SELECT GROUP_CONCAT(part, ' / ') FROM (SELECT COUNT(*) || ' ' || {label} || ' (' || "
                            f"CAST(ROUND(100.0 * COUNT(*) / (SELECT COUNT(*) FROM {tbl} y WHERE y.{kk} IN ({prev}))) "
                            f"AS INTEGER) || '%)' AS part FROM {tbl} x WHERE x.{kk} IN ({prev}) GROUP BY {label} "
                            f"ORDER BY COUNT(*) DESC))")
                elif how.startswith("pct:") and attrs[0] in ecols and found:
                    group = how[4:].replace("'", "''")
                    expr = (f"(SELECT CAST(ROUND(100.0 * SUM(x.{_sql_name(attrs[0])} = '{group}') / COUNT(*)) "
                            f"AS INTEGER) FROM {_sql_name(ename)} x WHERE x.{_sql_name(end_key)} IN ({prev}))")
                elif found and how in ("attr", "list"):
                    a = next((a for a in attrs if a in ecols), None)
                    val = _clean(f"x.{_sql_name(a)}", a) if a else None
                    if a and how == "list":
                        expr = (f"(SELECT GROUP_CONCAT(DISTINCT {val}) FROM {_sql_name(ename)} x "
                                f"WHERE x.{_sql_name(end_key)} IN ({prev}) AND {val} <> '')")
                    elif a:
                        expr = (f"(SELECT {val} FROM {_sql_name(ename)} x WHERE x.{_sql_name(end_key)} "
                                f"IN ({prev}) AND x.{_sql_name(a)} IS NOT NULL LIMIT 1)")
        sel.append(f"{expr} AS {_sql_name(col)}")
    where = ""
    order = [c[0] for c in ans["columns"]]
    if "ngd_in_area" in columns[name]:
        sel.append("CASE WHEN t.ngd_in_area = 1 THEN 'Yes' ELSE 'No - linked from nearby' END AS in_your_area")
        order.append("in_your_area")
        if ans.get("only_in_area"):
            where = " WHERE t.ngd_in_area = 1"
    sql = f"SELECT {', '.join(sel)} FROM {_sql_name(name)} t{where}"
    # worked-out columns wrap the query once per level: those using only gathered columns first, then those
    # using worked-out ones (few levels keep SQLite's parser happy)
    level, names = {}, {c for c, _ in derived}
    for col, expr in derived:
        uses = set(re.findall(r"[a-z_][a-z0-9_]*", expr)) & names
        level[col] = 1 + max((level.get(u, 0) for u in uses), default=0)
    for lv in sorted(set(level.values())):
        cols = [f"({expr}) AS {_sql_name(col)}" for col, expr in derived if level[col] == lv]
        sql = f"SELECT q.*, {', '.join(cols)} FROM ({sql}) q"
    return f"SELECT geom, {', '.join(_sql_name(c) for c in order)} FROM ({sql})"


def answer_layer_name(ans):
    return "Answer_" + C._safe_name(ans["title"].split(" (")[0])


def write_answer(out_path, tmp, ans, tables):
    """Writes the answer layer into the GeoPackage. Returns its name, or None."""
    gdal, _, _ = C._gdal()
    subj_name = layer_name(ans["subject"])
    sql = answer_sql(ans, tables, layer_columns(out_path), geometry_column(out_path, subj_name))
    if not sql:
        return None
    name = answer_layer_name(ans)
    tmp_gpkg = os.path.join(tmp, f"{name}.gpkg")
    gdal.VectorTranslate(tmp_gpkg, out_path, format="GPKG", SQLStatement=sql, SQLDialect="SQLITE", layerName=name)
    gdal.VectorTranslate(out_path, tmp_gpkg, format="GPKG", accessMode="update", layers=[name], layerName=name)
    return name


# ---------------------------------------------------------------------------------------------- the job
def joined_path(out_path):
    root, ext = os.path.splitext(out_path)
    return f"{root}_joined{ext}"


def run(task, ngd, places, types, link_ids, filters, aoi, bbox, wkt, mode, out_path, tmp, outside=True,
        joined="same", expected=None, places_cells=None, first_pages=None, answer=None):
    """Everything in the worker thread. ``joined``: None (no joined copies), 'same' (in the main
    GeoPackage) or 'separate' (all of them together in their own GeoPackage, ``<name>_joined.gpkg``).
    Returns a result dict for the tab to add to the map."""
    if joined is True:
        joined = "same"
    t_start = time.monotonic()
    notes, report = [], []
    store = Store()
    cancelled = task.isCanceled
    if isinstance(ngd.transport, RateLimited):
        bucket = ngd.transport.bucket
    else:
        bucket = _Bucket()
        _limit(ngd, bucket)
    _limit(places, bucket)          # one project, one limit
    tx = {}
    mark = [0]
    secs, tmark = {}, [time.monotonic()]

    def clock(label):
        now = time.monotonic()
        secs[label] = secs.get(label, 0) + now - tmark[0]
        tmark[0] = now

    def spent(label):
        tx[label] = tx.get(label, 0) + ngd.budget.used - mark[0]
        mark[0] = ngd.budget.used
    ngd_types = [t for t in types if t != NL.PLACES_ADDRESS]
    want_address = NL.PLACES_ADDRESS in types
    task.report(0, "Checking feature types")
    cids = latest_collections(ngd) if ngd_types else {}
    for t in ngd_types:
        if t not in cids:
            notes.append(f"{NL.title(t)} isn't offered by your OS NGD API - Features key - skipped.")
    ngd_types = [t for t in ngd_types if t in cids]
    expected = dict(expected or {})

    # 1. the area and its addresses, side by side: every page of every feature type, and the address squares
    def area_job():
        return download_area(ngd, cids, ngd_types, bbox, wkt, filters, expected, tmp, task, 1, 55, first_pages)

    def address_job():
        if not want_address:
            return [], {}, False
        return fetch_addresses(places, bbox, aoi, None, 55, 62, cancelled)
    got = parallel([area_job, address_job])
    for r in got:
        if isinstance(r, Exception):
            raise r
    (area_files, counts, truncated), (addresses, pool, tr) = got
    if truncated:
        notes.append("Stopped at the transaction limit - partial download.")
    spent("OS NGD features and addresses in the area")
    if want_address:
        if not addresses and not tr:
            notes.append("OS Places returned no addresses for this area - if there should be some, check that "
                         "your API key's project includes the OS Places API.")
        for r in addresses:
            store.add(NL.PLACES_ADDRESS, r, True)
        counts[NL.PLACES_ADDRESS] = len(addresses)
        if tr:
            truncated = True
            notes.append("OS Places stopped at the transaction limit - some addresses are missing.")
    clock("downloading the area")
    task.report(62, "Reading the downloaded features")
    for t, path in area_files.items():
        read_seq(path, t, store, inside=True)

    # 2. find the links; fetch linked features outside the area by their ID
    detected, fetched, outside_files = {}, {}, {}
    id_links = [lid for lid in link_ids if NL.LINK_BY_ID[lid]["kind"] == "id"]
    pairs = resolve_links(id_links, store, detected)
    quick = copy.copy(ngd)                              # optional lookups: don't sit through long retries
    quick.transport = ngd.transport.fail_fast()
    if places is not None:
        quick_places = copy.copy(places)
        quick_places.transport = places.transport.fail_fast()
    else:
        quick_places = None
    step = 0
    tried = {}                     # (type, key, distance) -> IDs already asked for: never ask twice
    skipped_filtered = {}
    barren = set()
    lookups = {"done": 0, "skipped": 0}
    for rnd in range(MAX_ROUNDS):
        for dist in NEAR:
            if not outside or truncated or cancelled():
                break
            want = {t: ks for t, ks in missing_targets(id_links, pairs, store).items() if t in types}
            # a filtered feature type (e.g. only School sites) isn't fetched by ID: what's linked but missing
            # is almost always one the filter left out on purpose (the house's ordinary site), and OS
            # struggles with ID + filter searches
            for t in [t for t in want if filters.get(t)]:
                skipped_filtered[t] = skipped_filtered.get(t, 0) + sum(len(v) for v in want[t].values())
                del want[t]
            # addresses already read in bulk (just beyond the edge, or non-postal) cost nothing
            for u in list(want.get(NL.PLACES_ADDRESS, {}).get("uprn", ())):
                if u in pool:
                    row = pool.pop(u)
                    if store.add(NL.PLACES_ADDRESS, row, False):
                        addresses.append(row)
                        fetched[NL.PLACES_ADDRESS] = fetched.get(NL.PLACES_ADDRESS, 0) + 1
            if NL.PLACES_ADDRESS in want:
                pairs = resolve_links(id_links, store, detected)
                want = {t: ks for t, ks in missing_targets(id_links, pairs, store).items() if t in types}
            for t in list(want):
                for key in list(want[t]):
                    seen = tried.setdefault((t, key, None if t == NL.PLACES_ADDRESS else dist), set())
                    want[t][key] = set(want[t][key]) - seen
                    seen |= want[t][key]
                    if not want[t][key]:
                        del want[t][key]
                if not want[t]:
                    del want[t]
            # a feature type where none of 20+ IDs turned up nearby: they're very unlikely to be further away
            # (more likely retired or not that kind of feature) - don't spend a wider search on them
            for t in list(want):
                if t in barren and dist != NEAR[0]:
                    del want[t]
            if not want:
                continue
            near = (bbox[0] - dist, bbox[1] - dist, bbox[2] + dist, bbox[3] + dist)
            n_want = sum(len(v) for ks in want.values() for v in ks.values())
            task.report(64 + step, f"Fetching {n_want:,} linked feature(s) within {dist / 1000:g} km of the area")
            got, rows, tr = fetch_outside(quick, quick_places, cids, want, store, outside_files, tmp, task,
                                          64 + step, 66 + step, notes, near, filters, pool, lookups)
            step = min(step + 3, 9)
            for t, ks in want.items():
                if t != NL.PLACES_ADDRESS and not got.get(t) and sum(len(v) for v in ks.values()) >= 20:
                    barren.add(t)
            for t, n in got.items():
                fetched[t] = fetched.get(t, 0) + n
            addresses.extend(rows)
            if tr:
                truncated = True
                notes.append("Stopped fetching linked features at the transaction limit - some links are left "
                             "unresolved (target_found = 0 in the link tables).")
            pairs = resolve_links(id_links, store, detected)
    spent("linked features outside the area")
    clock("fetching linked features")
    for t in skipped_filtered:
        notes.append(f"{NL.title(t)} is filtered, so links to {NL.plural(t)} the filter leaves out (e.g. a "
                     f"building's ordinary site) aren't fetched - they show as not found.")
    if cancelled():
        notes.append("Stopped early - everything downloaded up to then has been saved and linked.")
    if lookups["skipped"]:
        notes.append(f"{lookups['skipped']:,} more linked addresses would each have needed a transaction of their "
                     f"own - skipped (only {MAX_UPRN_LOOKUPS} are looked up one by one). Make the area a little "
                     "bigger to pick them up in bulk.")
    if outside and not truncated:
        left = {t: ks for t, ks in missing_targets(id_links, pairs, store).items() if t in types}
        n_left = sum(len(v) for ks in left.values() for v in ks.values())
        if n_left:
            notes.append(f"{n_left:,} linked feature(s) couldn't be found within {NEAR[-1] / 1000:g} km of the area "
                         "(e.g. addresses OS Places doesn't hold, or features since retired) - target_found = 0 in "
                         "the link tables.")
    t_net = time.monotonic() - t_start

    # 3. write the layers (GDAL)
    written = {}
    for i, t in enumerate(ngd_types):
        task.report(76 + 8 * i / max(1, len(ngd_types)), f"Writing {NL.title(t)}")
        n = write_ngd_layer(area_files.get(t), outside_files.get(t), aoi, out_path, layer_name(t), mode)
        if n:
            written[t] = n
    if want_address and addresses:
        written[NL.PLACES_ADDRESS] = write_address_layer(addresses, store, out_path)

    clock("writing the layers")

    # 4. spatial links (from the written layers)
    sp_detected = {}
    for lid in link_ids:
        lk = NL.LINK_BY_ID[lid]
        if lk["kind"] != "spatial":
            continue
        task.report(85, f"Working out '{NL.say(lk)}' from location")
        hl = gpkg_layer(out_path, layer_name(lk["holder"])) if lk["holder"] in written else None
        tl = gpkg_layer(out_path, layer_name(lk["target"])) if lk["target"] in written else None
        if hl is None or tl is None:
            pairs[lid] = []
            continue
        pairs[lid] = [(NL.norm(h, own_key(lk["holder"])), NL.norm(t, "osid"), op)
                      for h, t, op in spatial_pairs(lk, hl, tl)]
        sp_detected[lid] = lk["op"]

    # 4b. identifier links OS didn't include in the data: worked out from location instead, so answers
    # (addresses in a building, a building's site…) are still filled in
    fallback_used = {}
    for lid in id_links:
        d = detected.get(lid) or {}
        if d.get("how") != "not found" or lid not in NL.FALLBACK:
            continue
        sp_id, swap = NL.FALLBACK[lid]
        sp = NL.LINK_BY_ID[sp_id]
        if sp["holder"] not in written or sp["target"] not in written:
            continue
        task.report(86, f"Working out '{NL.say(NL.LINK_BY_ID[lid])}' from location")
        hl = gpkg_layer(out_path, layer_name(sp["holder"]))
        tl = gpkg_layer(out_path, layer_name(sp["target"]))
        if hl is None or tl is None:
            continue
        found = [(NL.norm(h, own_key(sp["holder"])), NL.norm(t, "osid")) for h, t, _ in spatial_pairs(sp, hl, tl)]
        if swap:     # e.g. (address uprn, building osid) -> (building osid, address uprn)
            pairs[lid] = [(t, h, "location") for h, t in found]
        else:
            pairs[lid] = [(h, t, "location") for h, t in found]
        detected[lid] = {"fields": [], "rev": [], "how": "location (not in OS's data)"}
        fallback_used[lid] = len(pairs[lid])

    # 5. link tables + register
    task.report(88, "Writing link tables")
    keys_cache = {}
    gdal_, _, _ = C._gdal()
    shared = gdal_.OpenEx(out_path, gdal_.OF_VECTOR | gdal_.OF_UPDATE) if os.path.exists(out_path) else None

    def keys(base, key):
        if (base, key) not in keys_cache:
            keys_cache[(base, key)] = written_keys(out_path, layer_name(base), key, shared) if base in written else {}
        return keys_cache[(base, key)]

    tables, relations, register = {}, [], []
    stamp = _dt.date.today().isoformat()
    for lid in link_ids:
        lk = NL.LINK_BY_ID[lid]
        prs = pairs.get(lid) or []
        h, t = lk["holder"], lk["target"]
        key = lk["key"] if lk["kind"] == "id" else "osid"
        hkeys, tkeys = keys(h, own_key(h)), keys(t, key)
        rows, found = [], 0
        for hk, tk, via in prs:
            hraw, hin = hkeys.get(hk, (hk, False))
            traw, tin = tkeys.get(tk, (tk, False))
            ok = tk in tkeys
            found += ok
            rows.append((str(hraw), str(traw), via, int(ok), int(hin), int(tin)))
        d = detected.get(lid) or {}
        via = ", ".join(d.get("fields") or d.get("rev") or []) if lk["kind"] == "id" else sp_detected.get(lid, "")
        how = d.get("how", "spatial") if lk["kind"] == "id" else "spatial"
        tname = f"link_{lid}"[:60]
        if rows:
            write_table(out_path, tname, [("from_key", "str"), ("to_key", "str"), ("via_field", "str"),
                                          ("target_found", "int"), ("from_in_area", "int"), ("to_in_area", "int")],
                        rows, index=("from_key", "to_key"), ds=shared)
            tables[lid] = tname
        cls_name, cls_text = NL.PLAIN_CLASSES[lk["cls"]]
        register.append((lid, NL.say(lk), NL.say(lk, "in"), NL.card_sentence(lk), NL.noun(h), NL.noun(t),
                         cls_name, cls_text, lk["card"], key, via, how, len(prs), found, len(prs) - found,
                         lk["note"], stamp, SPEC))
        scalar = lk["kind"] == "id" and d.get("fields") and not d.get("rev") and _scalar(store, h, d["fields"])
        relations.append({"link": lid, "table": tname if rows else None, "holder": h, "target": t, "key": key,
                          "direct": d["fields"] if scalar else []})
        icon = "🔗" if lk["kind"] == "id" else "⇢"
        if lid in fallback_used:
            report.append(f"⇢ {NL.say(lk)}: {len(prs):,} found from location - OS didn't include this link in the "
                          "data, so it was worked out from where the features are.")
        elif lk["kind"] == "id" and how == "not found":
            report.append(f"⚠ {NL.say(lk)}: " + (
                f"OS didn't include this link in the {NL.plural(h)} downloaded, so it's been left out."
                if store.props.get(h) else f"no {NL.plural(h)} in the area, so nothing to link."))
        elif not prs:
            report.append(f"{icon} {NL.say(lk)}: none found.")
        else:
            miss = len(prs) - found
            report.append(f"{icon} {NL.say(lk)}: {len(prs):,} found"
                          + (f" ({miss:,} point at features that weren't downloaded)" if miss else "")
                          + (" - the attribute name was guessed, worth checking" if how == "guess" else ""))
    write_table(out_path, "ngd_link_register",
                [("link_id", "str"), ("in_plain_english", "str"), ("and_the_other_way", "str"),
                 ("how_many", "str"), ("from_type", "str"), ("to_type", "str"), ("link_type", "str"),
                 ("link_type_means", "str"), ("cardinality", "str"), ("join_key", "str"), ("via_fields", "str"),
                 ("detected_by", "str"), ("links", "int"), ("targets_found", "int"), ("unresolved", "int"),
                 ("note", "str"), ("checked", "str"), ("source", "str")], register, ds=shared)
    shared = None          # closes the file before the joined copies and the answer read it

    # 6. joined copies (SQLite does the joins inside the GeoPackage)
    joined_layers = {}
    jout = joined_path(out_path) if joined == "separate" else out_path
    if joined and tables:
        cols = layer_columns(out_path)
        attrs = {t: NL.join_attrs(list(store.props.get(t, {}).values())[:300]) for t in written}
        for i, t in enumerate(written):
            task.report(92 + 7 * i / max(1, len(written)), f"Writing joined copy of {NL.title(t)}")
            sql = joined_sql(t, link_ids, tables, cols, attrs)
            if sql:
                try:
                    joined_layers[t] = write_joined(out_path, tmp, t, sql, jout)
                except RuntimeError as ex:
                    notes.append(f"Couldn't write the joined copy of {NL.title(t)} ({ex}).")
    clock("linking")

    # 7. the simple answer: one layer, one row per subject, friendly columns
    answer_name = None
    if answer:
        task.report(99, "Writing the answer")
        try:
            answer_name = write_answer(out_path, tmp, answer, tables)
        except RuntimeError as ex:
            notes.append(f"Couldn't write the answer layer ({ex}).")
    clock("building the answer")
    task.report(100, "Done")
    return {"out": out_path, "answer": answer_name, "tx": tx, "secs": secs, "joined_out": jout if joined_layers else None, "written": written,
            "fetched": fetched, "counts": counts,
            "tables": [(tn, lid) for lid, tn in tables.items()], "relations": relations, "joined": joined_layers,
            "notes": notes, "report": report, "used": ngd.budget.used, "truncated": truncated,
            "cancelled": cancelled(), "seconds": time.monotonic() - t_start, "network_seconds": t_net}


def _scalar(store, base, fields):
    """True if every sampled value of ``fields`` is a single identifier (so the holder layer itself can be
    the child of a QGIS relation, without the link table)."""
    sample = list(store.props.get(base, {}).values())[:200]
    for p in sample:
        for f in fields:
            v = p.get(f)
            if isinstance(v, (list, dict)) or (isinstance(v, str) and v[:1] in "[{"):
                return False
    return True


# ---------------------------------------------------------------------------------------------- main thread
_FIELD_WORDS = {"startnode": "as their start", "endnode": "as their end", "smallestsite_siteid": "smallest Site",
                "largestsite_siteid": "largest Site"}


def _cap(text):
    return text[:1].upper() + text[1:]


def add_relations(result, layers, stamp):
    """QGIS relations for the downloaded layers, named in plain English - the names are what a feature's
    form shows, e.g. a Site's form lists 'Buildings that mainly belong to this Site'.

    Single-valued links (e.g. Building.primarysiteid) relate the two layers directly. Others go through the
    link table: two relations (holder -> table, target -> table), set up as a many-to-many pair so each
    form lists the linked *features*, not link-table rows. ``layers``: {GeoPackage layer name: layer in the
    project}. Returns the relations added."""
    mgr = QgsProject.instance().relationManager()
    added = []

    def add(rid, name, child, child_field, parent, parent_field):
        if child is None or parent is None:
            return None
        if child.fields().indexOf(child_field) < 0 or parent.fields().indexOf(parent_field) < 0:
            return None
        rel = QgsRelation()
        rel.setId(re.sub(r"[^A-Za-z0-9_]", "_", rid))
        rel.setName(name)
        rel.setReferencingLayer(child.id())
        rel.setReferencedLayer(parent.id())
        rel.addFieldPair(child_field, parent_field)
        if not rel.isValid():
            return None
        mgr.addRelation(rel)
        added.append(rel)
        return rel

    def many_to_many(parent, rel, other):
        """Show the features at the other end of the link table in ``parent``'s form (QGIS 'nm-rel')."""
        if parent is None or rel is None or other is None:
            return
        try:
            cfg = parent.editFormConfig()
            cfg.setWidgetConfig(rel.id(), {"nm-rel": other.id()})
            parent.setEditFormConfig(cfg)
        except Exception:   # noqa: BLE001 - only changes how the form looks
            pass

    for r in result["relations"]:
        lk = NL.LINK_BY_ID[r["link"]]
        hl = layers.get(layer_name(r["holder"]))
        tl = layers.get(layer_name(r["target"]))
        tbl = layers.get(r["table"]) if r["table"] else None
        hkey = own_key(r["holder"])
        tkey = r["key"] if r["target"] != NL.PLACES_ADDRESS else "uprn"
        base = f"ngdlink_{stamp}_{r['link']}"
        direct = None
        for f in r["direct"]:
            name = _cap(lk["back"]) + (f" ({_FIELD_WORDS.get(f, f)})" if len(r["direct"]) > 1 else "")
            direct = add(f"{base}_{f}", name, hl, f, tl, tkey) or direct
        if tbl is not None and direct is None:
            from_rel = add(f"{base}_from", _cap(lk["fwd"]), tbl, "from_key", hl, hkey)
            to_rel = add(f"{base}_to", _cap(lk["back"]), tbl, "to_key", tl, tkey)
            many_to_many(hl, from_rel, to_rel)
            many_to_many(tl, to_rel, from_rel)
    return added
