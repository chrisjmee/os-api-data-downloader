"""Chris's 13:13 run: repeated UPRN lookups, 429s and 500s. Check the fixes against a fake that behaves badly."""
exec(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_links.py")).read().split("# --- tree behaviour")[0])
# 30 buildings in the area; each references a postal UPRN inside, an LPI-only UPRN (parent shell) and,
# for 10 of them, a UPRN just beyond the edge (in the 100 m margin). 5 UPRNs Places doesn't hold at all.
DATA["bld-fts-building-4"] = []
DATA["bld-fts-buildingpart-2"] = []
LPI_ONLY = {}
for i in range(30):
    refs = [{"uprn": 1000 + i}, {"uprn": 5000 + i}]
    if i < 10:
        refs.append({"uprn": 7000 + i})
    if i < 5:
        refs.append({"uprn": 9000 + i})
    parts = [{"buildingpartid": f"cccccccc-0000-0000-0001-{i:012d}"}]
    DATA["bld-fts-building-4"].append(({"osid": f"bbbbbbbb-0000-0000-0001-{i:012d}", "description": "House",
                                        "uprnreference": refs, "buildingpartreference": parts},
                                       poly(i * 3, 0, i * 3 + 2, 2), True))
    DATA["bld-fts-buildingpart-2"].append(({"osid": f"cccccccc-0000-0000-0001-{i:012d}", "description": "Building"},
                                           poly(i * 3, 0, i * 3 + 2, 2), False))   # all 'outside': fetched by ID
    ADDRESSES[str(1000 + i)] = {"UPRN": str(1000 + i), "ADDRESS": f"{i} A ROAD", "POSTCODE": "PR7 1AA",
                                "CLASSIFICATION_CODE": "RD04", "X_COORDINATE": i * 3 + 1.0, "Y_COORDINATE": 1.0}
    LPI_ONLY[str(5000 + i)] = {"UPRN": str(5000 + i), "ADDRESS": f"SHELL {i}", "POSTCODE_LOCATOR": "PR7 1AA",
                               "CLASSIFICATION_CODE": "PP", "X_COORDINATE": i * 3 + 1.0, "Y_COORDINATE": 1.5}
    if i < 10:
        ADDRESSES[str(7000 + i)] = {"UPRN": str(7000 + i), "ADDRESS": f"{i} EDGE ROAD", "POSTCODE": "PR7 1AB",
                                    "CLASSIFICATION_CODE": "CR", "X_COORDINATE": 150.0, "Y_COORDINATE": 50.0 + i}
calls = {"uprn": [], "bbox": 0, "ids": []}
_req = FakeTransport.request
def req(self, method, url, body=None, headers=None, retries=None):
    p = urllib.parse.urlsplit(url); q = dict(urllib.parse.parse_qsl(p.query))
    if p.path.endswith("/places/v1/bbox"):
        calls["bbox"] += 1
        x0, y0, x1, y1 = map(float, q["bbox"].split(","))
        res = []
        for u, a in ADDRESSES.items():
            if x0 <= a["X_COORDINATE"] <= x1 and y0 <= a["Y_COORDINATE"] <= y1:
                res.append({"DPA": a})
        if "LPI" in q.get("dataset", ""):
            for u, a in LPI_ONLY.items():
                if x0 <= a["X_COORDINATE"] <= x1 and y0 <= a["Y_COORDINATE"] <= y1:
                    res.append({"LPI": a})
        off = int(q.get("offset", 0))
        return 200, json.dumps({"header": {"totalresults": len(res)}, "results": res[off:off + 100]}).encode()
    if p.path.endswith("/places/v1/uprn"):
        calls["uprn"].append(q["uprn"])
        if len(calls["uprn"]) % 4 == 0:
            return 429, b"slow down"      # (retried by the transport in real life)
    if "/items" in p.path and " IN (" in q.get("filter", "") and "INTERSECTS" not in q.get("filter", ""):
        n = q["filter"].count(",") + 1
        calls["ids"].append(n)
        if n > 10:
            return 500, b"server error"   # big batches fail; smaller ones work
    return _req(self, method, url, body, headers)
FakeTransport.request = req
import os_api_data_downloader.core.transport as TR
TR.RETRIES = 0
tab = LT.LinksTab(None, FakeArea())
i = [i for i in range(tab.recipe.count()) if tab.recipe.itemText(i).startswith("1.")][0]
tab._apply_recipe(i)
tab.download()
t0 = time.time()
while (tab.task is not None or not hasattr(tab, "last_result")) and time.time() - t0 < 60:
    app.processEvents(); time.sleep(0.02)
print(tab.status.text().replace("<br>", "\n"))
print("uprn lookups:", sorted(calls["uprn"]), "bbox calls:", calls["bbox"], "id batch sizes:", calls["ids"])
assert len(calls["uprn"]) == len(set(calls["uprn"])), "a UPRN was looked up twice"
assert not any(u.startswith(("5", "7")) for u in calls["uprn"]), "shell / edge UPRNs should come from the bulk read"
assert set(calls["uprn"]) <= {str(9000 + i) for i in range(5)}
res = tab.last_result
assert res["written"]["bld-fts-buildingpart"] == 30, res["written"]
print("COST OK")
