"""Make the NGD Data Linkages output easy to read: the answer layer gets friendly column names, a colour
per category (e.g. building use) and a map tip that reads like the answer; supporting layers get quiet
styles so the answer stands out."""

from __future__ import annotations

from qgis.core import (
    QgsCategorizedSymbolRenderer, QgsGraduatedSymbolRenderer, QgsRendererCategory, QgsRendererRange,
    QgsSymbol, QgsWkbTypes,
)
from qgis.PyQt.QtGui import QColor

from ..core import ngd_links as NL

PALETTE = ["#1f6fd1", "#e8743b", "#19a979", "#ed4a7b", "#945ecf", "#13a4b4", "#d6b02c", "#6f8f2f",
           "#bf399e", "#5e6b7d", "#f2a26b", "#4fb3e8"]
MAX_CATEGORIES = 12


def _symbol(layer, colour, outline="#333333"):
    sym = QgsSymbol.defaultSymbol(layer.geometryType())
    sym.setColor(QColor(colour))
    gt = QgsWkbTypes.geometryType(layer.wkbType())
    if gt == QgsWkbTypes.PolygonGeometry:
        sym.setOpacity(0.8)
        try:
            sym.symbolLayer(0).setStrokeColor(QColor(outline))
            sym.symbolLayer(0).setStrokeWidth(0.2)
        except AttributeError:
            pass
    elif gt == QgsWkbTypes.PointGeometry:
        sym.setSize(2.6)
    elif gt == QgsWkbTypes.LineGeometry:
        sym.setWidth(0.8)
    return sym


def style_answer(layer, ans):
    """Aliases, colours and a map tip for an answer layer."""
    fields = layer.fields()
    cols = [c for c in ans["columns"] if fields.indexOf(c[0]) >= 0]
    for col, alias, *_ in cols:
        layer.setFieldAlias(fields.indexOf(col), alias)
    if fields.indexOf("in_your_area") >= 0:
        layer.setFieldAlias(fields.indexOf("in_your_area"), "In your area")
        cols = cols + [("in_your_area", "In your area")]
    # colour by the answer's main category
    by = ans["colour_by"]
    idx = fields.indexOf(by)
    if idx >= 0:
        values = [f[by] for f in layer.getFeatures()]
        numeric = all(isinstance(v, (int, float)) or v is None for v in values)
        if numeric:
            ranges = []
            for i, (lo, hi, label) in enumerate(((-0.5, 0.5, "None"), (0.5, 1.5, "1"), (1.5, 3.5, "2 - 3"),
                                                 (3.5, 1e9, "4 or more"))):
                ranges.append(QgsRendererRange(lo, hi, _symbol(layer, ["#cfd6de", "#9ecae1", "#3182bd",
                                                                       "#08306b"][i]), label))
            layer.setRenderer(QgsGraduatedSymbolRenderer(by, ranges))
        else:
            counts = {}
            for v in values:
                key = v if v not in (None, "") else None
                counts[key] = counts.get(key, 0) + 1
            top = sorted((k for k in counts if k is not None), key=lambda k: -counts[k])[:MAX_CATEGORIES]
            cats = [QgsRendererCategory(v, _symbol(layer, PALETTE[i % len(PALETTE)]), f"{v} ({counts[v]:,})")
                    for i, v in enumerate(top)]
            rest = sum(n for k, n in counts.items() if k not in top)
            if rest:
                cats.append(QgsRendererCategory(None, _symbol(layer, "#bdbdbd"),
                                                f"Other / not linked ({rest:,})"))
            layer.setRenderer(QgsCategorizedSymbolRenderer(by, cats))
    # the map tip / identify title read like the answer
    # one row per column that has a value for this feature - empty ones are left out of the tip
    rows = "".join(
        f"[% CASE WHEN \"{col}\" IS NOT NULL AND to_string(\"{col}\") <> '' THEN "
        f"'<tr><td style=\"color:#666;padding-right:8px\">{alias.replace(chr(39), chr(39) * 2)}</td><td>' || "
        f"to_string(\"{col}\") || '</td></tr>' END %]"
        for col, alias, *_ in cols if not alias.endswith(" ID"))
    layer.setMapTipTemplate(f"<b>{ans['title'].split(' (')[0]}</b><table>{rows}</table>")
    first = cols[0][0] if cols else None
    if first:
        layer.setDisplayExpression(f'"{first}"')
    layer.triggerRepaint()


QUIET = {
    "lus-fts-site": ("#00000000", "#2e7d32", True),            # outline only, dashed green
    "bld-fts-building": ("#c9c9c9", "#7a7a7a", False),
    "bld-fts-buildingpart": ("#00000000", "#9e9e9e", False),
    "lnd-fts-land": ("#e8f1e0", "#c5d6b8", False),
    "wtr-fts-water": ("#cfe6f7", "#8fbfe0", False),
}


def style_supporting(layer, base):
    """Quiet styles for the layers an answer was built from."""
    gt = QgsWkbTypes.geometryType(layer.wkbType())
    if base in QUIET and gt == QgsWkbTypes.PolygonGeometry:
        fill, line, dashed = QUIET[base]
        sym = QgsSymbol.defaultSymbol(layer.geometryType())
        sl = sym.symbolLayer(0)
        sl.setFillColor(QColor(fill))
        sl.setStrokeColor(QColor(line))
        sl.setStrokeWidth(0.5 if dashed else 0.2)
        if dashed:
            from qgis.PyQt.QtCore import Qt
            sl.setStrokeStyle(Qt.PenStyle.DashLine)
        layer.renderer().setSymbol(sym)
    elif base == NL.PLACES_ADDRESS and gt == QgsWkbTypes.PointGeometry:
        sym = _symbol(layer, "#444444")
        sym.setSize(1.6)
        layer.renderer().setSymbol(sym)
    layer.triggerRepaint()
