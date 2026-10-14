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
            feats = [{"type": "Feature", "id": p.get("osid", p.get("postcode")), "properties": p, "geometry": g} for p, g, _ in page]
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

# --- tree behaviour
assert "lus-fts-site" in tab.type_items and "!asu-admin" not in tab.type_items
li = tab.link_items["building_primary_site"][0]
li.setCheckState(0, Qt.CheckState.Checked)
assert set(tab.checked_types()) == {"bld-fts-building", "lus-fts-site"}, tab.checked_types()
assert all(i.checkState(0) == Qt.CheckState.Checked for i in tab.link_items["building_primary_site"])
tab.type_items["lus-fts-site"].setCheckState(0, Qt.CheckState.Unchecked)
assert tab.checked_links() == [], tab.checked_links()
tab.find.setText("usrn")
assert not tab.type_items["trn-ntwk-street"].isHidden()
assert tab.type_items["lnd-fts-land"].isHidden()
tab.find.setText("")
assert tab.link_items["sp_address_building"][0].isHidden()
tab.show_spatial.setChecked(True)
assert not tab.link_items["sp_address_building"][0].isHidden() or not tab.link_items["sp_address_building"][0].parent().isExpanded()
# every quick pick applies cleanly
for i in range(tab.recipe.count()):
    d = tab.recipe.itemData(i)
    if isinstance(d, tuple):
        tab._apply_recipe(i)
        assert tab.checked_types(), tab.recipe.itemText(i)
emerg = [i for i in range(tab.recipe.count()) if tab.recipe.itemText(i).startswith("3.")][0]
tab._apply_recipe(emerg)
assert "sal_roadnode" in tab.checked_links()
assert "get into this site" in tab.details.text()
edu = [i for i in range(tab.recipe.count()) if tab.recipe.itemText(i).startswith("5.")][0]
tab.show_spatial.setChecked(False)
tab._apply_recipe(edu)
assert "School" in tab.filters["lus-fts-site"] and "School" in (tab.where("lus-fts-site") or "")
assert "sp_address_site" not in tab.checked_links()      # spatial links stay off unless asked for
tab.show_spatial.setChecked(True)
tab._apply_recipe(edu)
assert "sp_address_site" in tab.checked_links()
tab.show_spatial.setChecked(False)
steps = tab.show_path(NL.PLACES_ADDRESS, "trn-ntwk-roadlink")
assert steps and "trn-ntwk-street" in tab.checked_types() and "How Address connects" in tab.details.text()
assert tab.show_path("wtr-ntwk-waterlinkset", "lus-fts-site") is None
tab._apply_recipe(emerg)
tab.tree.setCurrentItem(tab.link_items["sal_roadnode"][0])
assert "accessednetworknodeid" in tab.details.text() and "Road Node" in tab.details.text()
tab.tree.setCurrentItem(tab.type_items["lus-fts-site"])
assert "Site" in tab.details.text()

# --- the full download through the real QgsTask machinery
types = ["lus-fts-site", "bld-fts-building", "bld-fts-buildingpart", "lus-fts-siteaccesslocation",
         "trn-ntwk-roadnode", "trn-ntwk-roadlink", "trn-ntwk-street", NL.PLACES_ADDRESS]
links = ["building_primary_site", "building_sites", "building_parts", "building_uprn", "building_main",
         "buildingpart_site", "sal_site", "sal_roadnode", "roadlink_nodes", "roadlink_street", "site_uprn",
         "sp_address_buildingpart", "sp_address_site"]
tab.view.setCurrentIndex(1)   # everything
tab.set_selection(types, links)
assert set(tab.checked_types()) == set(types)
tab.download()
t0 = time.time()
while (tab.task is not None or not hasattr(tab, "last_result")) and time.time() - t0 < 60:
    app.processEvents()
    time.sleep(0.02)
print(tab.status.text().replace("<br>", "\n"))
res = tab.last_result
out = res["out"]
assert os.path.exists(out)


def rows(name):
    lyr = QgsVectorLayer(f"{out}|layername={name}", name, "ogr")
    assert lyr.isValid(), name
    return lyr, [f.attributes() for f in lyr.getFeatures()], [f.name() for f in lyr.fields()]


lyr, site_rows, sf = rows("Site")
assert len(site_rows) == 2, site_rows        # S1 in the area + S2 fetched by ID
ina = {r[sf.index("osid")]: r[sf.index("ngd_in_area")] for r in site_rows}
assert ina == {S1: 1, S2: 0}, ina
_, rn, rf = rows("Road_Node")
assert {r[rf.index("osid")] for r in rn} == {N1, N9}
_, st, stf = rows("Street")
assert len(st) == 1 and st[0][stf.index("usrn")] == 123
_, ad, af = rows("Address")
assert {r[af.index("uprn")] for r in ad} == {"100", "200"}, ad
_, bl, bf = rows("Building")
assert len(bl) == 1                          # B2 is never linked to from in-area data -> not fetched

_, lt, lf = rows("link_building_parts")
assert sorted(r[lf.index("to_key")] for r in lt) == [P1, P2] and all(r[lf.index("target_found")] for r in lt)
_, lt, lf = rows("link_buildingpart_site")
assert len(lt) == 4 and {r[lf.index("via_field")] for r in lt} == {"smallestsite_siteid", "largestsite_siteid"}
_, lt, lf = rows("link_roadlink_street")
assert lt[0][lf.index("to_key")] == "123" and lt[0][lf.index("target_found")] == 1
_, lt, lf = rows("link_sp_address_buildingpart")
assert lt and lt[0][lf.index("from_key")] == "100" and lt[0][lf.index("to_key")] == P1, lt
_, reg, regf = rows("ngd_link_register")
regd = {r[regf.index("link_id")]: r for r in reg}
assert regd["building_primary_site"][regf.index("via_fields")] == "primarysiteid"
assert regd["building_primary_site"][regf.index("in_plain_english")] == "Building → the Site it mainly belongs to"
assert regd["sal_site"][regf.index("unresolved")] == 0

_, bj, bjf = rows("Building_joined")
row = dict(zip(bjf, bj[0]))
print({k: v for k, v in row.items() if k.startswith(("primary_site", "sites", "buildingpart", "address", "n_"))})
assert row["primary_site_key"] == S1 and row["primary_site_description"] == "School"
assert row["buildingpart_n"] == 2 and row["address_n"] == 2
_, sj, sjf = rows("Site_joined")
srow = {r[sjf.index("osid")]: dict(zip(sjf, r)) for r in sj}
print({k: v for k, v in srow[S1].items() if k.startswith("n_")})
print("fetched", res["fetched"]); print([c for c in CALLS if "uprn" in c[0] or "bbox" in c[0]])
assert srow[S1]["n_building_primary_site"] >= 1

rels = QgsProject.instance().relationManager().relations()
names = sorted(r.name() for r in rels.values())
print(len(names), "relations:", [(r.name(), r.referencingLayer().name(), r.referencedLayer().name()) for r in rels.values()])
assert "Buildings that mainly belong to this Site" in names, names
for r in rels.values():
    assert r.isValid()
# a Site's form lists its Buildings through the direct relation
rel = [r for r in rels.values() if r.name() == "Buildings that mainly belong to this Site"][0]
site_layer = rel.referencedLayer()
s1 = [f for f in site_layer.getFeatures() if f["osid"] == S1][0]
kids = list(rel.getRelatedFeatures(s1))
assert [k["osid"] for k in kids] == [B1], kids
n_by_id = sum(1 for p, q in CALLS if "IN (" in q.get("filter", "") and "INTERSECTS" not in q.get("filter", ""))
print("fetch-by-id requests:", n_by_id, "transactions used:", res["used"])
print("ALL OK")

# the link-table relations are set up many-to-many, so a form lists the linked features themselves
blayer = [l for l in QgsProject.instance().mapLayers().values() if l.name() == "Building"][0]
rp = [r for r in rels.values() if r.name() == "The Building Parts it's made of"][0]
cfg = blayer.editFormConfig().widgetConfig(rp.id())
print("nm config:", cfg)
assert cfg.get("nm-rel")
names2 = [r.name() for r in rels.values()]
assert len(names2) == len(set(names2)), sorted(names2)
print("FORM CONFIG OK")
