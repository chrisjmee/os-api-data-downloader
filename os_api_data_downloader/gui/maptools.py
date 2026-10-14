"""Draw-a-rectangle / draw-a-polygon map tools."""

from __future__ import annotations

from qgis.core import Qgis, QgsGeometry, QgsPointXY
from qgis.gui import QgsMapTool, QgsMapToolExtent, QgsRubberBand
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QColor

try:
    _POLY = Qgis.GeometryType.Polygon
except AttributeError:  # QGIS < 3.30
    from qgis.core import QgsWkbTypes
    _POLY = QgsWkbTypes.PolygonGeometry


def make_band(canvas):
    band = QgsRubberBand(canvas, _POLY)
    band.setColor(QColor(227, 26, 28, 60))
    band.setStrokeColor(QColor("#e31a1c"))
    band.setWidth(2)
    return band


class PolygonTool(QgsMapTool):
    """Left-click to add vertices, right-click (or double-click) to finish, Esc to cancel."""
    finished = pyqtSignal(object)  # QgsGeometry in canvas CRS

    def __init__(self, canvas):
        super().__init__(canvas)
        self.points = []
        self.band = make_band(canvas)

    def canvasPressEvent(self, e):
        if e.button() == Qt.MouseButton.RightButton:
            self._finish()
            return
        self.points.append(self.toMapCoordinates(e.pos()))
        self._redraw()

    def canvasDoubleClickEvent(self, e):
        self._finish()

    def canvasMoveEvent(self, e):
        if self.points:
            self._redraw(self.toMapCoordinates(e.pos()))

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape:
            self.reset()
            self.canvas().unsetMapTool(self)

    def _redraw(self, floating=None):
        pts = list(self.points) + ([floating] if floating else [])
        self.band.setToGeometry(QgsGeometry.fromPolygonXY([[QgsPointXY(p) for p in pts]]), None)

    def _finish(self):
        geom = QgsGeometry.fromPolygonXY([[QgsPointXY(p) for p in self.points]]) if len(self.points) >= 3 else None
        self.reset()   # the tool's own sketch outline - the dock keeps its own highlight
        self.canvas().unsetMapTool(self)
        if geom is not None:
            self.finished.emit(geom)

    def reset(self):
        self.points = []
        self.band.reset(_POLY)

    def deactivate(self):
        self.reset()
        super().deactivate()


__all__ = ["PolygonTool", "QgsMapToolExtent", "make_band"]
