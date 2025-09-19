"""Export helpers for HexMosaic."""
from __future__ import annotations

import os
import subprocess
import sys
from typing import List, Tuple

from qgis.PyQt import QtCore, QtWidgets
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QImage, QPainter
from qgis.core import (
    QgsMapLayer,
    QgsMapLayerStyle,
    QgsMapRendererCustomPainterJob,
    QgsMapSettings,
    QgsProject,
    QgsRectangle,
    QgsVectorFileWriter,
)

from .settings_dialog import get_persistent_setting


class ExportMixin:
    def _sync_export_aoi_combo(self):
        # mirror items from self.cboAOI
        self.cboAOI_export.blockSignals(True)
        self.cboAOI_export.clear()
        for i in range(self.cboAOI.count()):
            self.cboAOI_export.addItem(self.cboAOI.itemText(i), self.cboAOI.itemData(i))
        self.cboAOI_export.blockSignals(False)

    def _save_layers_to_gpkg(self, layers_with_names, gpkg_path):
        """
        Save each (layer, layer_name) into the same GPKG.
        We remove any existing gpkg first for a clean write.
        """
        # Remove existing GPKG (and sidecars, if any)
        try:
            if os.path.exists(gpkg_path):
                os.remove(gpkg_path)
        except Exception:
            pass

        for lyr, lname in layers_with_names:
            err = QgsVectorFileWriter.writeAsVectorFormat(
                lyr,
                gpkg_path,
                "UTF-8",
                lyr.crs(),
                "GPKG",
                onlySelected=False,
                layerOptions=[f"LAYER_NAME={lname}", "SPATIAL_INDEX=YES"]
            )
            if err != QgsVectorFileWriter.NoError:
                return False
        return True

    def _apply_style(self, layer, style_filename):
        """
        Try to load a QML file from the Styles directory.
        style_filename example: 'aoi.qml'
        """
        styles_dir = get_persistent_setting("paths/styles_dir", "")
        if not styles_dir:
            return False
        qml_path = os.path.join(styles_dir, style_filename)
        if not os.path.isfile(qml_path):
            return False
        res, err = layer.loadNamedStyle(qml_path)
        layer.triggerRepaint()
        return bool(res)

    def _style_grid_layer(self, layer, kind):
        """
        Apply fallback styles if QML is missing.
        kind in {'tiles','edges','vertices','centroids'}
        """
        from qgis.core import QgsFillSymbol, QgsLineSymbol, QgsMarkerSymbol, QgsSingleSymbolRenderer # type: ignore

        if kind == 'tiles':
            # Polygon: 20% opacity orange fill, no stroke
            sym = QgsFillSymbol.createSimple({
                'color': '255,165,0,51',      # orange @ 20% (alpha 51)
                'outline_style': 'no',        # no stroke
            })
            layer.setRenderer(QgsSingleSymbolRenderer(sym))

        elif kind == 'edges':
            # Line: purple @ 80% opacity
            sym = QgsLineSymbol.createSimple({
                'line_color': '128,0,128,204',  # purple @ 80% (alpha 204)
                'line_width': '0.6',
                'line_width_unit': 'MM',
            })
            layer.setRenderer(QgsSingleSymbolRenderer(sym))

        elif kind == 'vertices':
            # Point: purple fully opaque
            sym = QgsMarkerSymbol.createSimple({
                'name': 'circle',
                'color': '128,0,128,255',   # purple @ 100%
                'outline_color': '0,0,0,0', # no outline
                'size': '1.8',
                'size_unit': 'MM',
            })
            layer.setRenderer(QgsSingleSymbolRenderer(sym))

        elif kind == 'centroids':
            # Point: orange full opacity with purple stroke
            sym = QgsMarkerSymbol.createSimple({
                'name': 'circle',
                'color': '255,165,0,255',   # orange @ 100%
                'outline_color': '128,0,128,255', # purple stroke
                'outline_width': '0.4',
                'outline_width_unit': 'MM',
                'size': '2.0',
                'size_unit': 'MM',
            })
            layer.setRenderer(QgsSingleSymbolRenderer(sym))

        layer.triggerRepaint()

    def _rebuild_export_tree(self):
        """
        Mirror the QGIS layer tree into a tri-state, checkable QTreeWidget.
        Store layer IDs on layer items via Qt.UserRole.
        Default: check everything except obvious helpers (you can tweak).
        """
        self.tw_export.blockSignals(True)
        self.tw_export.clear()

        proj = QgsProject.instance()
        root = proj.layerTreeRoot()

        # Heuristics for skipping by default (still shown, just unchecked)
        default_skip = [
            "aoi", "centroid helpers", "intersection helpers",
            "hex grid edges", "hex_vertices", "hex_centroids"
        ]

        def add_group(node, parent_item):
            item = QtWidgets.QTreeWidgetItem(parent_item, [node.name()])
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsTristate)
            item.setCheckState(0, Qt.Checked)  # groups default to checked; children decide final state
            for child in node.children():
                if child.nodeType() == child.NodeGroup:
                    add_group(child, item)
                else:
                    lyr = child.layer()
                    if not lyr: 
                        continue
                    li = QtWidgets.QTreeWidgetItem(item, [lyr.name()])
                    li.setFlags(li.flags() | Qt.ItemIsUserCheckable)
                    li.setData(0, Qt.UserRole, lyr.id())
                    # default check state
                    nm = lyr.name().lower()
                    check = Qt.Unchecked if any(s in nm for s in default_skip) else Qt.Checked
                    li.setCheckState(0, check)

        add_group(root, self.tw_export.invisibleRootItem())
        self.tw_export.expandAll()
        self.tw_export.blockSignals(False)

    def _set_tree_checked(self, item, state):
        """Recursively set check state for an item and its children."""
        for i in range(item.childCount()):
            child = item.child(i)
            if child.flags() & Qt.ItemIsUserCheckable:
                child.setCheckState(0, state)
            self._set_tree_checked(child, state)

    def _gather_checked_layer_ids(self):
        """Collect layer IDs from checked layer items."""
        ids = []

        def walk(item):
            for i in range(item.childCount()):
                child = item.child(i)
                lyr_id = child.data(0, Qt.UserRole)
                if lyr_id and child.checkState(0) == Qt.Checked:
                    ids.append(lyr_id)
                walk(child)

        walk(self.tw_export.invisibleRootItem())
        return ids

    def _compute_export_dims(self, aoi_layer, hex_m):
        """
        Returns (w_m, h_m, w_px, h_px, w_mm, h_mm) under the rule:
        - 64 px per 500 m (i.e., 0.128 px/m)
        - Export DPI = 128
        Page size is chosen so that: inches * 128 = pixels  => inches = meters / 1000
        Therefore: page_mm = meters * 25.4 / 1000 = meters * 0.0254
        """
        # AOI extent in layer CRS units (expect meters in projected CRS)
        ext = aoi_layer.extent()
        w_m = ext.width()
        h_m = ext.height()

        # Pixel density per meter from your spec
        ppm = 64.0 / 500.0  # 0.128 px/m
        w_px = int(round(w_m * ppm))
        h_px = int(round(h_m * ppm))

        # Page size in millimeters so that 128-dpi export yields the same pixel dims
        # inches = meters / 1000, so mm = inches * 25.4 = meters * 0.0254
        w_mm = w_m * 0.0254
        h_mm = h_m * 0.0254
        return w_m, h_m, w_px, h_px, w_mm, h_mm

    def _update_export_labels(self, aoi_layer, hex_m):
        w_m, h_m, w_px, h_px, w_mm, h_mm = self._compute_export_dims(aoi_layer, hex_m)
        self.lbl_export_px.setText(f"Pixels: {w_px} x {h_px}")
        self.lbl_export_page.setText(f"Page size: {w_mm:.2f} mm x {h_mm:.2f} mm")

    def _selected_aoi_layer_for_export(self):
        lyr_id = self.cboAOI_export.currentData()
        return QgsProject.instance().mapLayer(lyr_id) if lyr_id else None

    def _compute_export_info(self):
        aoi = self._selected_aoi_layer_for_export()
        if not aoi:
            self.log("Export: choose an AOI.")
            return
        try:
            hex_m = max(1.0, float(self.hex_scale_edit.text()))
        except Exception:
            hex_m = 500.0
            self.hex_scale_edit.setText("500")

        if aoi.crs().mapUnits() != QgsUnitTypes.DistanceMeters:
            self.log("Export: AOI CRS is not meters. Use a projected CRS (e.g., UTM) for exact sizing.")

        # compute
        ext = aoi.extent()
        w_m = ext.width(); h_m = ext.height()
        ppm = 64.0 / 500.0  # 0.128 px/m
        w_px = int(round(w_m * ppm)); h_px = int(round(h_m * ppm))
        w_mm = w_m * 0.0254; h_mm = h_m * 0.0254

        self.lbl_export_px.setText(f"Pixels: {w_px} x {h_px}")
        self.lbl_export_page.setText(f"Page size: {w_mm:.2f} mm x {h_mm:.2f} mm")

    def export_png_direct(self):
        """
        Render the chosen AOI extent directly to PNG at exact pixel size,
        using only the layers the user checked in the Export tree.
        """
        aoi = self._selected_aoi_layer_for_export()
        if not aoi:
            self.log("Export: choose an AOI.")
            return

        # ppm by your spec
        ppm = 64.0 / 500.0

        # Extent
        ext = aoi.extent()
        w_m = ext.width(); h_m = ext.height()
        w_px = max(1, int(round(w_m * ppm)))
        h_px = max(1, int(round(h_m * ppm)))

        # Output folder and filename
        out_root = get_persistent_setting("paths/out_dir", "")
        if not out_root or not os.path.isdir(out_root):
            self.log("Export: set a Project directory in Setup.")
            return

        export_dir = self._export_dir()
        os.makedirs(export_dir, exist_ok=True)

        base_name = (self.export_name_edit.text().strip()
                    or self.project_name_edit.text().strip()
                    or self._safe_filename(aoi.name()))
        base_name = self._safe_filename(base_name)

        fname = f"{base_name}_{w_px}x{h_px}.png"
        out_png = os.path.join(export_dir, fname)

        # Collect layer IDs from the tree, then resolve to QgsMapLayer objects
        layer_ids = self._gather_checked_layer_ids()
        if not layer_ids:
            self.log("Export: no layers selected. Check some layers in the tree.")
            return

        proj = QgsProject.instance()
        layers = []
        for lid in layer_ids:
            lyr = proj.mapLayer(lid)
            if lyr is not None:
                layers.append(lyr)

        if not layers:
            self.log("Export: could not resolve any selected layers. ")
            return

        # Map settings
        ms = QgsMapSettings()
        ms.setLayers(layers)  # pass QgsMapLayer objects
        ms.setDestinationCrs(aoi.crs())
        ms.setExtent(ext)
        ms.setOutputSize(QtCore.QSize(w_px, h_px))
        ms.setBackgroundColor(Qt.transparent)

        # Render to image
        img = QImage(w_px, h_px, QImage.Format_ARGB32)
        img.fill(Qt.transparent)
        painter = QPainter(img)
        try:
            job = QgsMapRendererCustomPainterJob(ms, painter)
            job.start()
            job.waitForFinished()
        finally:
            painter.end()

        if not img.save(out_png, "PNG"):
            self.log("Export: failed to write PNG.")
            return

        self.log(f"Exported PNG: {out_png}\nPixels: {w_px} x {h_px}  (AOI: {aoi.name()})")

    def _reveal_in_explorer(self, path: str):
        """Open a file/folder in the OS file browser."""
        try:
            if os.name == "nt":
                os.startfile(path)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as e:
            self.log(f"Could not open folder: {e}")