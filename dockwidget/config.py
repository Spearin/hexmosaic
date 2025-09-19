"""Configuration file helpers for HexMosaic."""
from __future__ import annotations

import json
import os
import shutil
from typing import Tuple

from qgis.PyQt import QtWidgets
from qgis.PyQt.QtCore import QSettings


class ConfigMixin:
    """Resolves and loads hexmosaic.config.json files."""

    def _plugin_default_config_path(self) -> str:
        # The default config lives in the plugin root "data" directory, not inside dockwidget/
        plugin_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(plugin_dir, "data", "hexmosaic.config.json")

    def _project_config_path(self) -> str:
        return os.path.join(self._project_root(), "hexmosaic.config.json")

    def _resolve_config_path(self) -> Tuple[str, str]:
        settings = QSettings("HexMosaicOrg", "HexMosaic")
        explicit = settings.value("config/path", "", type=str) or ""
        if explicit and os.path.isfile(explicit):
            # Validate that the explicit path is a JSON config with a schema_version
            try:
                import json
                with open(explicit, "r", encoding="utf-8") as fh:
                    j = json.load(fh)
                if isinstance(j, dict) and "schema_version" in j:
                    return explicit, "explicit"
                # invalid explicit file: clear the setting so it isn't re-used
                settings.setValue("config/path", "")
            except Exception:
                # If it can't be read as JSON, clear the explicit setting
                settings.setValue("config/path", "")

        project_path = self._project_config_path()
        if os.path.isfile(project_path):
            return project_path, "project"

        default_path = self._plugin_default_config_path()
        if os.path.isfile(default_path):
            return default_path, "default"

        return "", "missing"

    def _load_config(self):
        edit = getattr(self, 'cfg_path_edit', None)
        source_label = getattr(self, 'cfg_source_label', None)
        if not self._widget_is_alive(edit) or not self._widget_is_alive(source_label):
            return

        path, source = self._resolve_config_path()
        if not path:
            self.cfg = {}
            self.cfg_path = ""
            if self._widget_is_alive(edit):
                edit.setText("")
            if self._widget_is_alive(source_label):
                source_label.setText("source: -")
            self.log("Config: no configuration found (missing).")
            return

        try:
            with open(path, "r", encoding="utf-8") as handle:
                cfg = json.load(handle)
        except Exception as exc:  # pragma: no cover - filesystem errors
            self.cfg = {}
            self.cfg_path = ""
            if self._widget_is_alive(edit):
                edit.setText("")
            if self._widget_is_alive(source_label):
                source_label.setText("source: error")
            self.log(f"Config: failed to read {path}: {exc}")
            return

        if not isinstance(cfg, dict) or "schema_version" not in cfg:
            self.cfg = {}
            self.cfg_path = ""
            if self._widget_is_alive(edit):
                edit.setText("")
            if self._widget_is_alive(source_label):
                source_label.setText("source: invalid")
            self.log(f"Config: invalid or missing schema_version in {path}")
            return

        self.cfg = cfg
        self.cfg_path = path
        if self._widget_is_alive(edit):
            edit.setText(path)
        if self._widget_is_alive(source_label):
            source_label.setText(f"source: {source}")
        self.log(f"Config loaded from {source}: {path}")
