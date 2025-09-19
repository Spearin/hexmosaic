"""Project-level persistence helpers for HexMosaic."""
from __future__ import annotations

import json
import os
from typing import Any, Dict

from qgis.PyQt.QtCore import Qt, QSettings


class ProjectStateMixin:
    """Handles saving and restoring UI/project state."""

    def _collect_ui_settings(self) -> Dict[str, Any]:
        """Snapshot of UI fields that should persist per project."""
        return {
            "project": {
                "name": self.project_name_edit.text().strip(),
                "author": self.author_edit.text().strip(),
            },
            "paths": {
                "out_dir": self.out_dir_edit.text().strip(),
                "styles_dir": self.styles_dir_edit.text().strip(),
            },
            "grid": {
                "hex_scale_m": self.hex_scale_edit.text().strip(),
            },
            "aoi": {
                "allow_experimental": self.chk_experimental_aoi.isChecked(),
                "poi_layer_name": self.cbo_poi_layer.currentText().strip() if hasattr(self, "cbo_poi_layer") else "",
            },
            "opentopo": {
                "api_key": self.opentopo_key_edit.text().strip(),
            },
            "segmentation": {
                "rows": int(self.seg_rows_spin.value()) if hasattr(self, "seg_rows_spin") else 1,
                "cols": int(self.seg_cols_spin.value()) if hasattr(self, "seg_cols_spin") else 1,
                "mode": int(self.seg_mode_tabs.currentIndex()) if hasattr(self, "seg_mode_tabs") else 0,
                "map_tile": {
                    "scale": self.tile_scale_combo.currentData() if hasattr(self, "tile_scale_combo") else "1:250k",
                    "alignment": self.tile_alignment_combo.currentData() if hasattr(self, "tile_alignment_combo") else "extent",
                    "offset_ns": float(self.tile_offset_ns_spin.value()) if hasattr(self, "tile_offset_ns_spin") else 0.0,
                    "offset_ew": float(self.tile_offset_ew_spin.value()) if hasattr(self, "tile_offset_ew_spin") else 0.0,
                    "offset_unit": self.tile_offset_unit_combo.currentData() if hasattr(self, "tile_offset_unit_combo") else "km",
                },
                "metadata": self._segment_metadata,
            },
            "osm": {
                "aoi_layer_name": self.cboAOI_osm.currentText().strip() if hasattr(self, "cboAOI_osm") else "",
                "buffer_m": float(self.spin_osm_buffer.value()) if hasattr(self, "spin_osm_buffer") else 1000.0,
                "themes": {key: bool(chk.isChecked()) for key, chk in getattr(self, "osm_theme_checks", {}).items()},
                "local_path": self.osm_local_path_edit.text().strip() if hasattr(self, "osm_local_path_edit") else "",
            },
            "hex_elevation": {
                "dem_layer_name": self.cbo_hex_dem_layer.currentText().strip() if hasattr(self, "cbo_hex_dem_layer") else "",
                "hex_layer_name": self.cbo_hex_tiles_layer.currentText().strip() if hasattr(self, "cbo_hex_tiles_layer") else "",
                "method": self.cbo_hex_sample_method.currentData() if hasattr(self, "cbo_hex_sample_method") else "mean",
                "bucket_size": int(self.spin_hex_bucket.value()) if hasattr(self, "spin_hex_bucket") else 1,
                "overwrite": bool(self.chk_hex_overwrite.isChecked()) if hasattr(self, "chk_hex_overwrite") else False,
                "dem_source": self.cbo_dem_source.currentData() if hasattr(self, "cbo_dem_source") else "SRTMGL3",
            },
        }

    def _apply_ui_settings(self, data: Dict[str, Any]):
        """Apply saved values back to the UI widgets."""

        def resolve(*keys: str, default=""):
            current = data if isinstance(data, dict) else {}
            for key in keys[:-1]:
                if not isinstance(current, dict):
                    return default
                current = current.get(key, {})
            if not isinstance(current, dict):
                return default
            return current.get(keys[-1], default)

        self.project_name_edit.setText(resolve("project", "name", default=""))
        self.author_edit.setText(resolve("project", "author", default=""))
        self.out_dir_edit.setText(resolve("paths", "out_dir", default=""))
        self.styles_dir_edit.setText(resolve("paths", "styles_dir", default=""))
        self.hex_scale_edit.setText(resolve("grid", "hex_scale_m", default="500"))
        self.opentopo_key_edit.setText(resolve("opentopo", "api_key", default=""))
        self.chk_experimental_aoi.setChecked(bool(resolve("aoi", "allow_experimental", default=False)))

        poi_name = resolve("aoi", "poi_layer_name", default="")
        if isinstance(poi_name, str):
            self._pending_poi_layer_name = poi_name

        seg_data = data.get("segmentation", {}) if isinstance(data, dict) else {}
        if hasattr(self, "seg_rows_spin"):
            rows_val = seg_data.get("rows") if isinstance(seg_data, dict) else None
            try:
                rows_val = int(rows_val)
            except (TypeError, ValueError):
                rows_val = self.seg_rows_spin.value()
            self.seg_rows_spin.setValue(max(self.seg_rows_spin.minimum(), min(self.seg_rows_spin.maximum(), rows_val)))
        if hasattr(self, "seg_cols_spin"):
            cols_val = seg_data.get("cols") if isinstance(seg_data, dict) else None
            try:
                cols_val = int(cols_val)
            except (TypeError, ValueError):
                cols_val = self.seg_cols_spin.value()
            self.seg_cols_spin.setValue(max(self.seg_cols_spin.minimum(), min(self.seg_cols_spin.maximum(), cols_val)))

        if hasattr(self, "seg_mode_tabs"):
            mode_val = seg_data.get("mode") if isinstance(seg_data, dict) else None
            try:
                mode_idx = int(mode_val) if mode_val is not None else 0
            except (TypeError, ValueError):
                mode_idx = 0
            if 0 <= mode_idx < self.seg_mode_tabs.count():
                self.seg_mode_tabs.setCurrentIndex(mode_idx)

        map_tile_data = seg_data.get("map_tile", {}) if isinstance(seg_data, dict) else {}
        if hasattr(self, "tile_scale_combo") and isinstance(map_tile_data, dict):
            scale_val = map_tile_data.get("scale")
            if scale_val is not None:
                idx = self.tile_scale_combo.findData(scale_val)
                if idx < 0:
                    idx = self.tile_scale_combo.findText(str(scale_val))
                if idx >= 0:
                    self.tile_scale_combo.setCurrentIndex(idx)
        if hasattr(self, "tile_alignment_combo") and isinstance(map_tile_data, dict):
            alignment_val = map_tile_data.get("alignment")
            if alignment_val is not None:
                idx = self.tile_alignment_combo.findData(alignment_val)
                if idx < 0:
                    idx = self.tile_alignment_combo.findText(str(alignment_val))
                if idx >= 0:
                    self.tile_alignment_combo.setCurrentIndex(idx)
        if hasattr(self, "tile_offset_unit_combo") and isinstance(map_tile_data, dict):
            unit_val = map_tile_data.get("offset_unit")
            if unit_val is not None:
                idx = self.tile_offset_unit_combo.findData(unit_val)
                if idx < 0:
                    idx = self.tile_offset_unit_combo.findText(str(unit_val))
                if idx >= 0:
                    self.tile_offset_unit_combo.setCurrentIndex(idx)
        if hasattr(self, "tile_offset_ns_spin") and isinstance(map_tile_data, dict):
            try:
                ns_val = float(map_tile_data.get("offset_ns", self.tile_offset_ns_spin.value()))
            except (TypeError, ValueError):
                ns_val = self.tile_offset_ns_spin.value()
            self.tile_offset_ns_spin.setValue(ns_val)
        if hasattr(self, "tile_offset_ew_spin") and isinstance(map_tile_data, dict):
            try:
                ew_val = float(map_tile_data.get("offset_ew", self.tile_offset_ew_spin.value()))
            except (TypeError, ValueError):
                ew_val = self.tile_offset_ew_spin.value()
            self.tile_offset_ew_spin.setValue(ew_val)

        self._update_map_tile_controls_state()

        metadata = {}
        if isinstance(seg_data, dict):
            raw_meta = seg_data.get("metadata", {})
            if isinstance(raw_meta, dict):
                for key, entry in raw_meta.items():
                    if not isinstance(entry, dict):
                        continue
                    try:
                        row_int = int(entry.get("rows")) if entry.get("rows") is not None else None
                    except (TypeError, ValueError):
                        row_int = None
                    try:
                        col_int = int(entry.get("cols")) if entry.get("cols") is not None else None
                    except (TypeError, ValueError):
                        col_int = None
                    meta_entry = {
                        "parent": entry.get("parent"),
                        "rows": row_int,
                        "cols": col_int,
                        "segments": [str(s) for s in entry.get("segments", []) if s is not None],
                    }
                    for extra_key in (
                        "mode",
                        "scale",
                        "scale_label",
                        "alignment",
                        "offsets",
                        "origin",
                        "tile_width_km",
                        "tile_height_km",
                        "grid",
                        "subdir",
                    ):
                        if extra_key in entry:
                            meta_entry[extra_key] = entry[extra_key]
                    metadata[str(key)] = meta_entry
        self._segment_metadata = metadata
        self._update_segment_buttons_state()

        osm_data = data.get("osm", {}) if isinstance(data, dict) else {}
        if hasattr(self, "spin_osm_buffer") and isinstance(osm_data, dict):
            try:
                self.spin_osm_buffer.setValue(float(osm_data.get("buffer_m", self.spin_osm_buffer.value())))
            except Exception:
                pass
        if hasattr(self, "cboAOI_osm") and isinstance(osm_data, dict):
            name = str(osm_data.get("aoi_layer_name", ""))
            if name:
                idx = self.cboAOI_osm.findText(name, Qt.MatchFixedString)
                if idx >= 0:
                    self.cboAOI_osm.setCurrentIndex(idx)
        if hasattr(self, "osm_theme_checks") and isinstance(osm_data, dict):
            theme_flags = osm_data.get("themes", {}) if isinstance(osm_data, dict) else {}
            if isinstance(theme_flags, dict):
                for key, chk in self.osm_theme_checks.items():
                    chk.setChecked(bool(theme_flags.get(key, chk.isChecked())))
        if hasattr(self, "osm_local_path_edit") and isinstance(osm_data, dict):
            self.osm_local_path_edit.setText(str(osm_data.get("local_path", "")))

        hex_data = data.get("hex_elevation", {}) if isinstance(data, dict) else {}
        if hasattr(self, "spin_hex_bucket"):
            try:
                bucket_val = int(hex_data.get("bucket_size", self.spin_hex_bucket.value()))
            except (TypeError, ValueError):
                bucket_val = self.spin_hex_bucket.value()
            self.spin_hex_bucket.setValue(max(self.spin_hex_bucket.minimum(), min(self.spin_hex_bucket.maximum(), bucket_val)))
        if hasattr(self, "chk_hex_overwrite"):
            self.chk_hex_overwrite.setChecked(bool(hex_data.get("overwrite", False)))
        if hasattr(self, "cbo_hex_sample_method"):
            method_val = hex_data.get("method")
            if method_val is not None:
                idx = self.cbo_hex_sample_method.findData(method_val)
                if idx < 0:
                    idx = self.cbo_hex_sample_method.findText(str(method_val), Qt.MatchFixedString)
                if idx >= 0:
                    self.cbo_hex_sample_method.setCurrentIndex(idx)
        dem_pending = hex_data.get("dem_layer_name")
        if hasattr(self, "cbo_dem_source"):
            dem_key = hex_data.get("dem_source") if isinstance(hex_data, dict) else None
            if dem_key is not None:
                idx = self.cbo_dem_source.findData(dem_key)
                if idx < 0:
                    idx = self.cbo_dem_source.findText(str(dem_key), Qt.MatchFixedString)
                if idx >= 0:
                    self.cbo_dem_source.setCurrentIndex(idx)
            else:
                default_idx = self.cbo_dem_source.findData("SRTMGL3")
                if default_idx >= 0:
                    self.cbo_dem_source.setCurrentIndex(default_idx)

        if isinstance(dem_pending, str):
            self._pending_hex_dem_layer_name = dem_pending
        hex_pending = hex_data.get("hex_layer_name")
        if isinstance(hex_pending, str):
            self._pending_hex_tile_layer_name = hex_pending

    def _save_project_settings(self):
        path = self._project_settings_path()
        if not path:
            return
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(self._collect_ui_settings(), handle, indent=2)
            self.log(f"Saved project settings → {os.path.basename(path)}")
        except Exception as exc:  # pragma: no cover - filesystem errors
            self.log(f"Could not save project settings: {exc}")

    def _load_project_settings(self):
        path = self._project_settings_path()
        if not path or not os.path.isfile(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            self._apply_ui_settings(data)
            self.log(f"Loaded project settings from {os.path.basename(path)}")
        except Exception as exc:  # pragma: no cover - filesystem errors
            self.log(f"Could not read project settings: {exc}")

    def _on_project_read(self, *_):
        self._load_project_settings()
        if not self.out_dir_edit.text().strip():
            project_dir = self._project_dir()
            if project_dir:
                self.out_dir_edit.setText(project_dir)

    def _on_project_saved(self):
        if not self.out_dir_edit.text().strip():
            project_dir = self._project_dir()
            if project_dir:
                self.out_dir_edit.setText(project_dir)
        self._save_project_settings()

    def _on_project_cleared(self):
        self._segment_metadata = {}
        self._remove_all_segment_previews()
        self._populate_aoi_combo()
        self._populate_poi_combo()
        self._pending_hex_dem_layer_name = ""
        self._pending_hex_tile_layer_name = ""
        if hasattr(self, "cbo_hex_dem_layer"):
            self.cbo_hex_dem_layer.clear()
        if hasattr(self, "cbo_hex_tiles_layer"):
            self.cbo_hex_tiles_layer.clear()
        self._update_hex_elevation_button_state()
        self._osm_last_params = {}
        if hasattr(self, "cboAOI_osm"):
            self.cboAOI_osm.clear()
        if hasattr(self, "osm_local_path_edit"):
            self.osm_local_path_edit.clear()
        for chk in getattr(self, "osm_theme_checks", {}).values():
            chk.setChecked(False)

    def _save_setup_settings(self):
        settings = QSettings("HexMosaicOrg", "HexMosaic")
        settings.setValue("paths/out_dir", self.out_dir_edit.text())
        settings.setValue("paths/styles_dir", self.styles_dir_edit.text())
        settings.setValue("project/name", self.project_name_edit.text())
        settings.setValue("project/author", self.author_edit.text())
        settings.setValue("grid/hex_scale_m", self.hex_scale_edit.text())
        settings.setValue("opentopo/api_key", self.opentopo_key_edit.text())
        self._save_project_settings()

    def _load_setup_settings(self):
        settings = QSettings("HexMosaicOrg", "HexMosaic")
        self.out_dir_edit.setText(settings.value("paths/out_dir", "", type=str))
        self.styles_dir_edit.setText(settings.value("paths/styles_dir", "", type=str))
        self.project_name_edit.setText(settings.value("project/name", "", type=str))
        self.author_edit.setText(settings.value("project/author", "", type=str))
        self.hex_scale_edit.setText(settings.value("grid/hex_scale_m", "500", type=str))
        self.opentopo_key_edit.setText(settings.value("opentopo/api_key", "", type=str))
