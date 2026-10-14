"""Little blue (i) icons with short, plain-English explanations.

All the text lives in TEXTS below (one place to edit). ``apply(tab, key)``
attaches an icon next to each named widget on a tab, without changing how
the tab builds its layout.
"""

from __future__ import annotations

from qgis.PyQt.QtCore import QEvent, QObject, Qt
from qgis.PyQt.QtGui import QCursor
from qgis.PyQt.QtWidgets import (
    QBoxLayout, QCheckBox, QFormLayout, QHBoxLayout, QRadioButton, QToolButton, QToolTip, QWidget,
)

_STYLE = ("QToolButton{color:white;background:#1f6fd1;border:none;border-radius:8px;"
          "font-weight:bold;font-size:10px;font-family:Georgia,serif;}"
          "QToolButton:hover{background:#0b4fa3;}")

TEXTS = {
    "search": {
        "box": "One search for addresses and places. Type or paste an address, postcode, UPRN or place name "
               "and press Enter; the matches drop down in one list.\n"
               "• ◼ Named areas (OS NGD Geographic Names): choosing one zooms to it and makes its boundary "
               "the area of interest, so every tab downloads for it.\n"
               "• Addresses (OS Places): choosing one shows its UPRN and details and zooms to it. 'Copy UPRN' and "
               "'Copy address' put them on the clipboard.\n"
               "Place names are only looked up when there are no numbers in what you typed. Each lookup is one "
               "transaction.",
    },
    "area": {
        "r_view": "Use exactly what you can see in the map window now. Zoom or pan first to frame the area.",
        "r_window": "Draw a rectangle (a 'window') on the map: click 'Draw window', then drag a box.",
        "r_poly": "Draw any shape: click 'Draw polygon', click to add corners, right-click to finish "
                  "(Esc cancels).",
        "r_layer": "Use the polygons you've selected in a layer - e.g. a site boundary or a ward.",
        "clip_mode": "Cut at the edge: features crossing the boundary are cut, so nothing sticks out.\n"
                     "Keep whole features: anything touching the area is kept in full (good for buildings "
                     "and land parcels you want complete).",
        "size": "Choose the area to get data for:\n• Map view - exactly what's in the map window now.\n"
                "• Window - a rectangle you drag on the map ('Draw window').\n• Polygon - any shape: click "
                "corners, right-click to finish.\n• Selected polygons - e.g. a site boundary or ward you've "
                "selected in a layer.\n• Named area - search for a place name (e.g. Chorley) in the box at the top and "
                "choose a ◼ named area: its real boundary becomes the area.\n"
                "'Clear' removes a drawn shape. Bigger areas cost more transactions.",
    },
    "find": {
        "term": "Search what an OS NGD feature is described as, e.g. 'bridge', 'school' or 'pylon' - not "
                "the technical feature type name. Searches a local index, so this needs no API key and "
                "makes no network calls - it's instant.",
        "rebuild_btn": "Rebuilds the local index from live OS NGD data (needs an API key - it checks every "
                       "feature type's queryables once, so it takes a minute or two). Do this to pick up "
                       "feature types OS NGD has added or changed since the index was last built.",
        "tree": "Matching feature types, grouped as Polygons, Lines then Points. Under each is every "
                "description value your search matched - tick just the ones you want (e.g. only 'Weir' "
                "under a buildings type), or tick the feature type itself to tick all its matches. Only "
                "the values you tick are downloaded, not the whole feature type - estimate or download "
                "warns you if a filter couldn't be worked out for one. Then estimate or download as on the "
                "OS NGD tab.",
        "estimate_btn": "Counts the ticked feature types in your area, so you know the cost first.",
        "limit": "A safety cap. The download stops after this many transactions and keeps what it has.",
        "go": "Downloads the ticked feature types in your area into a new GeoPackage (one layer per feature "
              "type), clips them and adds them to the map.",
    },
    "links": {
        "recipe": "Start from a question instead of a list of layers - e.g. 'Tell me everything about this "
                  "property' or 'How do I get into this site?'. Each ticks the feature types and links that "
                  "answer it (and explains the path underneath); some also narrow Sites, e.g. to schools. "
                  "'How are two feature types connected?' finds and ticks the chain of links between any two. "
                  "Whole networks for data engineers are further down. A quick pick replaces what's ticked - "
                  "add or untick anything after.",
        "find": "Narrow the tree to feature types or links whose name or attribute matches, e.g. 'site', "
                "'usrn' or 'startnode'.",
        "show_spatial": "Spatial links (⇢) are worked out from geometry after downloading - e.g. which Building "
                        "an address point sits in. They're useful where no identifier link exists, but they're "
                        "derived, not authoritative, and are labelled so in every output.",
        "tree": "Themes > feature types > links. Tick a feature type to download it; tick a link (🔗 stored in "
                "the data, ⇢ spatial) to join two feature types - both are ticked for you. '→' links are held by "
                "that feature type, '←' links point at it. Colours: blue identifier, green network topology, "
                "brown containment, orange spatial. Greyed-out feature types aren't served by the OS APIs this "
                "plugin uses. Addresses come from OS Places, matched on UPRN.",
        "link_all_btn": "Ticks every link between the feature types you've ticked - the quickest way to link "
                        "everything you're downloading to everything else.",
        "outside": "A link's other end is often outside your area - the node at the far end of a road, the rest "
                   "of a Site. With this on, those features are fetched by their ID (about 1 transaction per 40, "
                   "1 per address) so every link resolves. They're marked ngd_in_area = 0 and kept whole.",
        "joined": "A '_joined' copy of each layer has the linked features' IDs and key details written into "
                  "its own table (e.g. each Building gets its Site's description). Links to many features become "
                  "a count and a comma-separated list. Choose to keep them in the same file as the layers, or "
                  "all together in a file of their own (…_joined.gpkg) - handy to share or open by itself.",
        "show_tables": "Each link is also a table (from_key -> to_key, the attribute it came from, and whether "
                       "the linked feature was found), plus 'Link register' with every link's class, "
                       "cardinality and the attribute actually used. Untick to keep them out of the Layers "
                       "panel (they're still in the GeoPackage and the QGIS relations still work).",
        "estimate_btn": "Counts the ticked feature types in your area, so you know the cost first. Linked "
                        "features outside the area are only known once the links are read.",
        "limit": "A safety cap across every API this download uses. It stops after this many transactions and "
                 "keeps what it has - links to anything not fetched are marked target_found = 0.",
        "go": "Downloads everything ticked into one GeoPackage, joins it, adds it to the map in a group and "
              "sets up QGIS relations - open a feature's form (Identify) to see what it's linked to.",
    },
    "ngd": {
        "list": "The OS National Geographic Database feature types. Tick the ones you want, e.g. buildings, "
                "land, road links. Type in the box to filter the list. Each feature type becomes a layer.",
        "estimate_btn": "Counts the features in your area for each ticked type, so you know the cost first. "
                        "OS NGD API doesn't give counts, so a few one-feature test requests are made "
                        "(usually under 20 transactions).",
        "filter_btn": "Like the filter options on the OS Data Hub: only download features whose attributes match "
                      "your rules, e.g. Description is Building and Height is greater than 15. Highlight a feature "
                      "type (or double-click it), then '+ Add rule' or '+ Add group'. The attributes and their "
                      "allowed values come from the API, and each value list shows the values actually found in your "
                      "area (read from up to 500 of its features - at most 5 transactions, remembered until the area "
                      "changes). Filtering happens on OS's server, so fewer matching "
                      "features means fewer transactions. You can also write the CQL query yourself.",
        "limit": "A safety cap. The download stops after this many transactions and keeps what it has.",
        "go": "Downloads the features in your area into a new GeoPackage (one layer per feature type), clips "
              "them and adds them to the map. Each request returns up to 100 features and is one "
              "transaction.",
    },
    "wfs": {
        "list": "The OS Features API feature types, including OS MasterMap Topography Layer "
                "(Topography_TopographicArea, _TopographicLine, _CartographicText…) and OS MasterMap Highways. "
                "Tick the ones you want.",
        "year": "Latest = the current data. A year gives that year's annual snapshot (the last full release "
                "in that year), if OS holds one for the feature type.",
        "estimate_btn": "Asks the service how many features are in your area (one transaction per type), "
                        "so you know the cost first.",
        "filter_btn": "Only download features whose attributes match your rules, e.g. Theme is one of Buildings, "
                      "Land. Highlight a feature type (or double-click it), then '+ Add rule' or '+ Add group'. "
                      "Each value list shows the values found in your area (up to 500 features, at most 5 "
                      "transactions). "
                      "Filtering happens on OS's server, so fewer matching features means fewer transactions.",
        "limit": "A safety cap. The download stops after this many transactions and keeps what it has.",
        "go": "Downloads the features in your area into a new GeoPackage (one layer per feature type), clips "
              "them and adds them to the map. Each request returns up to 100 features and is one "
              "transaction. OS plans to retire this API in favour of OS NGD API (around 2030).",
    },
    "places": {
        "tree": "Tick the kinds of address you want, using OS's AddressBase classification: R = Residential, "
                "C = Commercial (with sub-classes such as CE Education, CM Medical, CR Retail), X = Dual use, "
                "L = Land, M = Military, Z = Objects of interest, P = Parent shells, U = Unclassified. "
                "Expand any class to go down to tertiary (RD04 Terraced) and quaternary (CE01HE Higher Education) "
                "codes, or type in the find box above the list, e.g. terraced, school or CE03. "
                "Untick a main class to choose some of its sub-classes. Only what's ticked is requested, so "
                "fewer classes means fewer transactions.",
        "dataset": "DPA = Royal Mail postal addresses (where post is delivered).\nLPI = council addresses, which "
                   "also include land, objects and other non-postal places.\nBoth = all of them.",
        "split": "How to arrange the results: a separate layer for each main classification (Residential, "
                 "Commercial…), for each sub-classification (RD Dwelling, CE Education…), or all in one layer. "
                 "Points are coloured by classification either way.",
        "one_per_uprn": "With both DPA and LPI, most properties appear twice (once in each). Ticked = one point "
                        "per UPRN, using the Royal Mail address where there is one.",
        "limit": "A safety cap. The download stops after this many transactions and keeps what it has.",
        "go": "OS Places can only return 1 km² at a time, so the area is split into 1 km squares. Each square "
              "costs at least one transaction, plus one more for every 100 addresses in it. Addresses are "
              "clipped to your exact area and saved to a GeoPackage.",
    },
    "downloads": {
        "kind": "OS OpenData: free products such as OS Open Zoomstack, OS OpenMap Local and OS Open Roads.\n"
                "My data packages: premium or PSGA data you've ordered on the OS Data Hub (needs an API key "
                "with the OS Downloads API).",
        "product": "Click 'Load list' to fetch the products or your data packages.",
        "fmt": "The file format to download, e.g. GeoPackage.",
        "r_tiles": "Tiles: only the 100 km grid squares your area touches - much smaller than the whole "
                   "of Great Britain.\nGB: one file for the whole country.",
        "clip_cb": "After downloading, cut every layer in the files to your area and add those smaller layers "
                "to the map. The full download is kept too.",
        "folder": "Where downloaded files (and clipped copies) are saved.",
    },
    "settings": {
        "key_edit": "Your OS Data Hub project API key. Add OS NGD API - Features, OS Features API, OS Places "
                    "API and OS Downloads API to the project. It's stored encrypted in QGIS's password store.",
        "confirm_over": "Before a download that needs more than this many transactions, you'll be asked to "
                        "confirm. 0 = never ask.",
        "hard_limit": "The default safety cap for each download. 'No limit' = no cap.",
        "folder": "Where API downloads are saved as GeoPackages.",
    },
}


class _VisibilitySync(QObject):
    """Hide the (i) when its field is hidden (and show it again)."""

    def __init__(self, widget, icon):
        super().__init__(widget)
        self.icon = icon
        widget.installEventFilter(self)

    def eventFilter(self, obj, event):
        # *ToParent events fire even while the dock itself isn't on screen
        if event.type() in (QEvent.Type.Show, QEvent.Type.ShowToParent):
            self.icon.setVisible(not obj.isHidden())
        elif event.type() in (QEvent.Type.Hide, QEvent.Type.HideToParent):
            self.icon.setVisible(False)
        return False


def make_icon(text, parent=None):
    btn = QToolButton(parent)
    btn.setText("i")
    btn.setFixedSize(16, 16)
    btn.setStyleSheet(_STYLE)
    btn.setCursor(Qt.CursorShape.WhatsThisCursor)
    html = "<p style='white-space:pre-wrap; max-width:320px'>" + \
        text.replace("&", "&amp;").replace("<", "&lt;").replace("\n", "<br>") + "</p>"
    btn.setToolTip(html)
    btn.setAccessibleName("Help")
    btn.setAccessibleDescription(text)
    btn.clicked.connect(lambda: QToolTip.showText(QCursor.pos(), html, btn))
    btn.setProperty("ospt_info", text)
    return btn


def _find_layout(layout, widget):
    if layout is None:
        return None
    if isinstance(layout, QFormLayout):
        row, _ = layout.getWidgetPosition(widget)
        if row >= 0:
            return layout
    elif layout.indexOf(widget) >= 0:
        return layout
    for i in range(layout.count()):
        child = layout.itemAt(i).layout()
        found = _find_layout(child, widget)
        if found is not None:
            return found
    return None


def attach(widget, text):
    """Put an (i) icon immediately after ``widget`` in whatever layout holds it."""
    parent = widget.parentWidget()
    layout = _find_layout(parent.layout() if parent else None, widget)
    if layout is None:
        return None
    icon = make_icon(text)
    if isinstance(layout, QFormLayout):
        row, role = layout.getWidgetPosition(widget)
        layout.removeWidget(widget)
        box = QWidget()
        h = QHBoxLayout(box)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(4)
        compact = isinstance(widget, (QCheckBox, QRadioButton))
        h.addWidget(widget, 0 if compact else 1)
        h.addWidget(icon, 0, Qt.AlignmentFlag.AlignVCenter)
        if compact:
            h.addStretch(1)
        layout.setWidget(row, role, box)
    elif isinstance(layout, QBoxLayout) and layout.direction() in (QBoxLayout.Direction.LeftToRight,
                                                                   QBoxLayout.Direction.RightToLeft):
        layout.insertWidget(layout.indexOf(widget) + 1, icon, 0, Qt.AlignmentFlag.AlignVCenter)
    elif isinstance(layout, QBoxLayout):   # vertical: wrap the widget and the icon in a row
        idx = layout.indexOf(widget)
        stretch = layout.stretch(idx)
        layout.removeWidget(widget)
        box = QWidget()
        h = QHBoxLayout(box)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(4)
        h.addWidget(widget, 1)
        h.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
        layout.insertWidget(idx, box, stretch)
    else:
        return None
    icon._sync = _VisibilitySync(widget, icon)
    if widget.isHidden():
        icon.setVisible(False)
    return icon


def _resolve(tab, key):
    if ":" in key:
        attr, sub = key.split(":", 1)
        container = getattr(tab, {"opt": "opt"}[attr], {})
        return container.get(sub)
    return getattr(tab, key, None)


def fit_combos(root):
    """Keep tabs within the dock's width: drop-downs shrink instead of sizing to their longest item,
    and form labels move above their field when there isn't room beside it."""
    from qgis.PyQt.QtWidgets import QComboBox, QLineEdit
    for cb in root.findChildren(QComboBox):
        cb.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        cb.setMinimumContentsLength(8)
    for le in root.findChildren(QLineEdit):
        le.setMinimumWidth(min(le.minimumWidth(), 80))
    for fl in root.findChildren(QFormLayout):
        fl.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)


def apply(tab, section):
    fit_combos(tab)
    icons = []
    for key, text in TEXTS[section].items():
        w = _resolve(tab, key)
        if w is not None:
            icon = attach(w, text)
            if icon is not None:
                icons.append(icon)
    tab.info_icons = icons
    return icons
