"""Joins from OS's relationship model that need OS Select+Build are shown (never ticked) in the tree."""
import os
exec(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_links.py")).read().split("# --- tree behaviour")[0])
from os_api_data_downloader.core import ngd_model as NM

feats, edges = NM.model()
api = [e for e in edges if e["avail"] == "api"]
# every join both of whose features the APIs serve is either made here or is a GB Address-only field
for e in edges:
    if e["avail"] == "sb" and NM.base_for(e["s"]) and NM.base_for(e["t"]):
        assert e["s"] == "BuiltAddress", (e["s"], e["sf"], e["t"])
assert all(e["link"] in LT.NL.LINK_BY_ID for e in api)

top = [tab.tree.topLevelItem(i) for i in range(tab.tree.topLevelItemCount())]
sbt = [t for t in top if t.data(0, LT.KIND_ROLE) == "sbtheme"][0]
names = [sbt.child(i).text(0) for i in range(sbt.childCount())]
assert any(n.startswith("Ward") for n in names) and any("Valuation Office Agency" in n for n in names), names
addr = tab.type_items[LT.NL.PLACES_ADDRESS]
grp = [addr.child(i) for i in range(addr.childCount()) if addr.child(i).data(0, LT.KIND_ROLE) == "sbgroup"][0]
assert grp.childCount() >= 20 and not (grp.flags() & Qt.ItemFlag.ItemIsUserCheckable)
edge = grp.child(0)
tab.tree.setCurrentItem(edge)
assert "Can't be made here" in tab.details.text() and "=" in tab.details.text(), tab.details.text()
tab.find.setText("council tax")
assert not sbt.isHidden() and not grp.isHidden()
tab.find.setText("")
print("SELECTBUILD OK", len(api), "joins made here,", sum(e["avail"] != "api" for e in edges), "need Select+Build or partners")
