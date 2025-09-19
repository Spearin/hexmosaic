"""AOI management helpers for HexMosaic."""
from __future__ import annotations

import os
import shutil

from qgis.utils import iface
from qgis.PyQt import QtCore, QtWidgets
from qgis.PyQt.QtCore import Qt, QVariant
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeature,
    QgsField,
    QgsFields,
    QgsFillSymbol,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
    QgsProviderRegistry,
    QgsRasterLayer,
    QgsRectangle,
    QgsSingleSymbolRenderer,
    QgsSnappingConfig,
    QgsTolerance,
    QgsUnitTypes,
    QgsVectorFileWriter,
    QgsVectorLayer,
    QgsWkbTypes,
)

try:
    from qgis.PyQt import sip  # type: ignore
except ImportError:
    sip = None  # type: ignore[assignment]

from .settings_dialog import HexMosaicSettingsDialog, get_persistent_setting


class AoiMixin:
    def _generate_project_structure(self):
        """
        Make <Project>/Layers and <Project>/Export.
        Ensure groups exist and order top->bottom:
        Mosaic, OSM, Base, Elevation, Reference.
        Also ensures Base -> Base Grid and adds OpenTopoMap once.
        """
        # --- folders ---
        try:
            os.makedirs(self._layers_dir(), exist_ok=True)
            os.makedirs(self._export_dir(), exist_ok=True)
            os.makedirs(os.path.join(self._layers_dir(), "Base", "Base_Grid"), exist_ok=True)
        except Exception as e:
            self.log(f"Could not create folders: {e}")

        root = QgsProject.instance().layerTreeRoot()
        desired = ["Mosaic", "OSM", "Base", "Elevation", "Reference"]

        # --- ensure groups ---
        for name in desired:
            if not root.findGroup(name):
                root.addGroup(name)

        # ensure Base sub-group
        base_grp = root.findGroup("Base")
        if base_grp and not any(g.name() == "Base Grid" for g in base_grp.findGroups()):
            base_grp.addGroup("Base Grid")

        # --- robust reorder via clone-insert-remove (no takeChild) ---
        def move_group_to_index(parent, name, new_index):
            node = parent.findGroup(name)
            if node is None:
                return
            children = list(parent.children())
            try:
                old_index = children.index(node)
            except ValueError:
                return
            if old_index == new_index:
                return

            # when moving down, insert after the target to survive later removal
            insert_index = new_index + 1 if old_index < new_index else new_index
            parent.insertChildNode(insert_index, node.clone())
            # remove the original by pointer (safe regardless of index shifts)
            parent.removeChildNode(node)

        for i, name in enumerate(desired):
            move_group_to_index(root, name, i)

        # --- add OpenTopoMap once (under Reference) ---
        try:
            if not QgsProject.instance().mapLayersByName("OpenTopoMap"):
                rl = self.add_opentopo_basemap()  # your helper targets "Reference"
                if rl:
                    # push to bottom of Reference group (optional)
                    ref = root.findGroup("Reference")
                    if ref is not None:
                        node = ref.findLayer(rl.id())
                        if node is not None:
                            # same clone-insert-remove trick to force bottom
                            ref.insertChildNode(len(ref.children()), node.clone())
                            ref.removeChildNode(node)
                try:
                    v = iface.layerTreeView()
                    if v:
                        v.refreshLayerSymbology()
                except Exception:
                    pass
            else:
                self.log("OpenTopoMap already present; skipping.")
        except Exception as e:
            self.log(f"Could not auto-add OpenTopoMap: {e}")

        self.log("Project structure ready: Folders (Layers, Export) + Groups ordered.")

    def _ensure_group(self, name):
        root = QgsProject.instance().layerTreeRoot()
        grp = root.findGroup(name)
        return grp or root.addGroup(name)

    def _add_xyz_layer(self, title: str, url_tmpl: str, zmin=0, zmax=17, group_name="Reference"):
        """
        Add an XYZ/TMS basemap without external plugins.
        url_tmpl should use {s} for subdomain, e.g. 'https://a.tile.opentopomap.org/{z}/{x}/{y}.png'
        """
        try:
            # Make sure group exists
            grp = self._ensure_group(group_name)

            # QGIS wants {s} + 'subdomains=a,b,c' instead of {a}
            url_tmpl = url_tmpl.replace("{a}", "{s}")

            # Use provider metadata to encode the URI correctly
            prov_md = QgsProviderRegistry.instance().providerMetadata("wms") # type: ignore
            encoded = prov_md.encodeUri({
                "type": "xyz",
                "url": url_tmpl,
                "zmin": int(zmin),
                "zmax": int(zmax),
                "subdomains": "a,b,c",  # needed for {s}
                # Optional niceties:
                # "http-header:User-Agent": "QGIS-HexMosaic"
            })

            rl = QgsRasterLayer(encoded, title, "wms")
            if not rl.isValid():
                self.log(f"Failed to add XYZ layer: {title}")
                return None

            # Add to project without auto-grouping, then attach to our target group
            QgsProject.instance().addMapLayer(rl, False)
            grp.addLayer(rl)

            # Move it to the **bottom** of the group (correct index-based API)
            node = grp.findLayer(rl.id())
            if node is not None:
                children = grp.children()
                try:
                    old_idx = children.index(node)
                    taken = grp.takeChild(old_idx)
                    if taken is not None:
                        grp.insertChildNode(len(grp.children()), taken)
                except ValueError:
                    pass

            self.log(f"Added basemap: {title} -> {group_name}")
            return rl
        except Exception as e:
            self.log(f"Error adding basemap '{title}': {e}")
            return None

    def add_opentopo_basemap(self):
        # OpenTopoMap (XYZ), under 'Reference'
        url = "https://a.tile.opentopomap.org/{z}/{x}/{y}.png"
        return self._add_xyz_layer("OpenTopoMap", url, zmin=0, zmax=17, group_name="Reference")

    def _ensure_anchor_layer(self):
        """
        Ensure a single-point memory layer in EPSG:4326 called 'Project Anchor' under 'Reference'.
        Returns the layer.
        """
        proj = QgsProject.instance()
        # Search existing first
        for lyr in proj.mapLayers().values():
            if lyr.name() == "Project Anchor" and getattr(lyr, "geometryType", lambda: -1)() == 0:
                return lyr

        # Create new memory point layer in WGS84
        from qgis.core import QgsVectorLayer, QgsFields, QgsField, QgsWkbTypes, QgsCoordinateReferenceSystem # type: ignore
        vl = QgsVectorLayer("Point?crs=EPSG:4326", "Project Anchor", "memory")
        pr = vl.dataProvider()
        pr.addAttributes([QgsField("name", QVariant.String)])
        vl.updateFields()

        QgsProject.instance().addMapLayer(vl, False)
        ref_grp = self._ensure_group("Base")
        ref_grp.addLayer(vl)
        return vl

    def set_anchor_at_canvas_center(self):
        """
        Create/move the Project Anchor to the current canvas center (reprojected to EPSG:4326).
        """
        anchor = self._ensure_anchor_layer()

        canvas = iface.mapCanvas()
        center_map = canvas.center()                    # in project CRS
        proj_crs = canvas.mapSettings().destinationCrs()
        wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        tr = QgsCoordinateTransform(proj_crs, wgs84, QgsProject.instance().transformContext())
        ll = tr.transform(center_map)                   # lon/lat

        # Update/create the single feature
        pr = anchor.dataProvider()
        anchor.startEditing()
        pr.truncate()  # keep single point
        f = QgsFeature(anchor.fields())
        f.setAttributes(["anchor"])
        f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(ll.x(), ll.y())))
        pr.addFeature(f)
        anchor.commitChanges()
        anchor.triggerRepaint()

        self.log(f"Project Anchor set at lon/lat: {ll.x():.6f}, {ll.y():.6f} (EPSG:4326)")

    def _utm_epsg_for_lonlat(self, lon: float, lat: float) -> int:
        """
        Compute the UTM EPSG code for longitude/latitude in degrees.
        EPSG 326## for northern hemisphere, 327## for southern.
        """
        zone = int((lon + 180.0) / 6.0) + 1
        zone = max(1, min(60, zone))
        if lat >= 0:
            return 32600 + zone
        else:
            return 32700 + zone

    def set_project_crs_from_anchor(self):
        """
        Read the Project Anchor (WGS84), compute UTM zone, set project CRS.
        """
        anchor = None
        for lyr in QgsProject.instance().mapLayers().values():
            if lyr.name() == "Project Anchor" and getattr(lyr, "geometryType", lambda: -1)() == 0:
                anchor = lyr
                break

        if not anchor or anchor.featureCount() == 0:
            self.log("No Project Anchor found. Use 'Set Anchor at Canvas Center' first.")
            return

        feat = next(anchor.getFeatures(), None)
        if not feat or not feat.hasGeometry():
            self.log("Anchor has no geometry.")
            return

        # Ensure geometry in lon/lat
        wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        if anchor.crs() != wgs84:
            # reproject feature's coordinate to WGS84
            tr = QgsCoordinateTransform(anchor.crs(), wgs84, QgsProject.instance().transformContext())
            pt = tr.transform(feat.geometry().asPoint())
            lon, lat = pt.x(), pt.y()
        else:
            pt = feat.geometry().asPoint()
            lon, lat = pt.x(), pt.y()

        epsg = self._utm_epsg_for_lonlat(lon, lat)
        new_crs = QgsCoordinateReferenceSystem.fromEpsgId(epsg)
        if not new_crs.isValid():
            self.log(f"Computed CRS EPSG:{epsg} is not valid?")
            return

        QgsProject.instance().setCrs(new_crs)
        self.log(f"Project CRS set to UTM zone {epsg % 100} ({'N' if lat>=0 else 'S'}), EPSG:{epsg}")

        # Optional: zoom to something sensible
        iface.mapCanvas().refresh()

    def _create_spatial_index(self, vector_path):
        """Build a .qix spatial index for a saved shapefile. Silently ignore failures."""
        try:
            from qgis import processing # type: ignore
            if vector_path.lower().endswith(".shp") and os.path.exists(vector_path):
                processing.run("native:createspatialindex", {"INPUT": vector_path})
                return True
        except Exception:
            pass
        return False

    def _gather_aoi_layers(self):
        proj = QgsProject.instance()
        candidates = []
        for lyr in proj.mapLayers().values():
            if hasattr(lyr, "geometryType") and lyr.geometryType() == 2 and lyr.name().upper().startswith("AOI"):
                candidates.append(lyr)
        return sorted(candidates, key=lambda L: L.name().lower())

    def _gather_poi_layers(self):
        proj = QgsProject.instance()
        candidates = []
        for lyr in proj.mapLayers().values():
            if not hasattr(lyr, "geometryType"):
                continue
            try:
                geom_type = lyr.geometryType()
            except Exception:
                continue
            if geom_type == QgsWkbTypes.PointGeometry or geom_type == 0:
                candidates.append(lyr)
        return sorted(candidates, key=lambda L: L.name().lower())

    def _gather_raster_layers(self):
        proj = QgsProject.instance()
        layers = []
        for lyr in proj.mapLayers().values():
            if isinstance(lyr, QgsRasterLayer):
                layers.append(lyr)
        return sorted(layers, key=lambda L: L.name().lower())

    def _gather_hex_layers(self):
        proj = QgsProject.instance()
        layers = []
        for lyr in proj.mapLayers().values():
            if isinstance(lyr, QgsVectorLayer):
                try:
                    if QgsWkbTypes.geometryType(lyr.wkbType()) == QgsWkbTypes.PolygonGeometry:
                        layers.append(lyr)
                except Exception:
                    continue
        return sorted(layers, key=lambda L: L.name().lower())

    def _widget_is_alive(self, widget):
        """Return False if the Qt widget reference is gone or deleted."""
        if widget is None:
            return False

        try:
            from qgis.PyQt import sip  # type: ignore
        except ImportError:
            sip = None  # pragma: no cover - sip missing in some tests

        if sip is not None:
            try:
                if sip.isdeleted(widget):
                    return False
            except Exception:
                return False

        try:
            widget.objectName()
        except RuntimeError:
            return False

        return True
    def _populate_aoi_combo(self):
        """Refresh AOI-aware combos, including segmentation controls."""
        layers = self._gather_aoi_layers()
        if hasattr(self, "cboAOI"):
            prev = self.cboAOI.currentData() if self.cboAOI.count() else None
            self.cboAOI.blockSignals(True)
            self.cboAOI.clear()
            for lyr in layers:
                self.cboAOI.addItem(lyr.name(), lyr.id())
            if prev is not None:
                idx = self.cboAOI.findData(prev)
                if idx >= 0:
                    self.cboAOI.setCurrentIndex(idx)
            self.cboAOI.blockSignals(False)

        if hasattr(self, "cboAOI_segment"):
            parent_layers = [lyr for lyr in layers if "segment" not in lyr.name().lower()]
            prev_seg = self.cboAOI_segment.currentData() if self.cboAOI_segment.count() else None
            self.cboAOI_segment.blockSignals(True)
            self.cboAOI_segment.clear()
            for lyr in parent_layers:
                self.cboAOI_segment.addItem(lyr.name(), lyr.id())
            if prev_seg is not None:
                idx = self.cboAOI_segment.findData(prev_seg)
                if idx >= 0:
                    self.cboAOI_segment.setCurrentIndex(idx)
            self.cboAOI_segment.blockSignals(False)

        self._sync_aoi_combo_to_elev()
        self._sync_export_aoi_combo()
        if hasattr(self, "_sync_aoi_combo_to_osm"):
            self._sync_aoi_combo_to_osm(layers)
        self._update_segment_buttons_state()

    def _populate_poi_combo(self):
        if not hasattr(self, "cbo_poi_layer"):
            return

        layers = self._gather_poi_layers()
        prev_id = self.cbo_poi_layer.currentData() if self.cbo_poi_layer.count() else None
        prev_name = self.cbo_poi_layer.currentText() if self.cbo_poi_layer.count() else ""

        self.cbo_poi_layer.blockSignals(True)
        self.cbo_poi_layer.clear()
        for lyr in layers:
            self.cbo_poi_layer.addItem(lyr.name(), lyr.id())

        target_name = (self._pending_poi_layer_name or prev_name).strip()
        applied = False
        if target_name:
            idx = self.cbo_poi_layer.findText(target_name, Qt.MatchExactly)
            if idx >= 0:
                self.cbo_poi_layer.setCurrentIndex(idx)
                applied = True
        if not applied and prev_id is not None:
            idx = self.cbo_poi_layer.findData(prev_id)
            if idx >= 0:
                self.cbo_poi_layer.setCurrentIndex(idx)

        self.cbo_poi_layer.blockSignals(False)
        self._pending_poi_layer_name = ""
        self._update_poi_controls()

    def _selected_poi_layer(self):
        if not hasattr(self, "cbo_poi_layer"):
            return None
        lyr_id = self.cbo_poi_layer.currentData()
        return QgsProject.instance().mapLayer(lyr_id) if lyr_id else None

    def _update_poi_controls(self):
        if not hasattr(self, "btn_create_poi_aois"):
            return
        layer = self._selected_poi_layer()
        self.btn_create_poi_aois.setEnabled(layer is not None)
        if layer is not None:
            self._pending_poi_layer_name = layer.name()

    def _selected_aoi_layer(self):
        """Return the AOI layer object chosen in the combo, or None."""
        lyr_id = self.cboAOI.currentData()
        if not lyr_id:
            return None
        return QgsProject.instance().mapLayer(lyr_id)

    def _sync_aoi_combo_to_elev(self):
        self.cboAOI_elev.blockSignals(True)
        self.cboAOI_elev.clear()
        for i in range(self.cboAOI.count()):
            self.cboAOI_elev.addItem(self.cboAOI.itemText(i), self.cboAOI.itemData(i))
        self.cboAOI_elev.blockSignals(False)

    def _selected_aoi_layer_for_elev(self):
        lyr_id = self.cboAOI_elev.currentData()
        return QgsProject.instance().mapLayer(lyr_id) if lyr_id else None

    def _ensure_nested_groups(self, path_list):
        """Create/return a nested group path under the root. Example: ['Base','Base Grid','AOI 1 ...']"""
        root = QgsProject.instance().layerTreeRoot()
        grp = root
        for name in path_list:
            found = None
            for child in grp.findGroups():
                if child.name() == name:
                    found = child
                    break
            if not found:
                found = grp.addGroup(name)
            grp = found
        return grp

    def _next_aoi_index(self):
        """Find the next AOI index by scanning layer names like 'AOI <#> ...'."""
        import re
        idx = 0
        pat = re.compile(r"^AOI\s+(\d+)\b")
        for lyr in QgsProject.instance().mapLayers().values():
            m = pat.match(lyr.name())
            if m:
                try:
                    idx = max(idx, int(m.group(1)))
                except:
                    pass
        return idx + 1

    def _recalc_aoi_info(self):
        """
        Update labels, snap to hex multiples, compute counts, color warnings,
        and enable/disable the Create AOI button.
        """
        # hex size (m)
        try:
            hex_m = max(1.0, float(self.hex_scale_edit.text()))
        except Exception:
            hex_m = 500.0
            self.hex_scale_edit.setText("500")

        # read width/height numbers from the two edits
        def _read_f(le):
            try:
                return float(le.text())
            except Exception:
                return 0.0

        v1 = _read_f(self.width_input)
        v2 = _read_f(self.height_input)

        # convert / snap depending on units
        if self.unit_m.isChecked():
            # snap meters to nearest multiple of hex size
            if v1 > 0:
                v1s = max(hex_m, round(v1 / hex_m) * hex_m)
                if abs(v1s - v1) > 1e-9:
                    self.width_input.blockSignals(True)
                    self.width_input.setText(str(int(v1s)))
                    self.width_input.blockSignals(False)
                v1 = v1s
            if v2 > 0:
                v2s = max(hex_m, round(v2 / hex_m) * hex_m)
                if abs(v2s - v2) > 1e-9:
                    self.height_input.blockSignals(True)
                    self.height_input.setText(str(int(v2s)))
                    self.height_input.blockSignals(False)
                v2 = v2s
            w_m, h_m = v1, v2
            w_h = int(round(w_m / hex_m))
            h_h = int(round(h_m / hex_m))
        else:
            # values are hex counts; round and back-compute meters
            w_h = max(1, int(round(v1)))
            h_h = max(1, int(round(v2)))
            if str(w_h) != self.width_input.text():
                self.width_input.blockSignals(True)
                self.width_input.setText(str(w_h))
                self.width_input.blockSignals(False)
            if str(h_h) != self.height_input.text():
                self.height_input.blockSignals(True)
                self.height_input.setText(str(h_h))
                self.height_input.blockSignals(False)
            w_m = w_h * hex_m
            h_m = h_h * hex_m

        # update labels
        self.lblWHm.setText(f"Width x Height (m): {int(w_m)} x {int(h_m)}")
        self.lblWHh.setText(f"Width x Height (hexes): {w_h} x {h_h}")
        self.lblCount.setText(f"Total hexes: {w_h * h_h}")

        allow_experimental = getattr(self, "chk_experimental_aoi", None)
        allow_experimental = bool(allow_experimental and allow_experimental.isChecked())

        # validity: if either dimension > 99 hexes and experimental mode is off, disable Create
        too_wide = w_h > 99
        too_tall = h_h > 99
        oversize = too_wide or too_tall
        non_positive = (w_m <= 0 or h_m <= 0)
        invalid = non_positive or (oversize and not allow_experimental)

        warn_dimensions = oversize or non_positive
        self._set_warn(self.lblWHh, warn_dimensions)
        self._set_warn(self.lblWHm, warn_dimensions)
        self._set_warn(self.lblCount, warn_dimensions)
        self._set_warn(self.width_input, oversize)
        self._set_warn(self.height_input, oversize)

        if oversize:
            if allow_experimental:
                msg = (
                    "Experimental AOI sizes can be slow to edit, segment, or export. "
                    "Monitor QGIS performance before committing to production maps."
                )
            else:
                msg = (
                    "AOIs larger than 99 hexes are blocked. Enable experimental AOI "
                    "sizes to proceed."
                )
            self.lbl_experimental_warning.setText(msg)
            self.lbl_experimental_warning.setVisible(True)
        else:
            self.lbl_experimental_warning.clear()
            self.lbl_experimental_warning.setVisible(False)

        # disable/enable Create AOI
        self.btn_aoi.setEnabled(not invalid)

    def _set_warn(self, widget, warn: bool):
        """Apply red text when warn is True; else reset."""
        if warn:
            widget.setStyleSheet("color: rgb(200,0,0);")
        else:
            widget.setStyleSheet("")

    def _current_aoi_dimensions(self):
        try:
            hex_m = max(1.0, float(self.hex_scale_edit.text()))
        except Exception:
            hex_m = 500.0
            self.hex_scale_edit.setText("500")

        use_meters = self.unit_m.isChecked()
        try:
            width_val = float(self.width_input.text())
            height_val = float(self.height_input.text())
        except Exception:
            self.log("Invalid size.")
            return None

        if use_meters:
            w_m, h_m = width_val, height_val
        else:
            w_m = int(round(width_val)) * hex_m
            h_m = int(round(height_val)) * hex_m

        if w_m <= 0 or h_m <= 0:
            self.log("Width/Height must be > 0.")
            return None

        w_h = int(round(w_m / hex_m)) if hex_m else 0
        h_h = int(round(h_m / hex_m)) if hex_m else 0
        oversize = w_h > 99 or h_h > 99
        allow_experimental = bool(self.chk_experimental_aoi.isChecked())
        if oversize and not allow_experimental:
            self.log("AOIs larger than 99 hexes are blocked. Enable experimental AOI sizes to proceed.")
            return None

        return {
            "hex_m": hex_m,
            "width_m": w_m,
            "height_m": h_m,
            "width_hex": w_h,
            "height_hex": h_h,
            "oversize": oversize,
        }

    def _create_aoi_from_center(self, center_point, dims, index, label_suffix=None, file_hint=None):
        if not dims:
            return None

        w_m = dims["width_m"]
        h_m = dims["height_m"]

        canvas = iface.mapCanvas()
        crs = canvas.mapSettings().destinationCrs()

        xmin, xmax = center_point.x() - w_m / 2.0, center_point.x() + w_m / 2.0
        ymin, ymax = center_point.y() - h_m / 2.0, center_point.y() + h_m / 2.0

        w_m_i, h_m_i = int(round(w_m)), int(round(h_m))
        display_name = f"AOI {index} {w_m_i}m x {h_m_i}m"
        if label_suffix:
            display_name += f" - {label_suffix}"

        out_dir = get_persistent_setting("paths/out_dir", "")
        if not out_dir or not os.path.isdir(out_dir):
            self.log("No output directory set (Settings).")
            return None

        file_suffix = f"_{file_hint}" if file_hint else ""
        shp_name = self._safe_filename(f"AOI_{index}_{w_m_i}m_x_{h_m_i}m{file_suffix}.shp")
        shp_path = os.path.join(self._layers_dir(), shp_name)
        os.makedirs(os.path.dirname(shp_path), exist_ok=True)

        self._clean_vector_sidecars(shp_path)

        fields = QgsFields()
        fields.append(QgsField("id", QVariant.Int))

        writer = QgsVectorFileWriter(
            shp_path, "UTF-8", fields, QgsWkbTypes.Polygon, crs, "ESRI Shapefile"
        )

        if writer.hasError() != QgsVectorFileWriter.NoError:
            self.log(f"Failed to create shapefile: {shp_path}")
            del writer
            return None

        feat = QgsFeature(fields)
        feat.setAttribute("id", 1)
        feat.setGeometry(QgsGeometry.fromPolygonXY([[
            QgsPointXY(xmin, ymin),
            QgsPointXY(xmin, ymax),
            QgsPointXY(xmax, ymax),
            QgsPointXY(xmax, ymin)
        ]]))
        writer.addFeature(feat)
        del writer

        aoi_layer = QgsVectorLayer(shp_path, display_name, "ogr")
        if not aoi_layer.isValid():
            self.log("Saved AOI shapefile, but failed to load it.")
            return None

        qml_ok = self._apply_style(aoi_layer, "aoi.qml")
        if not qml_ok:
            sym = QgsFillSymbol.createSimple({
                'color': '255,255,255,0',
                'outline_color': '255,105,180',
                'outline_width': '0.6'
            })
            aoi_layer.setRenderer(QgsSingleSymbolRenderer(sym))

        proj = QgsProject.instance()
        root = proj.layerTreeRoot()
        base_grp = root.findGroup('Base') or root.addGroup('Base')

        to_remove = [lyr.id() for lyr in proj.mapLayers().values()
                    if lyr.providerType() == "memory" and lyr.name().startswith("AOI")]
        if to_remove:
            proj.removeMapLayers(to_remove)

        proj.addMapLayer(aoi_layer, False)
        base_grp.addLayer(aoi_layer)

        canvas.setExtent(aoi_layer.extent())
        canvas.refresh()

        style_msg = "Style: QML applied." if qml_ok else "Style: QML missing (used fallback)."
        self.log(f"{display_name} added to 'Base'. Saved to Shapefile. {style_msg}")
        return aoi_layer

    def _fill_from_canvas_extent(self):
        """Read the current map canvas extent and populate width/height inputs."""
        canvas = iface.mapCanvas()
        crs = canvas.mapSettings().destinationCrs()
        from qgis.core import QgsUnitTypes # type: ignore
        if crs.mapUnits() != QgsUnitTypes.DistanceMeters:
            self.log("Note: Canvas CRS is not meters; AOI sizes will not match game meters.")

        ext = canvas.extent()
        # width/height in layer units; we assume projected CRS in meters (warn elsewhere if not)
        w_m = max(0.0, ext.width())
        h_m = max(0.0, ext.height())        

        # hex size (m)
        try:
            hex_m = max(1.0, float(self.hex_scale_edit.text()))
        except Exception:
            hex_m = 500.0
            self.hex_scale_edit.setText("500")

        if self.unit_m.isChecked():
            # snap meters to hex multiple
            w_s = max(hex_m, round(w_m / hex_m) * hex_m)
            h_s = max(hex_m, round(h_m / hex_m) * hex_m)
            self.width_input.setText(str(int(w_s)))
            self.height_input.setText(str(int(h_s)))
        else:
            # fill as hex counts (rounded)
            w_h = max(1, int(round(w_m / hex_m)))
            h_h = max(1, int(round(h_m / hex_m)))
            self.width_input.setText(str(w_h))
            self.height_input.setText(str(h_h))

        # recompute labels / validity and update button state
        self._recalc_aoi_info()

    def _fill_from_anchor_point(self):
        """Use the WGS84 Project Anchor point (reprojected to project CRS) to center the AOI."""
        # find the anchor layer
        anchor = None
        for lyr in QgsProject.instance().mapLayers().values():
            if lyr.name() == "Project Anchor" and getattr(lyr, "geometryType", lambda: -1)() == 0:
                anchor = lyr
                break
        if not anchor or anchor.featureCount() == 0:
            self.log("No Project Anchor found. Use 'Set Anchor at Canvas Center' first.")
            return

        feat = next(anchor.getFeatures(), None)
        if not feat or not feat.hasGeometry():
            self.log("Anchor has no geometry.")
            return

        # transform anchor from its CRS (should be EPSG:4326) to the project CRS
        proj = QgsProject.instance()
        proj_crs = iface.mapCanvas().mapSettings().destinationCrs()
        tr = QgsCoordinateTransform(anchor.crs(), proj_crs, proj.transformContext())
        pt = tr.transform(feat.geometry().asPoint())  # project CRS point

        # center the canvas there (so user can see); AOI creation uses canvas center
        c = iface.mapCanvas()
        ext = c.extent()
        # keep same width/height; just recenter
        w = ext.width(); h = ext.height()
        new_ext = QgsRectangle(pt.x() - w/2, pt.y() - h/2, pt.x() + w/2, pt.y() + h/2)
        c.setExtent(new_ext)
        c.refresh()

        self.log("Canvas centered on Project Anchor. Now set sizes and click Create AOI.")

    def _open_settings(self):
        dlg = HexMosaicSettingsDialog(self)
        dlg.exec_()

    def create_aoi(self):
        """Create AOI at the map canvas center using the configured dimensions."""
        dims = self._current_aoi_dimensions()
        if not dims:
            return

        if dims.get("oversize") and self.chk_experimental_aoi.isChecked():
            self.log(
                "Experimental AOI size in use (>{} hexes). Large shapefiles may slow "
                "down QGIS and exports.".format(99)
            )

        canvas = iface.mapCanvas()
        center = canvas.center()
        aoi_idx = self._next_aoi_index()
        created = self._create_aoi_from_center(center, dims, aoi_idx)
        if created:
            self._populate_aoi_combo()

    def create_aois_from_poi(self):
        dims = self._current_aoi_dimensions()
        if not dims:
            return

        if dims.get("oversize") and self.chk_experimental_aoi.isChecked():
            self.log(
                "Experimental AOI size in use (>{} hexes). Large shapefiles may slow "
                "down QGIS and exports.".format(99)
            )

        poi_layer = self._selected_poi_layer()
        if not poi_layer:
            self.log("Select a Points of Interest layer to generate AOIs.")
            return

        features = list(poi_layer.selectedFeatures())
        if not features:
            features = list(poi_layer.getFeatures())
        if not features:
            self.log("The selected POI layer has no features to build AOIs from.")
            return

        proj = QgsProject.instance()
        project_crs = proj.crs()
        poi_crs = poi_layer.crs()
        transform = None
        if poi_crs and project_crs and poi_crs != project_crs:
            transform = QgsCoordinateTransform(poi_crs, project_crs, proj.transformContext())

        candidate_fields = [f for f in ("name", "Name", "NAME", "label", "Label", "LABEL", "title", "Title", "TITLE")
                             if poi_layer.fields().indexOf(f) >= 0]

        def _label_for_feature(feat):
            for field in candidate_fields:
                value = feat.attribute(field)
                if value is not None:
                    text = str(value).strip()
                    if text:
                        return text
            return ""

        created_count = 0
        next_idx = self._next_aoi_index()
        for feat in features:
            geom = feat.geometry()
            if geom is None or geom.isEmpty():
                continue

            if geom.isMultipart():
                pts = geom.asMultiPoint()
                pt = pts[0] if pts else None
            else:
                try:
                    pt = geom.asPoint()
                except Exception:
                    pts = geom.asMultiPoint()
                    pt = pts[0] if pts else None

            if not pt:
                continue

            if transform:
                try:
                    pt = transform.transform(pt)
                except Exception:
                    continue

            label_value = _label_for_feature(feat)
            label_suffix = label_value or f"POI {feat.id()}"
            file_hint = self._safe_filename(label_value.replace(" ", "_")) if label_value else f"POI_{feat.id()}"
            if not file_hint:
                file_hint = f"POI_{feat.id()}"
            file_hint = file_hint[:48]

            created = self._create_aoi_from_center(QgsPointXY(pt.x(), pt.y()), dims, next_idx, label_suffix=label_suffix, file_hint=file_hint)
            if created:
                created_count += 1
                next_idx += 1

        if created_count:
            self._populate_aoi_combo()
            self.log(f"Created {created_count} AOIs from {poi_layer.name()}.")
        else:
            self.log("No AOIs were generated from the selected POI layer.")

    def _ensure_snapping(self, tol_px=20):
        """Project-level snapping: all layers, vertex+segment, pixel tolerance."""
        su = iface.mapCanvas().snappingUtils()
        cfg = su.config()  # QgsSnappingConfig
        cfg.setEnabled(True)
        cfg.setMode(QgsSnappingConfig.AllLayers)
        cfg.setType(QgsSnappingConfig.VertexAndSegment)
        cfg.setTolerance(float(tol_px))
        cfg.setUnits(QgsTolerance.Pixels)
        cfg.setIntersectionSnapping(True)
        su.setConfig(cfg)

    def _aoi_layer(self):
        # Pick the first layer literally named "AOI"
        for lyr in QgsProject.instance().mapLayers().values():
            if lyr.name() == "AOI" and lyr.geometryType() == 2:  # 2 = polygon
                return lyr
        return None

    def _ensure_group(self, name):
        root = QgsProject.instance().layerTreeRoot()
        grp = root.findGroup(name)
        return grp or root.addGroup(name)

    def build_hex_grid(self):
        """Build hex grid from selected AOI; save as individual Shapefiles; load permanently with styling."""
        from qgis import processing # type: ignore

        # guards to prevent UnboundLocalError on early returns
        saved_tiles = saved_edges = saved_verts = saved_cents = False
        ix_tiles = ix_edges = ix_verts = ix_cents = False

        # --- inputs ---
        try:
            hex_m = max(1.0, float(self.hex_scale_edit.text()))
        except Exception:
            hex_m = 500.0
            self.hex_scale_edit.setText("500")

        aoi = self._selected_aoi_layer()
        if not aoi:
            self.log("Select an AOI from the dropdown (or click Refresh).")
            return

        out_root = get_persistent_setting("paths/out_dir", "")
        if not out_root or not os.path.isdir(out_root):
            self.log("No output directory set (Settings).")
            return

        self._ensure_snapping(20)
        crs = aoi.crs()
        extent = aoi.extent()
        ext_str = f"{extent.xMinimum()},{extent.xMaximum()},{extent.yMinimum()},{extent.yMaximum()} [{crs.authid()}]"

        # --- make on-disk folder structure: Base/Base_Grid/<AOI_safe> ---
        aoi_safe = self._safe_filename(aoi.name().replace(" ", "_"))
        base_dir = os.path.join(self._layers_dir(), "Base", "Base_Grid", aoi_safe)
        os.makedirs(base_dir, exist_ok=True)

        # --- 1) raw grid (TYPE=4 is hex in your build) ---
        params_grid = {
            'TYPE': 4,               # 4 = Hexagon in your QGIS
            'EXTENT': extent,        # try object first
            'HSPACING': hex_m,
            'VSPACING': hex_m,
            'HOVERLAY': 0,
            'VOVERLAY': 0,
            'CRS': crs,
            'OUTPUT': 'memory:hex_raw'
        }
        try:
            res_grid = processing.run('native:creategrid', params_grid)
        except Exception:
            params_grid.update({'EXTENT': ext_str, 'CRS': crs.authid()})
            res_grid = processing.run('native:creategrid', params_grid)
        grid_raw = res_grid['OUTPUT']

        # --- 2) clip to AOI ---
        grid = processing.run('native:clip', {
            'INPUT': grid_raw, 'OVERLAY': aoi, 'OUTPUT': 'memory:hex_tiles'
        })['OUTPUT']

        # --- 3) helpers ---
        edges = processing.run('native:polygonstolines', {
            'INPUT': grid, 'OUTPUT': 'memory:hex_edges'
        })['OUTPUT']
        vertices = processing.run('native:extractvertices', {
            'INPUT': grid, 'OUTPUT': 'memory:hex_vertices'
        })['OUTPUT']
        centroids = processing.run('native:centroids', {
            'INPUT': grid, 'ALL_PARTS': False, 'OUTPUT': 'memory:hex_centroids'
        })['OUTPUT']

        # --- 4) write each as Shapefile (clean sidecars first), then always try to load ---
        def _clean_sidecars(path_with_ext):
            base, _ = os.path.splitext(path_with_ext)
            for ext in (".shp", ".shx", ".dbf", ".prj", ".cpg", ".qix", ".qmd"):
                p = base + ext
                if os.path.exists(p):
                    try:
                        os.remove(p)
                    except Exception:
                        pass

        def _save_shp(layer, shp_path):
            """
            Robust Shapefile save:
            - remove existing sidecars
            - write with classic writer
            - return True if the .shp exists afterward
            """
            _clean_sidecars(shp_path)
            err = QgsVectorFileWriter.writeAsVectorFormat(
                layer,
                shp_path,
                "UTF-8",
                layer.crs(),
                "ESRI Shapefile",
                onlySelected=False,
                layerOptions=["ENCODING=UTF-8"]  # note: shapefile spatial index is built separately
            )
            return os.path.exists(shp_path)

        shp_tiles = os.path.join(base_dir, f"hex_tiles_{int(hex_m)}m.shp")
        shp_edges = os.path.join(base_dir, "hex_edges.shp")
        shp_verts = os.path.join(base_dir, "hex_vertices.shp")
        shp_cents = os.path.join(base_dir, "hex_centroids.shp")

        saved_tiles = _save_shp(grid, shp_tiles)
        saved_edges = _save_shp(edges, shp_edges)
        saved_verts = _save_shp(vertices, shp_verts)
        saved_cents = _save_shp(centroids, shp_cents)    

        # --- 4b) build spatial indexes (.qix) for faster rendering/snapping ---
        ix_tiles = self._create_spatial_index(shp_tiles) if saved_tiles else False
        ix_edges = self._create_spatial_index(shp_edges) if saved_edges else False
        ix_verts = self._create_spatial_index(shp_verts) if saved_verts else False
        ix_cents = self._create_spatial_index(shp_cents) if saved_cents else False            

        # --- 5) load disk layers regardless of return codes; style them; add to project ---
        def _load(path, title):
            lyr = QgsVectorLayer(path, title, "ogr")
            return lyr if lyr.isValid() else None

        L_grid = _load(shp_tiles, f'Hex Tiles ({int(hex_m)} m)')
        L_edge = _load(shp_edges, "Hex Grid Edges")
        L_vert = _load(shp_verts, "Intersection Helpers")
        L_cent = _load(shp_cents, "Centroid Helpers")

        # If any failed to load, tell the user which ones, but continue with those that did
        missing = []
        if not L_grid: missing.append("tiles")
        if not L_edge: missing.append("edges")
        if not L_vert: missing.append("vertices")
        if not L_cent: missing.append("centroids")

        if all([L_grid, L_edge, L_vert, L_cent]):
            status_suffix = "All shapefiles saved & loaded."
        else:
            status_suffix = "Loaded with issues: missing " + ", ".join(missing)

        # Style via QML first; fallback to programmatic styles
        if L_grid:
            if not self._apply_style(L_grid, "hex_tiles.qml"):
                self._style_grid_layer(L_grid, 'tiles')
        if L_edge:
            if not self._apply_style(L_edge, "hex_edges.qml"):
                self._style_grid_layer(L_edge, 'edges')
        if L_vert:
            if not self._apply_style(L_vert, "hex_vertices.qml"):
                self._style_grid_layer(L_vert, 'vertices')
        if L_cent:
            if not self._apply_style(L_cent, "hex_centroids.qml"):
                self._style_grid_layer(L_cent, 'centroids')

        proj = QgsProject.instance()
        grp = self._ensure_nested_groups(['Base', 'Base Grid', aoi.name()])

        # remove any existing memory layers under this AOI group
        for child in list(grp.children()):
            if hasattr(child, "layer") and child.layer() and child.layer().providerType() == "memory":
                proj.removeMapLayer(child.layerId())

        for lyr in [L_grid, L_edge, L_vert, L_cent]:
            if lyr:
                proj.addMapLayer(lyr, False)
                grp.addLayer(lyr)

        if L_grid:
            iface.mapCanvas().setExtent(L_grid.extent())
        elif aoi:
            iface.mapCanvas().setExtent(aoi.extent())
        iface.mapCanvas().refresh()

        ix_ok = all([ix_tiles, ix_edges, ix_verts, ix_cents])
        self.log(
            f"Hex grid + helpers saved to {os.path.relpath(base_dir, out_root)} and loaded permanently. "
            + ("Spatial indexes built." if ix_ok else "Spatial indexes built where possible.")
        )
