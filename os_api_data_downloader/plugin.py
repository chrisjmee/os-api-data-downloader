"""OS API Data Downloader - plugin entry point."""

from __future__ import annotations

import os

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QIcon
try:
    from qgis.PyQt.QtGui import QAction  # Qt6 / QGIS 4
except ImportError:
    from qgis.PyQt.QtWidgets import QAction

ICON = os.path.join(os.path.dirname(__file__), "icon.svg")
MENU = "OS API Data Downloader"


class OsApiDataDownloaderPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.dock = None
        self.action = None

    def initGui(self):
        self.action = QAction(QIcon(ICON), MENU, self.iface.mainWindow())
        self.action.setCheckable(True)
        self.action.toggled.connect(self._toggle)
        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToWebMenu(MENU, self.action)

    def _ensure_dock(self):
        if self.dock is None:
            from .gui.dock import OsApiDataDownloaderDock
            self.dock = OsApiDataDownloaderDock(self.iface)
            self.iface.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock)
            self.dock.visibilityChanged.connect(self.action.setChecked)
        return self.dock

    def _toggle(self, on):
        if on:
            self._ensure_dock().show()
            self.dock.raise_()
        elif self.dock is not None:
            self.dock.hide()

    def unload(self):
        if self.dock is not None:
            self.dock.cleanup()
            self.iface.removeDockWidget(self.dock)
            self.dock.deleteLater()
            self.dock = None
        if self.action is not None:
            self.iface.removePluginWebMenu(MENU, self.action)
            self.iface.removeToolBarIcon(self.action)
