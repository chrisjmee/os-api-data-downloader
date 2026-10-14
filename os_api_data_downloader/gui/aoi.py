"""The area panel shared by every tab: which area to get data for, and how to clip to it.

Area: the current map view, a window (rectangle) drawn on the map, a drawn polygon,
polygons selected in a layer, or an OS NGD Named Area found by name (its real boundary). Clip: cut features at the edge, or keep whole
features that touch the area.
"""

from __future__ import annotations

import json

from qgis.core import (
    QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsGeometry, QgsMapLayerProxyModel,
    QgsProject,
)
from qgis.gui import QgsMapLayerComboBox
from qgis.PyQt.QtCore import pyqtSignal
from qgis.PyQt.QtWidgets import (
    QButtonGroup, QComboBox, QGridLayout, QHBoxLayout, QLabel, QPushButton, QRadioButton, QVBoxLayout,
    QWidget,
)


from . import layers as L
from . import settings as S
from .maptools import _POLY, PolygonTool, QgsMapToolExtent, make_band

try:
    _POLYGONS = QgsMapLayerProxyModel.Filter.PolygonLayer
except AttributeError:  # QGIS < 3.34
    _POLYGONS = QgsMapLayerProxyModel.PolygonLayer

BNG = QgsCoordinateReferenceSystem("EPSG:27700")
MAX_FILTER_WKT = 4000   # keep GET URLs a sensible length; exact clipping happens locally
CLIP_MODES = [("Cut features at the edge of the area", "clip"),
              ("Keep whole features that touch the area", "intersects")]


class AreaPanel(QWidget):
    changed = pyqtSignal()

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.drawn = None
        self.drawn_kind = None
        self.band = make_band(iface.mapCanvas())
        self._tool = None
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        grid = QGridLayout()
        self.group = QButtonGroup(self)
        self.r_view = QRadioButton("Map view")
        self.r_window = QRadioButton("Window")
        self.r_poly = QRadioButton("Polygon")
        self.r_layer = QRadioButton("Selected polygons in")
        self.r_place = QRadioButton("Named area")
        self.named = None          # (BNG geometry, description) of the chosen place
        for i, r in enumerate((self.r_view, self.r_window, self.r_poly, self.r_layer, self.r_place)):
            self.group.addButton(r, i)
            r.toggled.connect(lambda on, r=r: on and self._choice_changed(r))
        self.r_view.setChecked(True)
        self.draw_window_btn = QPushButton("Draw window")
        self.draw_window_btn.clicked.connect(self.draw_window)
        self.draw_poly_btn = QPushButton("Draw polygon")
        self.draw_poly_btn.clicked.connect(self.draw_polygon)
        self.clear_btn = QPushButton("Clear")
        self.clear_btn.clicked.connect(self.clear)
        self.layer = QgsMapLayerComboBox()
        self.layer.setFilters(_POLYGONS)
        self.layer.layerChanged.connect(lambda _: self.r_layer.isChecked() and self.changed.emit())
        grid.addWidget(self.r_view, 0, 0)
        grid.addWidget(self.r_window, 1, 0)
        grid.addWidget(self.draw_window_btn, 1, 1)
        grid.addWidget(self.r_poly, 2, 0)
        grid.addWidget(self.draw_poly_btn, 2, 1)
        grid.addWidget(self.clear_btn, 1, 2, 2, 1)
        grid.addWidget(self.r_layer, 3, 0)
        grid.addWidget(self.layer, 3, 1, 1, 2)
        self.place_label = QLabel("<i>search for a place name at the top</i>")
        self.place_label.setWordWrap(True)
        grid.addWidget(self.r_place, 4, 0)
        grid.addWidget(self.place_label, 4, 1, 1, 2)
        v.addLayout(grid)
        row = QHBoxLayout()
        row.addWidget(QLabel("Clip"))
        self.clip_mode = QComboBox()
        for label, mode in CLIP_MODES:
            self.clip_mode.addItem(label, mode)
        i = self.clip_mode.findData(S.get("clip_mode"))
        self.clip_mode.setCurrentIndex(max(0, i))
        self.clip_mode.currentIndexChanged.connect(lambda _: S.set_("clip_mode", self.clip_mode.currentData()))
        row.addWidget(self.clip_mode, 1)
        v.addLayout(row)
        self.size = QLabel()
        self.size.setStyleSheet("color: palette(mid);")
        v.addWidget(self.size)
        iface.mapCanvas().extentsChanged.connect(self._update_size)
        self.changed.connect(self._update_size)
        self._update_size()

    # ---------------------------------------------------------------- drawing
    def _choice_changed(self, radio):
        if radio is self.r_window and self.drawn_kind != "window":
            self.draw_window()
        elif radio is self.r_poly and self.drawn_kind != "polygon":
            self.draw_polygon()
        elif radio is self.r_place:
            self._unset_tool()
            if self.named is None:
                self.band.reset(_POLY)
                self.size.setText("Type a place name in the search box at the top and choose a named area.")
            else:
                self.band.setToGeometry(self.named[0], BNG)
        elif radio in (self.r_view, self.r_layer):
            if self._tool is not None:
                self.iface.mapCanvas().unsetMapTool(self._tool)
                self._tool = None
            self._clear_band()
        self.changed.emit()

    def _unset_tool(self):
        if self._tool is not None:
            self.iface.mapCanvas().unsetMapTool(self._tool)
            self._tool = None

    # ---------------------------------------------------------------- named areas
    def use_place(self, r):
        """Make an OS NGD Named Area (from the search at the top) the area of interest. Returns its geometry."""
        geom = None
        if r.get("geometry"):
            from osgeo import ogr
            g = ogr.CreateGeometryFromJson(json.dumps(r["geometry"]))
            geom = QgsGeometry.fromWkt(g.ExportToWkt()) if g is not None else None
        if geom is None or geom.isEmpty():
            self.size.setText("That named area has no boundary to use.")
            return None
        self.named = (geom, f"{r['name']} ({r['kind']})" if r["kind"] else r["name"])
        self.place_label.setText(f"<b>{self.named[1]}</b>")
        self.r_place.blockSignals(True)
        self.r_place.setChecked(True)
        self.r_place.blockSignals(False)
        self._unset_tool()
        self.drawn, self.drawn_kind = None, None
        self.band.setToGeometry(geom, BNG)
        canvas = self.iface.mapCanvas()
        tr = QgsCoordinateTransform(BNG, canvas.mapSettings().destinationCrs(), QgsProject.instance())
        ext = tr.transformBoundingBox(geom.boundingBox())
        ext.scale(1.1)
        canvas.setExtent(ext)
        canvas.refresh()
        self.changed.emit()
        return geom

    def draw_window(self):
        self._tool = QgsMapToolExtent(self.iface.mapCanvas())
        self._tool.extentChanged.connect(lambda r: self._set(QgsGeometry.fromRect(r), "window"))
        self.iface.mapCanvas().setMapTool(self._tool)
        self.size.setText("Drag a rectangle on the map…")

    def draw_polygon(self):
        self._tool = PolygonTool(self.iface.mapCanvas())
        self._tool.finished.connect(lambda g: self._set(g, "polygon"))
        self.iface.mapCanvas().setMapTool(self._tool)
        self.size.setText("Click to add corners on the map, right-click to finish…")

    def _set(self, geom, kind):
        if geom is None or geom.isEmpty() or geom.area() <= 0:
            return
        self.drawn, self.drawn_kind = geom, kind
        self.band.setToGeometry(geom, None)
        radio = self.r_window if kind == "window" else self.r_poly
        radio.blockSignals(True)
        radio.setChecked(True)
        radio.blockSignals(False)
        if self._tool is not None:
            if hasattr(self._tool, "clearRubberBand"):
                self._tool.clearRubberBand()
            self.iface.mapCanvas().unsetMapTool(self._tool)
            self._tool = None
        self.changed.emit()

    def _clear_band(self):
        self.band.reset(_POLY)
        self.drawn, self.drawn_kind = None, None
        self.iface.mapCanvas().refresh()

    def clear(self):
        """Remove the drawn window/polygon from the map and go back to the map view."""
        self._clear_band()
        self.r_view.setChecked(True)
        self.changed.emit()

    # ---------------------------------------------------------------- the area
    def geometry_bng(self):
        canvas = self.iface.mapCanvas()
        if self.r_view.isChecked():
            return QgsGeometry.fromRect(L.canvas_extent_bng(canvas))
        if self.r_place.isChecked():
            if self.named is None:
                raise ValueError("Search for a place name at the top and choose a named area first.")
            return QgsGeometry(self.named[0])
        if self.r_window.isChecked() or self.r_poly.isChecked():
            if self.drawn is None:
                raise ValueError("Draw a window or polygon on the map first.")
            return L.geometry_to_bng(self.drawn, canvas.mapSettings().destinationCrs())
        lyr = self.layer.currentLayer()
        if lyr is None or not lyr.selectedFeatureCount():
            raise ValueError("Select one or more polygons in the chosen layer.")
        geoms = [f.geometry() for f in lyr.selectedFeatures() if f.hasGeometry()]
        return L.geometry_to_bng(QgsGeometry.unaryUnion(geoms), lyr.crs())

    def clip(self):
        return self.clip_mode.currentData()

    def description(self):
        if self.r_view.isChecked():
            return "map view"
        if self.r_window.isChecked():
            return "drawn window"
        if self.r_poly.isChecked():
            return "drawn polygon"
        if self.r_place.isChecked() and self.named:
            return self.named[1]
        lyr = self.layer.currentLayer()
        return f"{lyr.selectedFeatureCount()} selected polygon(s) in {lyr.name()}" if lyr else "selection"

    def _update_size(self):
        try:
            g = self.geometry_bng()
        except ValueError as ex:
            self.size.setText(str(ex))
            return
        except Exception:
            return
        km2 = g.area() / 1e6
        self.size.setText(f"Area: {km2:,.3f} km²" if km2 < 10 else f"Area: {km2:,.1f} km²")

    @staticmethod
    def filter_wkt(geom):
        """A WKT short enough for a GET request: simplified outward (results are clipped locally,
        so the filter may be a little bigger than the real shape, never smaller); falls back to the
        convex hull, then the bounding box."""
        wkt = geom.asWkt(1)
        tol = 5.0
        while len(wkt) > MAX_FILTER_WKT and tol < 5000:
            wkt = geom.buffer(tol, 2).simplify(tol).asWkt(1)
            tol *= 2
        if len(wkt) > MAX_FILTER_WKT:
            wkt = geom.convexHull().asWkt(1)
        if len(wkt) > MAX_FILTER_WKT:
            wkt = QgsGeometry.fromRect(geom.boundingBox()).asWkt(1)
        return wkt

    def cleanup(self):
        self.band.reset(_POLY)
        self.iface.mapCanvas().extentsChanged.disconnect(self._update_size)
