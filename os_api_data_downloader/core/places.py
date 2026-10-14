"""OS Places API - every address in an area, by classification.

* ``GET /search/places/v1/bbox``: at most 1 km² per request and 100 results per
  page (paged with ``offset``); every request is one OS Data Hub transaction.
* So an area is split into 1 km National Grid cells; only cells touching the
  area are requested, and results are de-duplicated and clipped to the shape.
* Classifications (AddressBase classification scheme, at any level: primary
  R = Residential, secondary RD = Dwelling, tertiary RD04 = Terraced,
  quaternary CE01HE = Higher Education) can be filtered on the server with
  ``fq`` - fewer pages, so fewer transactions - and are checked again locally.
  A very long choice is sent to the server as broader codes (kept to
  ``MAX_FQ_TERMS``) and narrowed locally.
"""

from __future__ import annotations

import json
import math
import re
import time

from .budget import Budget, BudgetExceeded
from .classification_codes import CODES as SCHEME
from .transport import HttpError, build_url, default_transport

PLACES_BASE = "https://api.os.uk/search/places/v1"
MAX_PAGE = 100
CELL = 1000.0

# AddressBase classification scheme: primary class -> (name, {secondary code: name})
CLASSES = {
    "R": ("Residential", {"RD": "Dwelling", "RH": "House in multiple occupation", "RI": "Residential institution",
                          "RB": "Ancillary building", "RC": "Car park space", "RG": "Garage"}),
    "C": ("Commercial", {"CA": "Agricultural", "CB": "Ancillary building", "CC": "Community services",
                         "CE": "Education", "CH": "Hotel / guest house", "CI": "Industrial", "CL": "Leisure",
                         "CM": "Medical", "CN": "Animal centre", "CO": "Office", "CR": "Retail",
                         "CS": "Storage land", "CT": "Transport", "CU": "Utility", "CX": "Emergency / rescue",
                         "CZ": "Information"}),
    "X": ("Dual use (residential and commercial)", {}),
    "L": ("Land", {"LA": "Agricultural", "LB": "Ancillary building", "LC": "Burial ground", "LD": "Development",
                   "LF": "Forestry", "LL": "Allotment", "LM": "Amenity", "LO": "Open space", "LP": "Park",
                   "LU": "Unused land", "LW": "Water"}),
    "M": ("Military", {"MA": "Army", "MB": "Ancillary building", "MF": "Air force", "MG": "Defence estates",
                       "MN": "Navy"}),
    "Z": ("Object of interest", {"ZA": "Archaeological dig site", "ZM": "Monument", "ZS": "Stately home",
                                 "ZU": "Underground feature", "ZV": "Other underground feature",
                                 "ZW": "Place of worship"}),
    "O": ("Other (OS only)", {}),
    "P": ("Parent shell", {"PP": "Property shell", "PS": "Street record"}),
    "U": ("Unclassified", {"UC": "Awaiting classification", "UP": "Pending investigation"}),
}
# the secondary classes OS uses only for its own records (Other) come from the scheme
for _c, _n in SCHEME.items():
    if len(_c) == 2 and _c[0] in CLASSES and _c not in CLASSES[_c[0]][1]:
        CLASSES[_c[0]][1][_c] = _n


def parent(code):
    """CE01HE -> CE01 -> CE -> C -> None."""
    return {6: code[:4], 4: code[:2], 2: code[:1]}.get(len(code))


def _level_key(c):
    return (list(CLASSES).index(c[0]) if c[:1] in CLASSES else 99, c)


def tree_parent(code):
    """The code's parent in the tree. The scheme writes '99' for 'no tertiary level', so e.g.
    ZW99CH (Church) sits straight under ZW (Place of worship) - there is no ZW99."""
    p = parent(code)
    while p and p not in SCHEME and not (len(p) == 1 and p in CLASSES):
        p = parent(p)
    return p


CHILDREN = {}
for _c in sorted(SCHEME, key=_level_key):
    if tree_parent(_c):
        CHILDREN.setdefault(tree_parent(_c), []).append(_c)
for _p, (_n, _subs) in CLASSES.items():        # secondaries we name that the scheme might not list
    for _s in _subs:
        if _s not in CHILDREN.get(_p, []):
            CHILDREN.setdefault(_p, []).append(_s)
MAX_FQ_TERMS = 30


def code_name(code):
    """The name for any code: our short names for the first two levels, the scheme's below that."""
    code = (code or "").strip().upper()
    if len(code) == 1 and code in CLASSES:
        return CLASSES[code][0]
    if len(code) == 2 and code[:1] in CLASSES and code in CLASSES[code[0]][1]:
        return CLASSES[code[0]][1][code]
    return SCHEME.get(code, code)


def code_label(code):
    """'Residential' for a primary, 'RD04 Terraced' below that."""
    return code_name(code) if len(code) == 1 else f"{code} {code_name(code)}"


CLASS_COLOURS = {"R": "#e8a33d", "C": "#4575b4", "X": "#9e5bb5", "L": "#5aae61", "M": "#7f7f7f",
                 "Z": "#d73027", "O": "#bababa", "P": "#c7b17d", "U": "#e0e0e0"}


def class_name(code):
    code = (code or "").strip().upper()
    if not code:
        return "Not classified"
    main = CLASSES.get(code[0])
    return main[0] if main else code[0]


def sub_name(code):
    code = (code or "").strip().upper()
    main = CLASSES.get(code[:1])
    if main and code[:2] in main[1]:
        return f"{code[:2]} - {main[1][code[:2]]}"
    return f"{code[:2]} - {class_name(code)}" if code else "Not classified"


def wanted_codes(selected):
    """``selected``: set of codes ticked at any level ('R', 'CE', 'RD04', 'CE01HE'). Returns the smallest
    list of prefixes that covers them (a code replaces everything below it), or None for everything."""
    selected = {s.upper() for s in selected}
    if all(p in selected for p in CLASSES):
        return None
    out = []

    def walk(c):
        if c in selected:
            out.append(c)
        else:
            for k in CHILDREN.get(c, []):
                walk(k)
    for p in CLASSES:
        walk(p)
    # codes we don't know (e.g. new to the scheme) are still honoured
    known = set(out)
    out += sorted(c for c in selected if c not in known and not any(c.startswith(k) for k in known)
                  and not any(c.startswith(x) for x in selected if x != c and x in SCHEME))
    return out


def server_prefixes(prefixes, max_terms=MAX_FQ_TERMS):
    """At most ``max_terms`` codes for the server filter: the most detailed codes are replaced by their
    parents until the list is short enough. Results are narrowed to ``prefixes`` locally anyway."""
    if prefixes is None:
        return None
    terms = list(dict.fromkeys(prefixes))
    while len(terms) > max_terms:
        longest = max(len(t) for t in terms)
        if longest <= 1:
            break
        terms = list(dict.fromkeys(parent(t) if len(t) == longest and parent(t) else t for t in terms))
        terms = [t for t in terms if not any(t != o and t.startswith(o) for o in terms)]
    return terms


def fq_for(prefixes):
    """Server-side filter: codes separated by spaces (matched as alternatives)."""
    if not prefixes:
        return None
    return " ".join(f"CLASSIFICATION_CODE:{p}*" for p in prefixes)


def matches(code, prefixes):
    if prefixes is None:
        return True
    code = (code or "").upper()
    return any(code.startswith(p) for p in prefixes)


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _uprn(v):
    s = re.sub(r"\D", "", str(v or ""))
    return s.lstrip("0") or s


def to_row(rec, dataset):
    """A DPA or LPI result -> flat row."""
    lpi = dataset == "LPI"
    code = rec.get("CLASSIFICATION_CODE") or ""
    return {
        "uprn": _uprn(rec.get("UPRN")), "address": rec.get("ADDRESS") or "",
        "postcode": (rec.get("POSTCODE_LOCATOR") if lpi else rec.get("POSTCODE")) or rec.get("POSTCODE") or "",
        "organisation": (rec.get("ORGANISATION") if lpi else rec.get("ORGANISATION_NAME")) or "",
        "classification": code, "classification_desc": rec.get("CLASSIFICATION_CODE_DESCRIPTION") or "",
        "class_group": class_name(code), "dataset": dataset,
        "status": rec.get("STATUS") or "", "logical_status": str(rec.get("LOGICAL_STATUS_CODE") or
                                                                rec.get("LPI_LOGICAL_STATUS_CODE") or ""),
        "parent_uprn": _uprn(rec.get("PARENT_UPRN")) if rec.get("PARENT_UPRN") else "",
        "usrn": str(rec.get("USRN") or ""), "udprn": str(rec.get("UDPRN") or ""),
        "toid": rec.get("TOPOGRAPHY_LAYER_TOID") or "",
        "local_custodian": rec.get("LOCAL_CUSTODIAN_CODE_DESCRIPTION") or "",
        "easting": _num(rec.get("X_COORDINATE")), "northing": _num(rec.get("Y_COORDINATE")),
    }


def grid_cells(xmin, ymin, xmax, ymax, cell=CELL):
    """1 km National Grid cells covering the extent (clipped to it)."""
    x0 = math.floor(xmin / cell) * cell
    y0 = math.floor(ymin / cell) * cell
    cells = []
    y = y0
    while y < ymax:
        x = x0
        while x < xmax:
            cells.append((max(x, xmin), max(y, ymin), min(x + cell, xmax), min(y + cell, ymax)))
            x += cell
        y += cell
    return [c for c in cells if c[2] > c[0] and c[3] > c[1]]


class PlacesError(Exception):
    pass


class PlacesClient:
    def __init__(self, api_key, transport=None, budget=None, include_dpa=True, include_lpi=False,
                 base=PLACES_BASE, max_retries=4, sleep=time.sleep):
        if not api_key:
            raise PlacesError("No OS Data Hub API key configured.")
        self.api_key = api_key
        self.transport = transport or default_transport()
        self.budget = budget or Budget()
        self.include_dpa, self.include_lpi = include_dpa, include_lpi
        if not include_dpa and not include_lpi:
            self.include_dpa = self.include_lpi = True
        self.base = base
        self.max_retries = max_retries
        self._sleep = sleep

    def _call(self, endpoint, params):
        params = dict(params, key=self.api_key, output_srs="EPSG:27700")
        url = build_url(f"{self.base}/{endpoint}", params)
        self.budget.spend(1)   # retries on 429 / 5xx happen in the transport and aren't counted twice
        status, content = self.transport.request("GET", url)
        text = content.decode("utf-8", "replace") if isinstance(content, bytes) else str(content)
        if status == 200:
            return json.loads(text) if text else {}
        if status in (401, 403):
            raise PlacesError("OS Places rejected the key (HTTP %s) - add 'OS Places API' to the key's "
                              "OS Data Hub project." % status)
        raise HttpError(status, text, url)

    @property
    def dataset(self):
        return ",".join(d for d, on in (("DPA", self.include_dpa), ("LPI", self.include_lpi)) if on)

    def bbox(self, xmin, ymin, xmax, ymax, fq=None):
        """All results in a box of at most 1 km² -> list of rows (DPA and/or LPI)."""
        params = {"bbox": f"{xmin:.2f},{ymin:.2f},{xmax:.2f},{ymax:.2f}", "srs": "EPSG:27700",
                  "dataset": self.dataset, "fq": fq or None}
        rows, offset = [], 0
        while True:
            data = self._call("bbox", dict(params, maxresults=MAX_PAGE, offset=offset))
            page = data.get("results") or []
            for r in page:
                if self.include_dpa and r.get("DPA"):
                    rows.append(to_row(r["DPA"], "DPA"))
                if self.include_lpi and r.get("LPI"):
                    rows.append(to_row(r["LPI"], "LPI"))
            total = (data.get("header") or {}).get("totalresults", 0)
            offset += MAX_PAGE
            if not page or offset >= total:
                return rows


def fetch_area(client, cells, prefixes=None, contains=None, one_per_uprn=True, progress=None,
               is_cancelled=None):
    """Every address in the cells -> (rows, info). ``prefixes``: classification codes wanted (None = all);
    ``contains(x, y)`` clips to the real shape; ``one_per_uprn`` keeps one row per UPRN (Royal Mail
    address preferred) when both DPA and LPI are requested."""
    fq = fq_for(server_prefixes(prefixes))
    out, index = [], {}
    info = {"cells": len(cells), "cells_done": 0, "requests": 0, "truncated": False, "cancelled": False}
    start = client.budget.used
    for i, cell in enumerate(cells):
        if is_cancelled and is_cancelled():
            info["cancelled"] = True
            break
        try:
            rows = client.bbox(*cell, fq=fq)
        except BudgetExceeded:
            info["truncated"] = True
            break
        for r in rows:
            if not matches(r["classification"], prefixes):
                continue
            x, y = r["easting"], r["northing"]
            if x is None or y is None or (contains and not contains(x, y)):
                continue
            key = r["uprn"] if one_per_uprn else (r["uprn"], r["dataset"])
            if key in index:
                j = index[key]
                if one_per_uprn and r["dataset"] == "DPA" and out[j]["dataset"] != "DPA":
                    out[j] = r
                continue
            index[key] = len(out)
            out.append(r)
        info["cells_done"] = i + 1
        if progress:
            progress(100.0 * (i + 1) / max(1, len(cells)), f"Cell {i + 1:,}/{len(cells):,} - {len(out):,} addresses")
    info["requests"] = client.budget.used - start
    return out, info


def split_rows(rows, how):
    """{layer name: rows}. how: 'one' | 'class' (primary) | 'subclass' (secondary) | 'code' (full code)."""
    if how == "one":
        return {"addresses": rows} if rows else {}
    groups = {}
    for r in rows:
        code = r["classification"]
        if how == "class":
            name = f"{class_name(code)} ({code[:1]})" if code else "Not classified"
        elif how == "code":
            name = f"{code} - {code_name(code)}" if code else "Not classified"
        else:
            name = sub_name(code)
        groups.setdefault(name, []).append(r)
    order = list(CLASSES)
    return dict(sorted(groups.items(), key=lambda kv: (order.index(kv[1][0]["classification"][:1])
                                                       if kv[1][0]["classification"][:1] in order else 99, kv[0])))


# ---------------------------------------------------------------- address search
_POSTCODE_RE = re.compile(r"^([A-Z]{1,2}\d[A-Z\d]?)\s*(\d[A-Z]{2})$")


def tidy_query(text):
    """A pasted multi-line address -> one line with commas; whitespace tidied."""
    parts = [p.strip(" ,;\t") for p in re.split(r"[\r\n\t;]+", text or "")]
    return re.sub(r"\s+", " ", ", ".join(p for p in parts if p)).strip()


def classify_query(text):
    """('postcode', 'PR7 1AB') | ('uprn', '100010012345') | ('text', text)."""
    t = tidy_query(text)
    compact = t.upper().replace(" ", "")
    if compact.isdigit() and 5 <= len(compact) <= 12:
        return "uprn", compact.lstrip("0") or compact
    m = _POSTCODE_RE.match(t.upper())
    if m:
        return "postcode", f"{m.group(1)} {m.group(2)}"
    return "text", t


def _search(self, endpoint, params, max_pages=1):
    rows, offset = [], 0
    for _ in range(max_pages):
        data = self._call(endpoint, dict(params, dataset=self.dataset, maxresults=MAX_PAGE if max_pages > 1 else
                                         params.get("maxresults", 20), offset=offset))
        page = data.get("results") or []
        for r in page:
            if self.include_dpa and r.get("DPA"):
                rows.append(dict(to_row(r["DPA"], "DPA"), match=r["DPA"].get("MATCH")))
            if self.include_lpi and r.get("LPI"):
                rows.append(dict(to_row(r["LPI"], "LPI"), match=r["LPI"].get("MATCH")))
        total = (data.get("header") or {}).get("totalresults", 0)
        offset += MAX_PAGE
        if not page or offset >= total:
            break
    return rows


def search(self, text, maxresults=20, fq=None):
    """Address, postcode or UPRN -> (kind, rows). Free text uses /find (best match first);
    a postcode lists every address in it; a UPRN goes straight to that address."""
    kind, value = classify_query(text)
    if kind == "uprn":
        rows = _search(self, "uprn", {"uprn": value})
    elif kind == "postcode":
        rows = _search(self, "postcode", {"postcode": value}, max_pages=10)
    else:
        rows = _search(self, "find", {"query": value, "maxresults": maxresults, "fq": fq or None})
        rows.sort(key=lambda r: -(r.get("match") or 0))
    seen, out = set(), []
    for r in rows:                     # one row per UPRN, the Royal Mail address first
        if r["uprn"] in seen:
            continue
        seen.add(r["uprn"])
        out.append(r)
    return kind, out


PlacesClient.search = search
