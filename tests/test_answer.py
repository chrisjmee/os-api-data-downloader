import os
exec(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_links.py")).read().split("# --- tree behaviour")[0])
from qgis.core import QgsProject
tab = LT.LinksTab(None, FakeArea())
assert tab.view.currentData() == "simple"
i = [i for i in range(tab.recipe.count()) if tab.recipe.itemText(i).startswith("1.")][0]
tab._apply_recipe(i)
assert "You'll get" in tab.details.text()
tab.download()
t0 = time.time()
while (tab.task is not None or not hasattr(tab, "last_result")) and time.time() - t0 < 60:
    app.processEvents(); time.sleep(0.02)
print(tab.status.text().replace("<br>", "\n"))
lyr = tab.last_answer_layer
assert lyr is not None and lyr.isValid()
rows = {f["uprn"]: {fld.name(): f[fld.name()] for fld in lyr.fields()} for f in lyr.getFeatures()}
for u, r in rows.items():
    print(u, {k: v for k, v in r.items() if k != "fid"})
r = rows["100"]
assert r["building_use"] == "Education" and r["building_type"] == "School" and r["site_use"] == "School" and r["addresses_in_building"] == 2
assert r["building_parts"] == 2 and r["land_use"] == "Education" and r["floor_area_m2"] == 5000 and r["floor_area_per_address_m2"] == 2500
assert lyr.attributeAlias(lyr.fields().indexOf("building_use")) == "Building use"
assert "Building use" in lyr.mapTipTemplate()
root = QgsProject.instance().layerTreeRoot()
g = root.children()[0]
print("tree:", g.name(), [c.name() for c in g.children()])
assert g.name().startswith("Answer: Tell me everything about this property")
assert not any("Link tables" in c.name() or "Joined" in c.name() for c in g.children())
sup = [c for c in g.children() if c.name().startswith("Supporting")][0]
assert all(not n.itemVisibilityChecked() for n in sup.children())
print("mix:", r["address_mix"], r["pct_residential"], r["pct_commercial"])
assert r["address_mix"] in ("1 Commercial (50%) / 1 Residential (50%)", "1 Residential (50%) / 1 Commercial (50%)")
assert r["pct_residential"] == 50 and r["pct_commercial"] == 50 and r["address_class"] == "Commercial"
assert "Addresses in your area: <b>1 Commercial (100%)</b>" in tab.status.text()
print("ANSWER OK")
