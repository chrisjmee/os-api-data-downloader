"""OS Places tab: every address in the area, chosen by classification
(Residential, Commercial, ...), as one layer or a layer per classification."""

from __future__ import annotations

import datetime as _dt
import os

from qgis.core import (
    QgsCategorizedSymbolRenderer, QgsCoordinateReferenceSystem, QgsCoordinateTransformContext, QgsFeature, QgsField,
    QgsFields, QgsGeometry, QgsMarkerSymbol, QgsPoint, QgsPointXY, QgsProject, QgsRectangle, QgsRendererCategory,
    QgsSingleSymbolRenderer,
    QgsVectorFileWriter, QgsVectorLayer, QgsWkbTypes,
)
from qgis.PyQt.QtCore import Qt, QTimer, QVariant
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QGridLayout, QLabel, QLineEdit, QMessageBox, QProgressBar, QPushButton,
    QSpinBox, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from ..core import places as P
from ..core.budget import Budget
from ..core.transport import QgisTransport
from . import clipping as C
from . import settings as S
from .tasks import FunctionTask, start

DATASETS = [("Royal Mail postal (DPA)", (True, False)),
            ("Council, incl. land and objects (LPI)", (False, True)),
            ("Both (DPA and LPI)", (True, True))]
SPLITS = [("One per classification (Residential…)", "class"),
          ("One per sub-class (RD Dwelling…)", "subclass"),
          ("One per full classification (RD04 Terraced…)", "code"),
          ("All in one layer", "one")]
FIELDS = [("uprn", "str"), ("address", "str"), ("postcode", "str"), ("organisation", "str"),
          ("classification", "str"), ("classification_desc", "str"), ("class_group", "str"), ("dataset", "str"),
          ("status", "str"), ("logical_status", "str"), ("parent_uprn", "str"), ("usrn", "str"), ("udprn", "str"),
          ("toid", "str"), ("local_custodian", "str"), ("easting", "float"), ("northing", "float")]
BNG = QgsCoordinateReferenceSystem("EPSG:27700")
try:
    from qgis.core import Qgis
    _POINT = Qgis.WkbType.Point
except AttributeError:  # QGIS < 3.30
    _POINT = QgsWkbTypes.Point

try:
    _CHECKABLE = Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsAutoTristate
except AttributeError:  # older Qt
    _CHECKABLE = Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsTristate


def _fields():
    f = QgsFields()
    for name, kind in FIELDS:
        f.append(QgsField(name, QVariant.Double if kind == "float" else QVariant.String))
    return f


def write_layers(groups, out_path):
    """{layer name: rows} -> GeoPackage point layers (EPSG:27700). Returns {layer name: (table, count)}."""
    fields = _fields()
    written = {}
    for name, rows in groups.items():
        table = C._safe_name(name)
        opts = QgsVectorFileWriter.SaveVectorOptions()
        opts.driverName = "GPKG"
        opts.layerName = table
        opts.fileEncoding = "UTF-8"
        if os.path.exists(out_path):
            opts.actionOnExistingFile = QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteLayer
        w = QgsVectorFileWriter.create(out_path, fields, _POINT, BNG,
                                       QgsCoordinateTransformContext(), opts)
        if w.hasError() != QgsVectorFileWriter.WriterError.NoError:
            raise RuntimeError(w.errorMessage())
        for r in rows:
            f = QgsFeature(fields)
            f.setAttributes([r[n] for n, _ in FIELDS])
            f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(r["easting"], r["northing"])))
            w.addFeature(f)
        del w
        written[name] = (table, len(rows), sorted({(r["classification"] or "?")[:1] for r in rows}))
    return written


# clearly different colours for layers split by sub-class or code (strong colours first, then lighter ones)
PALETTE = ["#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b", "#e377c2", "#17becf", "#bcbd22",
           "#7f7f7f", "#393b79", "#e7ba52", "#637939", "#ad494a", "#7b4173", "#3182bd", "#fd8d3c", "#74c476",
           "#9e9ac8", "#f768a1"]


def distinct_colours(n):
    """``n`` colours that are easy to tell apart: the palette, then evenly spread hues (golden angle)."""
    out = list(PALETTE[:n])
    i = 0
    while len(out) < n:
        hue = int((i * 137.508) % 360)
        sat, val = ((230, 200), (160, 235), (255, 150))[i % 3]
        out.append(QColor.fromHsv(hue, sat, val).name())
        i += 1
    return out


def _marker(code, colour=None):
    return QgsMarkerSymbol.createSimple({"name": "circle", "color": colour or P.CLASS_COLOURS.get(code, "#999999"),
                                         "size": "2.2", "outline_color": "#333333", "outline_width": "0.15"})


def style_by_class(layer, present, colour=None):
    """Colour by main classification, listing only the classifications actually in this layer
    (a layer holding one classification gets a single symbol). ``colour`` gives the whole layer
    one colour of its own (used when a download is split into several layers)."""
    if colour:
        layer.setRenderer(QgsSingleSymbolRenderer(_marker(present[0] if present else "", colour)))
        return
    if len(present) == 1:
        layer.setRenderer(QgsSingleSymbolRenderer(_marker(present[0])))
        return
    order = list(P.CLASSES)
    cats = [QgsRendererCategory(code, _marker(code), f"{P.CLASSES[code][0]} ({code})" if code in P.CLASSES else code)
            for code in sorted(present, key=lambda c: order.index(c) if c in order else 99)]
    layer.setRenderer(QgsCategorizedSymbolRenderer('left("classification", 1)', cats))


class PlacesTab(QWidget):
    def __init__(self, iface, area, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.area = area
        self.task = None
        v = QVBoxLayout(self)

        self.find = QLineEdit()
        self.find.setPlaceholderText("Find a classification, e.g. terraced, school, CE01…")
        self.find.setClearButtonEnabled(True)
        self.find.textChanged.connect(self._find)
        v.addWidget(self.find)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Classifications to include"])
        self.tree.setMinimumHeight(240)
        self.tree.setToolTip("Every AddressBase classification, down to tertiary (RD04 Terraced) and quaternary "
                             "(CE01HE Higher Education) level. Expand a class to choose part of it.")
        self.tree.blockSignals(True)
        for code in P.CLASSES:
            self.tree.addTopLevelItem(self._make_item(code))
        self.tree.blockSignals(False)
        self._summary_timer = QTimer(self)
        self._summary_timer.setSingleShot(True)
        self._summary_timer.setInterval(50)      # one update after a parent ticks all its children
        self._summary_timer.timeout.connect(self._update_summary)
        self.tree.itemChanged.connect(lambda *_: self._summary_timer.start())
        v.addWidget(self.tree, 1)
        row = QGridLayout()
        for i, (text, codes) in enumerate((("All", None), ("Residential", {"R"}), ("Commercial", {"C"}),
                                           ("None", set()), ("Res. + commercial", {"R", "C", "X"}))):
            b = QPushButton(text)
            b.setToolTip("Tick just these classifications")
            b.clicked.connect(lambda _=False, c=codes: self.tick(c))
            row.addWidget(b, i // 4, i % 4, 1, 1 if i < 4 else 2)
        v.addLayout(row)
        self.picked = QLabel()
        self.picked.setWordWrap(True)
        v.addWidget(self.picked)

        f = QFormLayout()
        self.dataset = QComboBox()
        for label, _ in DATASETS:
            self.dataset.addItem(label)
        self.dataset.currentIndexChanged.connect(lambda _: self._update_summary())
        f.addRow("Addresses", self.dataset)
        self.split = QComboBox()
        for label, how in SPLITS:
            self.split.addItem(label, how)
        f.addRow("Layers", self.split)
        self.one_per_uprn = QCheckBox("One point per UPRN")
        self.one_per_uprn.setChecked(True)
        f.addRow(self.one_per_uprn)
        self.limit = QSpinBox()
        self.limit.setRange(0, 10_000_000)
        self.limit.setSingleStep(500)
        self.limit.setSpecialValueText("No limit")
        self.limit.setSuffix(" transactions")
        f.addRow("Stop after", self.limit)
        v.addLayout(f)
        self.estimate = QLabel()
        self.estimate.setWordWrap(True)
        v.addWidget(self.estimate)
        self.go = QPushButton("Get addresses for my area")
        self.go.setStyleSheet("font-weight: bold;")
        self.go.clicked.connect(self.download)
        v.addWidget(self.go)
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        v.addWidget(self.progress)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        v.addWidget(self.status)
        area.changed.connect(self._update_summary)
        iface.mapCanvas().extentsChanged.connect(self._update_summary)
        self.refresh_settings()
        self._update_summary()

    def refresh_settings(self):
        self.limit.setValue(S.get("hard_limit"))

    # ---------------------------------------------------------------- classifications
    def _make_item(self, code):
        label = f"{P.code_name(code)} ({code})" if len(code) == 1 else f"{code} - {P.code_name(code)}"
        it = QTreeWidgetItem([label])
        it.setData(0, Qt.ItemDataRole.UserRole, code)
        it.setToolTip(0, label)
        kids = P.CHILDREN.get(code, [])
        it.setFlags(it.flags() | (_CHECKABLE if kids else Qt.ItemFlag.ItemIsUserCheckable))
        for k in kids:
            it.addChild(self._make_item(k))
        it.setCheckState(0, Qt.CheckState.Checked)
        return it

    def _items(self):
        """(primary item, [secondary items]) - kept for callers that only need two levels."""
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            yield top, [top.child(j) for j in range(top.childCount())]

    def _walk(self, item=None):
        items = [self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())] if item is None \
            else [item.child(j) for j in range(item.childCount())]
        for it in items:
            yield it
            yield from self._walk(it)

    def item(self, code):
        return next((it for it in self._walk() if it.data(0, Qt.ItemDataRole.UserRole) == code), None)

    def set_code(self, code, on=True):
        """Tick or untick one code at any level (and everything below it)."""
        it = self.item(code)
        if it is not None:
            it.setCheckState(0, Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)

    def _set_all(self, it, state):
        it.setCheckState(0, state)
        for j in range(it.childCount()):
            self._set_all(it.child(j), state)

    def tick(self, codes):
        """codes: None = everything, otherwise the codes (at any level) to tick; the rest are unticked."""
        self.tree.blockSignals(True)
        for top, _ in self._items():
            self._set_all(top, Qt.CheckState.Checked if codes is None else Qt.CheckState.Unchecked)
        if codes:
            for it in self._walk():
                if it.data(0, Qt.ItemDataRole.UserRole) in codes:
                    self._set_all(it, Qt.CheckState.Checked)
            # parents of what was ticked show as partly ticked
            for top, _ in self._items():
                self._refresh_state(top)
        self.tree.blockSignals(False)
        self._update_summary()

    def _refresh_state(self, it):
        if it.childCount() == 0:
            return it.checkState(0)
        states = {self._refresh_state(it.child(j)) for j in range(it.childCount())}
        state = states.pop() if len(states) == 1 else Qt.CheckState.PartiallyChecked
        it.setCheckState(0, state)
        return state

    def selected(self):
        """Codes ticked at the highest level possible: a fully ticked class stands for everything below it."""
        out = set()

        def walk(it):
            if it.checkState(0) == Qt.CheckState.Checked:
                out.add(it.data(0, Qt.ItemDataRole.UserRole))
            elif it.checkState(0) == Qt.CheckState.PartiallyChecked:
                for j in range(it.childCount()):
                    walk(it.child(j))
        for top, _ in self._items():
            walk(top)
        return out

    def _find(self, text):
        """Shows the classifications whose code or name contains the text (and their parents), expanded."""
        t = (text or "").strip().lower()

        def walk(it):
            own = not t or t in it.text(0).lower()
            kids = [walk(it.child(j)) for j in range(it.childCount())]
            show = own or any(kids)
            it.setHidden(not show)
            if t and any(kids):
                it.setExpanded(True)
            if own and t:    # a match shows all of its own children too
                for j in range(it.childCount()):
                    self._unhide(it.child(j))
            return show
        for i in range(self.tree.topLevelItemCount()):
            walk(self.tree.topLevelItem(i))
        if not t:
            self.tree.collapseAll()

    def _unhide(self, it):
        it.setHidden(False)
        for j in range(it.childCount()):
            self._unhide(it.child(j))

    def prefixes(self):
        return P.wanted_codes(self.selected())

    def _cells(self, geom):
        bb = geom.boundingBox()
        return P.grid_cells(bb.xMinimum(), bb.yMinimum(), bb.xMaximum(), bb.yMaximum()) if not bb.isEmpty() else [], bb

    def _update_summary(self):
        pre = self.prefixes()
        if pre is None:
            self.picked.setText("All classifications.")
        elif not pre:
            self.picked.setText("<span style='color:#d73027'>Nothing ticked.</span>")
        else:
            shown = ", ".join(pre[:25]) + (f" and {len(pre) - 25} more" if len(pre) > 25 else "")
            self.picked.setText("Including: " + shown)
            self.picked.setToolTip("\n".join(P.code_label(c) for c in pre))
        try:
            geom = self.area.geometry_bng()
        except Exception:
            self.estimate.setText("")
            return
        cells, _ = self._cells(geom)
        cells = [c for c in cells if geom.intersects(QgsRectangle(*c))]
        dpa, lpi = DATASETS[self.dataset.currentIndex()][1]
        note = "" if lpi or pre is None or not set(pre) & {"L", "M", "Z", "O", "P"} else \
            " Land, objects and parent shells are mostly council (LPI) addresses - choose LPI or Both for them."
        self.estimate.setText(f"{len(cells):,} OS Places request cell(s) of up to 1 km² → at least {len(cells):,} "
                              "transactions, plus one more per extra 100 addresses in a cell." + note)

    # ---------------------------------------------------------------- download
    def download(self):
        if self.task is not None:
            self.task.cancel()
            return
        pre = self.prefixes()
        if pre is not None and not pre:
            self.status.setText("✖ Tick at least one classification.")
            return
        if not S.load_api_key():
            self.status.setText("✖ Add an API key on the Settings tab (its project needs the OS Places API).")
            return
        try:
            geom = self.area.geometry_bng()
        except ValueError as ex:
            self.status.setText(f"✖ {ex}")
            return
        cells, _ = self._cells(geom)
        cells = [c for c in cells if geom.intersects(QgsRectangle(*c))]
        if not cells:
            self.status.setText("✖ The area is empty.")
            return
        confirm = S.get("confirm_over")
        if confirm and len(cells) > confirm and QMessageBox.question(
                self, "OS API Data Downloader", f"This area needs at least {len(cells):,} OS Places transactions. "
                                            "Continue?") != QMessageBox.StandardButton.Yes:
            self.status.setText("Stopped before downloading.")
            return
        dpa, lpi = DATASETS[self.dataset.currentIndex()][1]
        client = P.PlacesClient(S.load_api_key(), transport=QgisTransport(), budget=Budget(self.limit.value() or None),
                                include_dpa=dpa, include_lpi=lpi)
        engine = QgsGeometry.createGeometryEngine(geom.constGet())
        engine.prepareGeometry()

        def contains(x, y):
            return engine.intersects(QgsPoint(x, y))
        how = self.split.currentData()
        one = self.one_per_uprn.isChecked()
        folder = S.output_folder()
        os.makedirs(folder, exist_ok=True)
        stamp = _dt.datetime.now()
        stub = C.filename_stub(["all"] if pre is None else (P.code_label(c) for c in pre))
        out = os.path.join(folder, f"os_places_{stub}_{stamp:%Y%m%d_%H%M%S}.gpkg")
        k = 2
        while os.path.exists(out):
            out = os.path.join(folder, f"os_places_{stub}_{stamp:%Y%m%d_%H%M%S}_{k}.gpkg")
            k += 1
        where = self.area.description()
        picked = "all classifications" if pre is None else (
            ", ".join(P.code_label(c) for c in pre) if len(pre) <= 4 else
            ", ".join(P.code_label(c) for c in pre[:3]) + f" and {len(pre) - 3} more")

        def work(task):
            rows, info = P.fetch_area(client, cells, prefixes=pre, contains=contains, one_per_uprn=one,
                                      progress=task.report, is_cancelled=task.isCanceled)
            groups = P.split_rows(rows, how)
            written = write_layers(groups, out) if groups else {}
            return rows, info, written

        def finished(result, error):
            self.task = None
            self.progress.setVisible(False)
            self.go.setText("Get addresses for my area")
            if error is not None and not result:
                self.status.setText(f"✖ {error}")
                return
            rows, info, written = result
            root = QgsProject.instance().layerTreeRoot()
            group = root.insertGroup(0, f"OS Places - {picked} - {where} ({stamp:%d %b %Y %H:%M})") \
                if written else None
            lines = [f"✔ {len(rows):,} address(es) · {info['requests']:,} transaction(s)"
                     + (f" · saved to {out}" if written else "")]
            # split by main class: each class's own colour (Residential orange…); split more finely:
            # every layer a clearly different colour
            colours = distinct_colours(len(written)) if how in ("subclass", "code") and len(written) > 1 else None
            for k, (name, (table, n, present)) in enumerate(written.items()):
                lyr = QgsVectorLayer(f"{out}|layername={table}", name, "ogr")
                if lyr.isValid():
                    style_by_class(lyr, present, colours[k] if colours else None)
                    QgsProject.instance().addMapLayer(lyr, False)
                    node = group.addLayer(lyr)
                    node.setCustomProperty("showFeatureCount", True)
                    node.setExpanded(len(present) > 1 and not colours)
                lines.append(f"{name}: {n:,}")
            if info.get("truncated"):
                lines.append(f"<span style='color:#d73027'>Stopped at the transaction limit after "
                             f"{info['cells_done']:,} of {info['cells']:,} cells - partial result.</span>")
            if info.get("cancelled"):
                lines.append("Cancelled - partial result.")
            self.status.setText("<br>".join(lines))
            self.last_output = out

        self.task = FunctionTask("OS API Data Downloader - OS Places addresses", work, finished)
        self.task.progressChanged.connect(lambda p: self.progress.setValue(int(p)))
        self.progress.setValue(0)
        self.progress.setVisible(True)
        self.go.setText("Cancel")
        self.status.setText(f"Getting addresses ({len(cells):,} cells)…")
        start(self.task)

    def cleanup(self):
        if self.task is not None:
            self.task.cancel()
        try:
            self.iface.mapCanvas().extentsChanged.disconnect(self._update_summary)
        except TypeError:
            pass
