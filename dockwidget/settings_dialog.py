"""Settings dialog for HexMosaic dock widget."""
from __future__ import annotations

import os
from qgis.PyQt import QtWidgets, QtCore  # type: ignore
from qgis.PyQt.QtCore import QSettings


class HexMosaicSettingsDialog(QtWidgets.QDialog):
    """Modal dialog that captures persistent plugin settings."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("HexMosaic Settings")

        layout = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()

        self.out_dir = QtWidgets.QLineEdit()
        self.styles_dir = QtWidgets.QLineEdit()

        browse_out = QtWidgets.QPushButton("Browse...")
        browse_styles = QtWidgets.QPushButton("Browse...")

        row_out = QtWidgets.QHBoxLayout()
        row_out.addWidget(self.out_dir)
        row_out.addWidget(browse_out)

        row_styles = QtWidgets.QHBoxLayout()
        row_styles.addWidget(self.styles_dir)
        row_styles.addWidget(browse_styles)

        form.addRow("Project output directory:", row_out)
        form.addRow("Styles directory (.qml):", row_styles)

        layout.addLayout(form)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        layout.addWidget(buttons)

        org = QtWidgets.QApplication.instance().organizationName() or "HexMosaicOrg"
        app = QtWidgets.QApplication.instance().applicationName() or "HexMosaic"
        self._qsettings = QSettings(org, app)

        self.out_dir.setText(self._qsettings.value("paths/out_dir", "", type=str))
        self.styles_dir.setText(self._qsettings.value("paths/styles_dir", "", type=str))

        def _pick(target: QtWidgets.QLineEdit):
            start_dir = target.text().strip() or os.path.expanduser("~")
            directory = QtWidgets.QFileDialog.getExistingDirectory(self, "Select folder", start_dir)
            if directory:
                target.setText(directory)

        browse_out.clicked.connect(lambda: _pick(self.out_dir))
        browse_styles.clicked.connect(lambda: _pick(self.styles_dir))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

    def accept(self):
        self._qsettings.setValue("paths/out_dir", self.out_dir.text())
        self._qsettings.setValue("paths/styles_dir", self.styles_dir.text())
        super().accept()


def get_persistent_setting(key: str, default: str = "") -> str:
    """Fetch a plugin-scoped persistent setting from Qt's registry."""
    org = QtWidgets.QApplication.instance().organizationName() or "HexMosaicOrg"
    app = QtWidgets.QApplication.instance().applicationName() or "HexMosaic"
    store = QSettings(org, app)
    return store.value(key, default, type=str)
