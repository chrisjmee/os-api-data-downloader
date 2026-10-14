"""A postcode (or site) reaching beyond the drawn area is counted in full: the rest is read over its extent."""
import os
exec(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_links.py")).read().split("# --- tree behaviour")[0])
from os_api_data_downloader.core import ngd_links as NL2

DATA.clear()
DATA["asu-gbpcd-postcodeunitarea-1"] = [({"postcode": "PR7 1JA"}, poly(0, 0, 300, 100), True)]
DATA["bld-fts-building-4"] = [
    ({"osid": "bbbbbbbb-0000-0000-0000-00000000000%d" % i, "description": "House", "connectivity": "Terraced",
      "uprnreference": [{"uprn": 1000 + i}]}, poly(i * 30, 10, i * 30 + 25, 40), True) for i in range(10)]
ADDRESSES.clear()
for i in range(10):
    ADDRESSES[str(1000 + i)] = {"UPRN": str(1000 + i), "ADDRESS": f"{i} HIGH ST", "POSTCODE": "PR7 1JA",
                                "CLASSIFICATION_CODE": "RD06", "CLASSIFICATION_CODE_DESCRIPTION": "Terraced",
                                "X_COORDINATE": i * 30 + 12.0, "Y_COORDINATE": 25.0, "STATUS": "APPROVED"}
ADDRESSES["2000"] = {"UPRN": "2000", "ADDRESS": "0 HIGH ST (BLOCK)", "POSTCODE": "PR7 1JA",
                     "CLASSIFICATION_CODE": "PP", "CLASSIFICATION_CODE_DESCRIPTION": "Property Shell",
                     "X_COORDINATE": 13.0, "Y_COORDINATE": 26.0, "STATUS": "APPROVED"}
DATA["bld-fts-building-4"][0][0]["uprnreference"].append({"uprn": 2000})


def _bbox_of(g):
    xs, ys = [], []

    def walk(c):
        if c and isinstance(c[0], (int, float)):
            xs.append(c[0]); ys.append(c[1])
        else:
            for x in c:
                walk(x)
    walk(g["coordinates"])
    return min(xs), min(ys), max(xs), max(ys)


def _hits(box, g):
    a = _bbox_of(g)
    return not (a[2] < box[0] or a[0] > box[2] or a[3] < box[1] or a[1] > box[3])


class BoxTransport(FakeTransport):
    """Answers by the bbox asked for, like the real API."""
    def request(self, method, url, body=None, headers=None):
        parts = urllib.parse.urlsplit(url)
        q = dict(urllib.parse.parse_qsl(parts.query))
        m = re.search(r"/collections/([^/]+)/items$", parts.path)
        if m and q.get("bbox") and "IN (" not in q.get("filter", ""):
            box = [float(v) for v in q["bbox"].split(",")[:4]]
            rows = [r for r in DATA.get(m.group(1), []) if _hits(box, r[1])]
            off, lim = int(q.get("offset", 0)), int(q.get("limit", 100))
            feats = [{"type": "Feature", "id": p.get("osid", p.get("postcode")), "properties": p, "geometry": g}
                     for p, g, _ in rows[off:off + lim]]
            return 200, json.dumps({"type": "FeatureCollection", "features": feats, "links": []}).encode()
        if parts.path.endswith("/places/v1/bbox"):
            box = [float(v) for v in q["bbox"].split(",")]
            res = [{"DPA": a} for a in ADDRESSES.values()
                   if box[0] <= a["X_COORDINATE"] <= box[2] and box[1] <= a["Y_COORDINATE"] <= box[3]]
            off = int(q.get("offset", 0))
            return 200, json.dumps({"header": {"totalresults": len(res)}, "results": res[off:off + 100]}).encode()
        return super().request(method, url, body, headers)


LT.QgisTransport = BoxTransport
tab = LT.LinksTab(None, FakeArea())          # the area is 0..100 x 0..100: only 4 of the 10 houses
k = [i for i, r in enumerate(NL2.SHOWCASE_RECIPES) if r["key"] == "postcode"][0]
i = [i for i in range(tab.recipe.count()) if tab.recipe.itemData(i) == ("s", k)][0]
tab._apply_recipe(i)
tab.download()
t0 = time.time()
while (tab.task is not None or not hasattr(tab, "last_result")) and time.time() - t0 < 60:
    app.processEvents(); time.sleep(0.02)
lyr = tab.last_answer_layer
f = next(lyr.getFeatures())
print({c: f[c] for c in ("postcode", "addresses", "address_mix", "buildings", "residential_addresses")})
print([n for n in tab.last_result["notes"] if "beyond" in n])
assert f["addresses"] == 10 and "Parent" not in f["address_mix"] and f["buildings"] == 10, f["addresses"]
print("WIDEN OK")
