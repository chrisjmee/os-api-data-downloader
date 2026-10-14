"""Find an NGD Feature Type: a way into the ~100 OS NGD feature types for someone who doesn't know their
names. Search what a feature is *described as* (e.g. "bridge", "school", "pylon"), see every matching
description value grouped under its feature type (polygons, lines then points), tick the ones you actually
want and download just those - like the OS NGD tab, but starting from a search instead of the full list.

Searching is a local, offline lookup against ``core.ngd_index`` - every feature type's description-style
attribute and its allowed values, kept as a small CSV (either bundled with the plugin, or your own, rebuilt
from the live API with the 'Rebuild index' button) - so it's instant and needs no API key. The only network
calls this tab ever makes are the actual 'Estimate cost' / 'Download' requests, and rebuilding the index
itself (a deliberate, one-off action, not something that happens on an ordinary search).
"""

from __future__ import annotations

import datetime as _dt
import os
import tempfile

from qgis.core import QgsProject, QgsVectorLayer
from qgis.PyQt.QtCore import Qt, QTimer
from qgis.PyQt.QtWidgets import (
    QComboBox, QCompleter, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QProgressBar, QPushButton, QSpinBox,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from ..core import ngd_index as NI
from ..core.budget import Budget
from ..core.ngd_features import NgdFeaturesClient
from ..core.ngd_search import GEOM_ORDER, cql_for_values
from ..core.transport import QgisTransport
from . import clipping as C
from . import settings as S
from .tasks import FunctionTask, start

ID_ROLE = Qt.ItemDataRole.UserRole + 1
VALUE_ROLE = Qt.ItemDataRole.UserRole + 2
GROUP_LABEL = {"polygon": "Polygons", "line": "Lines", "point": "Points"}

try:
    _CHECKABLE = Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsAutoTristate
except AttributeError:  # older Qt
    _CHECKABLE = Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsTristate


def pages(n):
    return -(-int(n) // 100)


def filename_stub(term, ticked):
    """A short, readable base for the download's file name - e.g. 'bridge_footbridge_pipe_bridge' - built
    from the search term and the actual description values ticked, so the file says what's in it instead of
    just 'os_ngd_search'. ``ticked``: ``{feature class id: [description value, ...]}``."""
    values = sorted({v for vals in ticked.values() for v in vals}, key=str.lower)
    return C.filename_stub([term] + values)


class SearchTab(QWidget):
    def __init__(self, iface, area, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.area = area
        self.task = None
        self.estimates = {}
        self.index = NI.load()
        self.results = {}   # collection id -> (base_id, version, matched description value(s), geometry)
        self.attrs = {}      # collection id -> the attribute ({"name", "type"}) that carries its description
                             # values (straight from the index - no network needed), or None if none fits
        v = QVBoxLayout(self)

        self.intro = QLabel("Not sure which OS NGD feature type you need? Search what it's described as, "
                            "e.g. <i>bridge</i>, <i>school</i> or <i>pylon</i>, and tick any of the matches.")
        self.intro.setWordWrap(True)
        v.addWidget(self.intro)

        row = QHBoxLayout()
        self.term = QLineEdit()
        self.term.setPlaceholderText("Search feature types, e.g. bridge…")
        self.term.setClearButtonEnabled(True)
        self.term.returnPressed.connect(self.search)
        self.search_btn = QPushButton("Search")
        self.search_btn.clicked.connect(self.search)
        self.rebuild_btn = QPushButton("Rebuild index")
        self.rebuild_btn.clicked.connect(self.rebuild_index)
        row.addWidget(self.term, 1)
        row.addWidget(self.search_btn)
        row.addWidget(self.rebuild_btn)
        v.addLayout(row)

        row = QHBoxLayout()
        row.addWidget(QLabel("...or pick one:"))
        self.desc_combo = QComboBox()
        self.desc_combo.setEditable(True)
        self.desc_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        completer = QCompleter(self.desc_combo.model(), self.desc_combo)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self.desc_combo.setCompleter(completer)
        self.desc_combo.activated.connect(self._pick_description)
        row.addWidget(self.desc_combo, 1)
        v.addLayout(row)
        self._populate_desc_combo()

        self.index_label = QLabel()
        self.index_label.setWordWrap(True)
        v.addWidget(self.index_label)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setMinimumHeight(220)
        self.tree.itemChanged.connect(self._item_changed)
        v.addWidget(self.tree, 1)

        row = QHBoxLayout()
        self.clear_btn = QPushButton("Clear selection")
        self.clear_btn.clicked.connect(self.clear_selection)
        row.addWidget(self.clear_btn)
        row.addStretch(1)
        v.addLayout(row)
        self.picked = QLabel("Nothing ticked yet.")
        self.picked.setWordWrap(True)
        v.addWidget(self.picked)

        row = QHBoxLayout()
        row.addWidget(QLabel("Stop after"))
        self.limit = QSpinBox()
        self.limit.setRange(0, 10_000_000)
        self.limit.setSingleStep(500)
        self.limit.setSpecialValueText("No limit")
        self.limit.setSuffix(" transactions")
        row.addWidget(self.limit)
        row.addStretch(1)
        v.addLayout(row)

        row = QHBoxLayout()
        self.estimate_btn = QPushButton("Estimate cost")
        self.estimate_btn.clicked.connect(lambda: self.estimate())
        self.go = QPushButton("Download selected for my area")
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
        self._update_index_label()

    def refresh_settings(self):
        self.limit.setValue(S.get("hard_limit"))

    # ---------------------------------------------------------------- helpers
    def client(self, limit=None):
        return NgdFeaturesClient(S.load_api_key(), transport=QgisTransport(), budget=Budget(limit))

    def _start(self, task, label):
        self.task = task
        task.progressChanged.connect(lambda p: self.progress.setValue(int(p)))
        self.progress.setValue(0)
        self.progress.setVisible(True)
        self.go.setText("Cancel")
        self.estimate_btn.setEnabled(False)
        self.rebuild_btn.setEnabled(False)
        self.status.setText(label)
        start(task)

    def _finish(self):
        self.task = None
        self.progress.setVisible(False)
        self.go.setText("Download selected for my area")
        self.estimate_btn.setEnabled(True)
        self.rebuild_btn.setEnabled(True)

    def _area(self):
        try:
            geom = self.area.geometry_bng()
        except ValueError as ex:
            self.status.setText(f"✖ {ex}")
            return None
        bb = geom.boundingBox()
        return geom, (bb.xMinimum(), bb.yMinimum(), bb.xMaximum(), bb.yMaximum()), self.area.filter_wkt(geom)

    def _area_changed(self):
        if self.estimates:
            self.estimates = {}
            self.status.setText("The area changed - press 'Estimate cost' again for an up-to-date cost.")

    def _update_index_label(self):
        src, when = NI.source()
        if src is None:
            self.index_label.setText("No local index of OS NGD feature types yet - press 'Rebuild index' "
                                     "(needs an API key, one-off, roughly a minute).")
        elif when:
            self.index_label.setText(f"Searching your own index, rebuilt {when:%d %b %Y %H:%M}. Press "
                                     "'Rebuild index' any time to pick up changes on OS NGD.")
        else:
            self.index_label.setText("Searching the index bundled with the plugin. Press 'Rebuild index' "
                                     "with your own API key to refresh it from live OS NGD data.")

    def _populate_desc_combo(self):
        """Every distinct description value in the index, alphabetically, as another way to search - type
        to filter the list, or just scroll it, instead of having to already know a word to search for."""
        self.desc_combo.blockSignals(True)
        self.desc_combo.clear()
        self.desc_combo.addItem("")
        if self.index:
            values = sorted({v for info in self.index.values() for v in (info.get("values") or [])},
                            key=str.lower)
            self.desc_combo.addItems(values)
        self.desc_combo.setCurrentIndex(0)
        self.desc_combo.blockSignals(False)

    def _pick_description(self, index):
        """Choosing a value from the drop-down searches for it directly, the same as typing it."""
        text = self.desc_combo.itemText(index)
        if not text:
            return
        self.term.setText(text)
        self.search()

    # ---------------------------------------------------------------- search (instant - no network at all)
    def search(self):
        term = self.term.text().strip()
        if not term:
            self.status.setText("Type something to search for, e.g. 'bridge'.")
            return
        if self.index is None:
            self.status.setText("No local index yet - press 'Rebuild index' first (needs an API key). "
                                "After that, searching never needs one again.")
            return
        hits = NI.search(self.index, term)
        if not hits:
            self.tree.clear()
            self.results = {}
            self.attrs = {}
            self.status.setText(f"No OS NGD feature types are described as '{term}'. Try a different, more "
                               "general word.")
            self._selection_changed()
            return
        self.results = {}
        self.attrs = {}
        for base, matched in hits.items():
            info = self.index[base]
            cid = info["cid"]
            self.results[cid] = (base, info["version"], matched, info["geom"])
            self.attrs[cid] = {"name": info["attr"], "type": "string"} if info.get("attr") else None
        self._populate(term)

    def _populate(self, term):
        was_ticked = self.checked()   # {cid: [values]} - carried over if a value still exists after re-search
        self.tree.blockSignals(True)
        self.tree.clear()
        groups = {}
        for gk in GEOM_ORDER:
            top = QTreeWidgetItem([GROUP_LABEL[gk]])
            top.setFlags(Qt.ItemFlag.ItemIsEnabled)
            font = top.font(0)
            font.setBold(True)
            top.setFont(0, font)
            groups[gk] = top
        n = 0
        for cid, (base, ver, matched, geom_type) in sorted(self.results.items(), key=lambda kv: kv[1][0]):
            top = groups.get(geom_type, groups["polygon"])
            cls = QTreeWidgetItem([f"{base}  ({cid})"])
            cls.setData(0, ID_ROLE, cid)
            tip = cid
            if not self.attrs.get(cid):
                tip += "\n⚠ No attribute could be found to filter on - ticking this downloads the whole " \
                       "feature type, not just these values."
            cls.setToolTip(0, tip)
            cls.setFlags(cls.flags() | _CHECKABLE)
            prev = set(was_ticked.get(cid) or ())
            for val in matched:
                leaf = QTreeWidgetItem([val])
                leaf.setData(0, ID_ROLE, cid)
                leaf.setData(0, VALUE_ROLE, val)
                leaf.setFlags(leaf.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                leaf.setCheckState(0, Qt.CheckState.Checked if val in prev else Qt.CheckState.Unchecked)
                cls.addChild(leaf)
            top.addChild(cls)
            n += 1
        for gk in GEOM_ORDER:
            top = groups[gk]
            if top.childCount():
                self.tree.addTopLevelItem(top)
                top.setExpanded(True)
                for j in range(top.childCount()):
                    cls = top.child(j)
                    cls.setExpanded(True)
                    self._refresh_class_state(cls)
        self.tree.resizeColumnToContents(0)
        self.tree.blockSignals(False)
        self.status.setText(f"{n} feature type(s) described as '{term}'. Tick the description(s) you "
                            "actually want under each - only those are downloaded.")
        self._selection_changed()

    def _refresh_class_state(self, cls):
        """Sets a feature-type row's own tri-state checkbox from its ticked description values (so a
        carried-over tick, re-applied after a new search, shows correctly without a user click)."""
        if cls.childCount() == 0:
            return
        states = {cls.child(j).checkState(0) for j in range(cls.childCount())}
        cls.setCheckState(0, states.pop() if len(states) == 1 else Qt.CheckState.PartiallyChecked)

    def _item_changed(self, item, _col):
        if item.data(0, ID_ROLE) is not None:
            self._selection_changed()

    def checked(self):
        """{collection id: sorted [ticked description value(s)]} for every feature type with at least one
        ticked value. Ticking a feature type's own row ticks every value under it (built-in Qt tri-state
        cascade); this just reads the result back out, leaf by leaf."""
        out = {}
        for i in range(self.tree.topLevelItemCount()):
            group = self.tree.topLevelItem(i)
            for j in range(group.childCount()):
                cls = group.child(j)
                cid = cls.data(0, ID_ROLE)
                vals = sorted(cls.child(k).data(0, VALUE_ROLE) for k in range(cls.childCount())
                              if cls.child(k).checkState(0) == Qt.CheckState.Checked)
                if vals:
                    out[cid] = vals
        return out

    def clear_selection(self):
        self.tree.blockSignals(True)
        for i in range(self.tree.topLevelItemCount()):
            group = self.tree.topLevelItem(i)
            for j in range(group.childCount()):
                cls = group.child(j)
                cls.setCheckState(0, Qt.CheckState.Unchecked)
                for k in range(cls.childCount()):
                    cls.child(k).setCheckState(0, Qt.CheckState.Unchecked)
        self.tree.blockSignals(False)
        self._selection_changed()

    def _selection_changed(self):
        ticked = self.checked()
        labels = [f"{cid} ({', '.join(vals)})" for cid, vals in sorted(ticked.items())]
        self.picked.setText("Ticked: " + ", ".join(labels) if labels else "Nothing ticked yet.")

    def _where_for(self, c, values):
        """The CQL filter restricting ``c`` to just ``values`` (the description value(s) you ticked for
        it) - already known from the local index, no network needed - or None if no attribute could be
        found to filter on (the caller should then say the whole feature type was downloaded, not just the
        tick)."""
        attr = self.attrs.get(c)
        return cql_for_values(attr, values) if attr else None

    # ---------------------------------------------------------------- rebuild the local index
    def rebuild_index(self):
        if self.task is not None:
            return
        api_key = S.load_api_key()
        if not api_key:
            self.status.setText("Add an API key on the ⚙ Settings tab first - rebuilding checks every OS "
                                "NGD feature type once, which needs one.")
            return
        client = NgdFeaturesClient(api_key, transport=QgisTransport(), budget=Budget())

        def work(task):
            return NI.build(client, progress=task.report, is_cancelled=task.isCanceled)

        def finished(result, error):
            self._finish()
            if error is not None:
                self.status.setText(f"✖ {error}")
                return
            NI.save(result)
            self.index = result
            self._update_index_label()
            self._populate_desc_combo()
            self.status.setText(f"✔ Local index rebuilt: {len(result)} OS NGD feature types checked. "
                                "Searching is instant and up to date again.")

        self._start(FunctionTask("OS API Data Downloader - indexing OS NGD feature types", work, finished),
                    "Building a local index of every OS NGD feature type (one-off, roughly a minute)…")

    # ---------------------------------------------------------------- estimate / download
    def estimate(self, then=None):
        if self.task is not None:
            return
        ticked = self.checked()
        if not ticked:
            self.status.setText("Tick at least one description value above (search first if the list is "
                                "empty).")
            return
        area = self._area()
        if area is None:
            return
        _, bbox, wkt = area
        client = self.client()

        def work(task):
            out = {}
            items = list(ticked.items())
            for i, (c, values) in enumerate(items):
                if task.isCanceled():
                    break
                task.report(100 * i / len(items), f"Counting {c}")
                where = self._where_for(c, values)
                out[c] = (client.estimate_count(c, bbox, wkt, where=where)[0], where)
            return out, client.budget.used

        def finished(result, error):
            self._finish()
            if error is not None:
                self.status.setText(f"✖ {error}")
                return
            est, used = result
            self.estimates = {c: n for c, (n, _) in est.items()}
            tx = sum(pages(n) for n, _ in est.values())
            lines = [f"<b>About {tx:,} transaction(s)</b> to download {sum(n for n, _ in est.values()):,} "
                     f"feature(s) in the {self.area.description()} · counting used {used} transaction(s)"]
            for c, (n, where) in est.items():
                vals = ", ".join(ticked[c])
                lines.append(f"{c}: ~{n:,} features matching {vals}" if where else
                             f"{c}: ~{n:,} features ⚠ couldn't narrow to {vals} - this counts the whole "
                             "feature type")
            self.status.setText("<br>".join(lines))
            if then:
                # start the download after this task has fully finished (see FeaturesTab.estimate)
                QTimer.singleShot(0, lambda: then(tx))

        self._start(FunctionTask("OS API Data Downloader - counting OS NGD features", work, finished),
                    "Counting features in your area…")

    def download(self):
        if self.task is not None:
            self.task.cancel()
            return
        ticked = self.checked()
        if not ticked:
            self.status.setText("Tick at least one description value above (search first if the list is "
                                "empty).")
            return
        if not all(c in self.estimates for c in ticked):
            self.estimate(then=lambda tx: self._confirm_and_download(ticked, tx))
            return
        self._confirm_and_download(ticked, sum(pages(self.estimates[c]) for c in ticked))

    def _confirm_and_download(self, ticked, tx):
        confirm = S.get("confirm_over")
        if confirm and tx > confirm and QMessageBox.question(
                self, "OS API Data Downloader", f"This download needs about {tx:,} OS NGD API - Features "
                                        "transactions. Continue?") != QMessageBox.StandardButton.Yes:
            self.status.setText(self.status.text() + "<br>Stopped before downloading.")
            return
        area = self._area()
        if area is None:
            return
        geom, bbox, wkt = area
        folder = S.output_folder()
        os.makedirs(folder, exist_ok=True)
        stamp = _dt.datetime.now()
        stub = filename_stub(self.term.text(), ticked)
        out = os.path.join(folder, f"os_ngd_{stub}_{stamp:%Y%m%d_%H%M%S}.gpkg")
        k = 2
        while os.path.exists(out):      # two downloads in the same second must never share a file
            out = os.path.join(folder, f"os_ngd_{stub}_{stamp:%Y%m%d_%H%M%S}_{k}.gpkg")
            k += 1
        mode = self.area.clip()
        where = self.area.description()
        client = self.client(self.limit.value() or None)
        expected = dict(self.estimates)

        def work(task):
            results = []
            with tempfile.TemporaryDirectory(prefix="osdl_") as tmp:
                items = list(ticked.items())
                for i, (c, values) in enumerate(items):
                    if task.isCanceled():
                        break
                    seq = os.path.join(tmp, f"{C._safe_name(c)}.geojsons")
                    lo, hi = 100 * i / len(items), 100 * (i + 1) / len(items)

                    def prog(p, m=None, lo=lo, hi=hi):
                        task.report(lo + (hi - lo) * p / 100, m)
                    attr_where = self._where_for(c, values)
                    info = client.download(c, bbox, seq, wkt, expected=expected.get(c), progress=prog,
                                           is_cancelled=task.isCanceled, where=attr_where)
                    n = C.geojsonseq_to_gpkg(seq, geom, out, c, mode) if info["features"] else 0
                    results.append((c, info, n, attr_where))
                    if info["truncated"]:
                        break
            return results, client.budget.used

        def finished(result, error):
            self._finish()
            if error is not None and not result:
                self.status.setText(f"✖ {error}")
                return
            results, used = result
            root = QgsProject.instance().layerTreeRoot()
            group = root.insertGroup(0, f"OS NGD search - {where} ({stamp:%d %b %Y %H:%M})")
            lines = [f"✔ Saved to {out} · {used:,} transaction(s)"]
            for c, info, n, attr_where in results:
                if n:
                    label = ", ".join(ticked.get(c) or ()) or c   # the ticked value(s), not the bare cid
                    lyr = QgsVectorLayer(f"{out}|layername={C._safe_name(c)}", label, "ogr")
                    if lyr.isValid():
                        QgsProject.instance().addMapLayer(lyr, False)
                        node = group.addLayer(lyr)
                        node.setCustomProperty("showFeatureCount", True)
                note = " - stopped at the transaction limit (partial)" if info["truncated"] else ""
                vals = ", ".join(ticked.get(c) or ())
                flt = f" matching {vals}" if attr_where else (f" ⚠ couldn't narrow to {vals} - the whole "
                      "feature type was downloaded" if vals else "")
                lines.append(f"{c}: {n:,} feature(s){flt} in the {where} (from {info['features']:,} downloaded){note}")
            if not group.children():
                root.removeChildNode(group)
            if any(info.get("cancelled") for _, info, _, _ in results):
                lines.append("Cancelled - partial download.")
            self.status.setText("<br>".join(lines))
            self.last_output = out

        self._start(FunctionTask("OS API Data Downloader - downloading OS NGD search results", work, finished),
                    "Downloading…")

    def cleanup(self):
        if self.task is not None:
            self.task.cancel()
