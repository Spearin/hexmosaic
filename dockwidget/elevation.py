"""Elevation management helpers for HexMosaic."""
from __future__ import annotations

import json
import math
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Optional

from qgis.utils import iface
from qgis.PyQt.QtCore import Qt, QSettings
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsDistanceArea,
    QgsMapLayerStyle,
    QgsProject,
    QgsRasterLayer,
    QgsUnitTypes,
    QgsVectorLayer,
)

from ..utils.elevation_hex import (
    format_sampling_summary,
    sample_hex_elevations,
    write_hex_elevation_layer,
)


class ElevationMixin:
    def _refresh_elevation_styles(self):
        self.elev_style_combo.clear()
        styles_dir = self.styles_dir_edit.text().strip()
        if not styles_dir:
            return
        elev_dir = os.path.join(styles_dir, "elevation")
        if not os.path.isdir(elev_dir):
            return
        qmls = [f for f in os.listdir(elev_dir) if f.lower().endswith(".qml")]
        for q in sorted(qmls):
            self.elev_style_combo.addItem(q, os.path.join(elev_dir, q))

    def _estimate_aoi_area_km2(self, aoi_layer):
        """Approximate AOI area in square kilometres (returns None if unavailable)."""
        if not aoi_layer:
            return None
        extent = aoi_layer.extent()
        if extent.isEmpty():
            return None
        project = QgsProject.instance()
        tc = project.transformContext()
        src_crs = aoi_layer.crs()
        meter_crs = None
        if src_crs.isValid() and src_crs.mapUnits() == QgsUnitTypes.DistanceMeters:
            meter_crs = src_crs
        else:
            map_crs = iface.mapCanvas().mapSettings().destinationCrs()
            if map_crs.isValid() and map_crs.mapUnits() == QgsUnitTypes.DistanceMeters:
                meter_crs = map_crs
            else:
                wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
                try:
                    to_wgs = QgsCoordinateTransform(src_crs, wgs84, tc)
                    cx = (extent.xMinimum() + extent.xMaximum()) / 2.0
                    cy = (extent.yMinimum() + extent.yMaximum()) / 2.0
                    lon, lat = to_wgs.transform(cx, cy)
                    epsg = self._utm_epsg_for_lonlat(lon, lat)
                    meter_crs = QgsCoordinateReferenceSystem.fromEpsgId(epsg)
                except Exception:
                    meter_crs = None
        if meter_crs is None or not meter_crs.isValid():
            return None
        try:
            to_meter = QgsCoordinateTransform(src_crs, meter_crs, tc)
            rect_m = to_meter.transformBoundingBox(extent)
        except Exception:
            return None
        width = max(0.0, rect_m.width())
        height = max(0.0, rect_m.height())
        area_m2 = width * height
        if area_m2 <= 0:
            return None
        return area_m2 / 1_000_000.0

    def _max_area_for_dataset(self, preset):
        try:
            value = float(preset.get("max_km2"))
            if value > 0:
                return value
        except Exception:
            pass
        return None

    def _dem_source_presets(self):
        """Return available DEM download presets."""
        return [
            {"key": "SRTMGL3", "label": "SRTM 90m (SRTMGL3)", "provider": "opentopo", "demtype": "SRTMGL3", "max_km2": 4_050_000, "fallback": ["COP90", "COP30", "SRTMGL1", "AW3D30", "ASTER"]},
            {"key": "SRTMGL1", "label": "SRTM 30m (SRTMGL1)", "provider": "opentopo", "demtype": "SRTMGL1", "max_km2": 450_000, "fallback": ["COP30", "COP90", "AW3D30", "ASTER"]},
            {"key": "COP30", "label": "Copernicus GLO-30 (COP30)", "provider": "opentopo", "demtype": "COP30", "max_km2": 450_000, "fallback": ["SRTMGL3", "SRTMGL1", "AW3D30", "ASTER"]},
            {"key": "COP90", "label": "Copernicus GLO-90 (COP90)", "provider": "opentopo", "demtype": "COP90", "max_km2": 4_050_000, "fallback": ["SRTMGL3", "SRTMGL1", "COP30", "AW3D30", "ASTER"]},
            {"key": "AW3D30", "label": "ALOS World 3D 30m (AW3D30)", "provider": "opentopo", "demtype": "AW3D30", "max_km2": 450_000, "fallback": ["SRTMGL1", "COP30", "COP90", "ASTER"]},
            {"key": "ASTER", "label": "ASTER GDEM v3", "provider": "opentopo", "demtype": "ASTER", "max_km2": 450_000, "fallback": ["SRTMGL1", "COP30", "COP90", "AW3D30"]},
        ]

    def _apply_best_elevation_style(self, raster_layer: QgsRasterLayer):
        """
        Apply the best elevation style based on min elevation -> base 50.
        Returns the full QML path applied, or None if nothing applied.
        """
        if not raster_layer or not raster_layer.isValid():
            return None

        prov = raster_layer.dataProvider()
        stats = prov.bandStatistics(1)
        min_val = getattr(stats, "minimumValue", None)
        if min_val is None or math.isinf(min_val) or math.isnan(min_val):
            from qgis.core import QgsRasterBandStats
            stats = prov.bandStatistics(1, QgsRasterBandStats.All)
            min_val = stats.minimumValue

        if min_val is None:
            self.log("Elevation: could not read minimum elevation; leaving default style.")
            return None

        base = int(math.floor(float(min_val) / 50.0) * 50)

        elev_dir = self._styles_elevation_dir()
        if not elev_dir or not os.path.isdir(elev_dir):
            return None

        def _leading_int(path):
            fn = os.path.basename(path)
            num = ""
            for ch in fn:
                if ch.isdigit() or (ch == '-' and not num):
                    num += ch
                else:
                    break
            try:
                return int(num)
            except:
                return None

        candidates = [os.path.join(elev_dir, f) for f in os.listdir(elev_dir) if f.lower().endswith(".qml")]
        chosen = None
        for qml in candidates:
            n = _leading_int(qml)
            if n is not None and n == base:
                chosen = qml
                break

        if not chosen:
            self.log(f"No matching elevation style for base={base}; leaving default.")
            return None

        ok, _ = raster_layer.loadNamedStyle(chosen)
        raster_layer.triggerRepaint()
        if ok:
            self.log(f"Applied elevation style: {os.path.basename(chosen)} (min={min_val:.1f} -> base={base})")
            # reflect in the combo
            self._select_style_in_combo(chosen)
            return chosen
        return None

    def _select_style_in_combo(self, qml_path: str):
        if not qml_path:
            return
        for i in range(self.elev_style_combo.count()):
            if os.path.normcase(self.elev_style_combo.itemData(i)) == os.path.normcase(qml_path):
                self.elev_style_combo.setCurrentIndex(i)
                break

    def _apply_elevation_style_and_add(self):
        path = self.elev_path_edit.text().strip()
        if not os.path.isfile(path):
            self.log("Elevation: file not found.")
            return
        rl = QgsRasterLayer(path, os.path.basename(path))
        if not rl.isValid():
            self.log("Elevation: failed to load raster.")
            return

        # auto-style first, then fallback to user selection (if any)
        qml_used = self._apply_best_elevation_style(rl)
        if not qml_used:
            qml_path = self.elev_style_combo.currentData()
            if qml_path and os.path.isfile(qml_path):
                _ok, _ = rl.loadNamedStyle(qml_path)
                rl.triggerRepaint()

        proj = QgsProject.instance()
        elev_grp = (proj.layerTreeRoot().findGroup("Elevation") or
                    proj.layerTreeRoot().addGroup("Elevation"))
        proj.addMapLayer(rl, False); elev_grp.addLayer(rl)

        aoi = self._selected_aoi_layer_for_elev() or self._selected_aoi_layer()
        if aoi:
            iface.mapCanvas().setExtent(aoi.extent())
            iface.mapCanvas().refresh()

        # reflect final selection in combo
        if qml_used:
            idx = self.elev_style_combo.findText(os.path.basename(qml_used), Qt.MatchFixedString)
            if idx >= 0:
                self.elev_style_combo.setCurrentIndex(idx)

        self.log(f"Elevation added: {path}")

    def _apply_style_to_existing_dem(self):
        """
        Apply a style (auto or selected) to the DEM layer referenced in the DEM file field,
        without adding a duplicate layer. If the layer isn't loaded yet, load it once.
        """
        path = (self.elev_path_edit.text() or "").strip()
        if not path:
            self.log("DEM style: set a DEM file first.")
            return
        path_norm = os.path.normcase(os.path.abspath(path))

        # Try to find an already-loaded raster with this source
        proj = QgsProject.instance()
        target = None
        for lyr in proj.mapLayers().values():
            if isinstance(lyr, QgsRasterLayer):
                # compare by source path (normalize for Windows)
                try:
                    if os.path.normcase(os.path.abspath(lyr.source())) == path_norm:
                        target = lyr
                        break
                except Exception:
                    pass

        # If not loaded, load it once and add under Elevation
        if target is None:
            target = QgsRasterLayer(path, os.path.basename(path))
            if not target.isValid():
                self.log("DEM style: failed to load raster from path.")
                return
            elev_grp = (proj.layerTreeRoot().findGroup("Elevation") or
                        proj.layerTreeRoot().addGroup("Elevation"))
            proj.addMapLayer(target, False)
            elev_grp.addLayer(target)

        # Try auto-style first; else use the currently selected style in the combo
        qml_used = self._apply_best_elevation_style(target)
        if not qml_used:
            qml_path = self.elev_style_combo.currentData()
            if qml_path and os.path.isfile(qml_path):
                ok, _ = target.loadNamedStyle(qml_path); target.triggerRepaint()
                if ok:
                    self._select_style_in_combo(qml_path)
                    self.log(f"Applied style: {os.path.basename(qml_path)}")
                else:
                    self.log("DEM style: failed to apply selected QML.")

    def generate_hex_elevation_layer(self):
        dem_layer = self._selected_hex_dem_layer()
        if not dem_layer or not dem_layer.isValid():
            self.log("Hex elevation: select a DEM raster layer first.")
            return

        hex_layer = self._selected_hex_tiles_layer()
        if not hex_layer or not hex_layer.isValid():
            self.log("Hex elevation: select a hex polygon layer to sample.")
            return

        method = self.cbo_hex_sample_method.currentData() if hasattr(self, "cbo_hex_sample_method") else "mean"
        try:
            bucket_size = float(self.spin_hex_bucket.value()) if hasattr(self, "spin_hex_bucket") else 1.0
        except Exception:
            bucket_size = 1.0
            if hasattr(self, "spin_hex_bucket"):
                self.spin_hex_bucket.setValue(1)

        overwrite = bool(self.chk_hex_overwrite.isChecked()) if hasattr(self, "chk_hex_overwrite") else False

        base_layer = self._selected_aoi_layer_for_elev() or self._selected_aoi_layer()
        base_name = base_layer.name() if base_layer else hex_layer.name()
        shp_path = self._hex_elevation_output_path(base_name)

        if os.path.exists(shp_path) and not overwrite:
            self.log("Hex elevation: output exists. Enable overwrite to regenerate.")
            return

        start = time.time()
        try:
            result = sample_hex_elevations(dem_layer, hex_layer, method=method, bucket_size=bucket_size)
        except Exception as exc:
            self.log(f"Hex elevation: sampling failed - {exc}")
            return

        if not result.samples:
            self.log("Hex elevation: no features were sampled.")
            return

        self._clean_vector_sidecars(shp_path)

        dem_source = os.path.basename(dem_layer.source() or "") or dem_layer.name()
        generated_at = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

        ok, err = write_hex_elevation_layer(
            hex_layer,
            result,
            shp_path,
            dem_source=dem_source,
            bucket_method=str(method),
            generated_at=generated_at,
        )
        if not ok:
            self.log(f"Hex elevation: failed to write shapefile - {err}")
            return

        layer_name = f"{base_name} - Hex Elevation"
        new_layer = QgsVectorLayer(shp_path, layer_name, "ogr")
        if not new_layer or not new_layer.isValid():
            self.log("Hex elevation: output layer saved but could not be loaded.")
            return

        alias_map = {
            "elev_value": "elev_value",
            "elev_bucket": "elev_bucket",
            "dem_source": "dem_source",
            "bucket_method": "bucket_method",
            "generated_at": "generated_at",
        }
        for field_name, alias in alias_map.items():
            idx = new_layer.fields().indexOf(field_name)
            if idx < 0 and len(field_name) > 10:
                idx = new_layer.fields().indexOf(field_name[:10])
            if idx >= 0:
                new_layer.setFieldAlias(idx, alias)

        new_layer.setCustomProperty("hexmosaic/dem_source", dem_source)
        new_layer.setCustomProperty("hexmosaic/bucket_method", method)
        new_layer.setCustomProperty("hexmosaic/bucket_size", float(result.bucket_size))
        new_layer.setCustomProperty("hexmosaic/generated_at", generated_at)

        styled = False
        try:
            style = QgsMapLayerStyle()
            if style.readFromLayer(dem_layer):
                styled = bool(style.apply(new_layer))
        except Exception:
            styled = False

        if not styled:
            styled = self._apply_style(new_layer, "elevation_hex.qml")

        if styled:
            new_layer.triggerRepaint()

        proj = QgsProject.instance()
        target_group = self._ensure_nested_groups(["Elevation", "Hex Palette"])

        out_norm = os.path.normcase(os.path.abspath(shp_path))
        existing = [
            lyr.id()
            for lyr in proj.mapLayers().values()
            if hasattr(lyr, "source")
            and os.path.normcase(os.path.abspath(str(lyr.source()))) == out_norm
        ]
        if existing:
            proj.removeMapLayers(existing)

        proj.addMapLayer(new_layer, False)
        target_group.addLayer(new_layer)

        elapsed = time.time() - start
        summary = format_sampling_summary(result)
        self.log(f"Hex elevation: saved {os.path.basename(shp_path)} ({summary}, {elapsed:.1f}s).")

        for warn in result.warnings:
            self.log(f"Hex elevation warning: {warn}")

        self._populate_hex_elevation_inputs()
        self._rebuild_export_tree()

    def _aoi_extent_wgs84(self):
        """
        Returns (west, east, south, north) of the selected AOI in EPSG:4326.
        None if no AOI or empty.
        """
        aoi = self._selected_aoi_layer()
        if not aoi:
            return None

        ext = aoi.extent()
        if ext.isEmpty():
            return None

        src = aoi.crs()
        dst = QgsCoordinateReferenceSystem("EPSG:4326")
        if not src.isValid():
            return None

        tr = QgsCoordinateTransform(src, dst, QgsProject.instance().transformContext())
        ll = tr.transform(ext.xMinimum(), ext.yMinimum())
        ur = tr.transform(ext.xMaximum(), ext.yMaximum())

        west  = min(ll.x(), ur.x())
        east  = max(ll.x(), ur.x())
        south = min(ll.y(), ur.y())
        north = max(ll.y(), ur.y())
        return (west, east, south, north)

    def _bbox_wgs84_with_margin(self, aoi_layer, margin_m: int = 1000):
        """
        Return (west, east, south, north) in EPSG:4326 for the AOI extent
        expanded by `margin_m` meters on all sides (in a projected CRS).
        We expand in a meter CRS to avoid degree-vs-meter errors.
        """
        if not aoi_layer:
            return None

        ext_src = aoi_layer.extent()
        if ext_src.isEmpty():
            return None

        proj = QgsProject.instance()
        tc = proj.transformContext()

        # Pick a meter CRS to buffer the rectangle:
        # - If AOI is already meters, use it.
        # - Else try project CRS if meters.
        # - Else compute UTM from AOI centroid.
        src_crs = aoi_layer.crs()
        meter_crs = None
        if src_crs.isValid() and src_crs.mapUnits() == QgsUnitTypes.DistanceMeters:
            meter_crs = src_crs
        else:
            proj_crs = iface.mapCanvas().mapSettings().destinationCrs()
            if proj_crs.isValid() and proj_crs.mapUnits() == QgsUnitTypes.DistanceMeters:
                meter_crs = proj_crs
            else:
                # Build UTM from centroid (in WGS84)
                wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
                to_wgs = QgsCoordinateTransform(src_crs, wgs84, tc)
                cx = (ext_src.xMinimum() + ext_src.xMaximum()) / 2.0
                cy = (ext_src.yMinimum() + ext_src.yMaximum()) / 2.0
                c_ll = to_wgs.transform(cx, cy)
                epsg = self._utm_epsg_for_lonlat(c_ll.x(), c_ll.y())
                meter_crs = QgsCoordinateReferenceSystem.fromEpsgId(epsg)

        # Transform extent -> meter CRS, expand, then -> WGS84
        tr_to_m = QgsCoordinateTransform(src_crs, meter_crs, tc)
        rect_m = tr_to_m.transformBoundingBox(ext_src)
        rect_m.grow(margin_m)  # expand by margin on all sides

        wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        tr_to_wgs = QgsCoordinateTransform(meter_crs, wgs84, tc)
        rect_ll = tr_to_wgs.transformBoundingBox(rect_m)

        west, east = rect_ll.xMinimum(), rect_ll.xMaximum()
        south, north = rect_ll.yMinimum(), rect_ll.yMaximum()

        # clamp
        west  = max(-180.0, min(180.0, west))
        east  = max(-180.0, min(180.0, east))
        south = max(-90.0,  min(90.0,  south))
        north = max(-90.0,  min(90.0,  north))
        if east <= west or north <= south:
            return None
        return (west, east, south, north)

    def download_dem_from_opentopo(self):
        key = self.opentopo_key_edit.text().strip() or QSettings("HexMosaicOrg", "HexMosaic").value("opentopo/api_key", "", type=str)
        if not key:
            self.log("OpenTopography: Please set your API key in Setup.")
            self.tb.setCurrentIndex(0)
            return

        aoi = self._selected_aoi_layer_for_elev() or self._selected_aoi_layer()
        if not aoi:
            self.log("OpenTopography: Select an AOI first.")
            return

        pad = 0.01
        ext = aoi.extent()
        tr = QgsCoordinateTransform(aoi.crs(), QgsCoordinateReferenceSystem("EPSG:4326"),
                                    QgsProject.instance().transformContext())
        ll = tr.transform(ext.xMinimum(), ext.yMinimum())
        ur = tr.transform(ext.xMaximum(), ext.yMaximum())
        west  = max(-180.0, min(180.0, min(ll.x(), ur.x()) - pad))
        east  = max(-180.0, min(180.0, max(ll.x(), ur.x()) + pad))
        south = max(-90.0,  min(90.0,  min(ll.y(), ur.y()) - pad))
        north = max(-90.0,  min(90.0,  max(ll.y(), ur.y()) + pad))
        if east <= west or north <= south:
            self.log("OpenTopography: AOI extent invalid in WGS84.")
            return

        area_km2 = self._estimate_aoi_area_km2(aoi)

        presets = {p['key']: p for p in self._dem_source_presets()}
        initial_key = self.cbo_dem_source.currentData() if hasattr(self, 'cbo_dem_source') else 'SRTMGL3'

        def enqueue(keys, key):
            if key and key in presets and key not in keys:
                keys.append(key)

        candidate_keys = []
        enqueue(candidate_keys, initial_key)
        if initial_key in presets:
            for fb in presets[initial_key].get('fallback', []):
                enqueue(candidate_keys, fb)
        for key_default in ('SRTMGL3', 'SRTMGL1', 'COP30', 'COP90', 'AW3D30', 'ASTER'):
            enqueue(candidate_keys, key_default)

        attempted = []
        errors = []

        aoi_name = self._safe_filename(aoi.name()) if aoi.name() else "AOI"
        out_dir = self._layers_elevation_dir()

        for dataset_key in candidate_keys:
            preset = presets.get(dataset_key)
            if not preset:
                continue
            label = preset.get('label', dataset_key)
            attempted.append(label)
            max_area = self._max_area_for_dataset(preset)
            if area_km2 is not None and max_area is not None and area_km2 > max_area:
                self.log(f"DEM download: AOI area {area_km2:.1f} km^2 exceeds {label} limit {max_area:,.0f} km^2; skipping.")
                continue

            demtype = preset.get('demtype', dataset_key)
            base_url = preset.get('url', 'https://portal.opentopography.org/API/globaldem')

            params = {
                'demtype': demtype,
                'south':   f"{south:.8f}",
                'north':   f"{north:.8f}",
                'west':    f"{west:.8f}",
                'east':    f"{east:.8f}",
                'outputFormat': 'GTiff',
                'API_Key': key,
            }
            extra = preset.get('params')
            if isinstance(extra, dict):
                params.update(extra)

            url = base_url + '?' + urllib.parse.urlencode(params)
            headers = {"User-Agent": "HexMosaic/1.0"}
            req = urllib.request.Request(url, headers=headers)
            safe_key = self._safe_filename(dataset_key or demtype)
            out_src = os.path.join(out_dir, f"{aoi_name}_{safe_key}.tif")

            self.log(f"DEM download: requesting {label} ({demtype}).")
            try:
                with urllib.request.urlopen(req, timeout=120) as resp:
                    status = getattr(resp, 'status', 200)
                    data = resp.read()
            except urllib.error.HTTPError as err:
                body = err.read() if hasattr(err, 'read') else b''
                snippet = body[:200].decode('utf-8', errors='ignore').strip()
                self.log(f"DEM download failed for {label}: HTTP {err.code} {err.reason}. {snippet}")
                errors.append(f"{label} HTTP {err.code}")
                continue
            except urllib.error.URLError as err:
                self.log(f"DEM download failed for {label}: network error {err}.")
                errors.append(f"{label} network error")
                continue
            except Exception as err:
                self.log(f"DEM download failed for {label}: {err}.")
                errors.append(f"{label} {err}")
                continue

            if status >= 400 or status == 204 or not data:
                self.log(f"DEM download failed for {label}: HTTP {status} (empty response).")
                errors.append(f"{label} HTTP {status}")
                continue

            try:
                with open(out_src, 'wb') as fh:
                    fh.write(data)
            except Exception as err:
                self.log(f"DEM download: could not write file for {label} - {err}")
                errors.append(f"{label} write error")
                continue

            if not os.path.exists(out_src) or os.path.getsize(out_src) == 0:
                self.log(f"DEM download: file was empty for {label}.")
                errors.append(f"{label} empty file")
                continue

            proj_crs = iface.mapCanvas().mapSettings().destinationCrs()
            out_proj = os.path.join(out_dir, f"{aoi_name}_{safe_key}_proj.tif")
            try:
                from qgis import processing
                to_tr = QgsCoordinateTransform(aoi.crs(), proj_crs, QgsProject.instance().transformContext())
                a = aoi.extent()
                llp = to_tr.transform(a.xMinimum(), a.yMinimum())
                urp = to_tr.transform(a.xMaximum(), a.yMaximum())
                xmin, xmax = sorted([llp.x(), urp.x()])
                ymin, ymax = sorted([llp.y(), urp.y()])

                processing.run('gdal:warpreproject', {
                    'INPUT': out_src,
                    'SOURCE_CRS': QgsCoordinateReferenceSystem('EPSG:4326'),
                    'TARGET_CRS': proj_crs,
                    'RESAMPLING': 1,
                    'NODATA': None,
                    'TARGET_RESOLUTION': None,
                    'OPTIONS': '',
                    'DATA_TYPE': 0,
                    'TARGET_EXTENT': f"{xmin},{xmax},{ymin},{ymax}",
                    'TARGET_EXTENT_CRS': proj_crs.toWkt(),
                    'MULTITHREADING': True,
                    'EXTRA': '',
                    'OUTPUT': out_proj
                })
                use_path = out_proj if os.path.exists(out_proj) else out_src
            except Exception as e:
                self.log(f"Reproject (warp) failed; using source CRS raster. Details: {e}")
                use_path = out_src

            rl = QgsRasterLayer(use_path, os.path.basename(use_path))
            if not rl.isValid():
                self.log("Downloaded DEM but failed to load as raster.")
                errors.append(f"{label} load error")
                continue

            proj = QgsProject.instance()
            elev_grp = (proj.layerTreeRoot().findGroup('Elevation') or
                        proj.layerTreeRoot().addGroup('Elevation'))
            proj.addMapLayer(rl, False)
            elev_grp.addLayer(rl)

            self.elev_path_edit.setText(use_path)

            qml_used = self._apply_best_elevation_style(rl)
            if not qml_used:
                qml_path = self.elev_style_combo.currentData()
                if qml_path and os.path.isfile(qml_path):
                    ok, _ = rl.loadNamedStyle(qml_path); rl.triggerRepaint()
                    if ok:
                        self._select_style_in_combo(qml_path)
                        self.log(f"Applied fallback style: {os.path.basename(qml_path)}")

            try:
                iface.mapCanvas().setExtent(aoi.extent())
                iface.mapCanvas().refresh()
            except Exception:
                pass

            if hasattr(self, 'cbo_dem_source'):
                idx = self.cbo_dem_source.findData(dataset_key)
                if idx < 0:
                    idx = self.cbo_dem_source.findText(dataset_key, Qt.MatchFixedString)
                if idx >= 0:
                    self.cbo_dem_source.setCurrentIndex(idx)

            self.log(f"DEM added: {label} ({demtype}) -> {use_path}")
            if area_km2 is not None:
                limit_info = ''
                max_area = self._max_area_for_dataset(preset)
                if max_area is not None:
                    limit_info = f" (dataset limit {max_area:,.0f} km^2)"
                self.log(f"  AOI footprint: {area_km2:.1f} km^2{limit_info}")

            return

        if errors:
            self.log("DEM download failed. Tried datasets: " + '; '.join(errors))
        else:
            if area_km2 is not None:
                self.log(f"DEM download: AOI area {area_km2:.1f} km^2 exceeds limits for available datasets. Reduce the AOI or segment it.")
            else:
                self.log("DEM download: Unable to find a suitable dataset for the AOI extent.")

    def _populate_hex_elevation_inputs(self):
        dem_combo = getattr(self, "cbo_hex_dem_layer", None)
        hex_combo = getattr(self, "cbo_hex_tiles_layer", None)

        if not self._widget_is_alive(dem_combo) or not self._widget_is_alive(hex_combo):
            return

        try:
            rasters = self._gather_raster_layers()
            prev_dem_id = dem_combo.currentData() if dem_combo.count() else ""
            prev_dem_text = dem_combo.currentText() if dem_combo.count() else ""

            dem_combo.blockSignals(True)
            dem_combo.clear()
            for lyr in rasters:
                dem_combo.addItem(lyr.name(), lyr.id())

            matched_dem = False
            if prev_dem_id:
                idx = dem_combo.findData(prev_dem_id)
                if idx >= 0:
                    dem_combo.setCurrentIndex(idx)
                    matched_dem = True
            if not matched_dem and self._pending_hex_dem_layer_name:
                idx = dem_combo.findText(self._pending_hex_dem_layer_name, Qt.MatchFixedString)
                if idx >= 0:
                    dem_combo.setCurrentIndex(idx)
                    matched_dem = True
            if not matched_dem and prev_dem_text:
                idx = dem_combo.findText(prev_dem_text, Qt.MatchFixedString)
                if idx >= 0:
                    dem_combo.setCurrentIndex(idx)
                    matched_dem = True
            if matched_dem:
                self._pending_hex_dem_layer_name = ""
            dem_combo.blockSignals(False)

            hex_layers = self._gather_hex_layers()
            prev_hex_id = hex_combo.currentData() if hex_combo.count() else ""
            prev_hex_text = hex_combo.currentText() if hex_combo.count() else ""

            hex_combo.blockSignals(True)
            hex_combo.clear()
            for lyr in hex_layers:
                hex_combo.addItem(lyr.name(), lyr.id())

            matched_hex = False
            if prev_hex_id:
                idx = hex_combo.findData(prev_hex_id)
                if idx >= 0:
                    hex_combo.setCurrentIndex(idx)
                    matched_hex = True
            if not matched_hex and self._pending_hex_tile_layer_name:
                idx = hex_combo.findText(self._pending_hex_tile_layer_name, Qt.MatchFixedString)
                if idx >= 0:
                    hex_combo.setCurrentIndex(idx)
                    matched_hex = True
            if not matched_hex and prev_hex_text:
                idx = hex_combo.findText(prev_hex_text, Qt.MatchFixedString)
                if idx >= 0:
                    hex_combo.setCurrentIndex(idx)
                    matched_hex = True
            if matched_hex:
                self._pending_hex_tile_layer_name = ""
            hex_combo.blockSignals(False)

        except RuntimeError:
            return

        self._update_hex_elevation_button_state()

    def _selected_hex_dem_layer(self):
        combo = getattr(self, "cbo_hex_dem_layer", None)
        if not self._widget_is_alive(combo):
            return None
        lyr_id = combo.currentData() if combo.count() else None
        return QgsProject.instance().mapLayer(lyr_id) if lyr_id else None

    def _selected_hex_tiles_layer(self):
        combo = getattr(self, "cbo_hex_tiles_layer", None)
        if not self._widget_is_alive(combo):
            return None
        lyr_id = combo.currentData() if combo.count() else None
        return QgsProject.instance().mapLayer(lyr_id) if lyr_id else None

    def _update_hex_elevation_button_state(self):
        if not hasattr(self, "btn_generate_hex_elev"):
            return
        dem = self._selected_hex_dem_layer()
        tiles = self._selected_hex_tiles_layer()
        self.btn_generate_hex_elev.setEnabled(bool(dem and tiles))