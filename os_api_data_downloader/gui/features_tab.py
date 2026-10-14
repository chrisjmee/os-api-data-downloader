"""One tab per feature API: OS NGD API - Features, and OS Features API (OS MasterMap).

Tick feature types -> optionally filter each one on its attributes (like the
OS Data Hub's filter options) -> estimate the cost for the area -> download only
the matching features in the area into a GeoPackage (one layer per type),
clipped to the area, and added to the map in a group.
"""

from __future__ import annotations

import datetime as _dt
import os
import re
import tempfile

from qgis.core import QgsApplication, QgsProject, QgsVectorLayer
from qgis.PyQt.QtCore import Qt, QTimer
from qgis.PyQt.QtWidgets import (
    QComboBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
    QProgressBar, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from ..core import filters as F
from ..core.budget import Budget
from ..core.features_wfs import FeaturesWfsClient
from ..core.ngd_features import NgdFeaturesClient
from ..core.transport import QgisTransport
from . import clipping as C
from . import settings as S
from .filter_dialog import FilterDialog
from .tasks import FunctionTask, start

BASE_TEXT = Qt.ItemDataRole.UserRole + 1
SAMPLE_PAGES = 5        # value lists: read up to 5 pages (500 features, 5 transactions) of the area
FILTER_MARK = "  ⧩ filtered"

SOURCES = {
    "ngd": {"title": "OS NGD", "api": "OS NGD API - Features", "file": "os_ngd",
            "filter": "Filter, e.g. building, land, road…", "client": NgdFeaturesClient},
    "wfs": {"title": "OS MasterMap", "api": "OS Features API", "file": "os_mastermap",
            "filter": "Filter, e.g. topographic, highways…", "client": FeaturesWfsClient},
}


def natural_key(*texts):
    """Alphabetical, with numbers in numerical order (Building 2 before Building 10)."""
    out = []
    for t in texts:
        out.append(tuple((0, int(p), "") if p.isdigit() else (1, 0, p.lower())
                         for p in re.split(r"(\d+)", t or "") if p))
    return out


def pages(n):
    return -(-int(n) // 100)


class FeaturesTab(QWidget):
    def __init__(self, iface, area, kind, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.area = area
        self.kind = kind
        self.src = SOURCES[kind]
        self.task = None
        self.estimates = {}
        self._est_key = None
        self._est_where = {}
        self.filters = {}      # feature type id -> {'filter', 'cql', 'where', 'text'}
        self._attrs = {}       # (id, year) -> attribute list
        self._samples = {}     # (id, year, area) -> (values, features read, complete, transactions)
        v = QVBoxLayout(self)

        row = QHBoxLayout()
        self.filter = QLineEdit()
        self.filter.setPlaceholderText(self.src["filter"])
        self.filter.setClearButtonEnabled(True)
        self.filter.textChanged.connect(self._filter)
        self.load_btn = QPushButton("Load list")
        self.load_btn.clicked.connect(self.load_types)
        row.addWidget(self.filter, 1)
        row.addWidget(self.load_btn)
        v.addLayout(row)
        self.list = QListWidget()
        self.list.setMinimumHeight(180)
        self.list.itemChanged.connect(lambda _: self._selection_changed())
        self.list.itemDoubleClicked.connect(lambda it: self.edit_filter(it))
        self.list.currentItemChanged.connect(lambda *_: self._current_changed())
        v.addWidget(self.list, 1)
        row = QHBoxLayout()
        self.clear_btn = QPushButton("Clear selection")
        self.clear_btn.setToolTip("Untick everything in the list.")
        self.clear_btn.clicked.connect(self.clear_selection)
        row.addWidget(self.clear_btn)
        row.addStretch(1)
        v.addLayout(row)
        row = QHBoxLayout()
        self.filter_btn = QPushButton("⧩ Filter features…")
        self.filter_btn.setToolTip("Only download features with certain attribute values, e.g. a building's use or "
                                   "height - like the filter options on the OS Data Hub. Applies to the highlighted "
                                   "feature type (or double-click one).")
        self.filter_btn.clicked.connect(lambda: self.edit_filter())
        self.clear_filter_btn = QPushButton("Remove filter")
        self.clear_filter_btn.clicked.connect(self.clear_filter)
        row.addWidget(self.filter_btn, 1)
        row.addWidget(self.clear_filter_btn)
        v.addLayout(row)
        self.picked = QLabel("Nothing ticked yet.")
        self.picked.setWordWrap(True)
        self.picked.setTextFormat(Qt.TextFormat.RichText)
        v.addWidget(self.picked)

        f = QFormLayout()
        self.year = QComboBox()
        if kind == "wfs":
            self.year.addItem("Latest data", None)
            this_year = _dt.date.today().year
            for y in range(this_year - 1, 2015, -1):
                self.year.addItem(f"{y} annual snapshot", str(y))
            self.year.currentIndexChanged.connect(lambda _: self.load_types() if self.list.count() else None)
            f.addRow("Data", self.year)
        self.limit = QSpinBox()
        self.limit.setRange(0, 10_000_000)
        self.limit.setSingleStep(500)
        self.limit.setSpecialValueText("No limit")
        self.limit.setSuffix(" transactions")
        f.addRow("Stop after", self.limit)
        v.addLayout(f)

        row = QHBoxLayout()
        self.estimate_btn = QPushButton("Estimate cost")
        self.estimate_btn.clicked.connect(lambda: self.estimate())
        self.go = QPushButton("Download for my area")
        self.go.setStyleSheet("font-weight: bold;")
        self.go.clicked.connect(self.download)
        row.addWidget(self.estimate_btn)
        row.addWidget(self.go, 1)
        v.addLayout(row)
        self.progress = QProgressBar()
        self.progress.setVisible(False)
        v.addWidget(self.progress)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        v.addWidget(self.status)
        area.changed.connect(self._area_changed)
        self.refresh_settings()
        self._current_changed()

    def refresh_settings(self):
        self.limit.setValue(S.get("hard_limit"))

    # ---------------------------------------------------------------- helpers
    def _title_for(self, c):
        """The friendly title shown in the list for feature type ``c`` (e.g. 'Building'), falling back to
        its technical id if it isn't (or is no longer) in the list - used to name the downloaded layer in
        the Layers panel instead of the bare id."""
        it = self._item(c)
        text = (it.data(BASE_TEXT) if it else None) or c
        return text.split("  (")[0]

    def client(self, limit=None):
        kw = {"archive_year": self.year.currentData()} if self.kind == "wfs" else {}
        return self.src["client"](S.load_api_key(), transport=QgisTransport(), budget=Budget(limit), **kw)

    def _start(self, task, label):
        self.task = task
        task.progressChanged.connect(lambda p: self.progress.setValue(int(p)))
        self.progress.setValue(0)
        self.progress.setVisible(True)
        self.go.setText("Cancel")
        self.estimate_btn.setEnabled(False)
        self.status.setText(label)
        start(task)

    def _finish(self):
        self.task = None
        self.progress.setVisible(False)
        self.go.setText("Download for my area")
        self.estimate_btn.setEnabled(True)

    def _area(self):
        try:
            geom = self.area.geometry_bng()
        except ValueError as ex:
            self.status.setText(f"✖ {ex}")
            return None
        bb = geom.boundingBox()
        return geom, (bb.xMinimum(), bb.yMinimum(), bb.xMaximum(), bb.yMaximum()), self.area.filter_wkt(geom)

    def _area_changed(self):
        self._samples = {}
        if self.estimates:
            self.estimates = {}
            self.status.setText("The area changed - press 'Estimate cost' again for an up-to-date cost.")

    # ---------------------------------------------------------------- list
    def load_types(self):
        if not S.load_api_key():
            self.status.setText(f"✖ Add an API key on the Settings tab (its project needs {self.src['api']}).")
            return
        ticked = set(self.checked())
        QgsApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            cols = self.client().collections()
        except Exception as ex:
            self.status.setText(f"✖ {ex}")
            return
        finally:
            QgsApplication.restoreOverrideCursor()
        self.list.blockSignals(True)
        self.list.clear()
        for c in sorted(cols, key=lambda c: natural_key(c.get("title") or c["id"], c["id"])):
            title = c.get("title") or c["id"]
            it = QListWidgetItem(title if title == c["id"] else f"{title}  ({c['id']})")
            it.setData(Qt.ItemDataRole.UserRole, c["id"])
            it.setData(BASE_TEXT, it.text())
            it.setToolTip(c.get("description") or c["id"])
            self._mark(it)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked if c["id"] in ticked else Qt.CheckState.Unchecked)
            self.list.addItem(it)
        self.list.blockSignals(False)
        self.status.setText(f"{len(cols)} feature types. Tick the ones you want.")
        self._filter(self.filter.text())
        self._selection_changed()

    def _filter(self, text):
        t = (text or "").lower()
        for i in range(self.list.count()):
            it = self.list.item(i)
            it.setHidden(bool(t) and t not in it.text().lower())

    def checked(self):
        return [self.list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.list.count())
                if self.list.item(i).checkState() == Qt.CheckState.Checked]

    def clear_selection(self):
        self.list.blockSignals(True)
        for i in range(self.list.count()):
            self.list.item(i).setCheckState(Qt.CheckState.Unchecked)
        self.list.blockSignals(False)
        self._selection_changed()

    def _selection_changed(self):
        ids = self.checked()
        if not ids:
            self.picked.setText("Nothing ticked yet.")
            return
        lines = ["Ticked: " + ", ".join(ids)]
        for c in ids:
            if c in self.filters:
                lines.append(f"⧩ {c}: only where <i>{self._html(self.filters[c]['text'])}</i>")
        self.picked.setText("<br>".join(lines))

    @staticmethod
    def _html(text):
        return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    # ---------------------------------------------------------------- attribute filters
    def where(self, c):
        f = self.filters.get(c)
        return f["where"] if f else None

    def _item(self, c):
        for i in range(self.list.count()):
            if self.list.item(i).data(Qt.ItemDataRole.UserRole) == c:
                return self.list.item(i)
        return None

    def _mark(self, it):
        c = it.data(Qt.ItemDataRole.UserRole)
        base = it.data(BASE_TEXT) or it.text()
        f = self.filters.get(c)
        it.setText(base + (FILTER_MARK if f else ""))
        font = it.font()
        font.setBold(bool(f))
        it.setFont(font)
        tip = it.toolTip().split("\n\nFilter:")[0]
        it.setToolTip(tip + (f"\n\nFilter: {f['text']}" if f else ""))

    def _target(self, item=None):
        it = item or self.list.currentItem()
        if it is None:
            ids = self.checked()
            it = self._item(ids[0]) if len(ids) == 1 else None
        return it

    def _current_changed(self):
        it = self._target()
        has = it is not None
        self.filter_btn.setEnabled(has)
        self.clear_filter_btn.setEnabled(has and it.data(Qt.ItemDataRole.UserRole) in self.filters)
        if has:
            c = it.data(Qt.ItemDataRole.UserRole)
            self.filter_btn.setText(f"⧩ Filter {c}…" if len(c) < 34 else "⧩ Filter features…")
        else:
            self.filter_btn.setText("⧩ Filter features…")

    def attributes(self, c):
        """Filterable attributes of a feature type (cached)."""
        key = (c, self.year.currentData() if self.kind == "wfs" else None)
        if key not in self._attrs:
            cl = self.client()
            if self.kind == "ngd":
                self._attrs[key] = F.parse_queryables(cl.queryables(c))
            else:
                self._attrs[key] = F.parse_describe_feature_type(cl.describe(c))
        return self._attrs[key]

    def edit_filter(self, item=None, dialog_cls=FilterDialog):
        """Opens the filter window for the highlighted feature type. First reads a sample of the
        features in the area (cached) so the value drop-downs list what's actually there."""
        if self.task is not None:
            return None
        it = self._target(item)
        if it is None:
            self.status.setText("Highlight a feature type in the list (press 'Load list' first), then press Filter.")
            return None
        c = it.data(Qt.ItemDataRole.UserRole)
        note = ""
        QgsApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            attrs = self.attributes(c)
        except Exception as ex:
            attrs = []
            note = f"Couldn't get the list of attributes ({ex})."
            if self.kind == "ngd":
                note += " You can still write the query yourself."
        finally:
            QgsApplication.restoreOverrideCursor()
        if not attrs and self.kind == "wfs":
            self.status.setText(f"✖ {note or 'This feature type has no attributes that can be filtered.'}")
            return None
        if not attrs:
            return self._open_filter(it, c, attrs, note, None, "", dialog_cls)
        try:
            geom = self.area.geometry_bng()
        except ValueError:
            return self._open_filter(it, c, attrs, note, None, "Choose an area of interest to list the values found "
                                     "in it.", dialog_cls)
        bb = geom.boundingBox()
        bbox = (bb.xMinimum(), bb.yMinimum(), bb.xMaximum(), bb.yMaximum())
        wkt = self.area.filter_wkt(geom)
        key = (c, self.year.currentData() if self.kind == "wfs" else None, wkt or bbox)
        if key in self._samples:
            return self._open_filter(it, c, attrs, note, *self._sample_note(key), dialog_cls)
        client = self.client()

        def work(task):
            feats, pages_read, complete = [], 0, False
            pages = client.iter_pages(c, bbox, wkt, is_cancelled=task.isCanceled)
            for page in pages:
                feats.extend(page)
                pages_read += 1
                task.report(100 * pages_read / SAMPLE_PAGES, f"{len(feats):,} features read")
                if len(page) < 100:
                    complete = True
                    break
                if pages_read >= SAMPLE_PAGES:
                    break
            else:
                complete = not task.isCanceled()
            return F.collect_values(feats), len(feats), complete, client.budget.used

        def finished(result, error):
            self._finish()
            if error is not None:
                self.status.setText(f"Couldn't read the values in your area ({error}).")
                QTimer.singleShot(0, lambda: self._open_filter(
                    it, c, attrs, note, None, "Couldn't read the values in your area - type them instead.", dialog_cls))
                return
            self._samples[key] = result
            self.status.setText("")
            # open the window after this task has fully finished (see estimate())
            QTimer.singleShot(0, lambda: self._open_filter(it, c, attrs, note, *self._sample_note(key), dialog_cls))

        self._start(FunctionTask(f"OS API Data Downloader - reading {c} values in your area", work, finished),
                    f"Reading the values of {c} in your area (up to {SAMPLE_PAGES * 100} features, "
                    f"{SAMPLE_PAGES} transactions)…")
        return None

    def _sample_note(self, key):
        values, n, complete, used = self._samples[key]
        cost = f"{used} transaction{'s' if used != 1 else ''}"
        if n == 0:
            return values, f"There are no {key[0]} features in your area ({cost})."
        if complete:
            return values, f"The value lists show what's in your area: all {n:,} feature(s) ({cost})."
        return values, (f"The value lists show what's in the first {n:,} features in your area ({cost}); "
                        "other values can be typed.")

    def _open_filter(self, it, c, attrs, note, values, values_note, dialog_cls=FilterDialog):
        dlg = dialog_cls(it.data(BASE_TEXT) or c, attrs, self.kind, self.filters.get(c), note, self,
                         values=values, values_note=values_note)
        self._dialog = dlg
        if not dlg.exec():
            return dlg
        self.set_filter(c, dlg.result_value)
        if c not in self.checked():
            it.setCheckState(Qt.CheckState.Checked)
        return dlg

    def set_filter(self, c, value):
        """value: {'filter', 'cql', 'where', 'text'} or None to remove the filter."""
        old = self.filters.get(c)
        if value:
            self.filters[c] = value
        else:
            self.filters.pop(c, None)
        if (old or {}).get("where") != (value or {}).get("where"):
            self.estimates.pop(c, None)
        it = self._item(c)
        if it is not None:
            self.list.blockSignals(True)
            self._mark(it)
            self.list.blockSignals(False)
        self._selection_changed()
        self._current_changed()
        self.status.setText(f"⧩ {c}: only features where {value['text']}." if value
                            else f"{c}: no filter - every feature in the area.")

    def clear_filter(self):
        it = self._target()
        if it is not None:
            self.set_filter(it.data(Qt.ItemDataRole.UserRole), None)

    # ---------------------------------------------------------------- estimate
    def estimate(self, then=None):
        if self.task is not None:
            return
        cols = self.checked()
        if not cols:
            self.status.setText("Tick at least one feature type (press 'Load list' first).")
            return
        area = self._area()
        if area is None:
            return
        _, bbox, wkt = area
        client = self.client()
        wheres = {c: self.where(c) for c in cols}

        def work(task):
            out = {}
            for i, c in enumerate(cols):
                if task.isCanceled():
                    break
                task.report(100 * i / len(cols), f"Counting {c}")
                out[c] = client.estimate_count(c, bbox, wkt, where=wheres[c])[0]
            return out, client.budget.used, list(getattr(client, "notes", []))

        def finished(result, error):
            self._finish()
            if error is not None:
                self.status.setText(f"✖ {error}")
                return
            est, used, notes = result
            self.estimates = est
            self._est_where = dict(wheres)
            tx = sum(pages(n) for n in est.values())
            lines = [f"<b>About {tx:,} transaction(s)</b> to download {sum(est.values()):,} feature(s) in the "
                     f"{self.area.description()} · counting used {used} transaction(s)"]
            lines += [f"{c}: ~{n:,} features" + (" matching the filter" if wheres.get(c) else "")
                      for c, n in est.items()]
            lines += [f"<span style='color:#b35806'>{n}</span>" for n in notes]
            self.status.setText("<br>".join(lines))
            if then:
                # start the download after this task has fully finished (starting a task from inside
                # another task's finished() can leave the new one queued forever)
                QTimer.singleShot(0, lambda: then(tx))

        self._start(FunctionTask(f"OS API Data Downloader - counting {self.src['title']} features", work, finished),
                    "Counting features in your area…")

    # ---------------------------------------------------------------- download
    def download(self):
        if self.task is not None:
            self.task.cancel()
            return
        cols = self.checked()
        if not cols:
            self.status.setText("Tick at least one feature type (press 'Load list' first).")
            return
        # each estimate is for the filter at the time - a changed filter is re-counted
        if not all(c in self.estimates and self._est_where.get(c) == self.where(c) for c in cols):
            self.estimate(then=lambda tx: self._confirm_and_download(cols, tx))
            return
        self._confirm_and_download(cols, sum(pages(self.estimates[c]) for c in cols))

    def _confirm_and_download(self, cols, tx):
        confirm = S.get("confirm_over")
        if confirm and tx > confirm and QMessageBox.question(
                self, "OS API Data Downloader", f"This download needs about {tx:,} {self.src['api']} transactions. "
                                        "Continue?") != QMessageBox.StandardButton.Yes:
            self.status.setText(self.status.text() + "<br>Stopped before downloading.")
            return
        area = self._area()
        if area is None:
            return
        geom, bbox, wkt = area
        folder = S.output_folder()
        os.makedirs(folder, exist_ok=True)
        stamp = _dt.datetime.now()
        stub = C.filename_stub(self._title_for(c) for c in cols)
        out = os.path.join(folder, f"{self.src['file']}_{stub}_{stamp:%Y%m%d_%H%M%S}.gpkg")
        k = 2
        while os.path.exists(out):     # two downloads in the same second must never share a file
            out = os.path.join(folder, f"{self.src['file']}_{stub}_{stamp:%Y%m%d_%H%M%S}_{k}.gpkg")
            k += 1
        mode = self.area.clip()
        where = self.area.description()
        client = self.client(self.limit.value() or None)
        expected = dict(self.estimates)
        wheres = {c: self.where(c) for c in cols}

        def work(task):
            results = []
            with tempfile.TemporaryDirectory(prefix="osdl_") as tmp:
                for i, c in enumerate(cols):
                    if task.isCanceled():
                        break
                    seq = os.path.join(tmp, f"{C._safe_name(c)}.geojsons")
                    lo, hi = 100 * i / len(cols), 100 * (i + 1) / len(cols)

                    def prog(p, m=None, lo=lo, hi=hi):
                        task.report(lo + (hi - lo) * p / 100, m)
                    info = client.download(c, bbox, seq, wkt, expected=expected.get(c), progress=prog,
                                           is_cancelled=task.isCanceled, where=wheres[c])
                    n = C.geojsonseq_to_gpkg(seq, geom, out, c, mode) if info["features"] else 0
                    results.append((c, info, n))
                    if info["truncated"]:
                        break
            return results, client.budget.used, list(getattr(client, "notes", []))

        def finished(result, error):
            self._finish()
            if error is not None and not result:
                self.status.setText(f"✖ {error}")
                return
            results, used, notes = result
            root = QgsProject.instance().layerTreeRoot()
            group = root.insertGroup(0, f"{self.src['title']} - {where} ({stamp:%d %b %Y %H:%M})")
            lines = [f"✔ Saved to {out} · {used:,} transaction(s)"]
            for c, info, n in results:
                if n:
                    lyr = QgsVectorLayer(f"{out}|layername={C._safe_name(c)}", self._title_for(c), "ogr")
                    if lyr.isValid():
                        QgsProject.instance().addMapLayer(lyr, False)
                        node = group.addLayer(lyr)
                        node.setCustomProperty("showFeatureCount", True)
                note = " - stopped at the transaction limit (partial)" if info["truncated"] else ""
                flt = " matching the filter" if wheres.get(c) else ""
                lines.append(f"{c}: {n:,} feature(s){flt} in the {where} (from {info['features']:,} downloaded){note}")
            if not group.children():
                root.removeChildNode(group)
            lines += [f"<span style='color:#b35806'>{n}</span>" for n in notes]
            if any(info.get("cancelled") for _, info, _ in results):
                lines.append("Cancelled - partial download.")
            self.status.setText("<br>".join(lines))
            self.last_output = out

        self._start(FunctionTask(f"OS API Data Downloader - downloading {self.src['title']} features", work, finished),
                    "Downloading…")

    def cleanup(self):
        if self.task is not None:
            self.task.cancel()
