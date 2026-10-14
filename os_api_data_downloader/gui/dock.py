"""The dock: the area of interest (shared by every tab) above the tabs."""

from __future__ import annotations

from qgis.gui import QgsCollapsibleGroupBox, QgsDockWidget
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QLabel, QScrollArea, QTabWidget, QVBoxLayout, QWidget

from . import info
from .address_search import AddressSearch
from .aoi import AreaPanel
from .downloads_tab import DownloadsTab
from .features_tab import FeaturesTab
from .links_tab import LinksTab
from .places_tab import PlacesTab
from .search_tab import SearchTab
from .settings_tab import SettingsTab


class OsApiDataDownloaderDock(QgsDockWidget):
    def __init__(self, iface, parent=None):
        super().__init__("OS API Data Downloader", parent)
        self.setObjectName("OsApiDataDownloaderDock")
        self.iface = iface
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        scroll.setWidget(body)
        v = QVBoxLayout(body)
        byline = QLabel("Created by CJM")
        byline.setAlignment(Qt.AlignHCenter)
        byline.setStyleSheet("color: grey; font-style: italic;")
        v.addWidget(byline)
        self.area = AreaPanel(iface)
        box = QgsCollapsibleGroupBox("Search for an address or place")
        bv = QVBoxLayout(box)
        # addresses (OS Places) and OS NGD Named Areas in one list; a chosen named area becomes the area
        self.search = AddressSearch(iface, area=self.area)
        bv.addWidget(self.search)
        v.addWidget(box)
        box = QgsCollapsibleGroupBox("Area of interest")
        bv = QVBoxLayout(box)
        bv.addWidget(self.area)
        v.addWidget(box)
        self.tabs = QTabWidget()
        self.find = SearchTab(iface, self.area)
        self.links = LinksTab(iface, self.area)
        self.ngd = FeaturesTab(iface, self.area, "ngd")
        self.wfs = FeaturesTab(iface, self.area, "wfs")
        self.places = PlacesTab(iface, self.area)
        self.downloads = DownloadsTab(iface, self.area)
        self.settings = SettingsTab(on_changed=self.refresh_settings)
        for w, label in ((self.find, "Find an NGD Feature Type"), (self.links, "NGD Data Linkages"),
                         (self.ngd, "OS NGD"), (self.wfs, "OS MasterMap"), (self.places, "OS Addressing"), (self.downloads, "OS Data Packages"), (self.settings, "⚙")):
            self.tabs.addTab(w, label)
        self.tabs.setTabToolTip(self.tabs.indexOf(self.settings), "Settings: API key, transaction limits, folder")
        v.addWidget(self.tabs, 1)
        self.setWidget(scroll)
        for tab, section in ((self.search, "search"), (self.area, "area"), (self.find, "find"), (self.links, "links"),
                             (self.ngd, "ngd"), (self.wfs, "wfs"), (self.places, "places"), (self.downloads, "downloads"),
                             (self.settings, "settings")):
            info.apply(tab, section)

    def refresh_settings(self):
        for tab in (self.find, self.links, self.ngd, self.wfs, self.places):
            tab.refresh_settings()
        self.downloads.folder.setFilePath(self.settings.folder.filePath() or self.downloads.folder.filePath())

    def cleanup(self):
        self.search.cleanup()
        for tab in (self.find, self.links, self.ngd, self.wfs, self.places, self.downloads):
            tab.cleanup()
        self.area.cleanup()
