"""Polygons selected in the Layers panel become the area for every tab, and stay it."""
import os
exec(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_links.py")).read().split("# --- tree behaviour")[0])
from qgis.core import QgsFeature, QgsVectorLayer
from qgis.gui import QgsMapCanvas
from os_api_data_downloader.gui import aoi as AOI


class Iface(QObject):
    currentLayerChanged = pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self.canvas = QgsMapCanvas()
        self.active = None

    def mapCanvas(self):
        return self.canvas

    def activeLayer(self):
        return self.active

    def setActiveLayer(self, lyr):
        self.active = lyr
        self.currentLayerChanged.emit(lyr)


def polys(name, wkts):
    lyr = QgsVectorLayer("Polygon?crs=EPSG:27700", name, "memory")
    feats = []
    for w in wkts:
        f = QgsFeature()
        f.setGeometry(QgsGeometry.fromWkt(w))
        feats.append(f)
    lyr.dataProvider().addFeatures(feats)
    QgsProject.instance().addMapLayer(lyr)
    return lyr


iface = Iface()
panel = AOI.AreaPanel(iface)
assert panel.r_view.isChecked()
sites = polys("my sites", ["POLYGON((0 0, 60 0, 60 30, 0 30, 0 0))", "POLYGON((200 200, 300 200, 300 300, 200 300, 200 200))"])
other = polys("answer", ["POLYGON((0 0, 10 0, 10 10, 0 10, 0 0))"])
iface.setActiveLayer(sites)                      # chosen in the Layers panel
assert panel.layer.currentLayer() is sites
sites.selectByIds([sites.getFeatures().__next__().id()])   # select a polygon -> it becomes the area
assert panel.r_layer.isChecked(), "selecting a polygon should make it the area"
g = panel.geometry_bng()
assert abs(g.area() - 1800) < 1e-6, g.area()
assert "1 selected polygon(s) in my sites" in panel.description()
iface.setActiveLayer(other)                      # e.g. the answer layer made active after a download
assert panel.layer.currentLayer() is sites and abs(panel.geometry_bng().area() - 1800) < 1e-6
sites.selectAll()
assert abs(panel.geometry_bng().area() - (1800 + 10000)) < 1e-6
# the links tab sends the polygon itself (not its bounding box) and clips to it
tab = LT.LinksTab(None, panel)
geom, bbox, wkt = tab._area()
assert wkt is not None and bbox == (0.0, 0.0, 300.0, 300.0)
sites.removeSelection()
try:
    panel.geometry_bng()
    raise AssertionError("no selection should not silently fall back to a bigger area")
except ValueError as ex:
    assert "my sites" in str(ex)
print("AREA OK")
