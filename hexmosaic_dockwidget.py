# -*- coding: utf-8 -*-
"""
HexMosaic Dock — minimal AOI panel
Replaces Designer UI for now to avoid resource/Qt wiring issues.
"""
import os
import sys, subprocess
from qgis.utils import iface # pyright: ignore[reportMissingImports]
from qgis.PyQt import QtCore, QtWidgets # pyright: ignore[reportMissingImports]
from qgis.PyQt.QtCore import pyqtSignal, QVariant, Qt, QSettings # pyright: ignore[reportMissingImports]
from qgis.PyQt.QtGui import QImage, QPainter # pyright: ignore[reportMissingImports]
from qgis.core import ( # pyright: ignore[reportMissingImports]
    QgsVectorLayer, QgsField, QgsFeature, QgsGeometry, QgsPointXY, QgsProject,
    QgsVectorFileWriter, QgsSnappingConfig, QgsTolerance,
    QgsFillSymbol, QgsMarkerSymbol, QgsSingleSymbolRenderer,
    QgsFields, QgsWkbTypes, QgsLineSymbol,
    QgsUnitTypes, QgsLayoutSize, QgsLayoutPoint, QgsPrintLayout,
    QgsLayoutItemMap, QgsLayoutExporter, QgsRectangle, QgsMapSettings, QgsMapRendererCustomPainterJob
)

class HexMosaicSettingsDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("HexMosaic Settings")
        v = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()
        self.out_dir = QtWidgets.QLineEdit()
        self.styles_dir = QtWidgets.QLineEdit()
        b1 = QtWidgets.QPushButton("Browse…"); b2 = QtWidgets.QPushButton("Browse…")
        row1 = QtWidgets.QHBoxLayout(); row1.addWidget(self.out_dir); row1.addWidget(b1)
        row2 = QtWidgets.QHBoxLayout(); row2.addWidget(self.styles_dir); row2.addWidget(b2)
        form.addRow("Project output directory:", row1)
        form.addRow("Styles directory (.qml):", row2)
        v.addLayout(form)
        btns = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        v.addWidget(btns)
        # fill from QSettings
        s = QtWidgets.QApplication.instance().organizationName() or "HexMosaicOrg"
        q = QtWidgets.QApplication.instance().applicationName() or "HexMosaic"
        self._qs = QSettings(s, q)  # was QtWidgets.QSettings(...)
        self.out_dir.setText(self._qs.value("paths/out_dir", "", type=str))
        self.styles_dir.setText(self._qs.value("paths/styles_dir", "", type=str))

        def pick(le):
            d = QtWidgets.QFileDialog.getExistingDirectory(self, "Select folder", le.text() or os.path.expanduser("~"))
            if d: le.setText(d)
        b1.clicked.connect(lambda: pick(self.out_dir))
        b2.clicked.connect(lambda: pick(self.styles_dir))
        btns.accepted.connect(self.accept); btns.rejected.connect(self.reject)

    def accept(self):
        self._qs.setValue("paths/out_dir", self.out_dir.text())
        self._qs.setValue("paths/styles_dir", self.styles_dir.text())
        super().accept()

# --- settings helper (module-level) ---
def _get_setting(key, default=""):
    s = QtWidgets.QApplication.instance().organizationName() or "HexMosaicOrg"
    a = QtWidgets.QApplication.instance().applicationName() or "HexMosaic"
    q = QSettings(s, a)  # use QSettings (QtCore)
    return q.value(key, default, type=str)

class HexMosaicDockWidget(QtWidgets.QDockWidget):
    closingPlugin = pyqtSignal()

    def __init__(self, parent=None):
        super(HexMosaicDockWidget, self).__init__(parent)
        self.setObjectName("HexMosaicDockWidget")
        self.setWindowTitle("HexMosaic")

        # -- container & layout --
        container = QtWidgets.QWidget(self); self.setWidget(container)
        vbox = QtWidgets.QVBoxLayout(container)

        # --- LOG WIDGET: create early so self.log() can use it anytime ---
        self.log_view = QtWidgets.QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(2000)

        # ========== ACCORDION ==========
        self.tb = QtWidgets.QToolBox()
        vbox.addWidget(self.tb)

        # --- 1) SETUP ---
        pg_setup = QtWidgets.QWidget(); f1 = QtWidgets.QFormLayout(pg_setup)

        self.project_name_edit = QtWidgets.QLineEdit()
        self.author_edit = QtWidgets.QLineEdit()

        self.out_dir_edit = QtWidgets.QLineEdit()
        btn_out = QtWidgets.QPushButton("Browse…")
        btn_out.clicked.connect(lambda: self._browse_dir(self.out_dir_edit))
        row_out = QtWidgets.QHBoxLayout(); row_out.addWidget(self.out_dir_edit); row_out.addWidget(btn_out)

        self.styles_dir_edit = QtWidgets.QLineEdit()
        btn_styles = QtWidgets.QPushButton("Browse…")
        btn_styles.clicked.connect(lambda: self._browse_dir(self.styles_dir_edit))
        row_styles = QtWidgets.QHBoxLayout(); row_styles.addWidget(self.styles_dir_edit); row_styles.addWidget(btn_styles)

        self.hex_scale_edit = QtWidgets.QLineEdit("500")

        btn_save_setup = QtWidgets.QPushButton("Save Settings")
        btn_gen_groups = QtWidgets.QPushButton("Generate Groups and Layers")

        f1.addRow("Project name:", self.project_name_edit)
        f1.addRow("Author:", self.author_edit)
        f1.addRow("Project directory:", row_out)
        f1.addRow("Styles directory:", row_styles)
        f1.addRow("Hex scale (m):", self.hex_scale_edit)
        f1.addRow(btn_save_setup, btn_gen_groups)

        self.tb.addItem(pg_setup, "1. Setup")

        # --- 2) MAP AREA ---
        pg_aoi = QtWidgets.QWidget(); f2 = QtWidgets.QFormLayout(pg_aoi)

        self.unit_m = QtWidgets.QRadioButton("meters"); self.unit_h = QtWidgets.QRadioButton("hexes")
        self.unit_m.setChecked(True)
        row_units = QtWidgets.QHBoxLayout(); row_units.addWidget(self.unit_m); row_units.addWidget(self.unit_h); row_units.addStretch(1)

        self.width_input  = QtWidgets.QLineEdit("5000")
        self.height_input = QtWidgets.QLineEdit("5000")
        self.lblWHm = QtWidgets.QLabel("Width × Height (m): –")
        self.lblWHh = QtWidgets.QLabel("Width × Height (hexes): –")
        self.lblCount = QtWidgets.QLabel("Total hexes: –")
        btn_aoi = QtWidgets.QPushButton("Create AOI")

        f2.addRow("Units:", row_units)
        f2.addRow("Width:", self.width_input)
        f2.addRow("Height:", self.height_input)
        f2.addRow(self.lblWHm)
        f2.addRow(self.lblWHh)
        f2.addRow(self.lblCount)
        f2.addRow(btn_aoi)

        self.tb.addItem(pg_aoi, "2. Map Area")

        # --- 3) GENERATE GRID ---
        pg_grid = QtWidgets.QWidget(); f3 = QtWidgets.QFormLayout(pg_grid)
        self.cboAOI = QtWidgets.QComboBox()
        btn_refresh_aoi = QtWidgets.QPushButton("Refresh")
        row_aoi = QtWidgets.QHBoxLayout(); row_aoi.addWidget(self.cboAOI); row_aoi.addWidget(btn_refresh_aoi)
        btn_build_grid = QtWidgets.QPushButton("Build Hex Grid")
        f3.addRow("AOI:", row_aoi)
        f3.addRow(btn_build_grid)
        self.tb.addItem(pg_grid, "3. Generate Grid")

        # --- 4) SET ELEVATION HEIGHTMAP ---
        pg_elev = QtWidgets.QWidget(); f4 = QtWidgets.QFormLayout(pg_elev)
        self.elev_path_edit = QtWidgets.QLineEdit()
        btn_pick_elev = QtWidgets.QPushButton("Browse…")
        btn_pick_elev.clicked.connect(lambda: self._browse_dir(self.elev_path_edit) if False else None)
        # ^ if you want file browsing: use QFileDialog.getOpenFileName below in the clicked slot
        def _pick_elev():
            p, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Choose DEM (tif)", self.out_dir_edit.text() or "", "Rasters (*.tif *.tiff *.img *.vrt);;All files (*.*)")
            if p: self.elev_path_edit.setText(p)
        btn_pick_elev.clicked.disconnect(); btn_pick_elev.clicked.connect(_pick_elev)

        row_ep = QtWidgets.QHBoxLayout(); row_ep.addWidget(self.elev_path_edit); row_ep.addWidget(btn_pick_elev)
        self.elev_style_combo = QtWidgets.QComboBox()
        btn_refresh_styles = QtWidgets.QPushButton("Refresh styles")
        btn_apply_elev = QtWidgets.QPushButton("Apply to Project")

        f4.addRow("DEM file:", row_ep)
        f4.addRow("Style:", self.elev_style_combo)
        f4.addRow(btn_refresh_styles, btn_apply_elev)
        self.tb.addItem(pg_elev, "4. Set Elevation Heightmap")

        # --- 5) IMPORT OSM (placeholder) ---
        pg_osm = QtWidgets.QWidget(); f5 = QtWidgets.QVBoxLayout(pg_osm)
        f5.addWidget(QtWidgets.QLabel("Import OSM (coming soon)"))
        self.tb.addItem(pg_osm, "5. Import OSM")

        # --- 6) HEX MOSAIC PALETTE (placeholder) ---
        pg_mosaic = QtWidgets.QWidget(); f6 = QtWidgets.QVBoxLayout(pg_mosaic)
        btn_gen_mosaic = QtWidgets.QPushButton("Generate Mosaic Group and Layers")
        f6.addWidget(btn_gen_mosaic)
        self.tb.addItem(pg_mosaic, "6. Hex Mosaic Palette")

        # --- 7) EXPORT MAP ---
        pg_export = QtWidgets.QWidget()
        f7 = QtWidgets.QFormLayout(pg_export)

        # Layer selection tree
        self.tw_export = QtWidgets.QTreeWidget()
        self.tw_export.setHeaderLabels(["Group / Layer"])
        self.tw_export.setColumnCount(1)
        self.tw_export.setUniformRowHeights(True)
        self.tw_export.setRootIsDecorated(True)
        self.tw_export.setExpandsOnDoubleClick(True)
        self.tw_export.setMinimumHeight(220)

        btn_refresh_tree = QtWidgets.QPushButton("Refresh Layers")
        btn_check_all = QtWidgets.QPushButton("Check All")
        btn_uncheck_all = QtWidgets.QPushButton("Uncheck All")
        row_tree_btns = QtWidgets.QHBoxLayout()
        row_tree_btns.addWidget(btn_refresh_tree)
        row_tree_btns.addStretch(1)
        row_tree_btns.addWidget(btn_check_all)
        row_tree_btns.addWidget(btn_uncheck_all)

        f7.addRow(QtWidgets.QLabel("Select layers to include in export:"))
        f7.addRow(self.tw_export)
        f7.addRow(row_tree_btns)

        # Read-only computed fields
        self.lbl_export_px   = QtWidgets.QLabel("Pixels: – × –")
        self.lbl_export_page = QtWidgets.QLabel("Page size (mm @ 128 dpi rule): – × –")
        f7.addRow(self.lbl_export_px)
        f7.addRow(self.lbl_export_page)

        # AOI selector (reuse list)
        self.cboAOI_export = QtWidgets.QComboBox()
        btn_refresh_aoi2 = QtWidgets.QPushButton("Refresh AOIs")
        row_aoi_export = QtWidgets.QHBoxLayout()
        row_aoi_export.addWidget(self.cboAOI_export)
        row_aoi_export.addWidget(btn_refresh_aoi2)
        f7.addRow("AOI:", row_aoi_export)

        # Filename
        self.export_name_edit = QtWidgets.QLineEdit()
        # default from project name (settings) or AOI later
        self.export_name_edit.setPlaceholderText("export filename (without extension)")
        f7.addRow("Filename:", self.export_name_edit)

        # Actions
        btn_compute = QtWidgets.QPushButton("Compute")
        self.btn_export_png = QtWidgets.QPushButton("Export PNG (direct)")
        self.btn_open_folder = QtWidgets.QPushButton("Open Export Folder")
        row_actions = QtWidgets.QHBoxLayout()
        row_actions.addWidget(btn_compute)
        row_actions.addStretch(1)
        row_actions.addWidget(self.btn_export_png)
        row_actions.addWidget(self.btn_open_folder)

        f7.addRow(self.lbl_export_px)
        f7.addRow(self.lbl_export_page)
        f7.addRow(row_actions)

        self.tb.addItem(pg_export, "7. Export Map")

        # --- wire up Export Map (after widgets exist) ---
        btn_refresh_aoi2.clicked.connect(lambda: (self._populate_aoi_combo(),
                                                self._sync_export_aoi_combo(),
                                                self._rebuild_export_tree()))
        btn_refresh_tree.clicked.connect(self._rebuild_export_tree)
        btn_check_all.clicked.connect(lambda: self._set_tree_checked(self.tw_export.invisibleRootItem(), Qt.Checked))
        btn_uncheck_all.clicked.connect(lambda: self._set_tree_checked(self.tw_export.invisibleRootItem(), Qt.Unchecked))
        btn_compute.clicked.connect(self._compute_export_info)
        self.btn_export_png.clicked.connect(self.export_png_direct)
        btn_compute.clicked.connect(lambda: (
            self._selected_aoi_layer_for_export()
            and self._update_export_labels(self._selected_aoi_layer_for_export(),
                                        float(self.hex_scale_edit.text() or "500"))
        ))
        self.btn_open_folder.clicked.connect(lambda: self._reveal_in_explorer(self._export_dir()))

        # --- 8) LOG (inside toolbox) ---
        pg_log = QtWidgets.QWidget()
        vl_log = QtWidgets.QVBoxLayout(pg_log)
        self.log_view = QtWidgets.QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(2000)
        vl_log.addWidget(self.log_view)
        self._log_tab_index = self.tb.addItem(pg_log, "8. Log")

        # initial state
        self._load_setup_settings()
        proj_name = self.project_name_edit.text().strip()
        if hasattr(self, "export_name_edit") and not self.export_name_edit.text().strip():
            self.export_name_edit.setText(proj_name or "hexmosaic_export")
        self._populate_aoi_combo()
        self._refresh_elevation_styles()
        self._sync_export_aoi_combo()
        self._rebuild_export_tree()
        self.log("HexMosaic dock ready.")

    def _sync_export_aoi_combo(self):
        # mirror items from self.cboAOI
        self.cboAOI_export.blockSignals(True)
        self.cboAOI_export.clear()
        for i in range(self.cboAOI.count()):
            self.cboAOI_export.addItem(self.cboAOI.itemText(i), self.cboAOI.itemData(i))
        self.cboAOI_export.blockSignals(False)

    def closeEvent(self, event):
        self.closingPlugin.emit()
        event.accept()

    def _browse_dir(self, line_edit):
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "Select folder", line_edit.text() or os.path.expanduser("~"))
        if d: line_edit.setText(d)

    def _save_setup_settings(self):
        s = QSettings("HexMosaicOrg", "HexMosaic")
        s.setValue("paths/out_dir", self.out_dir_edit.text())
        s.setValue("paths/styles_dir", self.styles_dir_edit.text())
        s.setValue("project/name", self.project_name_edit.text())
        s.setValue("project/author", self.author_edit.text())
        s.setValue("grid/hex_scale_m", self.hex_scale_edit.text())

    def _load_setup_settings(self):
        s = QSettings("HexMosaicOrg", "HexMosaic")
        self.out_dir_edit.setText(s.value("paths/out_dir", "", type=str))
        self.styles_dir_edit.setText(s.value("paths/styles_dir", "", type=str))
        self.project_name_edit.setText(s.value("project/name", "", type=str))
        self.author_edit.setText(s.value("project/author", "", type=str))
        self.hex_scale_edit.setText(s.value("grid/hex_scale_m", "500", type=str))

    def _ellipsize(self, s: str, limit: int = 48) -> str:
        s = s.replace("\n", " ").strip()
        return s if len(s) <= limit else s[:limit - 1] + "…"

    def log(self, msg: str):
        # Ensure the log tab exists
        if not hasattr(self, "log_view"):
            return
        self.log_view.appendPlainText(msg)
        # Update the tab title with the latest line
        title = f"8. Log: {self._ellipsize(msg)}"
        # Qt will trim if too long; that’s okay
        if hasattr(self, "_log_tab_index"):
            self.tb.setItemText(self._log_tab_index, title)

    def _generate_group_skeleton(self):
        root = QgsProject.instance().layerTreeRoot()
        order = ["Elevation", "Reference", "OSM", "Base", "Mosaic"]
        for name in order:
            if not root.findGroup(name):
                root.addGroup(name)
        # Sub-groups we know we’ll use under Base
        base = root.findGroup("Base")
        if base and not any(g.name() == "Base Grid" for g in base.findGroups()):
            base.addGroup("Base Grid")
        self.log("Groups prepared: " + " > ".join(order))

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

    def _apply_elevation_style_and_add(self):
        path = self.elev_path_edit.text().strip()
        if not os.path.isfile(path):
            self.log("Elevation: file not found.")
            return
        lyr = QgsVectorLayer(path, os.path.basename(path), "gdal")  # gdal works for rasters; QGIS auto-detects
        if not lyr or not lyr.isValid():
            # Raster needs QgsRasterLayer; let QGIS provider load via 'gdal'
            from qgis.core import QgsRasterLayer
            path = self.elev_path_edit.text().strip()
            if not os.path.isfile(path):
                self.log("Elevation: file not found.")
                return

            lyr = QgsRasterLayer(path, os.path.basename(path))
            if not lyr.isValid():
                self.log("Elevation: failed to load raster.")
                return

        # style if chosen
        qml_path = self.elev_style_combo.currentData()
        if qml_path and os.path.isfile(qml_path):
            _ok, _ = lyr.loadNamedStyle(qml_path)
            lyr.triggerRepaint()

        # add to Elevation group
        proj = QgsProject.instance()
        root = proj.layerTreeRoot()
        elev_grp = root.findGroup("Elevation") or root.addGroup("Elevation")
        proj.addMapLayer(lyr, False); elev_grp.addLayer(lyr)
        self.log(f"Elevation added: {path}")

    def _create_spatial_index(self, vector_path):
        """Build a .qix spatial index for a saved shapefile. Silently ignore failures."""
        try:
            from qgis import processing
            if vector_path.lower().endswith(".shp") and os.path.exists(vector_path):
                processing.run("native:createspatialindex", {"INPUT": vector_path})
                return True
        except Exception:
            pass
        return False

    def _populate_aoi_combo(self):
        """List polygon layers whose name starts with 'AOI '."""
        self.cboAOI.clear()
        proj = QgsProject.instance()
        candidates = []
        for lyr in proj.mapLayers().values():
            # 2 = polygon; accept both memory and disk-backed; name convention 'AOI ...'
            if hasattr(lyr, "geometryType") and lyr.geometryType() == 2 and lyr.name().upper().startswith("AOI"):
                candidates.append(lyr)

        # sort by name for stability
        for lyr in sorted(candidates, key=lambda L: L.name().lower()):
            self.cboAOI.addItem(lyr.name(), lyr.id())

    def _selected_aoi_layer(self):
        """Return the AOI layer object chosen in the combo, or None."""
        lyr_id = self.cboAOI.currentData()
        if not lyr_id:
            return None
        return QgsProject.instance().mapLayer(lyr_id)

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
        styles_dir = _get_setting("paths/styles_dir", "")
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
        kind ∈ {'tiles','edges','vertices','centroids'}
        """
        from qgis.core import QgsFillSymbol, QgsLineSymbol, QgsMarkerSymbol, QgsSingleSymbolRenderer

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

    def _safe_filename(self, name):
        return "".join(c if c.isalnum() or c in ("_", "-", ".") else "_" for c in name)
    
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
        self.lbl_export_px.setText(f"Pixels: {w_px} × {h_px}")
        self.lbl_export_page.setText(f"Page size: {w_mm:.2f} mm × {h_mm:.2f} mm")

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

        self.lbl_export_px.setText(f"Pixels: {w_px} × {h_px}")
        self.lbl_export_page.setText(f"Page size: {w_mm:.2f} mm × {h_mm:.2f} mm")

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
        out_root = _get_setting("paths/out_dir", "")
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

        self.log(f"Exported PNG: {out_png}\nPixels: {w_px} × {h_px}  (AOI: {aoi.name()})")

    def _project_root(self) -> str:
        """Prefer Setup's Project directory; else the folder of the current .qgz; else home."""
        d = (self.out_dir_edit.text().strip()
            or _get_setting("paths/out_dir", ""))
        if d and os.path.isdir(d):
            return d
        proj_path = QgsProject.instance().fileName()
        if proj_path:
            return os.path.dirname(proj_path)
        return os.path.expanduser("~")

    def _export_dir(self) -> str:
        """Always export to <project root>/export."""
        return os.path.join(self._project_root(), "export")

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


    # ---------- logic ----------
    def _recalc_aoi_info(self):
        """Update labels and keep width/height multiples of hex scale when in meters; or convert hexes→meters."""
        try:
            hex_m = max(1.0, float(self.hex_scale_edit.text()))
        except:
            hex_m = 500.0
            self.hex_scale_edit.setText("500")
        # read width/height as floats
        try: v1 = float(self.width_input.text())
        except: v1 = 0
        try: v2 = float(self.height_input.text())
        except: v2 = 0

        if self.unit_m.isChecked():
            # snap to nearest multiple of hex size
            if v1 > 0:
                v1s = max(hex_m, round(v1 / hex_m) * hex_m)
                if abs(v1s - v1) > 1e-6: self.width_input.blockSignals(True); self.width_input.setText(str(int(v1s))); self.width_input.blockSignals(False); v1 = v1s
            if v2 > 0:
                v2s = max(hex_m, round(v2 / hex_m) * hex_m)
                if abs(v2s - v2) > 1e-6: self.height_input.blockSignals(True); self.height_input.setText(str(int(v2s))); self.height_input.blockSignals(False); v2 = v2s
            w_m, h_m = v1, v2
            w_h = int(round(w_m / hex_m)); h_h = int(round(h_m / hex_m))
        else:
            # values are hex counts; compute meters
            w_h, h_h = int(max(1, round(v1))), int(max(1, round(v2)))
            if str(w_h) != self.width_input.text():
                self.width_input.blockSignals(True); self.width_input.setText(str(w_h)); self.width_input.blockSignals(False)
            if str(h_h) != self.height_input.text():
                self.height_input.blockSignals(True); self.height_input.setText(str(h_h)); self.height_input.blockSignals(False)
            w_m, h_m = w_h * hex_m, h_h * hex_m

        # display
        self.lblWHm.setText(f"Width x Height (m): {int(w_m)} × {int(h_m)}")
        self.lblWHh.setText(f"Width x Height (hexes): {int(max(1, round(w_m/hex_m)))} × {int(max(1, round(h_m/hex_m)))}")
        self.lblCount.setText(f"Total hexes: {int(max(1, round(w_m/hex_m)))*int(max(1, round(h_m/hex_m)))}")

    def _open_settings(self):
        dlg = HexMosaicSettingsDialog(self)
        dlg.exec_()


    def create_aoi(self):
        """Create AOI as a shapefile (no temp layer), load it, style it, group it."""
        # --- sizes ---
        try:
            hex_m = max(1.0, float(self.hex_scale_edit.text()))
        except:
            hex_m = 500.0
            self.hex_scale_edit.setText("500")

        use_meters = self.unit_m.isChecked()
        try:
            a = float(self.width_input.text()); b = float(self.height_input.text())
        except:
            self.log("Invalid size.")
            return

        if use_meters:
            w_m, h_m = a, b
        else:
            w_m, h_m = int(a) * hex_m, int(b) * hex_m

        if w_m <= 0 or h_m <= 0:
            self.log("Width/Height must be > 0.")
            return

        # --- rectangle in current map CRS ---
        canvas = iface.mapCanvas()
        center = canvas.center()
        xmin, xmax = center.x() - w_m/2.0, center.x() + w_m/2.0
        ymin, ymax = center.y() - h_m/2.0, center.y() + h_m/2.0
        crs = canvas.mapSettings().destinationCrs()

        # --- unique names / paths ---
        aoi_idx = self._next_aoi_index()
        w_m_i, h_m_i = int(round(w_m)), int(round(h_m))
        display_name = f"AOI {aoi_idx} {w_m_i}m x {h_m_i}m"

        out_dir = _get_setting("paths/out_dir", "")
        if not out_dir or not os.path.isdir(out_dir):
            self.log("No output directory set (Settings).")
            return

        shp_name = self._safe_filename(f"AOI_{aoi_idx}_{w_m_i}m_x_{h_m_i}m.shp")
        shp_path = os.path.join(out_dir, shp_name)

        # --- hard overwrite any existing sidecars ---
        base, _ = os.path.splitext(shp_path)
        for ext in (".shp", ".shx", ".dbf", ".prj", ".cpg", ".qmd"):
            p = base + ext
            if os.path.exists(p):
                try: os.remove(p)
                except: pass

        # --- write shapefile directly (no temp layer added to project) ---
        fields = QgsFields()
        fields.append(QgsField("id", QVariant.Int))

        writer = QgsVectorFileWriter(
            shp_path, "UTF-8", fields, QgsWkbTypes.Polygon, crs, "ESRI Shapefile"
        )

        if writer.hasError() != QgsVectorFileWriter.NoError:
            self.log(f"Failed to create shapefile: {shp_path}")
            del writer
            return

        feat = QgsFeature(fields)
        feat.setAttribute("id", 1)
        feat.setGeometry(QgsGeometry.fromPolygonXY([[
            QgsPointXY(xmin, ymin),
            QgsPointXY(xmin, ymax),
            QgsPointXY(xmax, ymax),
            QgsPointXY(xmax, ymin)
        ]]))
        writer.addFeature(feat)
        del writer  # flush to disk

        # --- load disk layer, style, and add under 'Base' ---
        aoi = QgsVectorLayer(shp_path, display_name, "ogr")
        if not aoi.isValid():
            self.log("Saved AOI shapefile, but failed to load it.")
            return

        # Apply QML if present; fallback style otherwise
        qml_ok = self._apply_style(aoi, "aoi.qml")
        if not qml_ok:
            sym = QgsFillSymbol.createSimple({
                'color': '255,255,255,0',
                'outline_color': '255,105,180',
                'outline_width': '0.6'
            })
            aoi.setRenderer(QgsSingleSymbolRenderer(sym))

        proj = QgsProject.instance()
        root = proj.layerTreeRoot()
        base_grp = root.findGroup('Base') or root.addGroup('Base')

        # Remove any *memory* AOIs lingering from earlier runs (optional hygiene)
        to_remove = [lyr.id() for lyr in proj.mapLayers().values()
                    if lyr.providerType() == "memory" and lyr.name().startswith("AOI")]
        if to_remove:
            proj.removeMapLayers(to_remove)

        proj.addMapLayer(aoi, False)
        base_grp.addLayer(aoi)

        canvas.setExtent(aoi.extent())
        canvas.refresh()
        self.log(f"{display_name} added to 'Base'. Saved to Shapefile. "
                            + ("Style: QML applied." if qml_ok else "Style: QML missing (used fallback)."))

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
        from qgis import processing

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

        out_root = _get_setting("paths/out_dir", "")
        if not out_root or not os.path.isdir(out_root):
            self.log("No output directory set (Settings).")
            return

        self._ensure_snapping(20)
        crs = aoi.crs()
        extent = aoi.extent()
        ext_str = f"{extent.xMinimum()},{extent.xMaximum()},{extent.yMinimum()},{extent.yMaximum()} [{crs.authid()}]"

        # --- make on-disk folder structure: Base/Base_Grid/<AOI_safe> ---
        aoi_safe = self._safe_filename(aoi.name().replace(" ", "_"))
        base_dir = os.path.join(out_root, "Base", "Base_Grid", aoi_safe)
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
