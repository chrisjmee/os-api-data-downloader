"""Settings tab: API key, transaction controls, output folder."""

from __future__ import annotations

from qgis.core import QgsApplication
from qgis.gui import QgsFileWidget, QgsPasswordLineEdit
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QFormLayout, QGroupBox, QHBoxLayout, QLabel, QMessageBox, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from ..core.downloads import DownloadsClient
from ..core.ngd_features import NgdFeaturesClient
from ..core.transport import QgisTransport
from . import settings as S


def _hint(text):
    lab = QLabel(text)
    lab.setWordWrap(True)
    lab.setStyleSheet("color: palette(mid);")
    return lab


class SettingsTab(QWidget):
    def __init__(self, on_changed=None, parent=None):
        super().__init__(parent)
        self.on_changed = on_changed or (lambda: None)
        v = QVBoxLayout(self)

        g = QGroupBox("OS Data Hub API key")
        f = QFormLayout(g)
        self.key_edit = QgsPasswordLineEdit()
        self.key_edit.setPlaceholderText("Paste your project API key")
        f.addRow("Key", self.key_edit)
        row = QHBoxLayout()
        for text, slot in (("Save key", self.save_key), ("Test", self.test_key), ("Remove", self.clear_key)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            row.addWidget(b)
        f.addRow(row)
        self.key_status = QLabel()
        self.key_status.setWordWrap(True)
        f.addRow(self.key_status)
        f.addRow(_hint("Stored encrypted in the QGIS authentication database. Add OS NGD API - Features, "
                       "OS Places API and OS Downloads API to the key's OS Data Hub project. OpenData "
                       "downloads work without a key."))
        v.addWidget(g)

        g = QGroupBox("Transactions")
        f = QFormLayout(g)
        self.confirm_over = QSpinBox()
        self.confirm_over.setRange(0, 10_000_000)
        self.confirm_over.setSingleStep(500)
        self.confirm_over.setSuffix(" transactions")
        f.addRow("Ask before downloads over", self.confirm_over)
        self.hard_limit = QSpinBox()
        self.hard_limit.setRange(0, 10_000_000)
        self.hard_limit.setSingleStep(1000)
        self.hard_limit.setSpecialValueText("No limit")
        f.addRow("Default cap per download", self.hard_limit)
        f.addRow(_hint("Every API request returns up to 100 features and is one OS Data Hub transaction."))
        v.addWidget(g)

        g = QGroupBox("Output")
        f = QFormLayout(g)
        self.folder = QgsFileWidget()
        self.folder.setStorageMode(QgsFileWidget.StorageMode.GetDirectory)
        f.addRow("Save downloads in", self.folder)
        v.addWidget(g)

        save = QPushButton("Save settings")
        save.clicked.connect(self.save)
        v.addWidget(save)
        v.addStretch(1)
        self.load()

    def load(self):
        self.key_edit.setText("")
        self._update_key_status()
        self.confirm_over.setValue(S.get("confirm_over"))
        self.hard_limit.setValue(S.get("hard_limit"))
        self.folder.setFilePath(S.output_folder())

    def save(self):
        S.set_("confirm_over", self.confirm_over.value())
        S.set_("hard_limit", self.hard_limit.value())
        S.set_("folder", self.folder.filePath().strip())
        if self.key_edit.text().strip():
            self.save_key()
        self.on_changed()

    def _update_key_status(self):
        src = S.api_key_source()
        self.key_status.setText(f"✔ Key available ({src})" if src else "No key saved - only OS OpenData downloads "
                                "will work.")

    def save_key(self):
        key = self.key_edit.text().strip()
        if not key:
            return
        try:
            S.save_api_key(key)
        except Exception as ex:
            QMessageBox.warning(self, "OS API Data Downloader", str(ex))
            return
        self.key_edit.setText("")
        self._update_key_status()
        self.on_changed()

    def clear_key(self):
        S.clear_api_key()
        self._update_key_status()
        self.on_changed()

    def test_key(self):
        """Checks each API with requests that don't cost transactions (lists of feature types/packages)."""
        if self.key_edit.text().strip():
            self.save_key()
        key = S.load_api_key()
        if not key:
            self.key_status.setText("✖ No key saved.")
            return
        lines = []
        QgsApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            for name, fn in (
                    ("OS NGD API - Features", lambda: f"{len(NgdFeaturesClient(key, QgisTransport()).collections())} "
                                                      "feature types"),
                    ("OS Downloads API", lambda: f"{len(DownloadsClient(key, QgisTransport()).data_packages())} "
                                                 "data package(s)")):
                try:
                    lines.append(f"✔ {name}: {fn()}")
                except Exception as ex:
                    lines.append(f"✖ {name}: {str(ex)[:160]}")
        finally:
            QgsApplication.restoreOverrideCursor()
        self.key_status.setText("<br>".join(lines))
