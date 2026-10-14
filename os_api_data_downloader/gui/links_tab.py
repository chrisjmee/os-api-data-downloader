"""NGD Data Linkages: pick OS NGD feature types *and the links between them* in a tree, then download them
for the area with the linkages already made.

The tree follows the 'Find an NGD Feature Type' tab: themes, then feature types (tick to download), and
under each feature type the links it takes part in - '→' links it holds (e.g. Building → Site via
primarysiteid), '←' links that point at it. Ticking a link ticks both feature types it joins. '🔗' links are
stored in the data (identifiers and cross-references); '⇢' links are spatially derived and only shown when
asked for. Selecting any row explains it underneath - what the link is, which attribute carries it, its
class and cardinality - from the register in ``core.ngd_links``.

The download itself is in ``gui.linking``: one GeoPackage with a layer per feature type, a link table per
link, a register of the links, optional joined copies, and QGIS relations so a feature's form lists what it
is linked to.
"""

from __future__ import annotations

import datetime as _dt
import os
import tempfile
import time

from qgis.core import QgsProject, QgsVectorLayer
from qgis.PyQt.QtCore import Qt, QTimer
from qgis.PyQt.QtGui import QBrush, QColor
from qgis.PyQt.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFrame, QScrollArea, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QProgressBar, QPushButton, QSpinBox, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
    QWidget,
)

from ..core import ngd_index as NI
from ..core import ngd_links as NL
from ..core import places as P
from ..core.budget import Budget
from ..core.ngd_features import NgdFeaturesClient
from ..core.ngd_search import cql_for_values
from ..core.transport import QgisTransport
from . import answer_style as AS
from . import clipping as C
from . import linking as LK
from . import settings as S
from .tasks import FunctionTask, start

KIND_ROLE = Qt.ItemDataRole.UserRole + 1     # 'theme' | 'type' | 'link'
ID_ROLE = Qt.ItemDataRole.UserRole + 2       # theme name | base id | link id
SIDE_ROLE = Qt.ItemDataRole.UserRole + 3     # for links: 'out' (held by this type) | 'in'
GREY = QBrush(QColor("#8a8a8a"))
# link colours by type, in two sets so they stay readable on QGIS's light and dark themes
_LIGHT = {"A": "#1559b8", "B": "#17773f", "C": "#8a4f12", "D": "#b34700"}
_DARK = {"A": "#8ab8ff", "B": "#7ad69b", "C": "#e5ae6e", "D": "#ffa45c"}
LEGEND = [("A", "🔗 Stored ID"), ("B", "🔗 Network connection"), ("C", "🔗 Sits within"),
          ("D", "⇢ Worked out from location")]


def dark_theme():
    from qgis.PyQt.QtWidgets import QApplication
    app = QApplication.instance()
    return bool(app) and app.palette().window().color().lightness() < 128


def class_colours():
    return _DARK if dark_theme() else _LIGHT


def muted():
    """Colour for secondary text that is readable on either theme."""
    return "#a8a8a8" if dark_theme() else "#5f5f5f"


def warn():
    return "#ffb070" if dark_theme() else "#a84800"


def legend_html():
    """The link-colour key as small coloured chips with high-contrast text."""
    cols = class_colours()
    fg = "#111111" if dark_theme() else "#ffffff"
    chips = [f"<span style='background-color:{cols[k]};color:{fg};font-weight:600'>&nbsp;"
             f"{t.replace(' ', '&nbsp;')}&nbsp;</span>" for k, t in LEGEND]      # a chip never splits over lines
    return " ".join(chips)


def pages(n):
    """Transactions to download n features; None = 'more than a page' (at least 2)."""
    return 2 if n is None else -(-int(n) // 100)


class ValuesDialog(QDialog):
    """Tick description values of one feature type (from the local index), like the Find tab."""

    def __init__(self, title, values, ticked, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Only some {title} features")
        v = QVBoxLayout(self)
        v.addWidget(QLabel(f"Only download (and link) {title} features described as… Leave everything unticked "
                           "for all of them."))
        self.find = QLineEdit()
        self.find.setPlaceholderText("Find a value, e.g. school…")
        self.find.setClearButtonEnabled(True)
        v.addWidget(self.find)
        self.list = QListWidget()
        for val in values:
            it = QListWidgetItem(val)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked if val in ticked else Qt.CheckState.Unchecked)
            self.list.addItem(it)
        v.addWidget(self.list, 1)
        self.find.textChanged.connect(self._filter)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)
        self.resize(380, 460)

    def _filter(self, text):
        t = (text or "").lower()
        for i in range(self.list.count()):
            self.list.item(i).setHidden(bool(t) and t not in self.list.item(i).text().lower())

    def values(self):
        return [self.list.item(i).text() for i in range(self.list.count())
                if self.list.item(i).checkState() == Qt.CheckState.Checked]


def prebuild_layers(result, simple):
    """Opens the output layers in the worker thread (a QgsVectorLayer can be made there and handed to the
    main thread) - the main thread then only has to add them. {(path, layer name): layer}."""
    from qgis.core import QgsCoordinateTransformContext
    from qgis.PyQt.QtCore import QCoreApplication
    opts = QgsVectorLayer.LayerOptions(QgsCoordinateTransformContext())
    opts.loadDefaultStyle = False
    opts.readExtentFromXml = False
    out = result["out"]
    names = [(out, LK.layer_name(t)) for t in result["written"]]
    if result.get("answer"):
        names.append((out, result["answer"]))
    for _t, jname in (result.get("joined") or {}).items():
        names.append((result.get("joined_out") or out, jname))
    if not simple:
        names += [(out, tname) for tname, _ in result["tables"]] + [(out, "ngd_link_register")]
    main = QCoreApplication.instance().thread()
    built = {}
    for path, name in names:
        lyr = QgsVectorLayer(f"{path}|layername={name}", name, "ogr", opts)
        if lyr.isValid():
            lyr.moveToThread(main)
            built[(path, name)] = lyr
    return built


class LinksTab(QWidget):
    def __init__(self, iface, area, parent=None):
        super().__init__(parent)
        self.iface = iface
        self.area = area
        self.task = None
        self.estimates = {}
        self._first_pages = {}   # base -> features: in a small area the estimate reads everything already
        self._est_key = None
        self.filters = {}        # base id -> [description values]
        self.index = NI.load() or {}
        self.type_items = {}     # base id -> item
        self.link_items = {}     # link id -> [items]
        self.theme_items = {}
        self._syncing = False
        v = QVBoxLayout(self)

        self.intro = QLabel("Tick the OS NGD feature types you want, then open one to tick how it <b>links</b> to "
                            "others - e.g. a Building → <i>the Site it mainly belongs to</i>. The download joins "
                            "them for you, and fetches linked features just outside your area too.")
        self.intro.setWordWrap(True)
        v.addWidget(self.intro)

        row = QHBoxLayout()
        self.recipe = QComboBox()
        self.recipe.addItem("Quick pick - start from a question…", None)
        self._recipe_header("Show off OS NGD")
        for i, r in enumerate(NL.SHOWCASE_RECIPES):
            self.recipe.addItem(f"{r['name']} - \"{r['question']}\"", ("s", i))
        self._recipe_header("Answer a question")
        for i, r in enumerate(NL.RECIPES):
            self.recipe.addItem(f"{r['name']} - \"{r['question']}\"", ("q", i))
        self.recipe.addItem("10. How are two feature types connected? (find the path…)", "path")
        self._recipe_header("For data engineers")
        for i, r in enumerate(NL.ENGINEER_RECIPES):
            self.recipe.addItem(r["name"], ("e", i))
        self.recipe.addItem("Everything available, with every stored link", "all")
        self.recipe.view().setMinimumWidth(560)     # room for the questions in the drop-down
        self.recipe.activated.connect(self._apply_recipe)
        row.addWidget(self.recipe, 1)
        v.addLayout(row)

        row = QHBoxLayout()
        self.find = QLineEdit()
        self.find.setPlaceholderText("Find a feature type or link, e.g. site, usrn…")
        self.find.setClearButtonEnabled(True)
        self.find.textChanged.connect(self._filter)
        self.show_spatial = QCheckBox("Show spatial links")
        self.show_spatial.setToolTip("Also offer links calculated from geometry (e.g. address inside a building). "
                                     "They're labelled ⇢ and 'derived' - not authoritative identifier links.")
        self.show_spatial.toggled.connect(self._spatial_toggled)
        row.addWidget(self.find, 1)
        row.addWidget(self.show_spatial)
        v.addLayout(row)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setMinimumHeight(320)
        self.tree.itemChanged.connect(self._item_changed)
        self.tree.currentItemChanged.connect(lambda *_: self._show_details())
        self.tree.itemDoubleClicked.connect(lambda it, _c: self.edit_filter(it))
        v.addWidget(self.tree, 1)
        self._populate()

        self.details = QLabel()
        self.details.setWordWrap(True)
        self.details.setTextFormat(Qt.TextFormat.RichText)
        self.details.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.details.setStyleSheet("QLabel{background:palette(alternate-base);border:1px solid palette(mid);"
                                   "border-radius:4px;padding:6px;}")
        self.details.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.details_box = QScrollArea()          # long explanations scroll instead of being cut off
        self.details_box.setWidgetResizable(True)
        self.details_box.setFrameShape(QFrame.Shape.NoFrame)
        self.details_box.setWidget(self.details)
        self.details_box.setMinimumHeight(90)
        self.details_box.setMaximumHeight(170)
        # the colour key is always on show (not only before anything is selected)
        self.legend = QLabel(legend_html())
        self.legend.setTextFormat(Qt.TextFormat.RichText)
        self.legend.setWordWrap(True)
        self.legend.setToolTip("Stored ID: OS records the other feature's ID in the data.\n"
                               "Network connection: part of how the road / path / rail / water network joins up.\n"
                               "Sits within: OS records what the feature lies inside (e.g. its Site).\n"
                               "Worked out from location: calculated by the plugin from where features are.")
        v.addWidget(self.legend)
        v.addWidget(self.details_box)

        row = QHBoxLayout()
        self.link_all_btn = QPushButton("Link everything ticked")
        self.link_all_btn.setToolTip("Tick every link between the feature types you've ticked.")
        self.link_all_btn.clicked.connect(self.link_all)
        self.filter_btn = QPushButton("⧩ Filter…")
        self.filter_btn.setToolTip("Only download some features of the highlighted feature type, by what they're "
                                   "described as (e.g. only School sites). Or double-click a feature type.")
        self.filter_btn.clicked.connect(lambda: self.edit_filter())
        self.clear_btn = QPushButton("Clear selection")
        self.clear_btn.clicked.connect(self.clear_selection)
        row.addWidget(self.link_all_btn)
        row.addWidget(self.filter_btn)
        row.addStretch(1)
        row.addWidget(self.clear_btn)
        v.addLayout(row)

        self.picked = QLabel("Nothing ticked yet.")
        self.picked.setWordWrap(True)
        self.picked.setTextFormat(Qt.TextFormat.RichText)
        v.addWidget(self.picked)

        self.outside = QCheckBox("Fetch linked features outside the area by their ID")
        self.outside.setChecked(True)
        self.outside.setToolTip("E.g. the Road Node at the far end of a Road Link, or the rest of a Site. Costs "
                                "extra transactions (about 1 per 40 features), counted against 'Stop after'.")
        v.addWidget(self.outside)
        self.open_table = QCheckBox("Open the answer's attribute table when it's ready")
        self.open_table.setChecked(bool(S.get("links_open_table")))
        self.open_table.setToolTip("Off: the answer is added to the map only - click a feature with Identify, or "
                                   "right-click the layer > Open Attribute Table. Remembered.")
        self.open_table.toggled.connect(lambda on: S.set_("links_open_table", bool(on)))
        v.addWidget(self.open_table)
        row = QHBoxLayout()
        row.addWidget(QLabel("Show me"))
        self.view = QComboBox()
        self.view.addItem("Just the answer (simplest)", "simple")
        self.view.addItem("Everything - layers, joined copies and link tables", "all")
        self.view.setToolTip("'Just the answer': for a Quick pick question you get ONE layer that answers it - one "
                             "row per address, site, entrance… with plain columns such as 'Building use' and "
                             "'Site name' - and its table opens for you. The layers it was built from are kept, "
                             "switched off, in 'Supporting layers'.\n'Everything': every layer, a joined copy of "
                             "each and the link tables, for data engineers.")
        self.view.currentIndexChanged.connect(self._view_changed)
        row.addWidget(self.view, 1)
        v.addLayout(row)
        row = QHBoxLayout()
        self.joined_label = QLabel("Joined copies")
        row.addWidget(self.joined_label)
        self.joined = QComboBox()
        self.joined.addItem("In the same file as the layers", "same")
        self.joined.addItem("All together in a file of their own", "separate")
        self.joined.addItem("Don't make joined copies", None)
        self.joined.setToolTip("A joined copy is a layer with the linked features' details written into its own "
                               "table - e.g. each Building with its Site's description. 'A file of their own' "
                               "puts every joined layer together in one extra GeoPackage (…_joined.gpkg), "
                               "ready to share or open on its own.")
        row.addWidget(self.joined, 1)
        v.addLayout(row)
        self.show_tables = QCheckBox("Add the link tables to the map")
        self.show_tables.setChecked(True)
        v.addWidget(self.show_tables)
        self._recipe = None      # the Quick pick question being answered, if any

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
        self.go = QPushButton("Download linked data for my area")
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
        self._view_changed()
        self._spatial_toggled(False)
        self._selection_changed()
        self._show_details()

    def refresh_settings(self):
        self.limit.setValue(S.get("hard_limit"))

    # ---------------------------------------------------------------- tree
    def _link_text(self, lk, side):
        """Plain English: under Building '→ the Site it mainly belongs to'; under Site '← Buildings that
        mainly belong to this Site'. The technical detail is in the tooltip and the panel below."""
        icon = "🔗" if lk["kind"] == "id" else "⇢"
        text = lk["fwd"] if side == "out" else lk["back"]
        text = text[:1].upper() + text[1:]
        if lk["kind"] == "spatial":
            text += " (worked out from location)"
        return f"{icon} {'→' if side == 'out' else '←'} {text}"

    @staticmethod
    def _link_tip(lk):
        if lk["kind"] == "id":
            how = f"Stored in: {' / '.join(lk['fields'])}" + (f" (or {' / '.join(lk['rev'])})" if lk["rev"] else "")
        else:
            how = f"Worked out from location ({lk['op']}" + (f", within {lk['tol']:g} m)" if lk["tol"] else ")")
        return f"{NL.say(lk)}\n{NL.card_sentence(lk)}\n{how}"

    def _populate(self):
        self.tree.blockSignals(True)
        self.tree.clear()
        for theme, items in NL.THEMES:
            top = QTreeWidgetItem([theme])
            top.setData(0, KIND_ROLE, "theme")
            top.setData(0, ID_ROLE, theme)
            font = top.font(0)
            font.setBold(True)
            top.setFont(0, font)
            top.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsUserCheckable)
            top.setCheckState(0, Qt.CheckState.Unchecked)
            self.theme_items[theme] = top
            for base, ttl, note in items:
                info = NL.TYPES[base]
                it = QTreeWidgetItem([ttl + ("  ⚠ legacy" if info["legacy"] else "")])
                it.setData(0, KIND_ROLE, "type")
                it.setData(0, ID_ROLE, base)
                tip = base if info["available"] else info["note"]
                if note and info["available"]:
                    tip += "\n" + info["note"]
                it.setToolTip(0, tip)
                if info["available"]:
                    it.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable |
                                Qt.ItemFlag.ItemIsUserCheckable)
                    it.setCheckState(0, Qt.CheckState.Unchecked)
                    self.type_items[base] = it
                else:
                    it.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                    it.setForeground(0, GREY)
                    it.setText(0, f"{ttl}  (not available)")
                for lk in NL.links_for(base):
                    sides = ["out"] if lk["holder"] == base else []
                    if lk["target"] == base and lk["holder"] != base:
                        sides.append("in")
                    for side in sides:
                        li = QTreeWidgetItem([self._link_text(lk, side)])
                        li.setData(0, KIND_ROLE, "link")
                        li.setData(0, ID_ROLE, lk["id"])
                        li.setData(0, SIDE_ROLE, side)
                        li.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable |
                                    Qt.ItemFlag.ItemIsUserCheckable)
                        li.setCheckState(0, Qt.CheckState.Unchecked)
                        li.setForeground(0, QBrush(QColor(class_colours()[lk["cls"]])))
                        li.setToolTip(0, self._link_tip(lk))
                        it.addChild(li)
                        self.link_items.setdefault(lk["id"], []).append(li)
                top.addChild(it)
            self.tree.addTopLevelItem(top)
            top.setExpanded(True)
        self.tree.blockSignals(False)

    def _filter(self, text=None):
        t = (self.find.text() if text is None else text).strip().lower()
        spatial = self.show_spatial.isChecked()
        for i in range(self.tree.topLevelItemCount()):
            top = self.tree.topLevelItem(i)
            any_type = False
            theme_hit = bool(t) and t in top.text(0).lower()
            for j in range(top.childCount()):
                it = top.child(j)
                base = it.data(0, ID_ROLE)
                type_hit = not t or theme_hit or t in it.text(0).lower() or t in str(base).lower()
                any_link = False
                for k in range(it.childCount()):
                    li = it.child(k)
                    lk = NL.LINK_BY_ID[li.data(0, ID_ROLE)]
                    allowed = spatial or lk["kind"] == "id"
                    hit = type_hit or (t and (t in li.text(0).lower() or t in " ".join(lk["fields"]).lower()))
                    li.setHidden(not allowed or not hit)
                    any_link = any_link or (allowed and hit)
                show = type_hit or any_link
                it.setHidden(not show)
                if t and any_link:
                    it.setExpanded(True)
                elif not t:
                    it.setExpanded(False)
                any_type = any_type or show
            top.setHidden(not any_type)

    def _spatial_toggled(self, on):
        if not on:
            self._syncing = True
            self.tree.blockSignals(True)
            for lid, items in self.link_items.items():
                if NL.LINK_BY_ID[lid]["kind"] == "spatial":
                    for li in items:
                        li.setCheckState(0, Qt.CheckState.Unchecked)
            self.tree.blockSignals(False)
            self._syncing = False
        self._filter()
        self._selection_changed()

    def _set_link(self, lid, state):
        for li in self.link_items.get(lid, ()):
            li.setCheckState(0, state)

    def _item_changed(self, item, _col):
        if self._syncing:
            return
        kind = item.data(0, KIND_ROLE)
        state = item.checkState(0)
        self._syncing = True
        self.tree.blockSignals(True)
        try:
            if kind == "theme":
                if state != Qt.CheckState.PartiallyChecked:
                    for j in range(item.childCount()):
                        base = item.child(j).data(0, ID_ROLE)
                        if base in self.type_items and not item.child(j).isHidden():
                            self.type_items[base].setCheckState(0, state)
                            if state == Qt.CheckState.Unchecked:
                                self._untick_links_of(base)
            elif kind == "type":
                if state == Qt.CheckState.Unchecked:
                    self._untick_links_of(item.data(0, ID_ROLE))
            elif kind == "link":
                lid = item.data(0, ID_ROLE)
                self._set_link(lid, state)
                if state == Qt.CheckState.Checked:
                    lk = NL.LINK_BY_ID[lid]
                    for base in (lk["holder"], lk["target"]):
                        if base in self.type_items:
                            self.type_items[base].setCheckState(0, Qt.CheckState.Checked)
            self._refresh_themes()
        finally:
            self.tree.blockSignals(False)
            self._syncing = False
        self._selection_changed()

    def _untick_links_of(self, base):
        for lk in NL.links_for(base):
            self._set_link(lk["id"], Qt.CheckState.Unchecked)

    def _refresh_themes(self):
        for theme, top in self.theme_items.items():
            states = {self.type_items[b].checkState(0) for b in
                      (top.child(j).data(0, ID_ROLE) for j in range(top.childCount())) if b in self.type_items}
            if not states:
                top.setFlags(top.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
                top.setData(0, Qt.ItemDataRole.CheckStateRole, None)
                continue
            top.setCheckState(0, states.pop() if len(states) == 1 else Qt.CheckState.PartiallyChecked)

    def checked_types(self):
        return [b for b, it in self.type_items.items() if it.checkState(0) == Qt.CheckState.Checked]

    def checked_links(self):
        return [lid for lid, items in self.link_items.items() if items[0].checkState(0) == Qt.CheckState.Checked]

    def set_selection(self, types, links):
        """Replace the ticks (used by the quick picks and tests)."""
        self._syncing = True
        self.tree.blockSignals(True)
        try:
            for b, it in self.type_items.items():
                it.setCheckState(0, Qt.CheckState.Checked if b in types else Qt.CheckState.Unchecked)
            for lid in self.link_items:
                self._set_link(lid, Qt.CheckState.Checked if lid in links else Qt.CheckState.Unchecked)
                if lid in links:
                    lk = NL.LINK_BY_ID[lid]
                    for b in (lk["holder"], lk["target"]):
                        if b in self.type_items:
                            self.type_items[b].setCheckState(0, Qt.CheckState.Checked)
            self._refresh_themes()
        finally:
            self.tree.blockSignals(False)
            self._syncing = False
        self._selection_changed()

    def _view_changed(self, *_):
        everything = self.view.currentData() == "all"
        for w in (self.joined_label, self.joined, self.show_tables):
            w.setVisible(everything)

    def clear_selection(self):
        self._recipe = None
        self.filters = {}
        self._mark_filters()
        self.set_selection([], [])

    def link_all(self):
        types = set(self.checked_types())
        if len(types) < 1:
            self.status.setText("Tick some feature types first, then press 'Link everything ticked'.")
            return
        spatial = self.show_spatial.isChecked()
        links = set(self.checked_links())
        for lk in NL.LINKS:
            if lk["holder"] in types and lk["target"] in types and (lk["kind"] == "id" or spatial):
                links.add(lk["id"])
        self.set_selection(types, links)
        self.status.setText(f"{len(links)} link(s) ticked between your {len(types)} feature type(s).")

    def _recipe_header(self, text):
        self.recipe.addItem(f"── {text} ──", None)
        item = self.recipe.model().item(self.recipe.count() - 1)
        item.setEnabled(False)

    def _apply_recipe(self, index):
        data = self.recipe.itemData(index)
        self.recipe.setCurrentIndex(0)
        if data is None:
            return
        self._recipe = None
        if data == "path":
            self.find_path()
            return
        if data == "all":
            types = [b for b in self.type_items]
            links = [lk["id"] for lk in NL.LINKS if lk["kind"] == "id"]
            self.filters = {}
            self._mark_filters()
            self.set_selection(types, links)
            self.status.setText("Everything ticked - that's a lot of transactions for anything but a small area: "
                                "press 'Estimate cost' first.")
            return
        kind, i = data
        r = {"q": NL.RECIPES, "s": NL.SHOWCASE_RECIPES}.get(kind, NL.ENGINEER_RECIPES)[i]
        self.filters = {t: list(v) for t, v in (r.get("filters") or {}).items()}
        self._mark_filters()
        # spatial links (worked out from location) only when 'Show spatial links' is on - off by default
        spatial = self.show_spatial.isChecked()
        self.set_selection(r["types"], [lid for lid in r["links"]
                                        if spatial or NL.LINK_BY_ID[lid]["kind"] == "id"])
        self._recipe = r
        self.tree.setCurrentItem(None)
        self._show_recipe(r)
        self.status.setText(f"Ticked: {r['name']}. Untick anything you don't need, or add more.")

    def _show_recipe(self, r):
        html = f"<b>{r['name']}</b>"
        if r.get("question"):
            html += f"<br><i>\u201c{r['question']}\u201d</i>"
        if r.get("path"):
            html += f"<br>Path: {r['path']}"
        if r.get("answers"):
            html += f"<br>Answers: {r['answers']}"
        if r.get("filters"):
            for t, v in r["filters"].items():
                html += f"<br>⧩ Only {NL.plural(t)} described as: {', '.join(v[:5])}{'…' if len(v) > 5 else ''}"
        if r.get("answer"):
            names = [c[1] for c in r["answer"]["columns"] if not c[1].endswith(" ID")]
            html += (f"<br>You'll get: <b>{r['answer']['title']}</b> - {len(names)} columns, including "
                     + ", ".join(names[:14]) + (f" and {len(names) - 14} more" if len(names) > 14 else "") + ".")
        if r.get("note"):
            html += f"<br><span style='color:{muted()}'>{r['note']}</span>"
        self.details.setText(html)

    def find_path(self):
        """Quick pick 10: choose a start and an end feature type; the shortest chain of links between them
        is ticked and explained step by step."""
        dlg = QDialog(self)
        dlg.setWindowTitle("How are two feature types connected?")
        v = QVBoxLayout(dlg)
        v.addWidget(QLabel("Choose where to start and where to end. The shortest chain of links between them is "
                           "ticked, and each step is explained."))
        start, end = QComboBox(), QComboBox()
        for combo, default in ((start, NL.PLACES_ADDRESS), (end, "trn-ntwk-roadlink")):
            for theme, items in NL.THEMES:
                for base, ttl, _ in items:
                    if base in self.type_items:
                        combo.addItem(f"{ttl}  ({theme})", base)
            combo.setCurrentIndex(max(0, combo.findData(default)))
        for label, combo in (("Start", start), ("End", end)):
            row = QHBoxLayout()
            row.addWidget(QLabel(label))
            row.addWidget(combo, 1)
            v.addLayout(row)
        spatial = QCheckBox("Also use links worked out from location")
        spatial.setChecked(self.show_spatial.isChecked())
        v.addWidget(spatial)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(dlg.accept)
        bb.rejected.connect(dlg.reject)
        v.addWidget(bb)
        self._dialog = dlg
        if not dlg.exec():
            return None
        return self.show_path(start.currentData(), end.currentData(), spatial.isChecked())

    def show_path(self, a, b, spatial=False):
        steps = NL.find_path(a, b, spatial)
        if steps is None:
            self.details.setText(f"<b>{NL.noun(a)} → {NL.noun(b)}</b><br>No chain of links connects these in the "
                                 "data this plugin can download" + ("" if spatial else
                                                                     " - try again with links worked out from "
                                                                     "location") + ".")
            return None
        types = [a] + [lk["target"] if sd == "out" else lk["holder"] for lk, sd in steps]
        if spatial and any(lk["kind"] == "spatial" for lk, _ in steps):
            self.show_spatial.setChecked(True)
        self.filters = {}
        self._mark_filters()
        self.set_selection(types, [lk["id"] for lk, _ in steps])
        lines = NL.describe_path(a, steps)
        self.tree.setCurrentItem(None)
        self.details.setText(f"<b>How {NL.noun(a)} connects to {NL.noun(b)}</b> ({len(steps)} step(s))<br>"
                             + "<br>".join(lines))
        self.status.setText(f"Ticked the path from {NL.noun(a)} to {NL.noun(b)}.")
        return steps

    def _selection_changed(self):
        types = self.checked_types()
        links = self.checked_links()
        if not types:
            self.picked.setText("Nothing ticked yet.")
            return
        names = []
        for b in types:
            n = NL.title(b)
            if b in self.filters:
                n += f" <i>(only {', '.join(self.filters[b][:3])}{'…' if len(self.filters[b]) > 3 else ''})</i>"
            names.append(n)
        spatial = sum(1 for lid in links if NL.LINK_BY_ID[lid]["kind"] == "spatial")
        txt = f"<b>{len(types)}</b> feature type(s): {', '.join(names)}<br><b>{len(links)}</b> link(s)"
        if spatial:
            txt += f" ({spatial} spatial)"
        unlinked = [NL.title(b) for b in types if not any(
            b in (NL.LINK_BY_ID[lid]["holder"], NL.LINK_BY_ID[lid]["target"]) for lid in links)]
        if unlinked and links:
            txt += f" · not linked to anything: {', '.join(unlinked)}"
        self.picked.setText(txt)

    # ---------------------------------------------------------------- details
    def _show_details(self):
        it = self.tree.currentItem()
        if it is None:
            self.details.setText("Click a feature type or a link to see, in plain English, how it connects. "
                                 "The colours are explained in the key above.")
            self.filter_btn.setEnabled(False)
            return
        kind = it.data(0, KIND_ROLE)
        self.filter_btn.setEnabled(kind == "type" and self._values_for(it.data(0, ID_ROLE)) is not None)
        if kind == "theme":
            n = sum(1 for j in range(it.childCount()) if it.child(j).data(0, ID_ROLE) in self.type_items)
            self.details.setText(f"<b>{it.text(0)}</b> theme · {n} feature type(s) available. Tick the theme to "
                                 "tick all of them.")
            return
        if kind == "type":
            base = it.data(0, ID_ROLE)
            info = NL.TYPES[base]
            out = [lk for lk in NL.links_for(base) if lk["holder"] == base]
            inc = [lk for lk in NL.links_for(base) if lk["target"] == base and lk["holder"] != base]
            html = f"<b>{info['title']}</b> · {info['theme']}"
            if base in self.type_items:
                html += f" · <code>{base}</code>"
            if info["note"]:
                html += f"<br><span style='color:{warn()}'>{info['note']}</span>"
            html += (f"<br>Links to {len(out)} kind(s) of feature and is linked to from {len(inc)} - open it in "
                     "the tree to tick them.")
            if base in self.filters:
                html += f"<br>⧩ Only: {', '.join(self.filters[base])}"
            elif self._values_for(base):
                html += "<br>Double-click (or ⧩ Filter…) to download only some, e.g. by description."
            self.details.setText(html)
            return
        lk = NL.LINK_BY_ID[it.data(0, ID_ROLE)]
        cls_name, cls_text = NL.PLAIN_CLASSES[lk["cls"]]
        if lk["kind"] == "id":
            how = (f"OS stores this in the data: the {NL.noun(lk['holder'])}'s <code>{' / '.join(lk['fields'])}"
                   f"</code> holds the {NL.noun(lk['target'])}'s {lk['key'].upper()}")
            if lk["rev"]:
                how += f" (or the {NL.noun(lk['target'])} lists it in <code>{' / '.join(lk['rev'])}</code>)"
            how += ". The download checks the real data for it and says what it found."
        else:
            how = ("The plugin works this out from where the features are"
                   + (f" (nearest, within {lk['tol']:g} m)" if lk["tol"] else " (one inside the other)")
                   + " - OS doesn't supply it, so treat it as a best guess.")
        self.details.setText(
            f"<b>{NL.say(lk)}</b><br>"
            f"And the other way: {NL.say(lk, 'in')}<br>"
            f"{NL.card_sentence(lk)}<br>"
            f"<b>{cls_name}</b> - {cls_text}.<br>{how}"
            + (f"<br><i>{lk['note']}</i>" if lk["note"] else ""))

    # ---------------------------------------------------------------- description filters
    def _values_for(self, base):
        info = self.index.get(base) if self.index else None
        if not info or not info.get("attr") or not info.get("values"):
            return None
        return info

    def edit_filter(self, item=None):
        it = item or self.tree.currentItem()
        if it is None or it.data(0, KIND_ROLE) != "type":
            self.status.setText("Highlight a feature type in the tree first.")
            return None
        base = it.data(0, ID_ROLE)
        info = self._values_for(base)
        if info is None or base not in self.type_items:
            self.status.setText(f"{NL.title(base)} has no description values to filter on.")
            return None
        dlg = ValuesDialog(NL.title(base), info["values"], self.filters.get(base, []), self)
        self._dialog = dlg
        if not dlg.exec():
            return dlg
        vals = dlg.values()
        if vals:
            self.filters[base] = vals
            self.type_items[base].setCheckState(0, Qt.CheckState.Checked)
        else:
            self.filters.pop(base, None)
        self.estimates.pop(base, None)
        self._mark_filters()
        self._selection_changed()
        self._show_details()
        return dlg

    def _mark_filters(self):
        self.tree.blockSignals(True)
        for base, it in self.type_items.items():
            text = NL.title(base) + ("  ⚠ legacy" if NL.TYPES[base]["legacy"] else "")
            if base in self.filters:
                text += "  ⧩ filtered"
            it.setText(0, text)
            font = it.font(0)
            font.setBold(base in self.filters)
            it.setFont(0, font)
        self.tree.blockSignals(False)

    def where(self, base):
        vals = self.filters.get(base)
        info = self._values_for(base)
        if not vals or not info:
            return None
        return cql_for_values({"name": info["attr"], "type": "string"}, vals)

    # ---------------------------------------------------------------- helpers
    def _start(self, task, label):
        self.task = task

        def progress(p, task=task):
            self.progress.setValue(int(p))
            if getattr(task, "message", ""):       # say what it's doing, not just 'Downloading…'
                self.status.setText(f"{task.message}…")
        task.progressChanged.connect(progress)
        self.progress.setValue(0)
        self.progress.setVisible(True)
        self.go.setText("Cancel")
        self.estimate_btn.setEnabled(False)
        self.status.setText(label)
        start(task)

    def _finish(self):
        self.task = None
        self.progress.setVisible(False)
        self.go.setText("Download linked data for my area")
        self.estimate_btn.setEnabled(True)

    def _area(self):
        try:
            geom = self.area.geometry_bng()
        except ValueError as ex:
            self.status.setText(f"✖ {ex}")
            return None
        bb = geom.boundingBox()
        # a rectangle (map view, drawn window) is exactly its bounding box: send just the box - OS answers a
        # plain bbox from its spatial index, quicker than also testing an INTERSECTS shape on every feature
        rect = abs(geom.area() - bb.width() * bb.height()) < 1e-6 * max(1.0, geom.area())
        wkt = None if rect else self.area.filter_wkt(geom)
        return geom, (bb.xMinimum(), bb.yMinimum(), bb.xMaximum(), bb.yMaximum()), wkt

    def _area_changed(self):
        self._first_pages = {}
        if self.estimates:
            self.estimates = {}
            self.status.setText("The area changed - press 'Estimate cost' again for an up-to-date cost.")

    def _clients(self, limit=None):
        budget = Budget(limit)       # one budget for every API this download uses
        key = S.load_api_key()
        ngd = NgdFeaturesClient(key, transport=QgisTransport(), budget=budget)
        # with any address link, the LPI records come too: they hold the non-postal UPRNs (parent shells,
        # non-addressable objects) and USRNs that NGD links to - read in bulk, not one by one
        lpi = any(NL.PLACES_ADDRESS in (NL.LINK_BY_ID[lid]["holder"], NL.LINK_BY_ID[lid]["target"])
                  for lid in self.checked_links())
        places = P.PlacesClient(key, transport=QgisTransport(), budget=budget, include_dpa=True,
                                include_lpi=lpi) if NL.PLACES_ADDRESS in self.checked_types() else None
        return ngd, places

    def _check_ready(self):
        if not S.load_api_key():
            self.status.setText("✖ Add an API key on the ⚙ Settings tab (its project needs OS NGD API - Features, "
                                "and OS Places API for addresses).")
            return False
        if not self.checked_types():
            self.status.setText("Tick at least one feature type (or use a Quick pick).")
            return False
        return True

    # ---------------------------------------------------------------- estimate
    def estimate(self, then=None, quick=False):
        if self.task is not None or not self._check_ready():
            return
        area = self._area()
        if area is None:
            return
        geom, bbox, wkt = area
        ngd, places = self._clients()
        types = self.checked_types()
        wheres = {t: self.where(t) for t in types}
        cells = LK.tiles(bbox[0] - LK.ADDRESS_MARGIN, bbox[1] - LK.ADDRESS_MARGIN, bbox[2] + LK.ADDRESS_MARGIN, bbox[3] + LK.ADDRESS_MARGIN) if places is not None else []

        t_est = time.monotonic()

        def work(task):
            cids = LK.latest_collections(ngd)
            ngd_types = [t for t in types if t != NL.PLACES_ADDRESS and t in cids]
            first = {}
            out = LK.estimate_counts(ngd, cids, ngd_types, bbox, wkt, wheres, task, first, quick)   # several at once
            return out, ngd.budget.used, [t for t in types if t != NL.PLACES_ADDRESS and t not in cids], first

        def finished(result, error):
            self._finish()
            if error is not None:
                self.status.setText(f"✖ {error}")
                return
            est, used, missing, first = result
            self._est_secs = time.monotonic() - t_est
            self.estimates = est
            self._first_pages = first
            self._est_key = (tuple(sorted(types)), tuple(sorted((k, v or "") for k, v in wheres.items())))
            tx = sum(pages(n) for n in est.values()) + len(cells)
            unknown = [t for t, n in est.items() if n is None]
            known = sum(n for n in est.values() if n is not None)
            lines = [f"<b>{'At least' if unknown else 'About'} {tx:,} transaction(s)</b> for "
                     f"{'more than ' if unknown else ''}{known + 100 * len(unknown):,} feature(s) in the "
                     f"{self.area.description()} · counting used {used} transaction(s)"]
            lines += [f"{NL.title(t)}: " + ("more than 100 features - counted as they download" if n is None
                                             else f"~{n:,} features") + (" (filtered)" if wheres.get(t) else "")
                      for t, n in est.items() if n]
            if cells:
                lines.append(f"Addresses (OS Places): at least {len(cells)} transaction(s) - one per 1 km square, "
                             "more where a square has over 100 addresses")
            if self.outside.isChecked() and self.checked_links():
                lines.append(f"<span style='color:{warn()}'>Plus linked features outside the area: about 1 "
                             "transaction per 40 (1 per address) - only known once the links are read, and "
                             "capped by 'Stop after'.</span>")
            lines += [f"<span style='color:{warn()}'>{NL.title(t)} isn't offered by your key - it'll be skipped."
                      "</span>" for t in missing]
            self.status.setText("<br>".join(lines))
            if then:
                QTimer.singleShot(0, lambda: then(tx))

        self._start(FunctionTask("OS API Data Downloader - counting linked OS NGD features", work, finished),
                    "Counting features in your area…")

    # ---------------------------------------------------------------- download
    def download(self):
        if self.task is not None:
            self.task.cancel()
            return
        if not self._check_ready():
            return
        types = self.checked_types()
        key = (tuple(sorted(types)), tuple(sorted((t, self.where(t) or "") for t in types)))
        if not self.estimates or key != self._est_key:
            # a quick count: one request per feature type (its first page, reused by the download), no probes
            self.estimate(then=lambda tx: self._confirm_and_download(tx), quick=True)
            return
        area = self._area()
        cells = LK.tiles(area[1][0] - LK.ADDRESS_MARGIN, area[1][1] - LK.ADDRESS_MARGIN, area[1][2] + LK.ADDRESS_MARGIN, area[1][3] + LK.ADDRESS_MARGIN) if area and NL.PLACES_ADDRESS in types else []
        self._confirm_and_download(sum(pages(n) for n in self.estimates.values()) + len(cells))

    def _confirm_and_download(self, tx):
        confirm = S.get("confirm_over")
        if confirm and tx > confirm and QMessageBox.question(
                self, "OS API Data Downloader", f"This download needs about {tx:,} transactions (plus any linked "
                "features outside the area). Continue?") != QMessageBox.StandardButton.Yes:
            self.status.setText(self.status.text() + "<br>Stopped before downloading.")
            return
        area = self._area()
        if area is None:
            return
        geom, bbox, wkt = area
        types = self.checked_types()
        links = self.checked_links()
        folder = S.output_folder()
        os.makedirs(folder, exist_ok=True)
        stamp = _dt.datetime.now()
        stub = C.filename_stub(NL.title(t).split(" (")[0] for t in types)
        out = os.path.join(folder, f"os_ngd_linked_{stub}_{stamp:%Y%m%d_%H%M%S}.gpkg")
        k = 2
        while os.path.exists(out):
            out = os.path.join(folder, f"os_ngd_linked_{stub}_{stamp:%Y%m%d_%H%M%S}_{k}.gpkg")
            k += 1
        mode = self.area.clip()
        where = self.area.description()
        ngd, places = self._clients(self.limit.value() or None)
        filters = {t: self.where(t) for t in types if self.where(t)}
        expected = dict(self.estimates)
        first = dict(self._first_pages)
        cells = LK.tiles(bbox[0] - LK.ADDRESS_MARGIN, bbox[1] - LK.ADDRESS_MARGIN, bbox[2] + LK.ADDRESS_MARGIN, bbox[3] + LK.ADDRESS_MARGIN) if places is not None else []
        simple = self.view.currentData() == "simple"
        outside = self.outside.isChecked()
        joined = None if simple else self.joined.currentData()
        # the rich answer layer (densities, floor areas, composition…) belongs to 'Just the answer' only
        answer = (self._recipe or {}).get("answer") if simple else None
        if answer and answer["subject"] not in types:
            answer = None

        def work(task):
            with tempfile.TemporaryDirectory(prefix="osdl_links_") as tmp:
                result = LK.run(task, ngd, places, types, links, filters, geom, bbox, wkt, mode, out, tmp,
                                outside=outside, joined=joined, expected=expected, places_cells=cells,
                                first_pages=first, answer=answer)
            # open the layers here, in the background, so QGIS doesn't freeze while ~100 of them load
            task.report(100, "Opening the layers")
            result["prebuilt"] = prebuild_layers(result, simple)
            return result

        def finished(result, error):
            self._finish()
            if error is not None and not result:
                self.status.setText(f"✖ {error}")
                return
            self.last_result = result
            self._add_to_map(result, where, stamp, simple, answer)

        self._start(FunctionTask("OS API Data Downloader - downloading linked OS NGD data", work, finished),
                    "Downloading…")

    def _add_to_map(self, result, where, stamp, simple=False, answer=None):
        out = result["out"]
        project = QgsProject.instance()
        root = project.layerTreeRoot()
        group = root.insertGroup(0, f"OS NGD linked - {where} ({stamp:%d %b %Y %H:%M})")
        layers = {}

        opts = QgsVectorLayer.LayerOptions(QgsProject.instance().transformContext())
        opts.loadDefaultStyle = False        # no style lookup in the file for each of up to ~150 layers
        opts.readExtentFromXml = False

        prebuilt = result.get("prebuilt") or {}

        def add(path, name, title, parent, count=True, visible=True):
            lyr = prebuilt.get((path, name))
            if lyr is not None:
                lyr.setName(title)
            else:
                lyr = QgsVectorLayer(f"{path}|layername={name}", title, "ogr", opts)
            if not lyr.isValid():
                return None
            project.addMapLayer(lyr, False)
            layers[name] = lyr
            if parent is None:            # in the project (for the relations), not in the Layers panel
                return lyr
            node = parent.addLayer(lyr)
            if count:
                node.setCustomProperty("showFeatureCount", True)
            node.setItemVisibilityChecked(visible)
            return lyr

        answer_layer = None
        if result.get("answer") and answer:
            question = ((self._recipe or {}).get("question") or answer["title"]).rstrip(".")
            answer_layer = add(out, result["answer"], answer["title"], group)
            if answer_layer is not None:
                AS.style_answer(answer_layer, answer)
                group.setName(f"Answer: {question} - {where} ({stamp:%d %b %Y %H:%M})")
        base_parent = group
        if simple and answer_layer is not None:
            base_parent = group.addGroup("Supporting layers (what the answer was built from)")
        for t in result["written"]:
            lyr = add(out, LK.layer_name(t), NL.title(t).split(" (")[0], base_parent,
                      visible=not (simple and answer_layer is not None))
            if lyr is not None and simple:
                AS.style_supporting(lyr, t)
        if base_parent is not group:
            base_parent.setExpanded(False)
        if result["joined"]:
            separate = result.get("joined_out") and result["joined_out"] != out
            jg = group.addGroup("Joined copies" + (f" ({os.path.basename(result['joined_out'])})" if separate
                                                   else ""))
            for t, jname in result["joined"].items():
                add(result.get("joined_out") or out, jname, f"{NL.title(t).split(' (')[0]} (joined)", jg)
            jg.setExpanded(bool(separate))
        show_tables = not simple and self.show_tables.isChecked()
        tg = group.addGroup("Link tables") if show_tables else None
        if not simple:     # the simple view keeps them in the file only - fewer layers, faster
            for tname, lid in result["tables"]:
                add(out, tname, NL.say(NL.LINK_BY_ID[lid]), tg, count=False)
            add(out, "ngd_link_register", "Link register (every link in plain English)", tg, count=False)
        if tg is not None:
            tg.setExpanded(False)
        rels = LK.add_relations(result, layers, f"{stamp:%Y%m%d%H%M%S}")
        mins, secs = divmod(int(result.get("seconds", 0)), 60)
        took = f"{mins} min {secs} s" if mins else f"{secs} s"
        if answer_layer is not None:
            n = answer_layer.featureCount()
            lines = [f"<b>✔ Your answer: {answer['title']}</b> - {n:,} row(s), took {took}.",
                     ("Its table has opened: one row per feature, in plain columns. Or click"
                      if self.open_table.isChecked() else
                      "One row per feature, in plain columns - right-click the layer > Open Attribute Table, or click")
                     + " any feature on the map with Identify (or hover with Map Tips on) to read its answer.",
                     "The data it was built from is in 'Supporting layers' (switched off). Choose 'Show me: "
                     "Everything' for joined copies and link tables."]
            if self.iface is not None:
                try:
                    self.iface.setActiveLayer(answer_layer)
                    if self.open_table.isChecked():
                        self.iface.showAttributeTable(answer_layer)
                except Exception:   # noqa: BLE001 - a convenience only
                    pass
        else:
            lines = [f"✔ Saved · {result['used']:,} transaction(s) · took {took}"]
            if rels:
                lines.append(f"Click any feature with Identify to see what it's linked to ({len(rels)} link(s) set "
                             "up in QGIS).")
        secs = dict(result.get("secs") or {})
        if getattr(self, "_est_secs", None):
            secs = {"counting": self._est_secs, **secs}
            self._est_secs = None
        shown = [(k, v) for k, v in secs.items() if v >= 0.5]
        if shown:
            lines.append(f"<span style='color:{muted()}'>Time: " + " · ".join(f"{v:.0f} s {k}" for k, v in shown)
                         + "</span>")
        tx = {k: v for k, v in (result.get("tx") or {}).items() if v}
        if tx:
            lines.append(f"<span style='color:{muted()}'>Transactions: " + " · ".join(f"{v:,} {k}" for k, v in tx.items())
                         + "</span>")
        mix = self._address_mix(layers.get("Address"))
        if mix:
            lines.insert(1, f"Addresses in your area: <b>{mix}</b>")
        if result.get("joined_out") and result["joined_out"] != out:
            lines.append(f"✔ Joined copies, all together: {result['joined_out']}")
        if not simple or answer_layer is None:
            for t, n in result["written"].items():
                extra = (f" (+{result['fetched'][t]:,} linked from outside the area)" if result["fetched"].get(t)
                         else "")
                lines.append(f"{NL.title(t).split(' (')[0]}: {n:,} feature(s){extra}")
            lines += result["report"]
        else:
            lines += [r for r in result["report"] if r.startswith("⚠")]
        lines += [f"<span style='color:{warn()}'>{n}</span>" for n in result["notes"]]
        lines.append(f"<span style='color:{muted()}'>File: {out} · {result['used']:,} transaction(s)</span>")
        if result.get("cancelled"):
            lines.append("Cancelled - partial download.")
        self.status.setText("<br>".join(lines))
        self.last_output = out
        self.last_answer_layer = answer_layer

    @staticmethod
    def _address_mix(layer):
        """'34 Residential (72%) / 12 Commercial (26%) / 1 Mixed use (2%)' for the addresses in the area."""
        if layer is None or layer.fields().indexOf("class_group") < 0:
            return ""
        counts = {}
        for f in layer.getFeatures():
            if layer.fields().indexOf("ngd_in_area") >= 0 and f["ngd_in_area"] != 1:
                continue
            g = f["class_group"] or "Unclassified"
            if g == LK.PARENT_SHELL:         # the building record of a block of flats - the flats are counted
                continue
            g = "Mixed use" if g == LK.MIXED else g
            counts[g] = counts.get(g, 0) + 1
        total = sum(counts.values())
        if not total:
            return ""
        return " / ".join(f"{n:,} {g} ({round(100 * n / total)}%)"
                          for g, n in sorted(counts.items(), key=lambda kv: -kv[1]))

    def cleanup(self):
        if self.task is not None:
            self.task.cancel()
