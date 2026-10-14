"""Every OS enumeration value makes a filter OS's API accepts: no doubled quotes, and no comma or bracket
inside IN (...) (OS splits 'Ambulance, Fire And Police Station' there - HTTP 400)."""
import csv
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from os_api_data_downloader.core import filters as F, ngd_search as S  # noqa: E402

rows = list(csv.DictReader(open(os.path.join(ROOT, "os_api_data_downloader", "data", "ngd_feature_types.csv"))))
n = 0
for r in rows:
    vals = [v for v in r["values"].split("|") if v]
    if not r["attr"] or not vals:
        continue
    cql = S.cql_for_values({"name": r["attr"], "type": "string"}, vals)
    inside = re.findall(r"IN \((.*?)\)(?: OR|$|\))", cql)
    for part in inside:
        for v in re.findall(r"'([^']*)'", part):
            assert not any(ch in v for ch in ",()'"), (r["base_id"], v)
    assert "''" not in cql, (r["base_id"], cql)
    # each value is still asked for once
    for v in vals:
        assert f"'{v}'" in cql or F._cql_like(v) in cql, (r["base_id"], v)
    n += len(vals)
assert F.split_values("School; Ambulance, Fire And Police Station") == ["School", "Ambulance, Fire And Police Station"]
assert F.split_values("School, Hospital") == ["School", "Hospital"]
print(f"FILTERS OK ({n} values)")
