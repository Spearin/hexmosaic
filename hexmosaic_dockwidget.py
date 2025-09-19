import os
import shutil

from qgis.PyQt import QtWidgets  # pyright: ignore[reportMissingImports]
from qgis.PyQt.QtCore import Qt, pyqtSignal  # pyright: ignore[reportMissingImports]
from qgis.core import QgsProject, QgsTask, QgsApplication  # pyright: ignore[reportMissingImports]

from .dockwidget.settings_dialog import HexMosaicSettingsDialog, get_persistent_setting
from .dockwidget.paths import ProjectPathsMixin
from .dockwidget.project_state import ProjectStateMixin
from .dockwidget.config import ConfigMixin
from .dockwidget.elevation import ElevationMixin
from .dockwidget.segments import SegmentationMixin
from .dockwidget.exporting import ExportMixin
from .dockwidget.aoi import AoiMixin
from .dockwidget.osm import OsmImportMixin

class HexMosaicDockWidget(QtWidgets.QDockWidget, ProjectPathsMixin, ProjectStateMixin, ConfigMixin, ElevationMixin, SegmentationMixin, ExportMixin, AoiMixin, OsmImportMixin):
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
        btn_out = QtWidgets.QPushButton("Browseâ€¦")
        btn_out.clicked.connect(lambda: self._browse_dir(self.out_dir_edit))
        row_out = QtWidgets.QHBoxLayout(); row_out.addWidget(self.out_dir_edit); row_out.addWidget(btn_out)

        self.styles_dir_edit = QtWidgets.QLineEdit()
        btn_styles = QtWidgets.QPushButton("Browseâ€¦")
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
        
        # --- Config file UI (default â†’ project override) ---
        self.cfg_path_edit = QtWidgets.QLineEdit()
        self.cfg_path_edit.setReadOnly(True)
        self.cfg_source_label = QtWidgets.QLabel("source: â€“")

        btn_cfg_browse = QtWidgets.QPushButton("Browseâ€¦")
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
        self.lblWHm = QtWidgets.QLabel("Width Ã— Height (m): â€“")
        self.lblWHh = QtWidgets.QLabel("Width Ã— Height (hexes): â€“")
        self.lblCount = QtWidgets.QLabel("Total hexes: â€“")

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

        self.seg_mode_tabs = QtWidgets.QTabWidget()

        # Equal grid tab
        tab_equal = QtWidgets.QWidget()
        equal_form = QtWidgets.QFormLayout(tab_equal)

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
        equal_form.addRow("Rows x Columns:", row_seg_dims)
        self.seg_mode_tabs.addTab(tab_equal, "Equal Grid")

        # Map tile grid tab
        tab_tile = QtWidgets.QWidget()
        tile_form = QtWidgets.QFormLayout(tab_tile)

        self.tile_scale_combo = QtWidgets.QComboBox()
        for label, key, width_km in self._map_tile_scale_presets():
            self.tile_scale_combo.addItem(label, key)
        idx_default_scale = self.tile_scale_combo.findData('1:250k')
        if idx_default_scale >= 0:
            self.tile_scale_combo.setCurrentIndex(idx_default_scale)
        tile_form.addRow("Tile scale:", self.tile_scale_combo)

        self.tile_alignment_combo = QtWidgets.QComboBox()
        self.tile_alignment_combo.addItem("Match AOI extent (legacy)", "extent")
        self.tile_alignment_combo.addItem("Snap to MGRS minute grid (15')", "minute")
        self.tile_alignment_combo.addItem("Snap to MGRS degree grid (1Â°)", "degree")
        self.tile_alignment_combo.setCurrentIndex(1)
        tile_form.addRow("Alignment:", self.tile_alignment_combo)

        offset_widget = QtWidgets.QWidget()
        offset_grid = QtWidgets.QGridLayout(offset_widget)
        self.tile_offset_ns_spin = QtWidgets.QDoubleSpinBox()
        self.tile_offset_ns_spin.setRange(-500.0, 500.0)
        self.tile_offset_ns_spin.setDecimals(3)
        self.tile_offset_ns_spin.setSingleStep(0.1)
        self.tile_offset_ew_spin = QtWidgets.QDoubleSpinBox()
        self.tile_offset_ew_spin.setRange(-500.0, 500.0)
        self.tile_offset_ew_spin.setDecimals(3)
        self.tile_offset_ew_spin.setSingleStep(0.1)
        self.tile_offset_unit_combo = QtWidgets.QComboBox()
        self.tile_offset_unit_combo.addItem("Kilometres", "km")
        self.tile_offset_unit_combo.addItem("Arc-minutes", "arcmin")
        offset_grid.addWidget(QtWidgets.QLabel("North/South offset:"), 0, 0)
        offset_grid.addWidget(self.tile_offset_ns_spin, 0, 1)
        offset_grid.addWidget(QtWidgets.QLabel("East/West offset:"), 1, 0)
        offset_grid.addWidget(self.tile_offset_ew_spin, 1, 1)
        offset_grid.addWidget(QtWidgets.QLabel("Units:"), 0, 2)
        offset_grid.addWidget(self.tile_offset_unit_combo, 0, 3, 2, 1)
        tile_form.addRow("Offsets:", offset_widget)

        self.tile_offset_note = QtWidgets.QLabel("Offsets adjust tile origin relative to grid lines; positive values shift north/east.")
        self.tile_offset_note.setWordWrap(True)
        tile_form.addRow("", self.tile_offset_note)

        self.seg_mode_tabs.addTab(tab_tile, "Map Tile Grid")

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
        f2.addRow("Segmentation mode:", self.seg_mode_tabs)
        f2.addRow("", row_seg_actions)

        self.chk_experimental_aoi = QtWidgets.QCheckBox("Allow experimental AOI sizes")
        self.chk_experimental_aoi.setToolTip(
            "Bypass the 99Ã—99 hex guard for large test areas. Expect slower QGIS "
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
        self.seg_mode_tabs.currentChanged.connect(self._update_segment_buttons_state)
        self.tile_alignment_combo.currentIndexChanged.connect(self._update_map_tile_controls_state)
        self.tile_offset_unit_combo.currentIndexChanged.connect(self._update_map_tile_controls_state)
        self.btn_preview_segments.clicked.connect(self.preview_segments_for_selected_aoi)
        self.btn_segment_aoi.clicked.connect(self.segment_selected_aoi)
        self.btn_clear_segments.clicked.connect(self.clear_segments_for_selected_aoi)
        self.cboAOI_segment.currentIndexChanged.connect(self._update_segment_buttons_state)
        self._update_map_tile_controls_state()

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

        # DEM source options (OpenTopography GlobalDEM datasets)
        self.cbo_dem_source = QtWidgets.QComboBox()
        for preset in self._dem_source_presets():
            self.cbo_dem_source.addItem(preset["label"], preset["key"])
        default_idx = self.cbo_dem_source.findData("SRTMGL3")
        if default_idx >= 0:
            self.cbo_dem_source.setCurrentIndex(default_idx)
        f4.addRow("DEM source:", self.cbo_dem_source)

        btn_fetch_dem = QtWidgets.QPushButton("Download DEM for AOI")
        f4.addRow(btn_fetch_dem)
        btn_fetch_dem.clicked.connect(self.download_dem_from_opentopo)

        self.elev_path_edit = QtWidgets.QLineEdit()
        btn_pick_elev = QtWidgets.QPushButton("Browseâ€¦")
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

        # --- 5) IMPORT OSM ---
        pg_osm = QtWidgets.QWidget(); f5 = QtWidgets.QVBoxLayout(pg_osm)
        self._init_osm_ui(f5)
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
        self.lbl_export_px   = QtWidgets.QLabel("Pixels: â€“ Ã— â€“")
        self.lbl_export_page = QtWidgets.QLabel("Page size (mm @ 128 dpi rule): â€“ Ã— â€“")
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
        self._proj_signal_refs = []

        def _connect_project_signal(signal, slot):
            try:
                signal.connect(slot)
                self._proj_signal_refs.append((signal, slot))
            except Exception:
                pass

        self._layers_added_slot = lambda *_: self._populate_hex_elevation_inputs()
        self._layers_removed_slot = lambda *_: self._populate_hex_elevation_inputs()
        self._config_reload_on_read = lambda *_: self._load_config()
        self._config_reload_on_cleared = lambda: self._load_config()

        _connect_project_signal(proj.readProject, self._on_project_read)
        _connect_project_signal(proj.projectSaved, self._on_project_saved)
        _connect_project_signal(proj.cleared, self._on_project_cleared)
        _connect_project_signal(proj.layersAdded, self._layers_added_slot)
        _connect_project_signal(proj.layersRemoved, self._layers_removed_slot)
        _connect_project_signal(proj.readProject, self._config_reload_on_read)
        _connect_project_signal(proj.cleared, self._config_reload_on_cleared)
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

    def _init_osm_ui(self, parent_layout):
        """Create the OSM import UI controls and wire them to OsmImportMixin methods.
        parent_layout is a QLayout (usually the page layout for the OSM toolbox tab).
        """
        # AOI selector row
        row_aoi = QtWidgets.QHBoxLayout()
        row_aoi.addWidget(QtWidgets.QLabel("AOI:"))
        self.cboAOI_osm = QtWidgets.QComboBox()
        btn_refresh_aoi_osm = QtWidgets.QPushButton("Refresh AOIs")
        row_aoi.addWidget(self.cboAOI_osm)
        row_aoi.addWidget(btn_refresh_aoi_osm)
        parent_layout.addLayout(row_aoi)

        # Buffer input
        row_buf = QtWidgets.QHBoxLayout()
        row_buf.addWidget(QtWidgets.QLabel("Buffer (m):"))
        self.spin_osm_buffer = QtWidgets.QSpinBox()
        self.spin_osm_buffer.setRange(0, 100000)
        self.spin_osm_buffer.setValue(1000)
        row_buf.addWidget(self.spin_osm_buffer)
        row_buf.addStretch(1)
        parent_layout.addLayout(row_buf)

        # Theme checklist
        self.osm_theme_checks = {}
        theme_grid = QtWidgets.QGridLayout()
        lookup = self._theme_lookup()
        for i, (key, theme) in enumerate(lookup.items()):
            cb = QtWidgets.QCheckBox(theme.label)
            cb.setChecked(True if key in ("roads", "water", "landcover") else False)
            self.osm_theme_checks[key] = cb
            theme_grid.addWidget(cb, i // 2, i % 2)
        parent_layout.addLayout(theme_grid)

        # Local import row
        local_row = QtWidgets.QHBoxLayout()
        self.osm_local_path_edit = QtWidgets.QLineEdit()
        self.cbo_osm_local_theme = QtWidgets.QComboBox()
        btn_browse_local = QtWidgets.QPushButton("Browse…")
        btn_import_local = QtWidgets.QPushButton("Import Local")
        local_row.addWidget(self.osm_local_path_edit)
        local_row.addWidget(self.cbo_osm_local_theme)
        local_row.addWidget(btn_browse_local)
        local_row.addWidget(btn_import_local)
        parent_layout.addLayout(local_row)

        # Action buttons
        row_actions = QtWidgets.QHBoxLayout()
        self.btn_preview_osm = QtWidgets.QPushButton("Preview")
        self.btn_download_osm = QtWidgets.QPushButton("Download & Save")
        self.btn_refresh_osm = QtWidgets.QPushButton("Refresh Last")
        row_actions.addWidget(self.btn_preview_osm)
        row_actions.addWidget(self.btn_download_osm)
        row_actions.addWidget(self.btn_refresh_osm)
        row_actions.addStretch(1)
        parent_layout.addLayout(row_actions)

        # Wiring
        # Protect against the clicked(bool) signature which would pass a boolean
        # into _sync_aoi_combo_to_osm (causing a TypeError when iterating).
        btn_refresh_aoi_osm.clicked.connect(lambda: self._sync_aoi_combo_to_osm())
        btn_browse_local.clicked.connect(self.browse_osm_local_source)
        btn_import_local.clicked.connect(self.import_osm_from_local)
        self.btn_download_osm.clicked.connect(self.start_osm_download_task)
        self.btn_preview_osm.clicked.connect(lambda: self.log("OSM preview not implemented yet."))
        self.btn_refresh_osm.clicked.connect(self.refresh_osm_layers)

        # Initial population
        self._sync_aoi_combo_to_osm()
        # populate local theme combo
        lookup = self._theme_lookup()
        self.cbo_osm_local_theme.clear()
        for key, theme in lookup.items():
            self.cbo_osm_local_theme.addItem(theme.label, key)


    def start_osm_download_task(self):
        """Gather OSM download parameters and run network fetches in a QgsTask.

        We fetch raw Overpass JSON in the background, then construct layers and write/load gpkg on the main thread.
        """
        aoi_layer = self._selected_aoi_layer_for_osm() or self._selected_aoi_layer()
        if not aoi_layer:
            self.log("OSM import: Select an AOI to clip against.")
            return

        buffer_m = float(self.spin_osm_buffer.value()) if hasattr(self, "spin_osm_buffer") else 1000.0
        selected = [key for key, chk in getattr(self, "osm_theme_checks", {}).items() if chk.isChecked()]
        if not selected:
            self.log("OSM import: Choose at least one theme.")
            return

        try:
            clip_geom, clip_wgs84, target_crs = self._prepare_osm_clip_geometry(aoi_layer, buffer_m)
        except RuntimeError as exc:
            self.log(f"OSM import: {exc}")
            return

        bbox = clip_wgs84.boundingBox()
        bbox_str = f"{bbox.yMinimum():.8f},{bbox.xMinimum():.8f},{bbox.yMaximum():.8f},{bbox.xMaximum():.8f}"

        lookup = self._theme_lookup()
        themes = [lookup.get(k) for k in selected if lookup.get(k)]
        self.log("Starting OSM download task...")
        try:
            self.btn_download_osm.setEnabled(False)
        except Exception:
            pass

        # Define the background task
        parent = self

        class OsmFetchTask(QgsTask):
            def __init__(self, description, themes, bbox):
                super().__init__(description, QgsTask.CanCancel)
                self.themes = themes
                self.bbox = bbox

            def run(self):
                results = {}
                # Collect debug messages in the task (avoid GUI calls from background)
                self._debug = []
                try:
                    self._debug.append(f"OsmFetchTask.run: starting fetch for {len(self.themes)} themes")
                    for theme in self.themes:
                        theme_res = []
                        self._debug.append(f"OsmFetchTask.run: processing theme {theme.key}")
                        for spec in theme.layers:
                            try:
                                elements = parent._fetch_overpass_elements(spec, self.bbox)
                                cnt = len(elements) if elements is not None else 0
                                self._debug.append(f"OsmFetchTask.run: fetched {cnt} elements for {spec.storage_name}")
                            except Exception as e:
                                elements = []
                                self._debug.append(f"OsmFetchTask.run: error fetching {spec.storage_name}: {e}")
                                theme_res.append((spec, None, str(e)))
                                continue
                            theme_res.append((spec, elements, None))
                        results[theme.key] = (theme, theme_res)
                    self._results = results
                    return True
                except Exception as e:
                    self._debug.append(f"OsmFetchTask.run: unexpected exception: {e}")
                    self._results = {}
                    return False

            def finished(self, result):
                try:
                    # Emit any debug messages collected during run
                    for m in getattr(self, "_debug", []):
                        try:
                            parent.log(m)
                        except Exception:
                            pass

                    results = getattr(self, "_results", {})
                    if not results:
                        parent.log("OSM import: No results returned (task failed or empty).")
                        return
                    summary = []
                    for theme_key, (theme, spec_list) in results.items():
                        layers = []
                        total = 0
                        for spec, elements, err in spec_list:
                            if err or not elements:
                                if err:
                                    parent.log(f"OSM import: Error fetching {spec.storage_name}: {err}")
                                continue
                            try:
                                layer = parent._elements_to_layer(spec, elements, clip_geom, target_crs)
                            except Exception as e:
                                parent.log(f"OSM import: Failed to convert elements for {spec.storage_name}: {e}")
                                layer = None
                            if layer and layer.featureCount():
                                layers.append((layer, spec.storage_name))
                                total += layer.featureCount()
                        if layers:
                            gpkg_path = parent._osm_theme_path(theme.key)
                            try:
                                parent._write_theme_to_gpkg(gpkg_path, layers)
                                parent._load_theme_layers(theme, gpkg_path)
                                summary.append(f"{theme.label}: {total}")
                            except Exception as e:
                                parent.log(f"OSM import: Failed to write/load theme {theme.label}: {e}")
                        else:
                            parent._remove_theme_layers_from_project(theme)
                    if summary:
                        parent._osm_last_params = {
                            "aoi_id": aoi_layer.id(),
                            "buffer_m": buffer_m,
                            "themes": selected,
                        }
                        parent.log("OSM import complete -> " + "; ".join(summary))
                    else:
                        parent.log("OSM import finished with no layers created.")
                finally:
                    try:
                        parent.btn_download_osm.setEnabled(True)
                    except Exception:
                        pass

        task = OsmFetchTask("Fetch OSM via Overpass", themes, bbox_str)
        try:
            added = QgsApplication.taskManager().addTask(task)
        except Exception as e:
            added = False
            self.log(f"OSM import: Failed to submit task to task manager: {e}")

        if added:
            self.log("OSM import: Task submitted to QGIS task manager.")
        else:
            # Fallback: run synchronously so the user sees activity rather than nothing.
            self.log("OSM import: Task manager unavailable or rejected task; running fetch synchronously.")
            try:
                ok = task.run()
                task.finished(ok)
            except Exception as e:
                self.log(f"OSM import (fallback): exception during synchronous run: {e}")
                try:
                    self.btn_download_osm.setEnabled(True)
                except Exception:
                    pass


    # ---- per-project settings (JSON alongside the .qgz) ----











    # ---------------------------------------------------------------
    # Config helpers

    # --- paths ---


    # --- resolution order: explicit -> project -> default ---

    # --- load + validate ---

    # --- actions you can wire to buttons in Setup ---

    def browse_config_and_save(self):
        """Open a file dialog to select a config file, update the UI, and try to load it."""
        base = self._project_root() if hasattr(self, "_project_root") else ""
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select config file", base, "Config files (*.yml *.yaml *.json);;All files (*)")
        if not path:
            return
        try:
            # quick validation: ensure the selected file is a JSON with a schema_version
            valid = False
            try:
                import json
                with open(path, "r", encoding="utf-8") as fh:
                    j = json.load(fh)
                if isinstance(j, dict) and "schema_version" in j:
                    valid = True
            except Exception:
                valid = False

            if not valid:
                if hasattr(self, "log"):
                    self.log(f"Selected file does not look like a valid config: {path}")
                return

            # set the path into the readonly line edit
            if hasattr(self, "cfg_path_edit"):
                self.cfg_path_edit.setText(path)
            # update a small label to indicate the source if present
            if hasattr(self, "cfg_source_label"):
                import os
                self.cfg_source_label.setText(f"source: {os.path.basename(path)}")
            # persist as an explicit config selection so ConfigMixin._resolve_config_path
            # will pick this path first on subsequent loads
            try:
                from qgis.PyQt.QtCore import QSettings
                settings = QSettings("HexMosaicOrg", "HexMosaic")
                settings.setValue("config/path", path)
            except Exception:
                # fall back silently if QSettings is unavailable (e.g., tests)
                pass
            # attempt to load the config if the loader exists
            if hasattr(self, "_load_config"):
                try:
                    self._load_config()
                except Exception:
                    # don't raise during UI action; log for debugging
                    if hasattr(self, "log"):
                        self.log(f"Failed to load config from {path}")
        except Exception as exc:
            if hasattr(self, "log"):
                self.log(f"Error selecting config file: {exc}")

    def use_default_config(self):
        """Clear any explicit config selection and reload the default/project config."""
        try:
            from qgis.PyQt.QtCore import QSettings
            settings = QSettings("HexMosaicOrg", "HexMosaic")
            settings.setValue("config/path", "")
        except Exception:
            pass
        if hasattr(self, "_load_config"):
            try:
                self._load_config()
            except Exception:
                if hasattr(self, "log"):
                    self.log("Failed to reload config after resetting to default.")

    def copy_template_to_project(self, overwrite: bool = False):
        """Copy the plugin default config into the current project directory.

        If overwrite is False and a project-local config already exists, do nothing.
        After copying, persist the project-local path as the explicit config and reload.
        """
        try:
            # Resolve source and destination
            plugin_default = self._plugin_default_config_path() if hasattr(self, "_plugin_default_config_path") else None
            if not plugin_default or not os.path.isfile(plugin_default):
                if hasattr(self, "log"):
                    self.log("No plugin default config available to copy.")
                return
            project_root = self._project_root() if hasattr(self, "_project_root") else None
            if not project_root:
                if hasattr(self, "log"):
                    self.log("Project root not set; cannot copy config to project.")
                return
            dest = os.path.join(project_root, "hexmosaic.config.json")
            if os.path.isfile(dest) and not overwrite:
                if hasattr(self, "log"):
                    self.log(f"Project already has a config at {dest}; use overwrite=True to replace.")
                return
            # perform copy
            shutil.copyfile(plugin_default, dest)
            # persist explicit choice
            try:
                from qgis.PyQt.QtCore import QSettings
                settings = QSettings("HexMosaicOrg", "HexMosaic")
                settings.setValue("config/path", dest)
            except Exception:
                pass
            if hasattr(self, "log"):
                self.log(f"Copied default config to project: {os.path.basename(dest)}")
            if hasattr(self, "_load_config"):
                try:
                    self._load_config()
                except Exception:
                    if hasattr(self, "log"):
                        self.log("Failed to load config after copying template to project.")
        except Exception as exc:
            if hasattr(self, "log"):
                self.log(f"Error copying template to project: {exc}")



    # ------------------------------------------------



    def closeEvent(self, event):
        for signal, slot in getattr(self, '_proj_signal_refs', []):
            self._safe_disconnect(signal, slot)
        self._proj_signal_refs = []
        self._layers_added_slot = None
        self._layers_removed_slot = None
        self._config_reload_on_read = None
        self._config_reload_on_cleared = None
        self.closingPlugin.emit()
        event.accept()
    def _safe_disconnect(self, signal, slot=None):
        try:
            if slot is None:
                signal.disconnect()
            else:
                signal.disconnect(slot)
        except (TypeError, RuntimeError):
            # no existing connection (or already cleaned up) â€” ignore
            pass




    def _browse_dir(self, line_edit):
        d = QtWidgets.QFileDialog.getExistingDirectory(self, "Select folder", line_edit.text() or os.path.expanduser("~"))
        if d: line_edit.setText(d)



    def _ellipsize(self, s: str, limit: int = 48) -> str:
        s = s.replace("\n", " ").strip()
        return s if len(s) <= limit else s[:limit - 1] + "â€¦"

    def log(self, msg: str):
        # Ensure the log tab exists
        if not hasattr(self, "log_view"):
            return
        self.log_view.appendPlainText(msg)
        # Update the tab title with the latest line
        title = f"8. Log: {self._ellipsize(msg)}"
        # Qt will trim if too long; thatâ€™s okay
        if hasattr(self, "_log_tab_index"):
            self.tb.setItemText(self._log_tab_index, title)














    


   

    


    

        











































    




    
    

    












    # ---------- logic ----------














