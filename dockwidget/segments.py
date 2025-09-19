"""Segmentation and map tile helpers for HexMosaic."""
from __future__ import annotations

import math
import os
import shutil

from qgis.PyQt.QtCore import QVariant
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsDistanceArea,
    QgsFeature,
    QgsField,
    QgsFields,
    QgsFillSymbol,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
    QgsSingleSymbolRenderer,
    QgsUnitTypes,
    QgsVectorFileWriter,
    QgsVectorLayer,
    QgsWkbTypes,
)

class SegmentationMixin:
    def _map_tile_scale_presets(self):
        """Return available map tile scale presets as (label, key, width_km)."""
        return [
            ("1:25k (~5 km tile)", "1:25k", 5.0),
            ("1:50k (~10 km tile)", "1:50k", 10.0),
            ("1:100k (~20 km tile)", "1:100k", 20.0),
            ("1:200k (~40 km tile)", "1:200k", 40.0),
            ("1:250k (~50 km tile)", "1:250k", 50.0),
        ]

    def _map_tile_scale_lookup(self):
        if not hasattr(self, "_tile_scale_lookup"):
            lookup = {}
            for label, key, width_km in self._map_tile_scale_presets():
                lookup[key] = {"label": label, "width_km": width_km}
            self._tile_scale_lookup = lookup
        return self._tile_scale_lookup

    def _segment_mode(self):
        if hasattr(self, "seg_mode_tabs") and self.seg_mode_tabs.currentIndex() == 1:
            return "map_tile"
        return "equal"

    def _current_map_tile_settings(self):
        scale_key = None
        scale_label = ""
        width_km = 50.0
        if hasattr(self, "tile_scale_combo"):
            scale_key = self.tile_scale_combo.currentData()
            if scale_key is None:
                scale_key = self.tile_scale_combo.currentText()
        lookup = self._map_tile_scale_lookup()
        preset = lookup.get(scale_key) if scale_key else None
        if not preset:
            scale_key = "1:250k"
            preset = lookup.get(scale_key, {"label": "1:250k (~50 km tile)", "width_km": 50.0})
        scale_label = preset.get("label", "1:250k (~50 km tile)")
        width_km = float(preset.get("width_km", 50.0))

        alignment = "extent"
        if hasattr(self, "tile_alignment_combo"):
            alignment_data = self.tile_alignment_combo.currentData()
            if alignment_data:
                alignment = alignment_data

        offsets = {"ns": 0.0, "ew": 0.0, "unit": "km"}
        if hasattr(self, "tile_offset_ns_spin"):
            offsets["ns"] = float(self.tile_offset_ns_spin.value())
        if hasattr(self, "tile_offset_ew_spin"):
            offsets["ew"] = float(self.tile_offset_ew_spin.value())
        if hasattr(self, "tile_offset_unit_combo"):
            unit_data = self.tile_offset_unit_combo.currentData()
            if unit_data:
                offsets["unit"] = unit_data

        return {
            "scale_key": scale_key,
            "scale_label": scale_label,
            "width_km": width_km,
            "alignment": alignment,
            "offsets": offsets,
        }

    def _update_map_tile_controls_state(self):
        if not hasattr(self, "tile_alignment_combo"):
            return
        alignment = self.tile_alignment_combo.currentData()
        enable_offsets = alignment not in (None, "extent")
        for widget in (getattr(self, "tile_offset_ns_spin", None), getattr(self, "tile_offset_ew_spin", None), getattr(self, "tile_offset_unit_combo", None)):
            if widget is not None:
                widget.setEnabled(enable_offsets)
        suffix = ""
        if enable_offsets and hasattr(self, "tile_offset_unit_combo"):
            unit = self.tile_offset_unit_combo.currentData()
            suffix = " km" if unit == "km" else " arc-min"
        if hasattr(self, "tile_offset_ns_spin"):
            self.tile_offset_ns_spin.setSuffix(suffix)
        if hasattr(self, "tile_offset_ew_spin"):
            self.tile_offset_ew_spin.setSuffix(suffix)

    def _convert_meters_to_map_units(self, value_meters, map_units):
        if map_units == QgsUnitTypes.DistanceMeters:
            return value_meters
        factor = QgsUnitTypes.fromUnitToUnitFactor(QgsUnitTypes.DistanceMeters, map_units)
        return value_meters * factor

    def _convert_map_units_to_meters(self, value_units, map_units):
        if map_units == QgsUnitTypes.DistanceMeters:
            return value_units
        factor = QgsUnitTypes.fromUnitToUnitFactor(map_units, QgsUnitTypes.DistanceMeters)
        return value_units * factor

    def _round_up_to_increment(self, value, increment):
        if increment <= 0:
            return value
        units = max(1, math.ceil(value / increment - 1e-9))
        return units * increment

    def _map_tile_offsets_in_degrees(self, offsets, meters_per_deg_lat, meters_per_deg_lon):
        ns = float(offsets.get("ns", 0.0))
        ew = float(offsets.get("ew", 0.0))
        unit = offsets.get("unit", "km")
        if unit == "arcmin":
            return ns / 60.0, ew / 60.0
        # default kilometres
        lat_deg = (ns * 1000.0) / meters_per_deg_lat if meters_per_deg_lat else 0.0
        lon_deg = (ew * 1000.0) / meters_per_deg_lon if meters_per_deg_lon else 0.0
        return lat_deg, lon_deg

    def _prepare_map_tile_cells(self, parent_layer, hex_m):
        geoms = [feat.geometry() for feat in parent_layer.getFeatures()]
        if not geoms:
            return None, "Selected AOI has no geometry to segment."

        aoi_geom = QgsGeometry.unaryUnion(geoms)
        if aoi_geom.isEmpty():
            return None, "AOI geometry is empty; segmentation skipped."

        settings = self._current_map_tile_settings()
        width_km = max(0.001, settings.get("width_km", 50.0))
        tile_width_m = width_km * 1000.0
        alignment = settings.get("alignment", "extent")
        offsets = settings.get("offsets", {"ns": 0.0, "ew": 0.0, "unit": "km"})

        if alignment == "extent":
            result, err = self._prepare_map_tile_cells_extent(parent_layer, aoi_geom, tile_width_m, settings.get("scale_key"))
        else:
            result, err = self._prepare_map_tile_cells_geographic(parent_layer, aoi_geom, tile_width_m, alignment, offsets, settings.get("scale_key"))
        if err:
            return None, err

        if result is None:
            return None, "No segments were generated."

        result.setdefault("tile_width_km", width_km)
        result.setdefault("tile_height_km", width_km)
        result["scale_key"] = settings.get("scale_key")
        result["scale_label"] = settings.get("scale_label")
        result["alignment"] = alignment
        result["offsets"] = offsets
        subdir_default = f"MapTiles_{self._safe_filename(settings.get('scale_key', 'scale'))}_{alignment}"
        result.setdefault("subdir", subdir_default)
        return result, None

    def _prepare_map_tile_cells_extent(self, parent_layer, aoi_geom, tile_width_m, scale_key):
        map_units = parent_layer.crs().mapUnits()
        tile_width_units = self._convert_meters_to_map_units(tile_width_m, map_units)
        if tile_width_units <= 0:
            return None, "Tile width is too small."

        extent = aoi_geom.boundingBox()
        xmin, xmax = extent.xMinimum(), extent.xMaximum()
        ymin, ymax = extent.yMinimum(), extent.yMaximum()

        grid_min_x = math.floor(xmin / tile_width_units) * tile_width_units
        grid_max_x = math.ceil(xmax / tile_width_units) * tile_width_units
        grid_min_y = math.floor(ymin / tile_width_units) * tile_width_units
        grid_max_y = math.ceil(ymax / tile_width_units) * tile_width_units

        cols = max(1, int(math.ceil((grid_max_x - grid_min_x) / tile_width_units)))
        rows = max(1, int(math.ceil((grid_max_y - grid_min_y) / tile_width_units)))

        x_edges = [grid_min_x + i * tile_width_units for i in range(cols + 1)]
        y_edges = [grid_min_y + j * tile_width_units for j in range(rows + 1)]

        cells = self._build_cells_from_edges(aoi_geom, x_edges, y_edges)
        if not cells:
            return None, "No intersection between AOI and computed tile grid."

        origin_geo = None
        try:
            transform = QgsCoordinateTransform(parent_layer.crs(), QgsCoordinateReferenceSystem("EPSG:4326"), QgsProject.instance())
            origin_point = transform.transform(QgsPointXY(grid_min_x, grid_min_y))
            origin_geo = {"lon": origin_point.x(), "lat": origin_point.y()}
        except Exception:
            origin_geo = None

        result = {
            "cells": cells,
            "rows": rows,
            "cols": cols,
            "tile_width_units": tile_width_units,
            "tile_width_km": self._convert_map_units_to_meters(tile_width_units, map_units) / 1000.0,
            "tile_height_km": self._convert_map_units_to_meters(tile_width_units, map_units) / 1000.0,
            "origin": {
                "project": {"x": grid_min_x, "y": grid_min_y},
                "geographic": origin_geo,
            },
        }
        return result, None

    def _prepare_map_tile_cells_geographic(self, parent_layer, aoi_geom, tile_width_m, alignment, offsets, scale_key):
        project = QgsProject.instance()
        crs_src = parent_layer.crs()
        crs_geo = QgsCoordinateReferenceSystem("EPSG:4326")
        transform_to_geo = QgsCoordinateTransform(crs_src, crs_geo, project)
        transform_from_geo = QgsCoordinateTransform(crs_geo, crs_src, project)

        bbox = transform_to_geo.transformBoundingBox(aoi_geom.boundingBox())
        lon_min, lon_max = bbox.xMinimum(), bbox.xMaximum()
        lat_min, lat_max = bbox.yMinimum(), bbox.yMaximum()
        lon_center = (lon_min + lon_max) / 2.0
        lat_center = (lat_min + lat_max) / 2.0

        distance = QgsDistanceArea()
        try:
            distance.setSourceCrs(crs_geo, project.transformContext())
        except Exception:
            pass
        ellipsoid = project.ellipsoid()
        if not ellipsoid:
            ellipsoid = 'WGS84'
        try:
            distance.setEllipsoid(ellipsoid)
        except Exception:
            try:
                distance.setEllipsoid('WGS84')
            except Exception:
                pass
        if hasattr(distance, 'setEllipsoidalMode'):
            try:
                distance.setEllipsoidalMode(True)
            except Exception:
                pass

        try:
            meters_per_deg_lat = distance.measureLine(QgsPointXY(lon_center, lat_center), QgsPointXY(lon_center, lat_center + 1))
        except Exception:
            meters_per_deg_lat = 111320.0
        if not meters_per_deg_lat or math.isnan(meters_per_deg_lat):
            meters_per_deg_lat = 111320.0

        try:
            meters_per_deg_lon = distance.measureLine(QgsPointXY(lon_center, lat_center), QgsPointXY(lon_center + 1, lat_center))
        except Exception:
            meters_per_deg_lon = 111320.0 * max(0.1, math.cos(math.radians(lat_center)))
        if not meters_per_deg_lon or math.isnan(meters_per_deg_lon):
            meters_per_deg_lon = 111320.0 * max(0.1, math.cos(math.radians(lat_center)))

        increment_deg = 0.25 if alignment == "minute" else 1.0
        tile_lon_deg = self._round_up_to_increment(tile_width_m / meters_per_deg_lon, increment_deg)
        tile_lat_deg = self._round_up_to_increment(tile_width_m / meters_per_deg_lat, increment_deg)

        offset_lat_deg, offset_lon_deg = self._map_tile_offsets_in_degrees(offsets, meters_per_deg_lat, meters_per_deg_lon)

        grid_min_lon = math.floor((lon_min - offset_lon_deg) / tile_lon_deg) * tile_lon_deg + offset_lon_deg
        grid_max_lon = math.ceil((lon_max - offset_lon_deg) / tile_lon_deg) * tile_lon_deg + offset_lon_deg
        grid_min_lat = math.floor((lat_min - offset_lat_deg) / tile_lat_deg) * tile_lat_deg + offset_lat_deg
        grid_max_lat = math.ceil((lat_max - offset_lat_deg) / tile_lat_deg) * tile_lat_deg + offset_lat_deg

        cols = max(1, int(math.ceil((grid_max_lon - grid_min_lon) / tile_lon_deg - 1e-9)))
        rows = max(1, int(math.ceil((grid_max_lat - grid_min_lat) / tile_lat_deg - 1e-9)))

        lon_edges = [grid_min_lon + i * tile_lon_deg for i in range(cols + 1)]
        lat_edges = [grid_min_lat + j * tile_lat_deg for j in range(rows + 1)]

        cells = []
        feature_id = 1
        for row_index in range(rows):
            row_num = row_index + 1
            lat_bottom = lat_edges[rows - (row_index + 1)]
            lat_top = lat_edges[rows - row_index]
            for col_index in range(cols):
                col_num = col_index + 1
                lon_left = lon_edges[col_index]
                lon_right = lon_edges[col_index + 1]
                try:
                    ll = transform_from_geo.transform(QgsPointXY(lon_left, lat_bottom))
                    ul = transform_from_geo.transform(QgsPointXY(lon_left, lat_top))
                    ur = transform_from_geo.transform(QgsPointXY(lon_right, lat_top))
                    lr = transform_from_geo.transform(QgsPointXY(lon_right, lat_bottom))
                except Exception as exc:
                    return None, f"Coordinate transform failed: {exc}"

                rect_geom = QgsGeometry.fromPolygonXY([[ll, ul, ur, lr]])
                seg_geom = aoi_geom.intersection(rect_geom)
                if seg_geom.isEmpty():
                    continue
                seg_geom = seg_geom.makeValid()
                if seg_geom.isEmpty():
                    continue
                seg_geom.convertToMultiType()
                cells.append({
                    "id": feature_id,
                    "row": row_num,
                    "col": col_num,
                    "geometry": seg_geom,
                })
                feature_id += 1

        if not cells:
            return None, "No intersection between AOI and snapped map tiles."

        origin_project = None
        try:
            origin_project = transform_from_geo.transform(QgsPointXY(grid_min_lon, grid_min_lat))
        except Exception:
            origin_project = None

        result = {
            "cells": cells,
            "rows": rows,
            "cols": cols,
            "tile_width_km": tile_lon_deg * meters_per_deg_lon / 1000.0,
            "tile_height_km": tile_lat_deg * meters_per_deg_lat / 1000.0,
            "origin": {
                "project": {"x": origin_project.x(), "y": origin_project.y()} if origin_project else None,
                "geographic": {"lon": grid_min_lon, "lat": grid_min_lat},
            },
            "grid": {
                "tile_lon_deg": tile_lon_deg,
                "tile_lat_deg": tile_lat_deg,
                "meters_per_deg_lon": meters_per_deg_lon,
                "meters_per_deg_lat": meters_per_deg_lat,
            },
        }
        return result, None

    def _metadata_key_for_layer(self, layer):
        return self._safe_filename(layer.name().replace(" ", "_")).lower()

    def _selected_aoi_layer_for_segmentation(self):
        if not hasattr(self, "cboAOI_segment"):
            return None
        lyr_id = self.cboAOI_segment.currentData()
        return QgsProject.instance().mapLayer(lyr_id) if lyr_id else None

    def _has_segments_for_layer(self, layer):
        key = self._metadata_key_for_layer(layer)
        meta = self._segment_metadata.get(key, {})
        if meta.get("segments"):
            return True
        seg_dir = self._segment_directory_for_layer(layer)
        if os.path.isdir(seg_dir):
            for _, _, files in os.walk(seg_dir):
                if any(name.lower().endswith('.shp') for name in files):
                    return True
        return False

    def _update_segment_buttons_state(self):
        parent = self._selected_aoi_layer_for_segmentation()
        has_parent = parent is not None
        if hasattr(self, "btn_preview_segments"):
            self.btn_preview_segments.setEnabled(bool(has_parent))
        if hasattr(self, "btn_segment_aoi"):
            self.btn_segment_aoi.setEnabled(bool(has_parent))
        if hasattr(self, "btn_clear_segments"):
            self.btn_clear_segments.setEnabled(bool(has_parent and parent and self._has_segments_for_layer(parent)))

    def _clean_vector_sidecars(self, path_with_ext):
        base, _ = os.path.splitext(path_with_ext)
        for ext in (".shp", ".shx", ".dbf", ".prj", ".cpg", ".qix", ".qmd"):
            p = base + ext
            if os.path.exists(p):
                try:
                    os.remove(p)
                except Exception:
                    pass

    def _remove_segment_preview(self, parent_layer):
        key = self._metadata_key_for_layer(parent_layer)
        lyr_id = self._segment_preview_layers.pop(key, None)
        if lyr_id:
            lyr = QgsProject.instance().mapLayer(lyr_id)
            if lyr:
                QgsProject.instance().removeMapLayer(lyr.id())

    def _remove_all_segment_previews(self):
        proj = QgsProject.instance()
        for lyr_id in list(self._segment_preview_layers.values()):
            lyr = proj.mapLayer(lyr_id)
            if lyr:
                proj.removeMapLayer(lyr.id())
        self._segment_preview_layers.clear()

    def _remove_segment_layers(self, parent_layer):
        seg_dir = self._segment_directory_for_layer(parent_layer)
        seg_dir_abs = os.path.abspath(seg_dir)
        proj = QgsProject.instance()
        to_remove = []
        for lyr in proj.mapLayers().values():
            source = getattr(lyr, "source", lambda: "")()
            source_path = source.split("|")[0] if source else ""
            if source_path:
                try:
                    common = os.path.commonpath([os.path.abspath(source_path), seg_dir_abs])
                except ValueError:
                    common = ""
                if common == seg_dir_abs:
                    to_remove.append(lyr.id())
        if to_remove:
            proj.removeMapLayers(to_remove)

    def _ensure_segments_group(self, parent_layer):
        group_path = ["Base", "Base Grid", parent_layer.name(), "Segments"]
        return self._ensure_nested_groups(group_path)

    def preview_segments_for_selected_aoi(self):
        parent_layer = self._selected_aoi_layer_for_segmentation()
        if not parent_layer:
            self.log("Select an AOI to preview segments.")
            return

        mode = self._segment_mode()
        try:
            hex_m = max(1.0, float(self.hex_scale_edit.text()))
        except Exception:
            hex_m = 500.0
            self.hex_scale_edit.setText("500")

        if mode == "map_tile":
            result, err = self._prepare_map_tile_cells(parent_layer, hex_m)
        else:
            rows = max(1, int(self.seg_rows_spin.value())) if hasattr(self, "seg_rows_spin") else 1
            cols = max(1, int(self.seg_cols_spin.value())) if hasattr(self, "seg_cols_spin") else 1
            result, err = self._prepare_segment_cells(parent_layer, rows, cols, hex_m)
        if err:
            self.log(err)
            return

        cells = result.get("cells", []) if result else []
        if not cells:
            self.log("No segments were computed for preview.")
            return

        self._remove_segment_preview(parent_layer)

        crs = parent_layer.crs()
        mem_layer = QgsVectorLayer(f"MultiPolygon?crs={crs.authid()}", f"{parent_layer.name()} - Segment Preview", "memory")
        provider = mem_layer.dataProvider()
        provider.addAttributes([
            QgsField("id", QVariant.Int),
            QgsField("row", QVariant.Int),
            QgsField("col", QVariant.Int),
        ])
        mem_layer.updateFields()

        features = []
        for cell in cells:
            feat = QgsFeature(mem_layer.fields())
            feat.setAttribute("id", cell["id"])
            feat.setAttribute("row", cell["row"])
            feat.setAttribute("col", cell["col"])
            feat.setGeometry(cell["geometry"])
            features.append(feat)

        if features:
            provider.addFeatures(features)
            mem_layer.updateExtents()

        sym = QgsFillSymbol.createSimple({
            'color': '255,255,255,0',
            'outline_color': '0,0,0,200',
            'outline_width': '0.6',
            'outline_style': 'dash'
        })
        mem_layer.setRenderer(QgsSingleSymbolRenderer(sym))

        proj = QgsProject.instance()
        group = self._ensure_segments_group(parent_layer)
        proj.addMapLayer(mem_layer, False)
        group.insertLayer(0, mem_layer)

        key = self._metadata_key_for_layer(parent_layer)
        self._segment_preview_layers[key] = mem_layer.id()
        label = "map tiles" if self._segment_mode() == "map_tile" else "segments"
        self.log(f"Previewed {len(features)} {label} for {parent_layer.name()}.")

    def _prepare_segment_cells(self, parent_layer, rows, cols, hex_m):
        geoms = [feat.geometry() for feat in parent_layer.getFeatures()]
        if not geoms:
            return None, "Selected AOI has no geometry to segment."

        aoi_geom = QgsGeometry.unaryUnion(geoms)
        if aoi_geom.isEmpty():
            return None, "AOI geometry is empty; segmentation skipped."

        extent = aoi_geom.boundingBox()
        xmin, xmax = extent.xMinimum(), extent.xMaximum()
        ymin, ymax = extent.yMinimum(), extent.yMaximum()

        grid_min_x = math.floor(xmin / hex_m) * hex_m
        grid_max_x = math.ceil(xmax / hex_m) * hex_m
        grid_min_y = math.floor(ymin / hex_m) * hex_m
        grid_max_y = math.ceil(ymax / hex_m) * hex_m

        width_cells = max(cols, int(math.ceil((grid_max_x - grid_min_x) / hex_m)))
        if width_cells % cols != 0:
            width_cells = int(math.ceil(width_cells / cols) * cols)
            grid_max_x = grid_min_x + width_cells * hex_m

        height_cells = max(rows, int(math.ceil((grid_max_y - grid_min_y) / hex_m)))
        if height_cells % rows != 0:
            height_cells = int(math.ceil(height_cells / rows) * rows)
            grid_max_y = grid_min_y + height_cells * hex_m

        step_x = (grid_max_x - grid_min_x) / cols if cols else 0
        step_y = (grid_max_y - grid_min_y) / rows if rows else 0

        x_edges = [grid_min_x + i * step_x for i in range(cols + 1)] if cols else []
        y_edges = [grid_min_y + j * step_y for j in range(rows + 1)] if rows else []

        cells = []
        feature_id = 1
        for row_index in range(rows):
            row_num = row_index + 1
            ymin_seg = y_edges[rows - (row_index + 1)]
            ymax_seg = y_edges[rows - row_index]
            for col_index in range(cols):
                col_num = col_index + 1
                xmin_seg = x_edges[col_index]
                xmax_seg = x_edges[col_index + 1]

                rect_geom = QgsGeometry.fromPolygonXY([[
                    QgsPointXY(xmin_seg, ymin_seg),
                    QgsPointXY(xmin_seg, ymax_seg),
                    QgsPointXY(xmax_seg, ymax_seg),
                    QgsPointXY(xmax_seg, ymin_seg)
                ]])

                seg_geom = aoi_geom.intersection(rect_geom)
                if seg_geom.isEmpty():
                    continue

                seg_geom = seg_geom.makeValid()
                if seg_geom.isEmpty():
                    continue
                seg_geom.convertToMultiType()

                cells.append({
                    "id": feature_id,
                    "row": row_num,
                    "col": col_num,
                    "geometry": seg_geom,
                })
                feature_id += 1

        info = {
            "cells": cells,
            "aoi_geom": aoi_geom,
            "grid_min_x": grid_min_x,
            "grid_max_x": grid_max_x,
            "grid_min_y": grid_min_y,
            "grid_max_y": grid_max_y,
            "step_x": step_x,
            "step_y": step_y,
        }
        return info, None

    def segment_selected_aoi(self):
        parent_layer = self._selected_aoi_layer_for_segmentation()
        if not parent_layer:
            self.log('Select an AOI to segment.')
            return

        mode = self._segment_mode()
        try:
            hex_m = max(1.0, float(self.hex_scale_edit.text()))
        except Exception:
            hex_m = 500.0
            self.hex_scale_edit.setText('500')

        base_seg_dir = self._segment_directory_for_layer(parent_layer)
        os.makedirs(base_seg_dir, exist_ok=True)

        if mode == 'map_tile':
            result, err = self._prepare_map_tile_cells(parent_layer, hex_m)
        else:
            rows = max(1, int(self.seg_rows_spin.value())) if hasattr(self, 'seg_rows_spin') else 1
            cols = max(1, int(self.seg_cols_spin.value())) if hasattr(self, 'seg_cols_spin') else 1
            result, err = self._prepare_segment_cells(parent_layer, rows, cols, hex_m)
        if err:
            self.log(err)
            return

        result = result or {}
        cells = result.get('cells', [])
        if not cells:
            self.log('No segments were created for the selected AOI.')
            return

        if mode == 'map_tile':
            rows = int(result.get('rows') or 0)
            cols = int(result.get('cols') or 0)
            if rows <= 0:
                rows = len({cell['row'] for cell in cells})
            if cols <= 0:
                cols = len({cell['col'] for cell in cells})
            scale_key = result.get('scale_key') or 'map_tiles'
            alignment = result.get('alignment') or 'extent'
            subdir_name = result.get('subdir') or f"MapTiles_{self._safe_filename(scale_key)}_{alignment}"
            seg_dir = os.path.join(base_seg_dir, subdir_name)
        else:
            rows = max(1, int(self.seg_rows_spin.value())) if hasattr(self, 'seg_rows_spin') else 1
            cols = max(1, int(self.seg_cols_spin.value())) if hasattr(self, 'seg_cols_spin') else 1
            alignment = 'equal'
            subdir_name = ''
            seg_dir = base_seg_dir

        self._remove_segment_preview(parent_layer)
        self._remove_segment_layers(parent_layer, seg_dir)
        shutil.rmtree(seg_dir, ignore_errors=True)
        os.makedirs(seg_dir, exist_ok=True)

        fields = QgsFields()
        fields.append(QgsField('id', QVariant.Int))
        fields.append(QgsField('row', QVariant.Int))
        fields.append(QgsField('col', QVariant.Int))
        fields.append(QgsField('name', QVariant.String, len=80))
        fields.append(QgsField('scale', QVariant.String, len=32))
        fields.append(QgsField('align', QVariant.String, len=16))

        proj = QgsProject.instance()
        group = self._ensure_segments_group(parent_layer)
        created_layers = []
        segment_names = []
        scale_key = result.get('scale_key') if mode == 'map_tile' else ''
        scale_label = result.get('scale_label') if mode == 'map_tile' else ''
        alignment = result.get('alignment') if mode == 'map_tile' else 'equal'

        for cell in cells:
            seg_geom = cell['geometry']
            row_num = cell['row']
            col_num = cell['col']
            if mode == 'map_tile':
                scale_safe = self._safe_filename(scale_key or 'map_tiles')
                seg_name = f"{parent_layer.name()} - Tile {scale_key or scale_label or ''} R{row_num}C{col_num}"
                shp_name = self._safe_filename(f"Tile_{scale_safe}_R{row_num}_C{col_num}.shp")
            else:
                seg_name = f"{parent_layer.name()} - Segment R{row_num}C{col_num}"
                shp_name = self._safe_filename(f"Segment_{row_num}_{col_num}.shp")
            shp_path = os.path.join(seg_dir, shp_name)
            self._clean_vector_sidecars(shp_path)

            writer = QgsVectorFileWriter(
                shp_path, 'UTF-8', fields, QgsWkbTypes.MultiPolygon, parent_layer.crs(), 'ESRI Shapefile'
            )
            if writer.hasError() != QgsVectorFileWriter.NoError:
                del writer
                self.log(f'Failed to write segment shapefile: {shp_path}')
                continue

            feat = QgsFeature(fields)
            feat.setAttribute('id', cell['id'])
            feat.setAttribute('row', row_num)
            feat.setAttribute('col', col_num)
            feat.setAttribute('name', seg_name)
            feat.setAttribute('scale', scale_key if mode == 'map_tile' else '')
            feat.setAttribute('align', alignment if mode == 'map_tile' else 'equal')
            feat.setGeometry(seg_geom)
            writer.addFeature(feat)
            del writer

            seg_layer = QgsVectorLayer(shp_path, seg_name, 'ogr')
            if not seg_layer.isValid():
                self.log(f'Segment shapefile saved but failed to load: {shp_path}')
                continue

            styled = self._apply_style(seg_layer, 'aoi_segment.qml') or self._apply_style(seg_layer, 'aoi.qml')
            if not styled:
                sym = QgsFillSymbol.createSimple({
                    'color': '255,255,255,0',
                    'outline_color': '0,150,136',
                    'outline_width': '0.6'
                })
                seg_layer.setRenderer(QgsSingleSymbolRenderer(sym))

            proj.addMapLayer(seg_layer, False)
            group.addLayer(seg_layer)
            created_layers.append(seg_layer)
            segment_names.append(seg_layer.name())

        if not created_layers:
            self.log('No segments were created; the AOI may be too small for the requested grid.')
            shutil.rmtree(seg_dir, ignore_errors=True)
            self._update_segment_buttons_state()
            return

        key = self._metadata_key_for_layer(parent_layer)
        metadata_entry = {
            'parent': parent_layer.name(),
            'rows': rows,
            'cols': cols,
            'segments': segment_names,
            'mode': mode,
            'alignment': alignment,
        }
        if mode == 'map_tile':
            metadata_entry.update({
                'scale': scale_key,
                'scale_label': scale_label,
                'alignment': alignment,
                'offsets': result.get('offsets'),
                'origin': result.get('origin'),
                'tile_width_km': result.get('tile_width_km'),
                'tile_height_km': result.get('tile_height_km'),
                'grid': result.get('grid'),
                'subdir': os.path.relpath(seg_dir, base_seg_dir).replace('\\', '/') if seg_dir != base_seg_dir else '',
            })
        self._segment_metadata[key] = metadata_entry

        self._save_project_settings()
        self._populate_aoi_combo()
        if mode == 'map_tile':
            label = scale_label or scale_key or 'map tiles'
            self.log(f"Created {len(created_layers)} map tiles ({label}) for {parent_layer.name()} aligned to {alignment} grid.")
        else:
            self.log(f"Created {len(created_layers)} segments for {parent_layer.name()} in {rows}x{cols} grid.")

    def clear_segments_for_selected_aoi(self):
        parent_layer = self._selected_aoi_layer_for_segmentation()
        if not parent_layer:
            self.log("Select an AOI to clear segments.")
            return

        seg_dir = self._segment_directory_for_layer(parent_layer)
        self._remove_segment_preview(parent_layer)
        self._remove_segment_layers(parent_layer)
        shutil.rmtree(seg_dir, ignore_errors=True)

        key = self._metadata_key_for_layer(parent_layer)
        removed = False
        if key in self._segment_metadata:
            removed = bool(self._segment_metadata[key].get("segments"))
            self._segment_metadata.pop(key, None)

        self._save_project_settings()
        self._populate_aoi_combo()
        if removed:
            self.log(f"Removed stored segments for {parent_layer.name()}.")
        else:
            self.log(f"No stored segments found for {parent_layer.name()}.")    
    def _build_cells_from_edges(self, aoi_geom, x_edges, y_edges):
        cells = []
        rows = max(0, len(y_edges) - 1)
        cols = max(0, len(x_edges) - 1)
        feature_id = 1
        for row_index in range(rows):
            row_num = row_index + 1
            ymin_seg = y_edges[rows - (row_index + 1)]
            ymax_seg = y_edges[rows - row_index]
            for col_index in range(cols):
                col_num = col_index + 1
                xmin_seg = x_edges[col_index]
                xmax_seg = x_edges[col_index + 1]
                rect_geom = QgsGeometry.fromPolygonXY([
                    [
                        QgsPointXY(xmin_seg, ymin_seg),
                        QgsPointXY(xmin_seg, ymax_seg),
                        QgsPointXY(xmax_seg, ymax_seg),
                        QgsPointXY(xmax_seg, ymin_seg),
                    ]
                ])
                seg_geom = aoi_geom.intersection(rect_geom)
                if seg_geom.isEmpty():
                    continue
                seg_geom = seg_geom.makeValid()
                if seg_geom.isEmpty():
                    continue
                seg_geom.convertToMultiType()
                cells.append(
                    {
                        'id': feature_id,
                        'row': row_num,
                        'col': col_num,
                        'geometry': seg_geom,
                    }
                )
                feature_id += 1
        return cells
