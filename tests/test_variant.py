import os
exec(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_links.py")).read().split("# --- tree behaviour")[0])
FakeArea.clip = lambda self: "clip"
DATA["lus-fts-siteaccesslocation-2"][0][0]["accessedsiteid"] = S1
tab = LT.LinksTab(None, FakeArea())
tab.show_spatial.setChecked(True)
tab.outside.setChecked(False)
tab.view.setCurrentIndex(1)
tab.joined.setCurrentIndex(1)   # all joined copies together in their own file
tab.filters["lus-fts-site"] = ["School"]
tab._mark_filters()
tab.set_selection(["lus-fts-site", "lus-fts-siteaccesslocation", "trn-ntwk-roadlink", "trn-ntwk-roadnode"],
                  ["sal_site", "sal_roadnode", "sp_sal_site", "roadlink_nodes"])
assert "School" in tab.where("lus-fts-site")
# move the access point to 1 m inside the edge of S1
DATA["lus-fts-siteaccesslocation-2"][0] = (dict(DATA["lus-fts-siteaccesslocation-2"][0][0]), pt(99, 50), True)
tab.download()
t0 = time.time()
while (tab.task is not None or not hasattr(tab, "last_result")) and time.time() - t0 < 60:
    app.processEvents(); time.sleep(0.02)
print(tab.status.text().replace("<br>", "\n"))
res = tab.last_result
out = res["out"]
lyr = QgsVectorLayer(f"{out}|layername=Road_Link", "x", "ogr")
f = next(lyr.getFeatures())
print("clipped road link length", round(f.geometry().length(), 1), "in_area", f["ngd_in_area"])
assert f.geometry().length() < 10
rn = QgsVectorLayer(f"{out}|layername=Road_Node", "x", "ogr")
assert rn.featureCount() == 1      # N9 not fetched with 'outside' off
t = QgsVectorLayer(f"{out}|layername=link_roadlink_nodes", "x", "ogr")
print([(g["via_field"], g["target_found"]) for g in t.getFeatures()])
t = QgsVectorLayer(f"{out}|layername=link_sp_sal_site", "x", "ogr")
print("spatial nearest:", [(g["from_key"][:8], g["to_key"][:8], g["via_field"]) for g in t.getFeatures()])
assert t.featureCount() == 1
filters = [q.get("filter", "") for p, q in CALLS if "lus-fts-site-2" in p]
assert any("description IN ('School')" in x for x in filters), filters
jo = res["joined_out"]
print("joined file:", os.path.basename(jo), sorted(res["joined"].values()))
assert jo != out and os.path.exists(jo)
for jn in res["joined"].values():
    assert QgsVectorLayer(f"{jo}|layername={jn}", "x", "ogr").isValid()
    assert not QgsVectorLayer(f"{out}|layername={jn}", "x", "ogr").isValid()
print("VARIANT OK")
