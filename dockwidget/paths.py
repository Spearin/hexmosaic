"""Filesystem path helpers for the HexMosaic dock widget."""
from __future__ import annotations

import os

from qgis.core import QgsProject  # type: ignore

from .settings_dialog import get_persistent_setting


class ProjectPathsMixin:
    """Utilities for resolving project-relative and plugin paths."""

    def _project_file_path(self) -> str:
        """Absolute path to the current QGIS project file, or '' if unsaved."""
        return QgsProject.instance().fileName() or ""

    def _project_dir(self) -> str:
        project_file = self._project_file_path()
        return os.path.dirname(project_file) if project_file else ""

    def _project_settings_path(self) -> str:
        """Location for hexmosaic.project.json alongside the .qgz file."""
        project_dir = self._project_dir()
        if not project_dir:
            return ""
        return os.path.join(project_dir, "hexmosaic.project.json")

    def _project_root(self) -> str:
        """Resolves the working directory for output, falling back sanely."""
        configured = self.out_dir_edit.text().strip() or get_persistent_setting("paths/out_dir", "")
        if configured and os.path.isdir(configured):
            return configured
        project_path = QgsProject.instance().fileName()
        if project_path:
            return os.path.dirname(project_path)
        return os.path.expanduser("~")

    def _layers_dir(self) -> str:
        return os.path.join(self._project_root(), "Layers")

    def _export_dir(self) -> str:
        """Export root always lives in <project root>/Export (capital E)."""
        return os.path.join(self._project_root(), "Export")

    def _styles_elevation_dir(self) -> str:
        styles_dir = self.styles_dir_edit.text().strip() or get_persistent_setting("paths/styles_dir", "")
        return os.path.join(styles_dir, "elevation") if styles_dir else ""

    def _layers_elevation_dir(self) -> str:
        directory = os.path.join(self._layers_dir(), "Elevation")
        os.makedirs(directory, exist_ok=True)
        return directory

    def _layers_elevation_hex_dir(self) -> str:
        directory = os.path.join(self._layers_elevation_dir(), "HexPalette")
        os.makedirs(directory, exist_ok=True)
        return directory

    def _layers_osm_dir(self) -> str:
        directory = os.path.join(self._layers_dir(), "OSM")
        os.makedirs(directory, exist_ok=True)
        return directory

    def _layers_mosaic_dir(self) -> str:
        directory = os.path.join(self._layers_dir(), "Mosaic")
        os.makedirs(directory, exist_ok=True)
        return directory

    def _mosaic_output_path(self, layer_name: str) -> str:
        safe = self._safe_filename(layer_name.replace(" ", "_"))
        return os.path.join(self._layers_mosaic_dir(), f"{safe}.shp")

    def _osm_theme_path(self, theme_key: str) -> str:
        safe = self._safe_filename(theme_key)
        directory = os.path.join(self._layers_osm_dir(), safe)
        os.makedirs(directory, exist_ok=True)
        return directory

    def _hex_elevation_output_path(self, base_name: str) -> str:
        safe = self._safe_filename(base_name.replace(" ", "_"))
        return os.path.join(self._layers_elevation_hex_dir(), f"{safe}_hex_elevation.shp")

    def _segment_directory_for_layer(self, layer) -> str:
        parent_safe = self._safe_filename(layer.name().replace(" ", "_"))
        return os.path.join(self._layers_dir(), "Base", "Base_Grid", parent_safe, "Segments")

    @staticmethod
    def _safe_filename(name: str) -> str:
        return "".join(c if c.isalnum() or c in ("_", "-", ".") else "_" for c in name)
