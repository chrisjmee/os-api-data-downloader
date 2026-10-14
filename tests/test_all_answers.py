import os
exec(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_links.py")).read().split("# --- tree behaviour")[0])
from os_api_data_downloader.core import ngd_links as NL2
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
