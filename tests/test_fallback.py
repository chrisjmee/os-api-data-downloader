"""OS's API leaves out the Building cross-references: the answer must still have its addresses."""
import os
exec(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_links.py")).read().split("# --- tree behaviour")[0])
b = DATA["bld-fts-building-4"][0][0]
for k in ("uprnreference", "buildingpartreference", "sitereference", "primarysiteid", "mainbuildingid"):
    b.pop(k, None)
tab = LT.LinksTab(None, FakeArea())
i = [i for i in range(tab.recipe.count()) if tab.recipe.itemText(i).startswith("1.")][0]
tab._apply_recipe(i)
tab.download()
t0 = time.time()
while (tab.task is not None or not hasattr(tab, "last_result")) and time.time() - t0 < 60:
    app.processEvents(); time.sleep(0.02)
print("\n".join(r for r in tab.last_result["report"]))
lyr = tab.last_answer_layer
r = {f.name(): next(lyr.getFeatures())[f.name()] for f in lyr.fields()}
print({k: v for k, v in r.items() if v not in (None, "", 0)})
assert r["building_use"] == "Education" and r["addresses_in_building"] == 1 and r["site_use"] == "School"
assert r["building_parts"] == 2
print("FALLBACK OK")
