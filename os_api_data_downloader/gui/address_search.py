"""One search box for addresses and places.

Type or paste an address, postcode, UPRN or place name and press Enter; the
matches drop down in one list:
  * OS NGD Named Areas (OS NGD API - Features, Geographic Names) - choosing one
    zooms to it and makes its boundary the area of interest;
  * addresses (OS Places API) - choosing one zooms to it.
Place names are only looked up for text without numbers (a house number,
postcode or UPRN means an address), so an address search costs no extra
transaction.
"""

from __future__ import annotations

import json

from qgis.core import (
    QgsApplication, QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsFeature, QgsField, QgsFields,
    QgsFillSymbol, QgsGeometry, QgsPointXY, QgsProject, QgsVectorLayer,
)
from qgis.gui import QgsVertexMarker
from qgis.PyQt.QtCore import Qt, QVariant
from qgis.PyQt.QtGui import QColor, QGuiApplication
from qgis.PyQt.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from ..core import names as NM
from ..core import places as P
from ..core.transport import QgisTransport
from . import settings as S

BNG = QgsCoordinateReferenceSystem("EPSG:27700")


def label(r):
    if r.get("type") == "area":
        name = r["name"] + (f", {r['where']}" if r.get("where") else "")
        size = NM.size_text(r.get("area_m2"))
        bits = [name] + [b for b in (r.get("kind"), size) if b]
        return "◼ " + " · ".join(bits) + " (named area)"
    return f"{r['address']}  ·  UPRN {r['uprn']}"


def looks_like_place(query):
    return not any(ch.isdigit() for ch in query)


class AddressSearch(QWidget):
    def __init__(self, iface, area=None, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.area = area                     # the AreaPanel: a chosen named area becomes the area of interest
        self.results, self.current, self.marker = [], None, None
        self.layer_ids = {}
        self._names = None
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        self.box = QComboBox()
        self.box.setEditable(True)
        self.box.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.box.setMaxVisibleItems(15)
        self.box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.box.lineEdit().setPlaceholderText("Address, postcode, UPRN or place name, then Enter")
        self.box.lineEdit().setClearButtonEnabled(True)
        self.box.lineEdit().returnPressed.connect(self.search)
        self.box.activated.connect(self.select)
        self.box.setCompleter(None)
        go = QPushButton("Search")
        go.clicked.connect(lambda: self.search())
        row.addWidget(self.box, 1)
        row.addWidget(go)
        v.addLayout(row)
        self.details = QLabel()
        self.details.setWordWrap(True)
        self.details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        v.addWidget(self.details)
        row = QHBoxLayout()
        self.zoom_btn = QPushButton("Zoom to")
        self.copy_btn = QPushButton("Copy UPRN")
        self.copy_addr_btn = QPushButton("Copy address")
        self.add_btn = QPushButton("Add to map")
        self.buttons = [self.zoom_btn, self.copy_btn, self.copy_addr_btn, self.add_btn]
        for b, slot in zip(self.buttons, (self.zoom, self.copy_uprn, self.copy_address, self.add_to_map)):
            b.clicked.connect(slot)
            b.setEnabled(False)
            row.addWidget(b)
        v.addLayout(row)
        if area is not None:
            area.changed.connect(self._area_changed)

    def _area_changed(self):
        r = self.current
        if r is not None and r["type"] == "area" and not self.area.r_place.isChecked():
            where = f", {r['where']}" if r.get("where") else ""
            self.details.setText(f"<b>{r['name']}{where}</b> · {r['kind'] or 'named area'} - no longer the area "
                                 "of interest (choose it again, or tick 'Named area', to use it).")

    # ---------------------------------------------------------------- search
    def search(self, text=None):
        raw = text if isinstance(text, str) else self.box.currentText()
        i = self.box.findText(raw, Qt.MatchFlag.MatchExactly)
        if raw and i >= 0:          # already in the list: just pick it
            self.select(i)
            return
        query = P.tidy_query(raw)
        if not query:
            return
        key = S.load_api_key()
        if not key:
            self.details.setText("✖ Add an API key on the ⚙ Settings tab first.")
            return
        kind = P.classify_query(query)[0]
        areas, addresses, notes, used = [], [], [], 0
        QgsApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            if kind == "text" and looks_like_place(query):
                try:
                    if self._names is None or self._names.api_key != key:
                        self._names = NM.NgdNamesClient(key, transport=QgisTransport())
                    start = self._names.budget.used
                    areas = [dict(r, type="area") for r in self._names.find(query)]
                    used += self._names.budget.used - start
                except Exception as ex:
                    notes.append(f"Named areas not searched: {str(ex)[:120]}")
            try:
                client = P.PlacesClient(key, transport=QgisTransport(), include_dpa=True, include_lpi=True)
                kind, addresses = client.search(query)
                used += client.budget.used
            except Exception as ex:
                notes.append(f"Addresses not searched: {str(ex)[:120]}")
        finally:
            QgsApplication.restoreOverrideCursor()
        self.show_results(areas + [dict(r, type="address") for r in addresses], query, used, kind, notes)

    def show_results(self, rows, typed, used=0, kind="text", notes=()):
        self.results, self.current = list(rows), None
        self.clear_marker()
        self.box.blockSignals(True)
        self.box.clear()
        for r in self.results:
            self.box.addItem(label(r))
        self.box.setCurrentIndex(-1)
        self.box.setEditText(typed)
        self.box.blockSignals(False)
        n_area = sum(1 for r in self.results if r["type"] == "area")
        n_addr = len(self.results) - n_area
        parts = []
        if n_area:
            parts.append(f"{n_area} named area{'s' if n_area != 1 else ''}")
        if n_addr:
            what = {"postcode": " in this postcode", "uprn": " for this UPRN"}.get(kind, "")
            parts.append(f"{n_addr} address{'es' if n_addr != 1 else ''}{what}")
        head = (f"<b>{' and '.join(parts)}</b>" + (" - choose one from the list" if len(self.results) > 1 else "")
                if parts else "<span style='color:#d73027'>Nothing found</span>")
        self.details.setText(head + f" · {used} transaction(s)" +
                             "".join(f"<br><span style='color:#b35806'>{n}</span>" for n in notes))
        self._buttons()
        if len(self.results) == 1:
            self.select(0)
        elif self.results:
            self.box.showPopup()

    def select(self, i):
        if not 0 <= i < len(self.results):
            return
        r = self.current = self.results[i]
        self.box.blockSignals(True)
        self.box.setCurrentIndex(i)
        self.box.blockSignals(False)
        self.box.lineEdit().setCursorPosition(0)
        self.clear_marker()
        if r["type"] == "area":
            geom = self.area.use_place(r) if self.area is not None else None
            if geom is None:
                self.details.setText("That named area has no boundary to use.")
            else:
                where = f", {r['where']}" if r.get("where") else ""
                self.details.setText(
                    f"<span style='font-size:14px'><b>{r['name']}{where}</b></span> · {r['kind'] or 'named area'}<br>"
                    f"<b>Now the area of interest</b> ({geom.area() / 1e6:,.2f} km²) - every tab downloads for "
                    "this boundary.")
        else:
            cls = r["classification"]
            self.details.setText(
                f"<span style='font-size:14px'><b>{r['address']}</b></span><br>UPRN <b>{r['uprn']}</b> · "
                f"postcode <b>{r['postcode'] or '–'}</b><br>{P.class_name(cls)} - {r['classification_desc'] or cls} "
                f"({cls}) · {'Royal Mail (DPA)' if r['dataset'] == 'DPA' else 'Council (LPI)'} · "
                f"E {r['easting']:.0f}, N {r['northing']:.0f}")
            self.zoom()
        self._buttons()

    def _buttons(self):
        r = self.current
        self.zoom_btn.setEnabled(r is not None)
        self.add_btn.setEnabled(r is not None)
        self.copy_btn.setEnabled(r is not None and r["type"] == "address")
        self.copy_addr_btn.setEnabled(r is not None and r["type"] == "address")

    # ---------------------------------------------------------------- map
    def _to_map(self, x, y):
        canvas = self.iface.mapCanvas()
        tr = QgsCoordinateTransform(BNG, canvas.mapSettings().destinationCrs(), QgsProject.instance())
        return tr.transform(QgsPointXY(x, y))

    def clear_marker(self):
        if self.marker is not None:
            self.iface.mapCanvas().scene().removeItem(self.marker)
            self.marker = None

    def _area_geometry(self, r):
        from osgeo import ogr
        g = ogr.CreateGeometryFromJson(json.dumps(r["geometry"])) if r.get("geometry") else None
        return QgsGeometry.fromWkt(g.ExportToWkt()) if g is not None else None

    def zoom(self):
        r = self.current
        if r is None:
            return
        canvas = self.iface.mapCanvas()
        if r["type"] == "area":
            geom = self._area_geometry(r)
            if geom is not None:
                tr = QgsCoordinateTransform(BNG, canvas.mapSettings().destinationCrs(), QgsProject.instance())
                ext = tr.transformBoundingBox(geom.boundingBox())
                ext.scale(1.1)
                canvas.setExtent(ext)
                canvas.refresh()
            return
        if r["easting"] is None:
            return
        p = self._to_map(r["easting"], r["northing"])
        canvas.setCenter(p)
        if canvas.scale() > 2500:
            canvas.zoomScale(1250)
        canvas.refresh()
        self.clear_marker()
        self.marker = QgsVertexMarker(canvas)
        self.marker.setCenter(p)
        self.marker.setColor(QColor("#e31a1c"))
        self.marker.setIconSize(16)
        self.marker.setIconType(QgsVertexMarker.IconType.ICON_CIRCLE)
        self.marker.setPenWidth(3)

    def copy_uprn(self):
        if self.current and self.current["type"] == "address":
            QGuiApplication.clipboard().setText(self.current["uprn"])
            self.iface.messageBar().pushSuccess("OS API Data Downloader", f"Copied UPRN {self.current['uprn']}")

    def copy_address(self):
        if self.current and self.current["type"] == "address":
            QGuiApplication.clipboard().setText(self.current["address"])
            self.iface.messageBar().pushSuccess("OS API Data Downloader", "Copied the address")

    def _layer(self, kind, name=None):
        """Addresses share one layer; each named area gets its own layer, called after the area."""
        layer = QgsProject.instance().mapLayer(self.layer_ids.get(kind, "")) if kind != "area" else None
        if layer is None:
            if kind == "area":
                layer = QgsVectorLayer("MultiPolygon?crs=EPSG:27700", name or "Named area", "memory")
                names = ("name", "type", "osid", "area_ha")
                # see-through: a faint fill (10% opacity) and a solid outline, so the map shows through
                layer.renderer().setSymbol(QgsFillSymbol.createSimple(
                    {"color": "227,26,28,26", "outline_color": "227,26,28,255", "outline_width": "0.8",
                     "outline_style": "solid"}))
            else:
                layer = QgsVectorLayer("Point?crs=EPSG:27700", "OS Places addresses found", "memory")
                names = ("uprn", "address", "postcode", "classification", "classification_desc", "dataset")
            fields = QgsFields()
            for n in names:
                fields.append(QgsField(n, QVariant.Double if n == "area_ha" else QVariant.String))
            layer.dataProvider().addAttributes(fields)
            layer.updateFields()
            QgsProject.instance().addMapLayer(layer)
            if kind != "area":
                self.layer_ids[kind] = layer.id()
        return layer

    def add_to_map(self):
        r = self.current
        if r is None:
            return
        if r["type"] == "area":
            geom = self._area_geometry(r)
            if geom is None:
                return
            layer = self._layer("area", r["name"])
            f = QgsFeature(layer.fields())
            geom.convertToMultiType()
            f.setAttributes([r["name"], r["kind"], r.get("id"), round((r.get("area_m2") or geom.area()) / 1e4, 2)])
            f.setGeometry(geom)
        else:
            layer = self._layer("address")
            f = QgsFeature(layer.fields())
            f.setAttributes([r[n] for n in ("uprn", "address", "postcode", "classification", "classification_desc",
                                            "dataset")])
            f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(r["easting"], r["northing"])))
        layer.dataProvider().addFeatures([f])
        layer.updateExtents()
        layer.triggerRepaint()
        self.iface.messageBar().pushSuccess("OS API Data Downloader", f"Added to '{layer.name()}'")

    def cleanup(self):
        self.clear_marker()
