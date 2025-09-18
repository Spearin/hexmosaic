# -*- coding: utf-8 -*-
"""
HexMosaic Dock — minimal AOI panel
Replaces Designer UI for now to avoid resource/Qt wiring issues.
"""
import os
import sys, subprocess
import math
import urllib.request
import urllib.parse
import json, shutil
import time
from datetime import datetime
from qgis.utils import iface # pyright: ignore[reportMissingImports]
from qgis.PyQt import QtCore, QtWidgets # pyright: ignore[reportMissingImports]
from qgis.PyQt.QtCore import pyqtSignal, QVariant, Qt, QSettings # pyright: ignore[reportMissingImports]
from qgis.PyQt.QtGui import QImage, QPainter # pyright: ignore[reportMissingImports]
from qgis.core import ( # pyright: ignore[reportMissingImports]
    QgsVectorLayer, QgsRasterLayer, QgsCoordinateReferenceSystem, QgsField, QgsFeature, QgsGeometry, QgsPointXY, QgsProject,
    QgsVectorFileWriter, QgsSnappingConfig, QgsTolerance,
    QgsFillSymbol, QgsMarkerSymbol, QgsSingleSymbolRenderer,
    QgsFields, QgsWkbTypes, QgsLineSymbol, QgsMapLayerStyle,
    QgsUnitTypes, QgsLayoutSize, QgsLayoutPoint, QgsPrintLayout,
    QgsLayoutItemMap, QgsLayoutExporter, QgsRectangle, QgsMapSettings, QgsMapRendererCustomPainterJob,
    QgsCoordinateTransform, QgsCoordinateTransformContext, QgsProviderRegistry
)

from .utils.elevation_hex import ( # type: ignore
    format_sampling_summary,
    sample_hex_elevations,
    write_hex_elevation_layer,
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

        # Track per-AOI segmentation settings for persistence across sessions
        self._segment_metadata = {}
        # Track temporary preview layers keyed by AOI metadata key
        self._segment_preview_layers = {}
        # Remember desired POI layer by name until the combo is populated
        self._pending_poi_layer_name = ""
        # Remember DEM/hex selections for the elevation palette controls
        self._pending_hex_dem_layer_name = ""
        self._pending_hex_tile_layer_name = ""

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

        self.opentopo_key_edit = QtWidgets.QLineEdit()
        self.opentopo_key_edit.setEchoMode(QtWidgets.QLineEdit.Password)        

        btn_save_setup = QtWidgets.QPushButton("Save Settings")
        btn_reload_proj = QtWidgets.QPushButton("Reload Settings")
        btn_gen_structure = QtWidgets.QPushButton("Generate Project Structure")

        row_helpers = QtWidgets.QHBoxLayout()
        self.btn_add_opentopo  = QtWidgets.QPushButton("Add OpenTopoMap to Reference")
        self.btn_set_anchor    = QtWidgets.QPushButton("Set Anchor at Canvas Center")
        self.btn_set_crs_utm   = QtWidgets.QPushButton("Set Project CRS from Anchor")
        row_helpers.addWidget(self.btn_add_opentopo)
        row_helpers.addWidget(self.btn_set_anchor)
        row_helpers.addWidget(self.btn_set_crs_utm)

        f1.addRow(btn_reload_proj)
        f1.addRow("Project name:", self.project_name_edit)
        f1.addRow("Author:", self.author_edit)
        f1.addRow("Project directory:", row_out)
        f1.addRow("Styles directory:", row_styles)
        
        # --- Config file UI (default → project override) ---
        self.cfg_path_edit = QtWidgets.QLineEdit()
        self.cfg_path_edit.setReadOnly(True)
        self.cfg_source_label = QtWidgets.QLabel("source: –")

        btn_cfg_browse = QtWidgets.QPushButton("Browse…")
        btn_cfg_default = QtWidgets.QPushButton("Use Default")
        btn_cfg_copy = QtWidgets.QPushButton("Copy Template to Project")

        row_cfg1 = QtWidgets.QHBoxLayout()
        row_cfg1.addWidget(self.cfg_path_edit)
        row_cfg1.addWidget(btn_cfg_browse)

        row_cfg2 = QtWidgets.QHBoxLayout()
        row_cfg2.addWidget(self.cfg_source_label)
        row_cfg2.addStretch(1)
        row_cfg2.addWidget(btn_cfg_default)
        row_cfg2.addWidget(btn_cfg_copy)

        f1.addRow("Config file:", row_cfg1)
        f1.addRow("", row_cfg2)

        btn_cfg_browse.clicked.connect(self.browse_config_and_save)
        btn_cfg_default.clicked.connect(self.use_default_config)
        btn_cfg_copy.clicked.connect(lambda: self.copy_template_to_project(overwrite=False))

        f1.addRow("OpenTopography API key:", self.opentopo_key_edit)
        f1.addRow("Hex scale (m):", self.hex_scale_edit)
        f1.addRow(row_helpers)
        f1.addRow(btn_save_setup, btn_gen_structure)

        btn_save_setup.clicked.connect(self._save_setup_settings)
        btn_reload_proj.clicked.connect(self._load_project_settings)
        btn_gen_structure.clicked.connect(self._generate_project_structure)
        # Setup helper actions
        self.btn_add_opentopo.clicked.connect(self.add_opentopo_basemap)
        self.btn_set_anchor.clicked.connect(self.set_anchor_at_canvas_center)
        self.btn_set_crs_utm.clicked.connect(self.set_project_crs_from_anchor)

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

        # Points of interest source for AOI centroids
        self.cbo_poi_layer = QtWidgets.QComboBox()
        btn_refresh_poi = QtWidgets.QPushButton("Refresh")
        row_poi_combo = QtWidgets.QHBoxLayout()
        row_poi_combo.addWidget(self.cbo_poi_layer)
        row_poi_combo.addWidget(btn_refresh_poi)

        self.btn_create_poi_aois = QtWidgets.QPushButton("Create AOIs from POIs")
        self.btn_create_poi_aois.setEnabled(False)
        row_poi_actions = QtWidgets.QHBoxLayout()
        row_poi_actions.addStretch(1)
        row_poi_actions.addWidget(self.btn_create_poi_aois)

        # buttons row
        row_btns = QtWidgets.QHBoxLayout()
        btn_aoi_from_canvas = QtWidgets.QPushButton("Use Canvas Extent")
        btn_aoi_from_anchor = QtWidgets.QPushButton("Use Anchor as Center")
        row_btns.insertWidget(1, btn_aoi_from_anchor)
        btn_aoi_from_anchor.clicked.connect(self._fill_from_anchor_point)
        self.btn_aoi = QtWidgets.QPushButton("Create AOI")
        row_btns.addWidget(btn_aoi_from_canvas)
        row_btns.addStretch(1)
        row_btns.addWidget(self.btn_aoi)

        f2.addRow("Units:", row_units)
        f2.addRow("Width:", self.width_input)
        f2.addRow("Height:", self.height_input)
        f2.addRow(self.lblWHm)
        f2.addRow(self.lblWHh)
        f2.addRow(self.lblCount)
        f2.addRow("Points of interest:", row_poi_combo)
        f2.addRow("", row_poi_actions)

        # AOI segmentation controls
        self.cboAOI_segment = QtWidgets.QComboBox()
        btn_refresh_aoi_segment = QtWidgets.QPushButton("Refresh")
        row_aoi_segment = QtWidgets.QHBoxLayout()
        row_aoi_segment.addWidget(self.cboAOI_segment)
        row_aoi_segment.addWidget(btn_refresh_aoi_segment)

        self.seg_rows_spin = QtWidgets.QSpinBox()
        self.seg_rows_spin.setRange(1, 25)
        self.seg_rows_spin.setValue(2)
        self.seg_cols_spin = QtWidgets.QSpinBox()
        self.seg_cols_spin.setRange(1, 25)
        self.seg_cols_spin.setValue(2)
        row_seg_dims = QtWidgets.QHBoxLayout()
        row_seg_dims.addWidget(QtWidgets.QLabel("Rows:"))
        row_seg_dims.addWidget(self.seg_rows_spin)
        row_seg_dims.addSpacing(12)
        row_seg_dims.addWidget(QtWidgets.QLabel("Columns:"))
        row_seg_dims.addWidget(self.seg_cols_spin)
        row_seg_dims.addStretch(1)

        self.btn_preview_segments = QtWidgets.QPushButton("Preview Segments")
        self.btn_segment_aoi = QtWidgets.QPushButton("Segment AOI")
        self.btn_clear_segments = QtWidgets.QPushButton("Delete Segments")
        self.btn_preview_segments.setEnabled(False)
        self.btn_segment_aoi.setEnabled(False)
        self.btn_clear_segments.setEnabled(False)
        row_seg_actions = QtWidgets.QHBoxLayout()
        row_seg_actions.addWidget(self.btn_preview_segments)
        row_seg_actions.addWidget(self.btn_segment_aoi)
        row_seg_actions.addWidget(self.btn_clear_segments)
        row_seg_actions.addStretch(1)

        f2.addRow("AOI to segment:", row_aoi_segment)
        f2.addRow("Rows × Columns:", row_seg_dims)
        f2.addRow("", row_seg_actions)

        self.chk_experimental_aoi = QtWidgets.QCheckBox("Allow experimental AOI sizes")
        self.chk_experimental_aoi.setToolTip(
            "Bypass the 99×99 hex guard for large test areas. Expect slower QGIS "
            "renders, heavy shapefiles, and longer export times."
        )
        f2.addRow("", self.chk_experimental_aoi)

        self.lbl_experimental_warning = QtWidgets.QLabel()
        self.lbl_experimental_warning.setWordWrap(True)
        self.lbl_experimental_warning.setStyleSheet("color: rgb(200, 100, 0);")
        self.lbl_experimental_warning.setVisible(False)
        f2.addRow("", self.lbl_experimental_warning)
        f2.addRow(row_btns)
        
        btn_aoi_from_canvas.clicked.connect(self._fill_from_canvas_extent)
        self.btn_aoi.clicked.connect(self.create_aoi)
        btn_refresh_poi.clicked.connect(self._populate_poi_combo)
        self.cbo_poi_layer.currentIndexChanged.connect(self._update_poi_controls)
        self.btn_create_poi_aois.clicked.connect(self.create_aois_from_poi)
        btn_refresh_aoi_segment.clicked.connect(self._populate_aoi_combo)
        self.btn_preview_segments.clicked.connect(self.preview_segments_for_selected_aoi)
        self.btn_segment_aoi.clicked.connect(self.segment_selected_aoi)
        self.btn_clear_segments.clicked.connect(self.clear_segments_for_selected_aoi)
        self.cboAOI_segment.currentIndexChanged.connect(self._update_segment_buttons_state)

        for w in (self.hex_scale_edit, self.width_input, self.height_input):
            w.textChanged.connect(self._recalc_aoi_info)
        self.unit_m.toggled.connect(self._recalc_aoi_info)
        self.chk_experimental_aoi.toggled.connect(self._recalc_aoi_info)

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
        btn_refresh_aoi.clicked.connect(self._populate_aoi_combo)
        btn_build_grid.clicked.connect(self.build_hex_grid)

       # --- 4) SET ELEVATION HEIGHTMAP ---
        pg_elev = QtWidgets.QWidget(); f4 = QtWidgets.QFormLayout(pg_elev)

        # AOI selector for Elevation step (independent from other tabs)
        self.cboAOI_elev = QtWidgets.QComboBox()
        btn_refresh_aoi_elev = QtWidgets.QPushButton("Refresh")
        row_aoi_elev = QtWidgets.QHBoxLayout()
        row_aoi_elev.addWidget(self.cboAOI_elev)
        row_aoi_elev.addWidget(btn_refresh_aoi_elev)
        f4.addRow("AOI for DEM:", row_aoi_elev)

        # DEM source (OpenTopography demtype); default 90 m SRTM (SRTMGL3)
        self.cbo_dem_source = QtWidgets.QComboBox()
        self.cbo_dem_source.addItem("SRTM 90m (SRTMGL3) – recommended", "SRTMGL3")
        self.cbo_dem_source.addItem("SRTM 30m (SRTMGL1)", "SRTMGL1")
        # (Add more later if you like)
        f4.addRow("DEM source:", self.cbo_dem_source)

        btn_fetch_srtm = QtWidgets.QPushButton("Download DEM for AOI (OpenTopography)")
        f4.addRow(btn_fetch_srtm)
        btn_fetch_srtm.clicked.connect(self.download_dem_from_opentopo)

        self.elev_path_edit = QtWidgets.QLineEdit()
        btn_pick_elev = QtWidgets.QPushButton("Browse…")
        def _pick_elev():
            p, _ = QtWidgets.QFileDialog.getOpenFileName(
                self, "Choose DEM (tif)", self.out_dir_edit.text() or "",
                "Rasters (*.tif *.tiff *.img *.vrt);;All files (*.*)"
            )
            if p: self.elev_path_edit.setText(p)
        btn_pick_elev.clicked.connect(_pick_elev)
        row_ep = QtWidgets.QHBoxLayout(); row_ep.addWidget(self.elev_path_edit); row_ep.addWidget(btn_pick_elev)

        self.elev_style_combo = QtWidgets.QComboBox()
        btn_refresh_styles = QtWidgets.QPushButton("Refresh styles")
        btn_apply_elev = QtWidgets.QPushButton("Apply Style to DEM")

        f4.addRow("DEM file:", row_ep)
        f4.addRow("Style:", self.elev_style_combo)
        f4.addRow(btn_refresh_styles, btn_apply_elev)

        grp_hex_palette = QtWidgets.QGroupBox("Hex Elevation Layer")
        hex_form = QtWidgets.QFormLayout(grp_hex_palette)

        self.cbo_hex_dem_layer = QtWidgets.QComboBox()
        self.cbo_hex_tiles_layer = QtWidgets.QComboBox()
        btn_refresh_hex_layers = QtWidgets.QPushButton("Refresh layer lists")

        row_dem_select = QtWidgets.QHBoxLayout()
        row_dem_select.addWidget(self.cbo_hex_dem_layer)
        row_dem_select.addWidget(btn_refresh_hex_layers)

        hex_form.addRow("DEM raster:", row_dem_select)
        hex_form.addRow("Hex layer:", self.cbo_hex_tiles_layer)

        self.cbo_hex_sample_method = QtWidgets.QComboBox()
        self.cbo_hex_sample_method.addItem("Mean (average)", "mean")
        self.cbo_hex_sample_method.addItem("Median", "median")
        self.cbo_hex_sample_method.addItem("Minimum", "min")
        hex_form.addRow("Sampling method:", self.cbo_hex_sample_method)

        self.spin_hex_bucket = QtWidgets.QSpinBox()
        self.spin_hex_bucket.setRange(1, 1000)
        self.spin_hex_bucket.setValue(1)
        hex_form.addRow("Bucket size:", self.spin_hex_bucket)

        self.chk_hex_overwrite = QtWidgets.QCheckBox("Overwrite existing output")
        hex_form.addRow(self.chk_hex_overwrite)

        self.btn_generate_hex_elev = QtWidgets.QPushButton("Generate Hex Elevation Layer")
        self.btn_generate_hex_elev.setEnabled(False)
        hex_form.addRow(self.btn_generate_hex_elev)

        f4.addRow(grp_hex_palette)
        self.tb.addItem(pg_elev, "4. Set Elevation Heightmap")

        # wiring
        btn_refresh_aoi_elev.clicked.connect(self._populate_aoi_combo)
        btn_refresh_aoi_elev.clicked.connect(self._sync_aoi_combo_to_elev)
        btn_refresh_styles.clicked.connect(self._refresh_elevation_styles)
        self._safe_disconnect(btn_apply_elev.clicked, self._apply_elevation_style_and_add)
        self._safe_disconnect(btn_apply_elev.clicked)
        btn_apply_elev.clicked.connect(self._apply_style_to_existing_dem)
        btn_refresh_hex_layers.clicked.connect(self._populate_hex_elevation_inputs)
        self.cbo_hex_dem_layer.currentIndexChanged.connect(self._update_hex_elevation_button_state)
        self.cbo_hex_tiles_layer.currentIndexChanged.connect(self._update_hex_elevation_button_state)
        self.btn_generate_hex_elev.clicked.connect(self.generate_hex_elevation_layer)

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
        # ---- after UI constructed, before log "ready" ----
        proj = QgsProject.instance()

        # Load JSON if project is already open/saved
        self._load_project_settings()

        # Keep JSON in sync with the QGIS project lifecycle
        try:
            proj.readProject.connect(self._on_project_read)       # fired after a project is opened
            proj.projectSaved.connect(self._on_project_saved)     # fired after save/save-as
            proj.cleared.connect(self._on_project_cleared)        # new project or closed
            proj.layersAdded.connect(lambda *_: self._populate_hex_elevation_inputs())
            proj.layersRemoved.connect(lambda *_: self._populate_hex_elevation_inputs())
        except Exception:
            # Older QGIS builds may have slightly different signal names; safe to ignore if missing
            pass

        if hasattr(self, "export_name_edit") and not self.export_name_edit.text().strip():
            self.export_name_edit.setText(proj_name or "hexmosaic_export")
        self._load_project_settings()
        self._populate_poi_combo()
        self._populate_aoi_combo()
        self._populate_hex_elevation_inputs()
        self._refresh_elevation_styles()
        self._sync_export_aoi_combo()
        self._rebuild_export_tree()
        self._recalc_aoi_info() 
        self._load_config()
        self.log("HexMosaic dock ready.")

        QgsProject.instance().readProject.connect(lambda _: self._load_config())
        QgsProject.instance().cleared.connect(lambda: self._load_config())

    # ---- per-project settings (JSON alongside the .qgz) ----

    def _project_file_path(self) -> str:
        """Absolute path to the current QGIS project file, or '' if unsaved."""
        return QgsProject.instance().fileName() or ""

    def _project_dir(self) -> str:
        pf = self._project_file_path()
        return os.path.dirname(pf) if pf else ""

    def _project_settings_path(self) -> str:
        """hexmosaic.project.json alongside the .qgz (if project saved)."""
        d = self._project_dir()
        if not d:
            return ""
        return os.path.join(d, "hexmosaic.project.json")

    def _collect_ui_settings(self) -> dict:
        """Snapshot of UI fields that are project-scoped."""
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
                "metadata": self._segment_metadata,
            },
            "hex_elevation": {
                "dem_layer_name": self.cbo_hex_dem_layer.currentText().strip() if hasattr(self, "cbo_hex_dem_layer") else "",
                "hex_layer_name": self.cbo_hex_tiles_layer.currentText().strip() if hasattr(self, "cbo_hex_tiles_layer") else "",
                "method": self.cbo_hex_sample_method.currentData() if hasattr(self, "cbo_hex_sample_method") else "mean",
                "bucket_size": int(self.spin_hex_bucket.value()) if hasattr(self, "spin_hex_bucket") else 1,
                "overwrite": bool(self.chk_hex_overwrite.isChecked()) if hasattr(self, "chk_hex_overwrite") else False,
            }
        }

    def _apply_ui_settings(self, data: dict):
        """Apply values from dict to the UI, with safe defaults."""
        get = lambda *keys, default="": (
            (lambda d, ks: (d := d) and [d := d.get(k, {}) for k in ks[:-1]] and (d.get(ks[-1], default)))(data, keys)
        )
        self.project_name_edit.setText(get("project", "name", default=""))
        self.author_edit.setText(get("project", "author", default=""))
        self.out_dir_edit.setText(get("paths", "out_dir", default=""))
        self.styles_dir_edit.setText(get("paths", "styles_dir", default=""))
        self.hex_scale_edit.setText(get("grid", "hex_scale_m", default="500"))
        self.opentopo_key_edit.setText(get("opentopo", "api_key", default=""))
        self.chk_experimental_aoi.setChecked(bool(get("aoi", "allow_experimental", default=False)))
        poi_name = get("aoi", "poi_layer_name", default="")
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

        metadata = {}
        if isinstance(seg_data, dict):
            raw_meta = seg_data.get("metadata", {})
            if isinstance(raw_meta, dict):
                for key, entry in raw_meta.items():
                    if not isinstance(entry, dict):
                        continue
                    row_val = entry.get("rows")
                    col_val = entry.get("cols")
                    try:
                        row_int = int(row_val) if row_val is not None else None
                    except (TypeError, ValueError):
                        row_int = None
                    try:
                        col_int = int(col_val) if col_val is not None else None
                    except (TypeError, ValueError):
                        col_int = None
                    meta_entry = {
                        "parent": entry.get("parent"),
                        "rows": row_int,
                        "cols": col_int,
                        "segments": [str(s) for s in entry.get("segments", []) if s is not None],
                    }
                    metadata[str(key)] = meta_entry
        self._segment_metadata = metadata
        self._update_segment_buttons_state()

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
        if isinstance(dem_pending, str):
            self._pending_hex_dem_layer_name = dem_pending
        hex_pending = hex_data.get("hex_layer_name")
        if isinstance(hex_pending, str):
            self._pending_hex_tile_layer_name = hex_pending

    def _save_project_settings(self):
        """Write hexmosaic.project.json next to the .qgz (if project has a path)."""
        p = self._project_settings_path()
        if not p:
            # Project not saved yet; nothing to write to disk.
            return
        try:
            with open(p, "w", encoding="utf-8") as f:
                import json
                json.dump(self._collect_ui_settings(), f, indent=2)
            self.log(f"Saved project settings → {os.path.basename(p)}")
        except Exception as e:
            self.log(f"Could not save project settings: {e}")

    def _load_project_settings(self):
        """Read hexmosaic.project.json if present; apply to UI."""
        p = self._project_settings_path()
        if not p or not os.path.isfile(p):
            # If no JSON yet, fall back to global QSettings you already load.
            return
        try:
            with open(p, "r", encoding="utf-8") as f:
                import json
                data = json.load(f)
            self._apply_ui_settings(data)
            self.log(f"Loaded project settings from {os.path.basename(p)}")
        except Exception as e:
            self.log(f"Could not read project settings: {e}")

    def _on_project_read(self, *args, **kwargs):
        # New project loaded from disk
        self._load_project_settings()
        # If the per-project out_dir was empty, default to the .qgz folder
        if not self.out_dir_edit.text().strip():
            pf = self._project_dir()
            if pf:
                self.out_dir_edit.setText(pf)

    def _on_project_saved(self):
        # Make sure out_dir defaults to the project folder if blank
        if not self.out_dir_edit.text().strip():
            pf = self._project_dir()
            if pf:
                self.out_dir_edit.setText(pf)
        self._save_project_settings()

    def _on_project_cleared(self):
        # Optional: clear project-scoped UI fields for a truly fresh start
        # (we keep global QSettings fallback intact)
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

    # ---------------------------------------------------------------
    # Config helpers

    # --- paths ---
    def _plugin_default_config_path(self) -> str:
        # points to <plugin>/data/hexmosaic.config.json
        plug_dir = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(plug_dir, "data", "hexmosaic.config.json")

    def _project_config_path(self) -> str:
        # <project root>/hexmosaic.config.json
        return os.path.join(self._project_root(), "hexmosaic.config.json")

    # --- resolution order: explicit -> project -> default ---
    def _resolve_config_path(self):
        s = QSettings("HexMosaicOrg", "HexMosaic")
        explicit = s.value("config/path", "", type=str) or ""
        if explicit and os.path.isfile(explicit):
            return explicit, "explicit"

        proj_path = self._project_config_path()
        if os.path.isfile(proj_path):
            return proj_path, "project"

        default_path = self._plugin_default_config_path()
        if os.path.isfile(default_path):
            return default_path, "default"

        return "", "missing"

    # --- load + validate ---
    def _load_config(self):
        path, source = self._resolve_config_path()
        if not path:
            self.cfg = {}
            self.cfg_path = ""
            self.cfg_path_edit.setText("")
            self.cfg_source_label.setText("source: –")
            self.log("Config: no configuration found (missing).")
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception as e:
            self.cfg = {}
            self.cfg_path = ""
            self.cfg_path_edit.setText("")
            self.cfg_source_label.setText("source: error")
            self.log(f"Config: failed to read {path}: {e}")
            return

        if not isinstance(cfg, dict) or "schema_version" not in cfg:
            self.cfg = {}
            self.cfg_path = ""
            self.cfg_path_edit.setText("")
            self.cfg_source_label.setText("source: invalid")
            self.log(f"Config: invalid or missing schema_version in {path}")
            return

        self.cfg = cfg
        self.cfg_path = path
        self.cfg_path_edit.setText(path)
        self.cfg_source_label.setText(f"source: {source}")
        self.log(f"Config loaded from {source}: {path}")

    # --- actions you can wire to buttons in Setup ---
    def browse_config_and_save(self):
        p, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Choose hexmosaic.config.json", self._project_root(),
            "JSON (*.json);;All files (*.*)"
        )
        if not p:
            return
        s = QSettings("HexMosaicOrg", "HexMosaic")
        s.setValue("config/path", p)
        self._load_config()

    def use_default_config(self):
        s = QSettings("HexMosaicOrg", "HexMosaic")
        s.setValue("config/path", "")  # clear explicit
        self._load_config()

    def copy_template_to_project(self, overwrite=False):
        src = self._plugin_default_config_path()
        dst = self._project_config_path()
        try:
            if os.path.exists(dst) and not overwrite:
                self.log(f"Config: file already exists, not overwriting: {dst}")
                return
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copyfile(src, dst)
            self.log(f"Config: template copied to {dst}")
            # optionally point QSettings to the new project copy:
            s = QSettings("HexMosaicOrg", "HexMosaic")
            s.setValue("config/path", dst)
            self._load_config()
        except Exception as e:
            self.log(f"Config: failed to copy template: {e}")

    # ------------------------------------------------


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

    def _safe_disconnect(self, signal, slot=None):
        try:
            if slot is None:
                signal.disconnect()
            else:
                signal.disconnect(slot)
        except (TypeError, RuntimeError):
            # no existing connection (or already cleaned up) — ignore
            pass

    def _project_root(self) -> str:
        """Prefer Setup's Project directory; else the folder of the current .qgz; else home."""
        d = (self.out_dir_edit.text().strip() or _get_setting("paths/out_dir", ""))
        if d and os.path.isdir(d):
            return d
        proj_path = QgsProject.instance().fileName()
        if proj_path:
            return os.path.dirname(proj_path)
        return os.path.expanduser("~")

    def _layers_dir(self) -> str:
        return os.path.join(self._project_root(), "Layers")

    def _export_dir(self) -> str:
        # Capital-E per your spec
        return os.path.join(self._project_root(), "Export")

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
        s.setValue("opentopo/api_key", self.opentopo_key_edit.text())

        self._save_project_settings()

    def _load_setup_settings(self):
        s = QSettings("HexMosaicOrg", "HexMosaic")
        self.out_dir_edit.setText(s.value("paths/out_dir", "", type=str))
        self.styles_dir_edit.setText(s.value("paths/styles_dir", "", type=str))
        self.project_name_edit.setText(s.value("project/name", "", type=str))
        self.author_edit.setText(s.value("project/author", "", type=str))
        self.hex_scale_edit.setText(s.value("grid/hex_scale_m", "500", type=str))
        self.opentopo_key_edit.setText(s.value("opentopo/api_key", "", type=str))

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

    def _generate_project_structure(self):
        """
        Make <Project>/Layers and <Project>/Export.
        Ensure groups exist and order top->bottom:
        Mosaic, OSM, Base, Elevation, Reference.
        Also ensures Base ▸ Base Grid and adds OpenTopoMap once.
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

            self.log(f"Added basemap: {title} → {group_name}")
            return rl
        except Exception as e:
            self.log(f"Error adding basemap '{title}': {e}")
            return None

    def add_opentopo_basemap(self):
        # OpenTopoMap (XYZ), under 'Reference'
        url = "https://a.tile.opentopomap.org/{z}/{x}/{y}.png"
        return self._add_xyz_layer("OpenTopoMap", url, zmin=0, zmax=17, group_name="Reference")

    def _styles_elevation_dir(self) -> str:
        styles_dir = self.styles_dir_edit.text().strip() or _get_setting("paths/styles_dir", "")
        return os.path.join(styles_dir, "elevation") if styles_dir else ""

    def _layers_elevation_dir(self) -> str:
        d = os.path.join(self._layers_dir(), "Elevation")
        os.makedirs(d, exist_ok=True)
        return d

    def _layers_elevation_hex_dir(self) -> str:
        d = os.path.join(self._layers_elevation_dir(), "HexPalette")
        os.makedirs(d, exist_ok=True)
        return d

    def _hex_elevation_output_path(self, base_name: str) -> str:
        safe = self._safe_filename(base_name.replace(" ", "_"))
        return os.path.join(self._layers_elevation_hex_dir(), f"{safe}_hex_elevation.shp")

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

    def _apply_best_elevation_style(self, raster_layer: QgsRasterLayer):
        """
        Apply the best elevation style based on min elevation → base 50.
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
            self.log(f"Applied elevation style: {os.path.basename(chosen)} (min={min_val:.1f} → base={base})")
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
            self.log(f"Hex elevation: sampling failed – {exc}")
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
            self.log(f"Hex elevation: failed to write shapefile – {err}")
            return

        layer_name = f"{base_name} – Hex Elevation"
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

        # AOI
        aoi = self._selected_aoi_layer_for_elev() or self._selected_aoi_layer()
        if not aoi:
            self.log("OpenTopography: Select an AOI first.")
            return

        # AOI extent → WGS84, with a small pad (so coverage survives reprojection)
        pad = 0.01  # ~0.5% bbox pad; tweak if needed
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

        demtype = self.cbo_dem_source.currentData() or "SRTMGL3"

        params = {
            "demtype": demtype,
            "south":   f"{south:.8f}",
            "north":   f"{north:.8f}",
            "west":    f"{west:.8f}",
            "east":    f"{east:.8f}",
            "outputFormat": "GTiff",
            "API_Key": key
        }
        url = "https://portal.opentopography.org/API/globaldem?" + urllib.parse.urlencode(params)

        aoi_name = self._safe_filename(aoi.name())
        out_dir = self._layers_elevation_dir()
        out_src = os.path.join(out_dir, f"{aoi_name}_{demtype}.tif")

        self.log(f"OpenTopography: downloading {demtype}…")
        try:
            _fname, _hdrs = urllib.request.urlretrieve(url, out_src)
        except Exception as e:
            self.log(f"OpenTopography: download failed: {e}")
            return
        if not os.path.exists(out_src) or os.path.getsize(out_src) == 0:
            self.log("OpenTopography: download produced no file.")
            return

        # Reproject to project CRS so it overlays perfectly
        proj_crs = iface.mapCanvas().mapSettings().destinationCrs()
        out_proj = os.path.join(out_dir, f"{aoi_name}_{demtype}_proj.tif")

        try:
            from qgis import processing
            # Build an output bounds in target CRS based on AOI extent (tight crop)
            to_tr = QgsCoordinateTransform(aoi.crs(), proj_crs, QgsProject.instance().transformContext())
            a = aoi.extent()
            llp = to_tr.transform(a.xMinimum(), a.yMinimum())
            urp = to_tr.transform(a.xMaximum(), a.yMaximum())
            xmin, xmax = sorted([llp.x(), urp.x()])
            ymin, ymax = sorted([llp.y(), urp.y()])

            processing.run("gdal:warpreproject", {
                "INPUT": out_src,
                "SOURCE_CRS": QgsCoordinateReferenceSystem("EPSG:4326"),
                "TARGET_CRS": proj_crs,
                "RESAMPLING": 1,  # Bilinear for DEM
                "NODATA": None,
                "TARGET_RESOLUTION": None,  # let GDAL pick; or set e.g. project units per pixel
                "OPTIONS": "",
                "DATA_TYPE": 0,  # keep source
                "TARGET_EXTENT": f"{xmin},{xmax},{ymin},{ymax}",
                "TARGET_EXTENT_CRS": proj_crs.toWkt(),
                "MULTITHREADING": True,
                "EXTRA": "",
                "OUTPUT": out_proj
            })
            use_path = out_proj if os.path.exists(out_proj) else out_src
        except Exception as e:
            self.log(f"Reproject (warp) failed; using source CRS raster. Details: {e}")
            use_path = out_src

        # Add to project (Elevation group), but keep the VIEW at the AOI
        rl = QgsRasterLayer(use_path, os.path.basename(use_path))
        if not rl.isValid():
            self.log("Downloaded DEM but failed to load as raster.")
            return
        proj = QgsProject.instance()
        elev_grp = (proj.layerTreeRoot().findGroup("Elevation") or
                    proj.layerTreeRoot().addGroup("Elevation"))
        proj.addMapLayer(rl, False)
        elev_grp.addLayer(rl)

        # Store path in the field so the style button knows which layer to touch
        self.elev_path_edit.setText(out_dir)

        # Try auto-style first; if it returns a QML, reflect that in the combo
        qml_used = self._apply_best_elevation_style(rl)
        if not qml_used:
            # fall back to current combobox style if available
            qml_path = self.elev_style_combo.currentData()
            if qml_path and os.path.isfile(qml_path):
                ok, _ = rl.loadNamedStyle(qml_path); rl.triggerRepaint()
                if ok:
                    self._select_style_in_combo(qml_path)
                    self.log(f"Applied fallback style: {os.path.basename(qml_path)}")

        # Keep the map on the AOI (avoids zoom-out surprises)
        try:
            iface.mapCanvas().setExtent(aoi.extent())
            iface.mapCanvas().refresh()
        except Exception:
            pass

        self.log(f"OpenTopography: DEM added → {out_dir}")


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
            # reproject feature’s coordinate to WGS84
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

    def _populate_hex_elevation_inputs(self):
        if not hasattr(self, "cbo_hex_dem_layer"):
            return

        rasters = self._gather_raster_layers()
        prev_dem_id = self.cbo_hex_dem_layer.currentData() if self.cbo_hex_dem_layer.count() else ""
        prev_dem_text = self.cbo_hex_dem_layer.currentText() if self.cbo_hex_dem_layer.count() else ""

        self.cbo_hex_dem_layer.blockSignals(True)
        self.cbo_hex_dem_layer.clear()
        for lyr in rasters:
            self.cbo_hex_dem_layer.addItem(lyr.name(), lyr.id())

        matched_dem = False
        if prev_dem_id:
            idx = self.cbo_hex_dem_layer.findData(prev_dem_id)
            if idx >= 0:
                self.cbo_hex_dem_layer.setCurrentIndex(idx)
                matched_dem = True
        if not matched_dem and self._pending_hex_dem_layer_name:
            idx = self.cbo_hex_dem_layer.findText(self._pending_hex_dem_layer_name, Qt.MatchFixedString)
            if idx >= 0:
                self.cbo_hex_dem_layer.setCurrentIndex(idx)
                matched_dem = True
        if not matched_dem and prev_dem_text:
            idx = self.cbo_hex_dem_layer.findText(prev_dem_text, Qt.MatchFixedString)
            if idx >= 0:
                self.cbo_hex_dem_layer.setCurrentIndex(idx)
                matched_dem = True
        if matched_dem:
            self._pending_hex_dem_layer_name = ""
        self.cbo_hex_dem_layer.blockSignals(False)

        hex_layers = self._gather_hex_layers()
        prev_hex_id = self.cbo_hex_tiles_layer.currentData() if self.cbo_hex_tiles_layer.count() else ""
        prev_hex_text = self.cbo_hex_tiles_layer.currentText() if self.cbo_hex_tiles_layer.count() else ""

        self.cbo_hex_tiles_layer.blockSignals(True)
        self.cbo_hex_tiles_layer.clear()
        for lyr in hex_layers:
            self.cbo_hex_tiles_layer.addItem(lyr.name(), lyr.id())

        matched_hex = False
        if prev_hex_id:
            idx = self.cbo_hex_tiles_layer.findData(prev_hex_id)
            if idx >= 0:
                self.cbo_hex_tiles_layer.setCurrentIndex(idx)
                matched_hex = True
        if not matched_hex and self._pending_hex_tile_layer_name:
            idx = self.cbo_hex_tiles_layer.findText(self._pending_hex_tile_layer_name, Qt.MatchFixedString)
            if idx >= 0:
                self.cbo_hex_tiles_layer.setCurrentIndex(idx)
                matched_hex = True
        if not matched_hex and prev_hex_text:
            idx = self.cbo_hex_tiles_layer.findText(prev_hex_text, Qt.MatchFixedString)
            if idx >= 0:
                self.cbo_hex_tiles_layer.setCurrentIndex(idx)
                matched_hex = True
        if matched_hex:
            self._pending_hex_tile_layer_name = ""
        self.cbo_hex_tiles_layer.blockSignals(False)

        self._update_hex_elevation_button_state()

    def _selected_hex_dem_layer(self):
        if not hasattr(self, "cbo_hex_dem_layer"):
            return None
        lyr_id = self.cbo_hex_dem_layer.currentData()
        return QgsProject.instance().mapLayer(lyr_id) if lyr_id else None

    def _selected_hex_tiles_layer(self):
        if not hasattr(self, "cbo_hex_tiles_layer"):
            return None
        lyr_id = self.cbo_hex_tiles_layer.currentData()
        return QgsProject.instance().mapLayer(lyr_id) if lyr_id else None

    def _update_hex_elevation_button_state(self):
        if not hasattr(self, "btn_generate_hex_elev"):
            return
        dem = self._selected_hex_dem_layer()
        tiles = self._selected_hex_tiles_layer()
        self.btn_generate_hex_elev.setEnabled(bool(dem and tiles))

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

    def _selected_aoi_layer_for_segmentation(self):
        if not hasattr(self, "cboAOI_segment"):
            return None
        lyr_id = self.cboAOI_segment.currentData()
        return QgsProject.instance().mapLayer(lyr_id) if lyr_id else None

    def _segment_directory_for_layer(self, layer):
        parent_safe = self._safe_filename(layer.name().replace(" ", "_"))
        return os.path.join(self._layers_dir(), "Base", "Base_Grid", parent_safe, "Segments")

    def _metadata_key_for_layer(self, layer):
        return self._safe_filename(layer.name().replace(" ", "_")).lower()

    def _has_segments_for_layer(self, layer):
        key = self._metadata_key_for_layer(layer)
        meta = self._segment_metadata.get(key, {})
        if meta.get("segments"):
            return True
        seg_dir = self._segment_directory_for_layer(layer)
        if os.path.isdir(seg_dir):
            for name in os.listdir(seg_dir):
                if name.lower().endswith(".shp"):
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

        rows = max(1, int(self.seg_rows_spin.value())) if hasattr(self, "seg_rows_spin") else 1
        cols = max(1, int(self.seg_cols_spin.value())) if hasattr(self, "seg_cols_spin") else 1

        try:
            hex_m = max(1.0, float(self.hex_scale_edit.text()))
        except Exception:
            hex_m = 500.0
            self.hex_scale_edit.setText("500")

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
        mem_layer = QgsVectorLayer(f"MultiPolygon?crs={crs.authid()}", f"{parent_layer.name()} – Segment Preview", "memory")
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
        self.log(f"Previewed {len(features)} segments for {parent_layer.name()}.")

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
            self.log("Select an AOI to segment.")
            return

        rows = max(1, int(self.seg_rows_spin.value())) if hasattr(self, "seg_rows_spin") else 1
        cols = max(1, int(self.seg_cols_spin.value())) if hasattr(self, "seg_cols_spin") else 1

        try:
            hex_m = max(1.0, float(self.hex_scale_edit.text()))
        except Exception:
            hex_m = 500.0
            self.hex_scale_edit.setText("500")

        seg_dir = self._segment_directory_for_layer(parent_layer)
        os.makedirs(seg_dir, exist_ok=True)

        result, err = self._prepare_segment_cells(parent_layer, rows, cols, hex_m)
        if err:
            self.log(err)
            return
        cells = result.get("cells", []) if result else []

        self._remove_segment_preview(parent_layer)
        self._remove_segment_layers(parent_layer)
        shutil.rmtree(seg_dir, ignore_errors=True)
        os.makedirs(seg_dir, exist_ok=True)

        fields = QgsFields()
        fields.append(QgsField("id", QVariant.Int))
        fields.append(QgsField("row", QVariant.Int))
        fields.append(QgsField("col", QVariant.Int))
        fields.append(QgsField("name", QVariant.String, len=80))

        proj = QgsProject.instance()
        group = self._ensure_segments_group(parent_layer)
        created_layers = []
        segment_names = []
        for cell in cells:
            seg_geom = cell["geometry"]
            row_num = cell["row"]
            col_num = cell["col"]
            seg_name = f"{parent_layer.name()} – Segment R{row_num}C{col_num}"
            shp_name = self._safe_filename(f"Segment_{row_num}_{col_num}.shp")
            shp_path = os.path.join(seg_dir, shp_name)
            self._clean_vector_sidecars(shp_path)

            writer = QgsVectorFileWriter(
                shp_path, "UTF-8", fields, QgsWkbTypes.MultiPolygon, parent_layer.crs(), "ESRI Shapefile"
            )
            if writer.hasError() != QgsVectorFileWriter.NoError:
                del writer
                self.log(f"Failed to write segment shapefile: {shp_path}")
                continue

            feat = QgsFeature(fields)
            feat.setAttribute("id", cell["id"])
            feat.setAttribute("row", row_num)
            feat.setAttribute("col", col_num)
            feat.setAttribute("name", seg_name)
            feat.setGeometry(seg_geom)
            writer.addFeature(feat)
            del writer

            seg_layer = QgsVectorLayer(shp_path, seg_name, "ogr")
            if not seg_layer.isValid():
                self.log(f"Segment shapefile saved but failed to load: {shp_path}")
                continue

            styled = self._apply_style(seg_layer, "aoi_segment.qml") or self._apply_style(seg_layer, "aoi.qml")
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
            self.log("No segments were created; the AOI may be too small for the requested grid.")
            shutil.rmtree(seg_dir, ignore_errors=True)
            self._update_segment_buttons_state()
            return

        key = self._metadata_key_for_layer(parent_layer)
        self._segment_metadata[key] = {
            "parent": parent_layer.name(),
            "rows": rows,
            "cols": cols,
            "segments": segment_names,
        }

        self._save_project_settings()
        self._populate_aoi_combo()
        self.log(f"Created {len(created_layers)} segments for {parent_layer.name()} in {rows}×{cols} grid.")

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
        self.lblWHm.setText(f"Width x Height (m): {int(w_m)} × {int(h_m)}")
        self.lblWHh.setText(f"Width x Height (hexes): {w_h} × {h_h}")
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
            display_name += f" – {label_suffix}"

        out_dir = _get_setting("paths/out_dir", "")
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

