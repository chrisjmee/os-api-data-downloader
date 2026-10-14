"""Downloads tab: OS OpenData products and your premium / PSGA data packages
(OS Downloads API), with the option to clip everything downloaded to the area
chosen at the top of the panel."""

from __future__ import annotations

import os

from qgis.core import QgsApplication, QgsProject, QgsRectangle, QgsVectorLayer
from qgis.gui import QgsFileWidget
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QHeaderView, QLabel,
    QProgressBar, QPushButton, QRadioButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..core.downloads import DownloadsClient, human_size, squares_for_extent
from ..core.transport import QgisTransport
from . import clipping as C
from . import settings as S
from .tasks import FunctionTask, start

LOADABLE = (".gpkg", ".shp", ".geojson", ".gml", ".csv", ".zip", ".tif", ".tiff", ".asc")


def _add_vector(uri, name, provider="ogr"):
    lyr = QgsVectorLayer(uri, name, provider)
    if lyr.isValid():
        QgsProject.instance().addMapLayer(lyr)
        return 1
    return 0


def _add_raster(path):
    from qgis.core import QgsRasterLayer
    lyr = QgsRasterLayer(path, os.path.basename(path))
    if lyr.isValid():
        QgsProject.instance().addMapLayer(lyr)
        return 1
    return 0


class DownloadsTab(QWidget):
    def __init__(self, iface, area, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.area = area
        self.files = []
        self.task = None
        v = QVBoxLayout(self)

        f = QFormLayout()
        self.kind = QComboBox()
        self.kind.addItem("OS OpenData product", "open")
        self.kind.addItem("My data packages (premium / PSGA)", "package")
        self.kind.currentIndexChanged.connect(self._kind_changed)
        f.addRow("Download", self.kind)
        row = QHBoxLayout()
        self.product = QComboBox()
        self.product.currentIndexChanged.connect(self._product_changed)
        load = QPushButton("Load list")
        load.clicked.connect(self.load_products)
        row.addWidget(self.product, 1)
        row.addWidget(load)
        f.addRow("Product", row)
        self.version = QComboBox()
        self.version_label = QLabel("Version")
        f.addRow(self.version_label, self.version)
        self.fmt = QComboBox()
        self.fmt_label = QLabel("Format")
        f.addRow(self.fmt_label, self.fmt)
        self.r_tiles = QRadioButton("Tiles covering my area")
        self.r_gb = QRadioButton("Great Britain")
        self.r_tiles.setChecked(True)
        self.area_label = QLabel("Coverage")
        row = QHBoxLayout()
        row.addWidget(self.r_tiles)
        row.addWidget(self.r_gb)
        f.addRow(self.area_label, row)
        v.addLayout(f)
        lst = QPushButton("List files")
        lst.clicked.connect(self.list_files)
        v.addWidget(lst)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["File", "Area", "Format", "Size"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setMinimumHeight(120)
        v.addWidget(self.table, 1)

        f = QFormLayout()
        self.clip_cb = QCheckBox("Clip the downloaded data to my area")
        self.clip_cb.setChecked(True)
        f.addRow(self.clip_cb)
        self.folder = QgsFileWidget()
        self.folder.setStorageMode(QgsFileWidget.StorageMode.GetDirectory)
        self.folder.setFilePath(S.output_folder())
        f.addRow("Save to", self.folder)
        v.addLayout(f)
        self.go = QPushButton()
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
        self._kind_changed()

    # ---------------------------------------------------------------- helpers
    def _client(self):
        return DownloadsClient(api_key=S.load_api_key() or None, transport=QgisTransport())

    def _go_label(self):
        return "Download selected files (all if none selected)"

    def _kind_changed(self):
        kind = self.kind.currentData()
        pkg = kind == "package"
        for w in (self.version, self.version_label):
            w.setVisible(pkg)
        for w in (self.fmt, self.fmt_label, self.r_tiles, self.r_gb, self.area_label):
            w.setVisible(not pkg)
        self.product.clear()
        self.table.setRowCount(0)
        self.files = []
        self.go.setText(self._go_label())

    def _busy(self, fn):
        QgsApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            return fn()
        except Exception as ex:
            self.status.setText(f"✖ {ex}")
            return None
        finally:
            QgsApplication.restoreOverrideCursor()

    def _aoi(self):
        try:
            return self.area.geometry_bng()
        except ValueError as ex:
            self.status.setText(f"✖ {ex}")
            return None

    def _start(self, task):
        self.task = task
        task.progressChanged.connect(lambda p: self.progress.setValue(int(p)))
        self.progress.setValue(0)
        self.progress.setVisible(True)
        self.go.setText("Cancel")
        start(task)

    def _finish(self):
        self.task = None
        self.progress.setVisible(False)
        self.go.setText(self._go_label())

    # ---------------------------------------------------------------- OpenData / packages
    def load_products(self):
        client = self._client()
        if self.kind.currentData() == "open":
            items = self._busy(client.products)
            if items is None:
                return
            self.product.clear()
            for p in items:
                self.product.addItem(f"{p.get('name') or p.get('id')}", p)
            self.status.setText(f"{len(items)} OpenData products.")
        else:
            items = self._busy(client.data_packages)
            if items is None:
                return
            self.product.clear()
            for p in items:
                self.product.addItem(f"{p.get('name')} ({p.get('productName') or p.get('productId', '')})", p)
            self.status.setText(f"{len(items)} data package(s) on this API key's account."
                                if items else "No data packages found for this key.")

    def _product_changed(self):
        p = self.product.currentData()
        self.version.clear()
        self.fmt.clear()
        if not p:
            return
        if self.kind.currentData() == "package":
            for ver in sorted(p.get("versions") or [], key=lambda x: x.get("createdOn") or "", reverse=True):
                self.version.addItem(f"{ver.get('createdOn', '')[:10]} - {ver.get('reason') or ''} "
                                     f"({ver.get('format') or ''})", ver)
        else:
            all_dl = p.get("_downloads")
            if all_dl is None:
                all_dl = self._busy(lambda: self._client().product_downloads(p["id"])) or []
                p["_downloads"] = all_dl
                self.product.setItemData(self.product.currentIndex(), p)
            fmts = []
            for d in all_dl:
                if d.get("format") and d["format"] not in fmts:
                    fmts.append(d["format"])
                    self.fmt.addItem(d["format"], d["format"])
            gb_only = {d.get("area") for d in all_dl} <= {"GB"}
            self.r_gb.setChecked(gb_only)
            self.r_tiles.setEnabled(not gb_only)
            if not gb_only:
                self.r_tiles.setChecked(True)

    def list_files(self):
        p = self.product.currentData()
        if not p:
            self.status.setText("Load the product list and choose one first.")
            return
        client = self._client()
        if self.kind.currentData() == "package":
            ver = self.version.currentData()
            if not ver:
                return
            detail = self._busy(lambda: client.data_package_version(p["id"], ver["id"]))
            files = (detail or {}).get("downloads") or []
            self.files = [dict(f, area="", format=detail.get("format", ""), keyed=True) for f in files]
        else:
            fmt = self.fmt.currentData()
            if self.r_gb.isChecked():
                areas = ["GB"]
            else:
                geom = self._aoi()
                if geom is None:
                    return
                bb = geom.boundingBox()
                areas = squares_for_extent(bb.xMinimum(), bb.yMinimum(), bb.xMaximum(), bb.yMaximum(),
                                           intersects=lambda c: geom.intersects(QgsRectangle(*c)))
            files = []
            for a in areas:
                files.extend(self._busy(lambda a=a: client.product_downloads(p["id"], area=a, fmt=fmt)) or [])
            if not files and not self.r_gb.isChecked():
                self.status.setText(f"No tiled files for {', '.join(areas)} - this product may only be "
                                    "supplied for the whole of GB.")
            self.files = [dict(f, keyed=False) for f in files]
        self.table.setRowCount(len(self.files))
        for r, fl in enumerate(self.files):
            for c, val in enumerate([fl.get("fileName"), fl.get("area"), fl.get("format"),
                                     human_size(fl.get("size"))]):
                self.table.setItem(r, c, QTableWidgetItem(str(val or "")))
        if self.files:
            total = sum(f.get("size") or 0 for f in self.files)
            self.status.setText(f"{len(self.files)} file(s), {human_size(total)} in total.")

    def _download_files(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()}) or list(range(len(self.files)))
        todo = [self.files[r] for r in rows]
        if not todo:
            self.status.setText("List the files first.")
            return
        clip = self.clip_cb.isChecked()
        aoi = self._aoi() if clip else None
        if clip and aoi is None:
            return
        mode = self.area.clip()
        where = self.area.description()
        folder = self.folder.filePath() or S.output_folder()
        S.set_("folder", folder)
        client = self._client()
        pkg = self.product.currentData() or {}
        sub = (pkg.get("name") or pkg.get("id") or "download").replace("/", "_")
        dest = os.path.join(folder, sub)
        log = []

        def work(task):
            done, clipped = [], []
            share = 70.0 if clip else 100.0
            for i, fl in enumerate(todo):
                if task.isCanceled():
                    break
                base = share * i / len(todo)
                task.report(base, f"Downloading {fl.get('fileName')}")
                done.append(client.download(fl["url"], dest, fl.get("fileName"), keyed=fl.get("keyed"),
                                            progress=lambda p, base=base: task.report(base + p * share / 100 / len(todo)),
                                            is_cancelled=task.isCanceled))
            if clip and done and not task.isCanceled():
                try:
                    clipped = C.clip_downloads(done, aoi, os.path.join(dest, "clipped"), sub, mode,
                                               is_cancelled=task.isCanceled, log=log.append,
                                               progress=lambda p, m=None: task.report(70 + 0.3 * p, m))
                except Exception as ex:
                    log.append(f"Could not clip: {ex}")
            return done, clipped

        def finished(result, error):
            self._finish()
            if error is not None and not result:
                self.status.setText(f"✖ {error}")
                return
            paths, clipped = result
            added = 0
            if clip:
                for out, lname, n in clipped:
                    if lname is None:
                        added += _add_raster(out)
                    elif n:
                        added += _add_vector(f"{out}|layername={lname}", f"{lname} (clipped)")
            else:
                for p in paths:
                    if p.lower().endswith((".tif", ".tiff", ".asc")):
                        added += _add_raster(p)
                    elif p.lower().endswith(LOADABLE):
                        for uri, provider, name in C.vector_sublayers(p):
                            added += _add_vector(uri, name, provider)
            msg = f"✔ Downloaded {len(paths)} file(s) to {dest}"
            if clip:
                kept = sum(n or 0 for _, _, n in clipped)
                msg += f"<br>✔ Clipped to the {where}: {kept:,} feature(s) in " \
                       f"{len([c for c in clipped if c[2]])} layer(s), saved in {os.path.join(dest, 'clipped')}"
            if added:
                msg += f" · {added} added to the map"
            for line in log[-6:]:
                msg += f"<br><span style='color:#555'>{line}</span>"
            self.status.setText(msg)

        self._start(FunctionTask("OS API Data Downloader - downloading", work, finished))

    # ---------------------------------------------------------------- go
    def download(self):
        if self.task is not None:
            self.task.cancel()
            return
        self._download_files()

    def cleanup(self):
        if self.task is not None:
            self.task.cancel()

