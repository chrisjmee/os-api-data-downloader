"""Attribute filters, built the same way as the OS Data Hub's "Advanced Filter Options":
rules (attribute · operator · value) and groups of rules, each group matching *all*
(AND) or *any* (OR) of its rules.

A filter is a plain dict, so it is easy to keep, copy and test::

    {"join": "AND", "items": [
        {"attr": "description", "op": "=", "value": "Building"},
        {"join": "OR", "items": [{"attr": "height", "op": ">", "value": "15"}, ...]},
    ]}

``to_cql`` turns it into CQL text for OS NGD API - Features (``filter``,
``filter-lang=cql-text``), combined with the area filter by the API client.

The attribute lists come from the API: ``parse_queryables`` reads OS NGD's
``/collections/{id}/queryables`` (JSON Schema, with allowed values as ``enum``).
"""

from __future__ import annotations

import re

# (code, label, needs a value)
OPERATORS = (
    ("=", "is", True),
    ("<>", "is not", True),
    ("IN", "is one of", True),
    ("LIKE%", "contains", True),
    ("LIKE^", "starts with", True),
    ("LIKE$", "ends with", True),
    (">", "is greater than", True),
    (">=", "is at least", True),
    ("<", "is less than", True),
    ("<=", "is at most", True),
    ("BETWEEN", "is between", True),
    ("NULL", "is empty", False),
    ("NOTNULL", "is not empty", False),
)
OP_LABEL = {c: lbl for c, lbl, _ in OPERATORS}
NEEDS_VALUE = {c: nv for c, _, nv in OPERATORS}
TEXT_ONLY = {"LIKE%", "LIKE^", "LIKE$"}
ORDERED = {">", ">=", "<", "<=", "BETWEEN"}

NUMERIC = {"integer", "number"}


class FilterError(ValueError):
    pass


# ---------------------------------------------------------------- attribute lists
def parse_queryables(doc):
    """OS NGD queryables (JSON Schema) -> [{'name','title','type','enum'}] sorted by title.
    Geometry and array attributes are left out (use the area for the geometry)."""
    out = []
    for name, spec in (doc.get("properties") or {}).items():
        spec = spec or {}
        typ = spec.get("type") or ""
        if isinstance(typ, list):       # the real API writes e.g. ["integer", "null"] for nullable attributes
            typ = next((t for t in typ if t and t != "null"), "")
        if not isinstance(typ, str):
            typ = ""
        fmt = spec.get("format") or ""
        if name.lower() in ("geometry", "geom", "shape") or "geometry" in fmt or spec.get("$ref", "").find("geo") >= 0:
            continue
        if typ in ("array", "object"):
            continue
        if fmt in ("date", "date-time"):
            typ = fmt
        out.append({"name": name, "title": spec.get("title") or name, "type": typ or "string",
                    "enum": [str(v) for v in spec.get("enum") or []],
                    "description": spec.get("description") or ""})
    return sorted(out, key=lambda a: a["title"].lower())


# ---------------------------------------------------------------- helpers
def is_group(item):
    return isinstance(item, dict) and "items" in item


def rules(flt):
    """All the rules in a filter, flattened."""
    for it in (flt or {}).get("items", []):
        if is_group(it):
            yield from rules(it)
        else:
            yield it


def is_empty(flt):
    return not any(True for _ in rules(flt))


def _split_list(value):
    """A list of values: given as a list (kept whole - OS values can contain commas, e.g. 'Ambulance, Fire
    And Police Station'), or typed: separated by ; or new lines when either is used, otherwise by commas."""
    if isinstance(value, (list, tuple, set)):
        parts = [str(p).strip() for p in value if str(p).strip()]
    elif re.search(r"[;\n]", str(value)):
        parts = [p.strip() for p in re.split(r"[;\n]", str(value)) if p.strip()]
    else:
        parts = [p.strip() for p in str(value).split(",") if p.strip()]
    if not parts:
        raise FilterError("Enter at least one value (separate several values with commas).")
    return parts


def split_values(value):
    """The values typed or picked for 'is one of' (no error when empty)."""
    try:
        return _split_list(value)
    except FilterError:
        return []


def _check_value(attr, typ, op, value):
    if typ in NUMERIC:
        try:
            float(value)
        except (TypeError, ValueError):
            raise FilterError(f"{attr}: '{value}' isn't a number.") from None
    elif typ == "boolean":
        if str(value).strip().lower() not in ("true", "false"):
            raise FilterError(f"{attr}: use true or false.")
    elif typ == "date" and op in ORDERED | {"=", "<>", "IN"}:
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", str(value).strip()):
            raise FilterError(f"{attr}: write dates as YYYY-MM-DD.")


def _values(rule, types):
    """Validated value(s) for a rule as a list of strings."""
    attr, op = rule["attr"], rule["op"]
    typ = (types or {}).get(attr, "string")
    if not isinstance(typ, str):
        typ = "string"
    if op not in NEEDS_VALUE:
        raise FilterError(f"Unknown operator {op!r}.")
    if not NEEDS_VALUE[op]:
        return [], typ
    raw = rule.get("value")
    if raw is None or str(raw).strip() == "":
        raise FilterError(f"{attr} {OP_LABEL[op]} …: enter a value.")
    if op == "IN":
        vals = _split_list(raw)
    elif op == "BETWEEN":
        vals = _split_list(raw)
        if len(vals) != 2:
            raise FilterError(f"{attr} is between: enter two values, e.g. 5, 20.")
    else:
        vals = [str(raw).strip()]
    if op in TEXT_ONLY and typ not in ("string", ""):
        raise FilterError(f"{attr}: '{OP_LABEL[op]}' only works on text attributes.")
    for v in vals:
        _check_value(attr, typ, op, v)
    return vals, typ


# ---------------------------------------------------------------- CQL (OS NGD)
def _cql_ident(name):
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name):
        raise FilterError(f"Unexpected attribute name {name!r}.")
    return name


def _cql_lit(value, typ):
    if typ in NUMERIC:
        return str(value).strip()
    if typ == "boolean":
        return str(value).strip().lower()
    return "'" + str(value).replace("'", "''") + "'"


# characters OS's API mishandles inside a quoted value: a doubled '' is rejected, and a comma or bracket
# inside IN (...) is taken as the end of the value ("Ambulance, Fire And Police Station" becomes
# 'Ambulance' + 'Fire And Police Station', HTTP 400)
_AWKWARD = "',()"


def _cql_like(value):
    # % and _ are CQL wildcards - a user's literal ones are kept as typed (rare in OS data). Each awkward
    # character becomes the one-character wildcard _ , which matches it exactly in practice.
    v = str(value)
    for ch in _AWKWARD:
        v = v.replace(ch, "_")
    return v


def _has_quote(value, typ):
    return typ not in NUMERIC and typ != "boolean" and any(ch in str(value) for ch in _AWKWARD)


def _rule_cql(rule, types):
    vals, typ = _values(rule, types)
    a, op = _cql_ident(rule["attr"]), rule["op"]
    if op == "NULL":
        return f"{a} IS NULL"
    if op == "NOTNULL":
        return f"{a} IS NOT NULL"
    if op == "IN":
        # OS's API checks values against its list of allowed values before un-doubling quotes, so
        # "Children''s Nursery" is rejected (HTTP 400). Values with an apostrophe are matched with LIKE and a
        # one-character wildcard instead: description LIKE 'Children_s Nursery'.
        plain = [v for v in vals if not _has_quote(v, typ)]
        quoted = [v for v in vals if _has_quote(v, typ)]
        parts = [f"{a} IN ({', '.join(_cql_lit(v, typ) for v in plain)})"] if plain else []
        parts += [f"{a} LIKE '{_cql_like(v)}'" for v in quoted]
        return parts[0] if len(parts) == 1 else "(" + " OR ".join(parts) + ")"
    if op == "BETWEEN":
        return f"{a} BETWEEN {_cql_lit(vals[0], typ)} AND {_cql_lit(vals[1], typ)}"
    if op in TEXT_ONLY:
        v = _cql_like(vals[0])
        pat = {"LIKE%": f"%{v}%", "LIKE^": f"{v}%", "LIKE$": f"%{v}"}[op]
        return f"{a} LIKE '{pat}'"
    if op in ("=", "<>") and _has_quote(vals[0], typ):
        return f"{a} {'NOT ' if op == '<>' else ''}LIKE '{_cql_like(vals[0])}'"
    return f"{a} {op} {_cql_lit(vals[0], typ)}"


def to_cql(flt, types=None, _top=True):
    """CQL text for a filter, or '' when it has no rules."""
    parts = []
    for it in (flt or {}).get("items", []):
        if is_group(it):
            sub = to_cql(it, types, _top=False)
            if sub:
                parts.append(sub)
        else:
            parts.append(_rule_cql(it, types))
    if not parts:
        return ""
    join = " OR " if (flt.get("join") or "AND").upper() == "OR" else " AND "
    text = join.join(parts)
    return text if (_top or len(parts) == 1) else f"({text})"


# ---------------------------------------------------------------- plain-English summary
def describe(flt, titles=None, _top=True):
    titles = titles or {}
    parts = []
    for it in (flt or {}).get("items", []):
        if is_group(it):
            sub = describe(it, titles, _top=False)
            if sub:
                parts.append(sub)
        else:
            name = titles.get(it["attr"], it["attr"])
            val = "" if not NEEDS_VALUE.get(it["op"], True) else f" {it.get('value', '')}"
            if it["op"] == "BETWEEN":
                v = [p.strip() for p in str(it.get("value", "")).split(",")]
                val = f" {v[0]} and {v[-1]}"
            parts.append(f"{name} {OP_LABEL.get(it['op'], it['op'])}{val}")
    if not parts:
        return ""
    join = " or " if (flt.get("join") or "AND").upper() == "OR" else " and "
    text = join.join(parts)
    return text if (_top or len(parts) == 1) else f"({text})"


# ---------------------------------------------------------------- values found in the area
def value_text(v):
    """How a value is shown in the value list (and written into a rule)."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        if v.is_integer():
            return str(int(v))
        return f"{round(v, 3):.3f}".rstrip("0").rstrip(".")
    return str(v)


def _sort_key(item):
    v = item[0]
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return (0, float(v), "")
    return (1, 0.0, str(v).casefold())


def collect_values(features, max_distinct=1000):
    """Distinct attribute values in a set of GeoJSON features, for the value drop-downs.

    Returns {attribute: [(text, count), ...]} sorted numerically for numbers and
    alphabetically otherwise. Empty (null) values, lists and objects are skipped; at most
    ``max_distinct`` values are kept per attribute."""
    counts = {}
    for f in features:
        for k, v in (f.get("properties") or {}).items():
            if v is None or isinstance(v, (dict, list)) or v == "":
                continue
            c = counts.setdefault(k, {})
            if v in c:
                c[v] += 1
            elif len(c) < max_distinct:
                c[v] = 1
    out = {}
    for k, c in counts.items():
        merged = {}
        for v, n in sorted(c.items(), key=_sort_key):
            t = value_text(v)
            merged[t] = merged.get(t, 0) + n
        out[k] = list(merged.items())
    return out
