import os
"""The eight showcase quick picks each build their answer layer."""
exec(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_links.py")).read().split("# --- tree behaviour")[0])
from os_api_data_downloader.core import ngd_links as NL2
DATA["asu-gbpcd-postcodeunitarea-1"] = [({"postcode": "PR7 1AA"}, poly(0, 0, 100, 100), True)]
ADDRESSES["100"]["USRN"] = 123
PN1, PN2 = "dddddddd-0000-0000-0000-000000000001", "dddddddd-0000-0000-0000-000000000002"
DATA["trn-ntwk-pathlink-3"] = [({"osid": "dddddddd-0000-0000-0000-000000000010", "description": "Path",
                                 "startnode": PN1, "endnode": PN2, "geometry_length_m": 80.0},
                                line((5, 5), (85, 5)), True)]
DATA["trn-ntwk-pathnode-1"] = [({"osid": PN1}, pt(5, 5), True), ({"osid": PN2}, pt(85, 5), True)]
DATA["trn-ntwk-connectinglink-1"] = [({"osid": "dddddddd-0000-0000-0000-000000000020", "pathnodeid": PN2},
                                      line((85, 5), (95, 95)), True)]
DATA["gnm-fts-crowdsourcednamepoint-1"] = [({"osid": "eeeeeeee-0000-0000-0000-000000000001", "name1_text": "The Old School",
                                             "description": "Building", "matcheduprn": 100, "matchedosid": S1},
                                            pt(20, 20), True)]
ok = []
for k in range(len(NL2.RECIPES)):
    tab = LT.LinksTab(None, FakeArea())
    i = [i for i in range(tab.recipe.count()) if tab.recipe.itemData(i) == ("q", k)][0]
    tab._apply_recipe(i)
    tab.download()
    t0 = time.time()
    while (tab.task is not None or not hasattr(tab, "last_result")) and time.time() - t0 < 60:
        app.processEvents(); time.sleep(0.02)
    lyr = getattr(tab, "last_answer_layer", None)
    name = NL2.RECIPES[k]["name"]
    if lyr is None:
        print("NO ANSWER", name, [n[-400:] for n in tab.last_result["notes"] if "answer" in n][:1]); continue
    cols = [f.name() for f in lyr.fields()]
    f = next(lyr.getFeatures(), None)
    print(name, "->", lyr.featureCount(), "rows")
    if f:
        print("   ", {c: f[c] for c in cols if f[c] not in (None, "", 0) and not c.endswith("osid")})
    ok.append(name)
print("ANSWERS", len(ok), "of", len(NL2.RECIPES))
assert len(ok) == len(NL2.RECIPES)
print("SHOWCASE OK")
