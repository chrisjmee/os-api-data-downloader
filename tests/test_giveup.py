"""Offline end-to-end test of the NGD Data Linkages tab with a fake OS API (run with python3.12 in QGIS)."""
import json
import os
import re
import sys
import tempfile
import time
import urllib.parse

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from qgis.core import QgsApplication, QgsGeometry, QgsProject, QgsRectangle, QgsVectorLayer  # noqa: E402

app = QgsApplication([], True)
app.initQgis()

from qgis.PyQt.QtCore import QObject, Qt, pyqtSignal  # noqa: E402

from os_api_data_downloader.core import ngd_links as NL  # noqa: E402
from os_api_data_downloader.gui import links_tab as LT, settings as S  # noqa: E402


def poly(x0, y0, x1, y1):
    return {"type": "Polygon", "coordinates": [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]]}


def pt(x, y):
    return {"type": "Point", "coordinates": [x, y]}


def line(*xy):
    return {"type": "LineString", "coordinates": [list(p) for p in xy]}


S1, S2 = "aaaaaaaa-0000-0000-0000-000000000001", "aaaaaaaa-0000-0000-0000-000000000002"
B1, B2 = "bbbbbbbb-0000-0000-0000-000000000001", "bbbbbbbb-0000-0000-0000-000000000002"
P1, P2 = "cccccccc-0000-0000-0000-000000000001", "cccccccc-0000-0000-0000-000000000002"
A1 = "dddddddd-0000-0000-0000-000000000001"
N1, N9 = "eeeeeeee-0000-0000-0000-000000000001", "eeeeeeee-0000-0000-0000-000000000009"
L1 = "ffffffff-0000-0000-0000-000000000001"
ST = "99999999-0000-0000-0000-000000000001"

# (collection, props, geometry, inside the area?)
DATA = {
    "lus-fts-site-2": [
        ({"osid": S1, "description": "School", "oslandusetiera": "Education", "oslandusetierb": ["Primary Education"],
          "name1_text": "St Mary's Primary", "geometry_area_m2": 10000.0, "addresscount_total": 2,
          "addresscount_residential": 1, "addresscount_commercial": 1, "mainbuildingid": B1},
         poly(0, 0, 100, 100), True),
        ({"osid": S2, "description": "Hospital"}, poly(1000, 1000, 1100, 1100), False),
    ],
    "bld-fts-building-4": [
        ({"osid": B1, "description": "School", "primarysiteid": S1, "mainbuildingid": B1, "buildinguse": "Education",
          "numberoffloors": 2, "geometry_area_m2": 2500.0, "height_relativemax_m": 9.5, "buildingage_period": "1980-1989",
          "roofshapeaspect_areafacingsouth_m2": 100.0, "roofshapeaspect_areaflat_m2": 400.0,
          "roofmaterial_solarpanelpresence": "Present", "connectivity": "Standalone",
          "sitereference": [{"siteid": S1, "buildingid": B1, "buildingversiondate": "2025-01-01"}],
          "buildingpartreference": [{"buildingpartid": P1}, {"buildingpartid": P2}],
          "uprnreference": [{"uprn": 100, "buildingid": B1}, {"uprn": 200, "buildingid": B1}]},
         poly(10, 10, 60, 60), True),
        ({"osid": B2, "description": "Hospital", "primarysiteid": S2}, poly(1010, 1010, 1020, 1020), False),
    ],
    "bld-fts-buildingpart-2": [
        ({"osid": P1, "description": "Building", "smallestsite_siteid": S1, "largestsite_siteid": S1},
         poly(10, 10, 30, 60), True),
        ({"osid": P2, "description": "Building", "smallestsite_siteid": S1, "largestsite_siteid": S2},
         poly(30, 10, 60, 60), True),
    ],
    "lus-fts-siteaccesslocation-2": [
        ({"osid": A1, "access_purpose": "Public", "accessedsiteid": S2, "accessednetworknodeid": N9},
         pt(90, 50), True),
    ],
    "trn-ntwk-roadnode-1": [
        ({"osid": N1, "description": "Road Node"}, pt(95, 95), True),
        ({"osid": N9, "description": "Road Node"}, pt(500, 500), False),
    ],
    "trn-ntwk-roadlink-5": [
        ({"osid": L1, "description": "Single Carriageway", "startnode": N1, "endnode": N9,
          "streetreference": [{"usrn": 123, "roadlinkid": L1}]}, line((95, 95), (500, 500)), True),
    ],
    "lnd-fts-land-3": [
        ({"osid": "11111111-0000-0000-0000-000000000001", "description": "Bare Earth Or Grass", "geometry_area_m2": 4000.0,
          "smallestsite_siteid": S1, "largestsite_siteid": S1, "lowertierlocalauthority_gsscode": "E07000118"},
         poly(60, 0, 100, 100), True),
        ({"osid": "11111111-0000-0000-0000-000000000002", "description": "Made Surface", "geometry_area_m2": 2000.0,
          "smallestsite_siteid": S1, "largestsite_siteid": S1}, poly(0, 60, 60, 100), True),
    ],
    "trn-ntwk-street-1": [
        ({"osid": ST, "usrn": 123, "designatedname1_text": "High Street"}, line((95, 95), (600, 600)), False),
    ],
}
ADDRESSES = {
    "100": {"UPRN": "100", "ADDRESS": "1 SCHOOL LANE", "POSTCODE": "PR7 1AA", "CLASSIFICATION_CODE": "CE03", "CLASSIFICATION_CODE_DESCRIPTION": "School",
            "X_COORDINATE": 20.0, "Y_COORDINATE": 20.0, "STATUS": "APPROVED"},
    "200": {"UPRN": "200", "ADDRESS": "2 FAR AWAY", "POSTCODE": "PR7 9ZZ", "CLASSIFICATION_CODE": "RD04", "CLASSIFICATION_CODE_DESCRIPTION": "Terraced",
            "X_COORDINATE": 2000.0, "Y_COORDINATE": 2000.0, "STATUS": "APPROVED"},
}
CALLS = []


class FakeTransport:
    def request(self, method, url, body=None, headers=None):
        parts = urllib.parse.urlsplit(url)
        q = dict(urllib.parse.parse_qsl(parts.query))
        CALLS.append((parts.path, q))
        path = parts.path
        if path.endswith("/collections"):
            cols = [{"id": c, "title": c} for c in DATA] + [{"id": "bld-fts-building-3"}]
            return 200, json.dumps({"collections": cols}).encode()
        m = re.search(r"/collections/([^/]+)/items$", path)
        if m:
            cid = m.group(1)
            rows = DATA.get(cid, [])
            flt = q.get("filter", "")
            mi = re.search(r"(\w+) IN \(([^)]*)\)", flt)
            if mi and "INTERSECTS" not in flt:
                attr = mi.group(1)
                vals = {v.strip().strip("'").lower() for v in mi.group(2).split(",")}
                rows = [r for r in rows if str(r[0].get(attr)).lower() in vals]
            else:
                rows = [r for r in rows if r[2]]
                if mi:     # attribute filter on the area download, e.g. description IN ('School')
                    vals = {v.strip().strip("'") for v in mi.group(2).split(",")}
                    rows = [r for r in rows if str(r[0].get(mi.group(1))) in vals]
            off, lim = int(q.get("offset", 0)), int(q.get("limit", 100))
            page = rows[off:off + lim]
            feats = [{"type": "Feature", "id": p["osid"], "properties": p, "geometry": g} for p, g, _ in page]
            return 200, json.dumps({"type": "FeatureCollection", "features": feats, "links": []}).encode()
        if path.endswith("/places/v1/bbox"):
            res = [{"DPA": ADDRESSES["100"]}] if q.get("offset", "0") == "0" else []
            return 200, json.dumps({"header": {"totalresults": 1}, "results": res}).encode()
        if path.endswith("/places/v1/uprn"):
            a = ADDRESSES.get(q["uprn"])
            return 200, json.dumps({"header": {"totalresults": 1 if a else 0},
                                    "results": [{"DPA": a}] if a else []}).encode()
        return 404, b"not found"


class FakeArea(QObject):
    changed = pyqtSignal()

    def geometry_bng(self):
        return QgsGeometry.fromRect(QgsRectangle(0, 0, 100, 100))

    @staticmethod
    def filter_wkt(g):
        return g.asWkt(1)

    def clip(self):
        return "intersects"

    def description(self):
        return "test area"


S.load_api_key = lambda: "KEY"
_get = S.get
S.get = lambda k: {"hard_limit": 0, "confirm_over": 0}.get(k, None) if k in ("hard_limit", "confirm_over") else _get(k)
out_dir = tempfile.mkdtemp()
S.output_folder = lambda: out_dir
LT.QgisTransport = FakeTransport

tab = LT.LinksTab(None, FakeArea())


calls = []
_req = FakeTransport.request
def req(self, method, url, body=None, headers=None, retries=None):
    p = urllib.parse.urlsplit(url); q = dict(urllib.parse.parse_qsl(p.query))
    if "lus-fts-site" in p.path and "osid IN (" in q.get("filter", ""):
        calls.append(q["filter"].count(",") + 1)
        return 500, b'{"code":500}'
    return _req(self, method, url, body, headers)
FakeTransport.request = req
import os_api_data_downloader.core.transport as TR
TR.RETRIES = 0
# 40 buildings each in its own (missing) site
for i in range(40):
    DATA["bld-fts-building-4"].append(({"osid": f"bbbbbbbb-0000-0000-0002-{i:012d}", "description": "House",
                                        "primarysiteid": f"aaaaaaaa-0000-0000-0002-{i:012d}"},
                                       poly(i, 0, i + 1, 1), True))
tab = LT.LinksTab(None, FakeArea())
tab.set_selection(["bld-fts-building", "lus-fts-site"], ["building_primary_site"])
tab.download()
t0 = time.time()
while (tab.task is not None or not hasattr(tab, "last_result")) and time.time() - t0 < 60:
    app.processEvents(); time.sleep(0.02)
print("site ID requests:", calls)
print([n for n in tab.last_result["notes"]])
assert len(calls) <= 4, calls
# now with Site filtered: no ID requests at all
calls.clear()
tab.filters["lus-fts-site"] = ["School"]
del tab.last_result
tab.download()
t0 = time.time()
while (tab.task is not None or not hasattr(tab, "last_result")) and time.time() - t0 < 60:
    app.processEvents(); time.sleep(0.02)
print(tab.status.text()[:300])
print("filtered:", calls, tab.last_result["notes"][:1])
assert not calls
print("GIVEUP OK")
