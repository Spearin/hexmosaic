"""Hex Mosaic palette helpers for HexMosaic."""
from __future__ import annotations

import csv
import json
import os
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from qgis.PyQt import QtWidgets
from qgis.PyQt.QtCore import Qt, QVariant
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeature,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
    QgsRectangle,
    QgsSpatialIndex,
    QgsVectorFileWriter,
    QgsVectorLayer,
    QgsWkbTypes,
)


@dataclass
class MosaicClass:
    """Represents a palette class defined in the profile."""

    class_id: str
    target_layer: str
    mode: str  # "polygon" or "line"
    priority: int
    matchers: Sequence[dict]
    line_behavior: Optional[str] = None


class MosaicPaletteMixin:
    """UI and automation helpers for Hex Mosaic palette workflows."""

    _MOSAIC_PROFILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "profiles", "hexmosaic_profile.json")
    _STYLE_CATALOG = os.path.join(os.path.dirname(os.path.dirname(__file__)), "styles", "layer_specs.csv")

    # Defaults used when the profile does not specify extra parameters.
    _DEFAULT_AREA_THRESHOLD = 0.0
    _DEFAULT_LINE_BUFFER_M = 30.0

    _DEFAULT_LINE_STEP_M = 200.0

    _DEFAULT_LAYER_HINTS = {
        "forest": {"polygons": ["landcover_forest", "Landcover - Forest"]},
        "wetland": {"polygons": ["landcover_wetland", "Landcover - Wetlands", "water_polygons", "Water - Polygons"]},
        "fields": {"polygons": ["landcover_fields", "Landcover - Fields"]},
        "vineyards": {"polygons": ["landcover_fields", "Landcover - Fields"]},
        "builtup_commercial_industry": {"polygons": ["landcover_industrial", "Landcover - Industrial"]},
        "builtup_town": {"polygons": ["buildings", "Buildings"]},
        "builtup_highrise": {"polygons": ["buildings", "Buildings"]},
        "builtup_highrise_fcrs": {"polygons": ["buildings", "Buildings"]},
        "water_lake": {"polygons": ["water_polygons", "Water - Polygons"]},
        "water_river": {"polygons": ["water_riverbank", "Water - Riverbanks"]},
        "water_stream_major": {"lines": ["water_major", "Water - Major Rivers"]},
        "water_stream_minor": {"lines": ["water_minor", "Water - Streams"]},
        "road_highway": {"lines": ["roads_highways", "Roads - Highways"]},
        "road_primary": {"lines": ["roads_primary", "Roads - Primary"]},
        "road_secondary": {"lines": ["roads_minor", "Roads - Minor", "roads_tracks", "Roads - Tracks & Paths"]},
        "rail": {"lines": ["rail_lines", "Rail"]},
        "airstrip": {"lines": ["airstrips", "Aeroways"]},
    }




# ------------------------------------------------------------------
# UI initialisation

    def _init_mosaic_ui(self, parent_layout: QtWidgets.QVBoxLayout) -> None:
        self._load_mosaic_profile()
        self._load_style_catalog()
        self._mosaic_updating = False
        self._mosaic_class_state: Dict[str, dict] = {
            cls.class_id: {
                "polygons": set(),
                "lines": set(),
                "area_threshold": self._DEFAULT_AREA_THRESHOLD,
                "line_buffer": self._DEFAULT_LINE_BUFFER_M,
                "line_step": self._DEFAULT_LINE_STEP_M,
            }
            for cls in self._mosaic_classes.values()
        }

        description = QtWidgets.QLabel(
            "Automate Hex Mosaic palette layers from imported OSM data or start fresh "
            "manual layers using the game styles."
        )
        description.setWordWrap(True)
        parent_layout.addWidget(description)

        row_hex = QtWidgets.QHBoxLayout()
        self.cbo_mosaic_hex_layer = QtWidgets.QComboBox()
        self.cbo_mosaic_hex_layer.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToContents)
        btn_refresh = QtWidgets.QPushButton("Refresh Layers")
        row_hex.addWidget(QtWidgets.QLabel("Hex layer:"))
        row_hex.addWidget(self.cbo_mosaic_hex_layer, 1)
        row_hex.addWidget(btn_refresh, 0)
        parent_layout.addLayout(row_hex)

        body_layout = QtWidgets.QHBoxLayout()
        parent_layout.addLayout(body_layout)


        class_container = QtWidgets.QVBoxLayout()
        body_layout.addLayout(class_container, 1)

        self.chk_mosaic_select_all = QtWidgets.QCheckBox('Select All')
        self.chk_mosaic_select_all.setTristate(True)
        self.chk_mosaic_select_all.stateChanged.connect(self._on_select_all_toggled)
        class_container.addWidget(self.chk_mosaic_select_all)

        self.lst_mosaic_classes = QtWidgets.QListWidget()
        self.lst_mosaic_classes.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.lst_mosaic_classes.setAlternatingRowColors(True)
        self.lst_mosaic_classes.itemChanged.connect(self._on_class_check_changed)
        self.lst_mosaic_classes.currentItemChanged.connect(self._on_class_selection_changed)
        class_container.addWidget(self.lst_mosaic_classes, 1)

        self._mosaic_detail_widget = QtWidgets.QWidget()
        detail_layout = QtWidgets.QFormLayout(self._mosaic_detail_widget)
        detail_layout.setFieldGrowthPolicy(QtWidgets.QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        body_layout.addWidget(self._mosaic_detail_widget, 2)

        self.lbl_mosaic_class = QtWidgets.QLabel("�")
        detail_layout.addRow("Class:", self.lbl_mosaic_class)

        self.lbl_mosaic_style = QtWidgets.QLabel("�")
        detail_layout.addRow("Style preset:", self.lbl_mosaic_style)

        self.lst_mosaic_polygons = QtWidgets.QListWidget()
        self.lst_mosaic_polygons.setAlternatingRowColors(True)
        self.lst_mosaic_polygons.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self.lst_mosaic_polygons.itemChanged.connect(self._on_polygon_layer_toggled)
        detail_layout.addRow("Polygon layers:", self.lst_mosaic_polygons)

        self.lst_mosaic_lines = QtWidgets.QListWidget()
        self.lst_mosaic_lines.setAlternatingRowColors(True)
        self.lst_mosaic_lines.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self.lst_mosaic_lines.itemChanged.connect(self._on_line_layer_toggled)
        detail_layout.addRow("Line layers:", self.lst_mosaic_lines)

        self.dsb_mosaic_area_threshold = QtWidgets.QDoubleSpinBox()
        self.dsb_mosaic_area_threshold.setRange(0.0, 1.0)
        self.dsb_mosaic_area_threshold.setDecimals(2)
        self.dsb_mosaic_area_threshold.setSingleStep(0.05)
        self.dsb_mosaic_area_threshold.valueChanged.connect(self._on_area_threshold_changed)
        detail_layout.addRow("Area threshold:", self.dsb_mosaic_area_threshold)

        self.dsb_mosaic_line_buffer = QtWidgets.QDoubleSpinBox()
        self.dsb_mosaic_line_buffer.setRange(0.0, 1000.0)
        self.dsb_mosaic_line_buffer.setSuffix(" m")
        self.dsb_mosaic_line_buffer.setDecimals(1)
        self.dsb_mosaic_line_buffer.setSingleStep(5.0)
        self.dsb_mosaic_line_buffer.valueChanged.connect(self._on_line_buffer_changed)
        detail_layout.addRow("Line buffer:", self.dsb_mosaic_line_buffer)

        self.dsb_mosaic_line_step = QtWidgets.QDoubleSpinBox()
        self.dsb_mosaic_line_step.setRange(1.0, 1000.0)
        self.dsb_mosaic_line_step.setDecimals(1)
        self.dsb_mosaic_line_step.setSingleStep(10.0)
        self.dsb_mosaic_line_step.setSuffix(" m")
        self.dsb_mosaic_line_step.valueChanged.connect(self._on_line_step_changed)
        detail_layout.addRow("Sampling step:", self.dsb_mosaic_line_step)

        row_buttons = QtWidgets.QHBoxLayout()
        self.btn_mosaic_apply_style = QtWidgets.QPushButton("Apply Style to Sources")
        self.btn_mosaic_manual_layer = QtWidgets.QPushButton("Create Manual Layer")
        row_buttons.addWidget(self.btn_mosaic_apply_style)
        row_buttons.addWidget(self.btn_mosaic_manual_layer)
        detail_layout.addRow(row_buttons)

        row_detect = QtWidgets.QHBoxLayout()
        self.btn_mosaic_detect_class = QtWidgets.QPushButton("Detect Class (Hex)")
        self.btn_mosaic_clone_sources = QtWidgets.QPushButton("Clone Sources")
        row_detect.addWidget(self.btn_mosaic_detect_class)
        row_detect.addWidget(self.btn_mosaic_clone_sources)
        detail_layout.addRow(row_detect)

        parent_layout.addSpacing(12)
        bottom_row = QtWidgets.QHBoxLayout()
        parent_layout.addLayout(bottom_row)
        self.btn_mosaic_run_selected = QtWidgets.QPushButton("Generate Selected Classes")
        self.btn_mosaic_run_all = QtWidgets.QPushButton("Generate All Classes")
        bottom_row.addWidget(self.btn_mosaic_run_selected)
        bottom_row.addWidget(self.btn_mosaic_run_all)
        bottom_row.addStretch(1)

        parent_layout.addStretch(1)

        btn_refresh.clicked.connect(self._populate_mosaic_inputs)
        self.btn_mosaic_apply_style.clicked.connect(self._apply_style_to_selected_sources)
        self.btn_mosaic_manual_layer.clicked.connect(self._create_manual_layer)
        self.btn_mosaic_detect_class.clicked.connect(self._detect_current_class)
        self.btn_mosaic_clone_sources.clicked.connect(self._clone_selected_sources)
        self.btn_mosaic_run_selected.clicked.connect(lambda: self._run_mosaic_automation(checked_only=True))
        self.btn_mosaic_run_all.clicked.connect(lambda: self._run_mosaic_automation(checked_only=False))

        self._populate_mosaic_inputs()
        if self.lst_mosaic_classes.count():
            self.lst_mosaic_classes.setCurrentRow(0)

    # ------------------------------------------------------------------
    # Profile & style loading

    def _load_mosaic_profile(self) -> None:
        if hasattr(self, "_mosaic_classes"):
            return
        try:
            with open(self._MOSAIC_PROFILE, "r", encoding="utf-8") as handle:
                profile = json.load(handle)
        except Exception as exc:
            self.log(f"Mosaic: failed to read profile -> {exc}")
            profile = {}
        classes = {}
        for entry in profile.get("classes", []):
            class_id = entry.get("id")
            target = entry.get("target_layer")
            priority = entry.get("priority", 0)
            if not class_id or not target:
                continue
            mode = "polygon" if entry.get("fill") else "line" if entry.get("line") else "polygon"
            line_behavior = entry.get("line")
            classes[class_id] = MosaicClass(
                class_id=class_id,
                target_layer=target,
                mode=mode,
                priority=priority,
                matchers=entry.get("match", []),
                line_behavior=line_behavior,
            )
        self._mosaic_classes: Dict[str, MosaicClass] = classes

    def _load_style_catalog(self) -> None:
        if hasattr(self, "_style_catalog"):
            return
        catalog: Dict[str, Tuple[str, str]] = {}
        if os.path.isfile(self._STYLE_CATALOG):
            try:
                with open(self._STYLE_CATALOG, newline="", encoding="utf-8") as handle:
                    reader = csv.DictReader(handle)
                    for row in reader:
                        name = (row.get("name") or "").strip()
                        qml = (row.get("FC Southern Storm style") or "").strip()
                        geometry = (row.get("type") or "").strip().lower()
                        if name and qml:
                            catalog[name] = (geometry, qml)
            except Exception as exc:
                self.log(f"Mosaic: could not read style catalog -> {exc}")
        self._style_catalog = catalog

    # ------------------------------------------------------------------

    # UI state helpers

    def _class_state(self, class_id: str) -> dict:
        state = self._mosaic_class_state.setdefault(
            class_id,
            {
                "polygons": set(),
                "lines": set(),
                "area_threshold": self._DEFAULT_AREA_THRESHOLD,
                "line_buffer": self._DEFAULT_LINE_BUFFER_M,
                "line_step": self._DEFAULT_LINE_STEP_M,
            },
        )
        self._ensure_id_set(state, "polygons")
        self._ensure_id_set(state, "lines")
        return state

    def _ensure_id_set(self, state: dict, key: str) -> Set[str]:
        value = state.get(key)
        if isinstance(value, set):
            return value
        if not value:
            value = set()
        else:
            value = {str(v) for v in value}
        state[key] = value
        return value

    def _prime_default_sources(self, vector_layers: Sequence[QgsVectorLayer]) -> None:
        for class_id, cls in self._mosaic_classes.items():
            state = self._class_state(class_id)
            self._prune_missing_sources(state, vector_layers)
            self._apply_default_source_hints(cls, state, vector_layers)

    def _prune_missing_sources(self, state: dict, vector_layers: Sequence[QgsVectorLayer]) -> None:
        existing_ids = {layer.id() for layer in vector_layers}
        self._ensure_id_set(state, "polygons").intersection_update(existing_ids)
        self._ensure_id_set(state, "lines").intersection_update(existing_ids)

    def _apply_default_source_hints(
        self,
        cls: MosaicClass,
        state: dict,
        vector_layers: Sequence[QgsVectorLayer],
    ) -> None:
        hints = self._DEFAULT_LAYER_HINTS.get(cls.class_id)
        if not hints:
            return
        polygons = self._ensure_id_set(state, "polygons")
        if cls.mode == "polygon" and not polygons:
            polygon_hints = hints.get("polygons", [])
            for layer in vector_layers:
                if any(self._layer_matches_hint(layer, hint) for hint in polygon_hints):
                    polygons.add(layer.id())
        lines = self._ensure_id_set(state, "lines")
        if cls.mode == "line" and not lines:
            line_hints = hints.get("lines", [])
            for layer in vector_layers:
                if any(self._layer_matches_hint(layer, hint) for hint in line_hints):
                    lines.add(layer.id())

    def _layer_matches_hint(self, layer: QgsVectorLayer, hint: str) -> bool:
        hint_lower = hint.lower()
        name = layer.name().lower()
        if hint_lower in name:
            return True
        provider = layer.dataProvider()
        source = provider.dataSourceUri() if provider else ""
        return hint_lower in source.lower()

    def _update_select_all_checkbox(self) -> None:
        if not hasattr(self, "chk_mosaic_select_all"):
            return
        total = self.lst_mosaic_classes.count()
        checked = 0
        for i in range(total):
            if self.lst_mosaic_classes.item(i).checkState() == Qt.Checked:
                checked += 1
        self.chk_mosaic_select_all.blockSignals(True)
        try:
            if total == 0:
                self.chk_mosaic_select_all.setCheckState(Qt.Unchecked)
            elif checked == 0:
                self.chk_mosaic_select_all.setCheckState(Qt.Unchecked)
            elif checked == total:
                self.chk_mosaic_select_all.setCheckState(Qt.Checked)
            else:
                self.chk_mosaic_select_all.setCheckState(Qt.PartiallyChecked)
        finally:
            self.chk_mosaic_select_all.blockSignals(False)

    def _on_select_all_toggled(self, state: int) -> None:
        if self._mosaic_updating:
            return
        if state == Qt.PartiallyChecked:
            return
        self._mosaic_updating = True
        try:
            target_state = Qt.Checked if state == Qt.Checked else Qt.Unchecked
            for i in range(self.lst_mosaic_classes.count()):
                item = self.lst_mosaic_classes.item(i)
                item.setCheckState(target_state)
        finally:
            self._mosaic_updating = False
            self._update_select_all_checkbox()
        self._sync_detail_panel()

    def _populate_mosaic_inputs(self) -> None:
        self._mosaic_updating = True
        try:
            self.cbo_mosaic_hex_layer.blockSignals(True)
            current_hex = self.cbo_mosaic_hex_layer.currentData()
            self.cbo_mosaic_hex_layer.clear()
            vector_layers = [
                lyr
                for lyr in QgsProject.instance().mapLayers().values()
                if isinstance(lyr, QgsVectorLayer)
            ]
            self._prime_default_sources(vector_layers)
            for layer in vector_layers:
                if QgsWkbTypes.geometryType(layer.wkbType()) == QgsWkbTypes.PolygonGeometry:
                    self.cbo_mosaic_hex_layer.addItem(layer.name(), layer.id())
            if current_hex:
                idx = self.cbo_mosaic_hex_layer.findData(current_hex)
                if idx >= 0:
                    self.cbo_mosaic_hex_layer.setCurrentIndex(idx)
            self.cbo_mosaic_hex_layer.blockSignals(False)

            self.lst_mosaic_classes.blockSignals(True)
            self.lst_mosaic_classes.clear()
            for cls in self._mosaic_classes.values():
                state = self._class_state(cls.class_id)
                item = QtWidgets.QListWidgetItem(f"{cls.class_id}  ?  {cls.target_layer}")
                item.setData(Qt.UserRole, cls.class_id)
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable | Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                item.setCheckState(Qt.Checked if cls.class_id in self._mosaic_class_state else Qt.Unchecked)
                self.lst_mosaic_classes.addItem(item)
            self.lst_mosaic_classes.blockSignals(False)
            self._update_select_all_checkbox()

            self._populate_source_lists()
        finally:
            self._mosaic_updating = False
            if self.lst_mosaic_classes.count() and not self.lst_mosaic_classes.currentItem():
                self.lst_mosaic_classes.setCurrentRow(0)
            else:
                self._sync_detail_panel()

    def _populate_source_lists(self) -> None:
        current_class = self._current_class_id()
        vector_layers = [
            lyr
            for lyr in QgsProject.instance().mapLayers().values()
            if isinstance(lyr, QgsVectorLayer)
        ]
        state = None
        cls = self._mosaic_classes.get(current_class) if current_class else None
        if cls:
            state = self._class_state(current_class)
            self._prune_missing_sources(state, vector_layers)
            self._apply_default_source_hints(cls, state, vector_layers)
        selected_polys: Set[str] = set()
        selected_lines: Set[str] = set()
        if state:
            selected_polys = set(self._ensure_id_set(state, "polygons"))
            selected_lines = set(self._ensure_id_set(state, "lines"))

        self._mosaic_updating = True
        try:
            self.lst_mosaic_polygons.blockSignals(True)
            self.lst_mosaic_polygons.clear()
            for layer in vector_layers:
                if QgsWkbTypes.geometryType(layer.wkbType()) != QgsWkbTypes.PolygonGeometry:
                    continue
                item = QtWidgets.QListWidgetItem(layer.name())
                item.setData(Qt.UserRole, layer.id())
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Checked if layer.id() in selected_polys else Qt.Unchecked)
                self.lst_mosaic_polygons.addItem(item)
            self.lst_mosaic_polygons.blockSignals(False)

            self.lst_mosaic_lines.blockSignals(True)
            self.lst_mosaic_lines.clear()
            for layer in vector_layers:
                if QgsWkbTypes.geometryType(layer.wkbType()) != QgsWkbTypes.LineGeometry:
                    continue
                item = QtWidgets.QListWidgetItem(layer.name())
                item.setData(Qt.UserRole, layer.id())
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Checked if layer.id() in selected_lines else Qt.Unchecked)
                self.lst_mosaic_lines.addItem(item)
            self.lst_mosaic_lines.blockSignals(False)
        finally:
            self._mosaic_updating = False
            self._sync_detail_panel()
    def _on_class_check_changed(self, item: QtWidgets.QListWidgetItem) -> None:
        if self._mosaic_updating:
            return
        class_id = item.data(Qt.UserRole)
        if not class_id:
            return
        if item.checkState() == Qt.Checked:
            self._class_state(class_id)
        else:
            state = self._mosaic_class_state.get(class_id)
            if state:
                self._ensure_id_set(state, "polygons").clear()
                self._ensure_id_set(state, "lines").clear()
        self._update_select_all_checkbox()
        self._sync_detail_panel()

    def _on_class_selection_changed(self, current: QtWidgets.QListWidgetItem, _previous: QtWidgets.QListWidgetItem) -> None:
        if self._mosaic_updating:
            return
        self._populate_source_lists()

    def _on_polygon_layer_toggled(self, item: QtWidgets.QListWidgetItem) -> None:
        if self._mosaic_updating:
            return
        class_id = self._current_class_id()
        if not class_id:
            return
        state = self._class_state(class_id)
        polygons = self._ensure_id_set(state, "polygons")
        layer_id = item.data(Qt.UserRole)
        if item.checkState() == Qt.Checked:
            polygons.add(layer_id)
        else:
            polygons.discard(layer_id)

    def _on_line_layer_toggled(self, item: QtWidgets.QListWidgetItem) -> None:
        if self._mosaic_updating:
            return
        class_id = self._current_class_id()
        if not class_id:
            return
        state = self._class_state(class_id)
        lines = self._ensure_id_set(state, "lines")
        layer_id = item.data(Qt.UserRole)
        if item.checkState() == Qt.Checked:
            lines.add(layer_id)
        else:
            lines.discard(layer_id)

    def _on_area_threshold_changed(self, value: float) -> None:
        if self._mosaic_updating:
            return
        class_id = self._current_class_id()
        if not class_id:
            return
        state = self._class_state(class_id)
        state["area_threshold"] = float(value)

    def _on_line_buffer_changed(self, value: float) -> None:
        if self._mosaic_updating:
            return
        class_id = self._current_class_id()
        if not class_id:
            return
        state = self._class_state(class_id)
        state["line_buffer"] = float(value)

    def _on_line_step_changed(self, value: float) -> None:
        if self._mosaic_updating:
            return
        class_id = self._current_class_id()
        if not class_id:
            return
        state = self._class_state(class_id)
        state["line_step"] = float(value)

    def _sync_detail_panel(self) -> None:
        class_id = self._current_class_id()
        cls = self._mosaic_classes.get(class_id) if class_id else None
        state = self._class_state(class_id) if cls else None
        if not cls or state is None:
            self.lbl_mosaic_class.setText("???")
            self.lbl_mosaic_style.setText("???")
            for widget in (
                self.lst_mosaic_polygons,
                self.lst_mosaic_lines,
                self.dsb_mosaic_area_threshold,
                self.dsb_mosaic_line_buffer,
                self.dsb_mosaic_line_step,
                self.btn_mosaic_apply_style,
                self.btn_mosaic_manual_layer,
                self.btn_mosaic_detect_class,
                self.btn_mosaic_clone_sources,
            ):
                widget.setEnabled(False)
            return

        style_entry = self._style_catalog.get(cls.target_layer)
        style_text = style_entry[1] if style_entry else "(no preset)"
        self.lbl_mosaic_class.setText(f"{cls.class_id} ({cls.mode})")
        self.lbl_mosaic_style.setText(style_text)

        self._mosaic_updating = True
        try:
            self.dsb_mosaic_area_threshold.setValue(float(state.get("area_threshold", self._DEFAULT_AREA_THRESHOLD)))
            self.dsb_mosaic_line_buffer.setValue(float(state.get("line_buffer", self._DEFAULT_LINE_BUFFER_M)))
            self.dsb_mosaic_line_step.setValue(float(state.get("line_step", self._DEFAULT_LINE_STEP_M)))
        finally:
            self._mosaic_updating = False

        polygons_enabled = cls.mode == "polygon"
        lines_enabled = cls.mode == "line"
        polygons = self._ensure_id_set(state, "polygons")
        lines = self._ensure_id_set(state, "lines")

        self.lst_mosaic_polygons.setEnabled(polygons_enabled)
        self.dsb_mosaic_area_threshold.setEnabled(False)
        self.dsb_mosaic_area_threshold.setValue(0.0)

        self.lst_mosaic_lines.setEnabled(lines_enabled)
        self.dsb_mosaic_line_buffer.setEnabled(lines_enabled)
        self.dsb_mosaic_line_step.setEnabled(lines_enabled)
        self.btn_mosaic_apply_style.setEnabled(bool(style_entry))
        self.btn_mosaic_manual_layer.setEnabled(True)

        has_sources = (polygons_enabled and bool(polygons)) or (lines_enabled and bool(lines))
        self.btn_mosaic_detect_class.setEnabled(has_sources)
        self.btn_mosaic_clone_sources.setEnabled(has_sources)

    def _current_class_id(self) -> Optional[str]:
        item = self.lst_mosaic_classes.currentItem()
        return item.data(Qt.UserRole) if item else None

    # ------------------------------------------------------------------
    # Actions


    def _apply_style_to_selected_sources(self) -> None:
        class_id = self._current_class_id()
        if not class_id:
            self.log("Mosaic: select a class before applying styles.")
            return
        cls = self._mosaic_classes.get(class_id)
        if not cls:
            return
        style_entry = self._style_catalog.get(cls.target_layer)
        if not style_entry:
            self.log(f"Mosaic: no style preset registered for {cls.target_layer}.")
            return
        qml_path = style_entry[1]
        state = self._class_state(class_id)
        sources = (
            self._ensure_id_set(state, "polygons")
            if cls.mode == "polygon"
            else self._ensure_id_set(state, "lines")
        )
        if not sources:
            self.log("Mosaic: choose source layers first.")
            return
        count = 0
        for layer_id in sources:
            layer = QgsProject.instance().mapLayer(layer_id)
            if isinstance(layer, QgsVectorLayer) and self._apply_style(layer, qml_path):
                count += 1
        self.log(f"Mosaic: applied style '{qml_path}' to {count} source layer(s).")

    def _create_manual_layer(self) -> None:
        class_id = self._current_class_id()
        hex_layer = self._resolve_hex_layer()
        if not class_id or hex_layer is None:
            self.log("Mosaic: choose a class and hex layer first.")
            return
        cls = self._mosaic_classes[class_id]
        output_name = f"{hex_layer.name().split('(')[0].strip()}_{cls.target_layer}_manual"
        shp_path = self._mosaic_output_path(output_name)
        crs = hex_layer.crs()
        if cls.mode == "polygon":
            mem = QgsVectorLayer(f"Polygon?crs={crs.authid()}", output_name, "memory")
            provider = mem.dataProvider()
            provider.addAttributes(list(hex_layer.fields()))
            provider.addAttributes([QgsField("class_id", QVariant.String)])
            mem.updateFields()
        else:
            mem = QgsVectorLayer(f"LineString?crs={crs.authid()}", output_name, "memory")
            provider = mem.dataProvider()
            provider.addAttributes([
                QgsField("class_id", QVariant.String),
                QgsField("source", QVariant.String),
            ])
            mem.updateFields()
        try:
            self._write_vector_to_shp(mem, shp_path)
        except RuntimeError as exc:
            self.log(f"Mosaic: {exc}")
            return
        layer = QgsVectorLayer(shp_path, output_name, "ogr")
        if not layer.isValid():
            self.log("Mosaic: failed to load manual layer from disk.")
            return
        self._finalize_output_layer(layer, hex_layer, cls)
        self.log(
            f"Mosaic: created manual layer at {os.path.relpath(shp_path, self._project_root()) if self._project_root() else shp_path}."
        )

    def _detect_current_class(self) -> None:
        class_id = self._current_class_id()
        if not class_id:
            self.log("Mosaic: choose a class first.")
            return
        cls = self._mosaic_classes.get(class_id)
        if not cls:
            return
        hex_layer = self._resolve_hex_layer()
        if hex_layer is None:
            self.log("Mosaic: choose a Hex Tiles layer first.")
            return
        vector_layers = [
            lyr
            for lyr in QgsProject.instance().mapLayers().values()
            if isinstance(lyr, QgsVectorLayer)
        ]
        state = self._class_state(class_id)
        self._prune_missing_sources(state, vector_layers)
        self._apply_default_source_hints(cls, state, vector_layers)
        cache = _HexCache(hex_layer)
        if cls.mode == "polygon":
            self._generate_polygon_class(hex_layer, cache, cls, state)
        else:
            self._generate_line_class(hex_layer, cache, cls, state)

    def _clone_selected_sources(self) -> None:
        class_id = self._current_class_id()
        if not class_id:
            self.log("Mosaic: choose a class first.")
            return
        cls = self._mosaic_classes.get(class_id)
        if not cls:
            return
        hex_layer = self._resolve_hex_layer()
        if hex_layer is None:
            self.log("Mosaic: choose a Hex Tiles layer first.")
            return
        target_crs = hex_layer.crs()
        transform_context = QgsProject.instance().transformContext()
        vector_layers = [
            lyr
            for lyr in QgsProject.instance().mapLayers().values()
            if isinstance(lyr, QgsVectorLayer)
        ]
        state = self._class_state(class_id)
        self._prune_missing_sources(state, vector_layers)
        self._apply_default_source_hints(cls, state, vector_layers)
        if cls.mode == "polygon":
            source_layers = self._resolve_layers(self._ensure_id_set(state, "polygons"), QgsWkbTypes.PolygonGeometry)
            geometry_template = "Polygon"
            expected_type = QgsWkbTypes.PolygonGeometry
        else:
            source_layers = self._resolve_layers(self._ensure_id_set(state, "lines"), QgsWkbTypes.LineGeometry)
            geometry_template = "LineString"
            expected_type = QgsWkbTypes.LineGeometry
        if not source_layers:
            self.log(f"Mosaic: class '{cls.class_id}' skipped (no {cls.mode} sources selected).")
            return
        base_label = hex_layer.name().split('(')[0].strip()
        output_name = f"{base_label}_{cls.target_layer}_clone".strip("_")
        mem = QgsVectorLayer(f"{geometry_template}?crs={target_crs.authid()}", output_name, "memory")
        provider = mem.dataProvider()
        provider.addAttributes([
            QgsField("class_id", QVariant.String),
            QgsField("source_layer", QVariant.String),
        ])
        mem.updateFields()
        fields = mem.fields()
        total = 0
        for layer in source_layers:
            transformer = None
            if layer.crs() != target_crs:
                transformer = QgsCoordinateTransform(layer.crs(), target_crs, transform_context)
            for feature in layer.getFeatures():
                geom = feature.geometry()
                if geom is None or geom.isEmpty():
                    continue
                geom = QgsGeometry(geom)
                try:
                    if transformer:
                        geom.transform(transformer)
                except Exception:
                    continue
                geom = geom.makeValid()
                if geom.isEmpty() or QgsWkbTypes.geometryType(geom.wkbType()) != expected_type:
                    continue
                new_feat = QgsFeature(fields)
                new_feat.setGeometry(geom)
                new_feat.setAttributes([
                    cls.class_id,
                    layer.name(),
                ])
                provider.addFeature(new_feat)
                total += 1
        if total == 0:
            self.log(f"Mosaic: class '{cls.class_id}' -> no features cloned from selected sources.")
            return
        mem.updateExtents()
        shp_path = self._mosaic_output_path(output_name)
        try:
            self._write_vector_to_shp(mem, shp_path)
        except RuntimeError as exc:
            self.log(f"Mosaic: {exc}")
            return
        layer = QgsVectorLayer(shp_path, output_name, "ogr")
        if not layer.isValid():
            self.log("Mosaic: failed to load cloned layer from disk.")
            return
        self._finalize_output_layer(layer, hex_layer, cls)
        rel = os.path.relpath(shp_path, self._project_root()) if self._project_root() else shp_path
        self.log(f"Mosaic: cloned {total} feature(s) for {cls.class_id}, saved to {rel}.")

    def _run_mosaic_automation(self, checked_only: bool) -> None:
        hex_layer = self._resolve_hex_layer()
        if hex_layer is None:
            self.log("Mosaic: choose a Hex Tiles layer first.")
            return
        selected_class_ids: List[str] = []
        for i in range(self.lst_mosaic_classes.count()):
            item = self.lst_mosaic_classes.item(i)
            class_id = item.data(Qt.UserRole)
            if not class_id:
                continue
            if not checked_only or item.checkState() == Qt.Checked:
                selected_class_ids.append(class_id)
        if not selected_class_ids:
            self.log("Mosaic: no classes selected for automation.")
            return

        vector_layers = [
            lyr
            for lyr in QgsProject.instance().mapLayers().values()
            if isinstance(lyr, QgsVectorLayer)
        ]
        self._prime_default_sources(vector_layers)
        cache = _HexCache(hex_layer)
        results = []
        for class_id in selected_class_ids:
            cls = self._mosaic_classes.get(class_id)
            if not cls:
                continue
            state = self._class_state(class_id)
            self._prune_missing_sources(state, vector_layers)
            self._apply_default_source_hints(cls, state, vector_layers)
            if cls.mode == "polygon":
                output = self._generate_polygon_class(hex_layer, cache, cls, state)
            else:
                output = self._generate_line_class(hex_layer, cache, cls, state)
            if output:
                results.append(output)
        if not results:
            self.log("Mosaic: no layers generated. Check source selections.")
            return
        self.log(f"Mosaic: generated {len(results)} layer(s).")

    # ------------------------------------------------------------------
    # Automation helpers

    def _generate_polygon_class(self, hex_layer: QgsVectorLayer, cache: "_HexCache", cls: MosaicClass, state: dict):
        polygon_layers = self._resolve_layers(state.get("polygons", set()), QgsWkbTypes.PolygonGeometry)
        if not polygon_layers:
            self.log(f"Mosaic: class '{cls.class_id}' skipped (no polygon sources selected).")
            return None
        sources = self._prepare_polygon_sources(polygon_layers, hex_layer.crs())
        if not sources:
            self.log(f"Mosaic: class '{cls.class_id}' has no usable polygon geometries after reprojection.")
            return None

        mem = QgsVectorLayer(f"Polygon?crs={hex_layer.crs().authid()}", cls.target_layer, "memory")
        provider = mem.dataProvider()
        provider.addAttributes(list(hex_layer.fields()))
        provider.addAttributes([
            QgsField("class_id", QVariant.String),
            QgsField("coverage", QVariant.Double, len=10, prec=4),
            QgsField("source_layers", QVariant.String),
        ])
        mem.updateFields()
        fields = mem.fields()
        total = 0

        for feature in cache.features:
            geom = cache.geometries[feature.id()]
            if geom.isEmpty():
                continue
            area = geom.area()
            if area <= 0:
                continue
            centroid = cache.centroids.get(feature.id())
            centroid_hit = False
            if centroid is not None:
                centroid_hit = self._centroid_hits_sources(centroid, sources)
            bbox = geom.boundingBox()
            coverage = self._polygon_overlap_area(geom, bbox, sources)
            ratio = min(1.0, coverage / area) if area else 0.0
            if not centroid_hit and coverage <= 0.0:
                continue
            new_attrs = list(feature.attributes())
            new_attrs.extend([
                cls.class_id,
                round(ratio, 4),
                ";".join(sorted(layer.name() for layer in polygon_layers)),
            ])
            out_feat = QgsFeature(fields)
            out_feat.setGeometry(geom)
            out_feat.setAttributes(new_attrs)
            provider.addFeature(out_feat)
            total += 1

        if total == 0:
            self.log(f"Mosaic: class '{cls.class_id}' -> no tiles intersect selected sources.")
            return None

        base_label = hex_layer.name().split("(")[0].strip()
        output_name = f"{base_label}_{cls.target_layer}".strip("_")
        shp_path = self._mosaic_output_path(output_name)
        try:
            self._write_vector_to_shp(mem, shp_path)
        except RuntimeError as exc:
            self.log(f"Mosaic: {exc}")
            return None
        layer = QgsVectorLayer(shp_path, output_name, "ogr")
        if not layer.isValid():
            self.log(f"Mosaic: failed to load polygon layer for {cls.class_id}.")
            return None
        self._finalize_output_layer(layer, hex_layer, cls)
        self.log(
            f"Mosaic: {cls.class_id} -> {total} tiles, saved to {os.path.relpath(shp_path, self._project_root()) if self._project_root() else shp_path}."
        )
        return layer

    def _generate_line_class(self, hex_layer: QgsVectorLayer, cache: "_HexCache", cls: MosaicClass, state: dict):
        line_layers = self._resolve_layers(state.get("lines", set()), QgsWkbTypes.LineGeometry)
        if not line_layers:
            self.log(f"Mosaic: class '{cls.class_id}' skipped (no line sources selected).")
            return None
        buffer_dist = float(state.get("line_buffer", self._DEFAULT_LINE_BUFFER_M))
        step_dist = float(state.get("line_step", self._DEFAULT_LINE_STEP_M))
        target_crs = hex_layer.crs()
        transform_context = QgsProject.instance().transformContext()

        pieces: List[QgsGeometry] = []
        for source_layer in line_layers:
            transformer = None
            if source_layer.crs() != target_crs:
                transformer = QgsCoordinateTransform(source_layer.crs(), target_crs, transform_context)
            for feature in source_layer.getFeatures():
                geom = feature.geometry()
                if geom is None or geom.isEmpty():
                    continue
                geom = QgsGeometry(geom)
                try:
                    if transformer:
                        geom.transform(transformer)
                except Exception:
                    continue
                geom = geom.makeValid()
                if geom.isEmpty() or geom.type() != QgsWkbTypes.LineGeometry:
                    continue
                if buffer_dist > 0 and cls.line_behavior == "edge":
                    buffered = geom.buffer(buffer_dist, 8)
                else:
                    buffered = None
                path = cache.trace_line(geom, cls.line_behavior or "center_to_edge", buffered, step_dist)
                if path is not None and not path.isEmpty():
                    pieces.append(path)

        if not pieces:
            self.log(f"Mosaic: class '{cls.class_id}' -> no line paths produced.")
            return None

        union = QgsGeometry.unaryUnion(pieces)
        if union is None or union.isEmpty():
            self.log(f"Mosaic: class '{cls.class_id}' -> unable to merge generated line segments.")
            return None

        mem = QgsVectorLayer(f"LineString?crs={target_crs.authid()}", cls.target_layer, "memory")
        provider = mem.dataProvider()
        provider.addAttributes([
            QgsField("class_id", QVariant.String),
            QgsField("source_layers", QVariant.String),
        ])
        mem.updateFields()

        line_features = []
        if union.type() == QgsWkbTypes.LineGeometry:
            line_features.append(union)
        elif union.isMultipart():
            for geom in union.asGeometryCollection():
                if geom.type() == QgsWkbTypes.LineGeometry:
                    line_features.append(QgsGeometry(geom))
        else:
            line_features.append(union)

        total = 0
        for geom in line_features:
            if geom.isEmpty():
                continue
            feat = QgsFeature(mem.fields())
            feat.setGeometry(geom)
            feat.setAttributes([
                cls.class_id,
                ";".join(sorted(layer.name() for layer in line_layers)),
            ])
            provider.addFeature(feat)
            total += 1

        if total == 0:
            self.log(f"Mosaic: class '{cls.class_id}' -> no valid line geometries after union.")
            return None

        base_label = hex_layer.name().split("(")[0].strip()
        output_name = f"{base_label}_{cls.target_layer}".strip("_")
        shp_path = self._mosaic_output_path(output_name)
        try:
            self._write_vector_to_shp(mem, shp_path)
        except RuntimeError as exc:
            self.log(f"Mosaic: {exc}")
            return None
        layer = QgsVectorLayer(shp_path, output_name, "ogr")
        if not layer.isValid():
            self.log(f"Mosaic: failed to load line layer for {cls.class_id}.")
            return None
        self._finalize_output_layer(layer, hex_layer, cls)
        self.log(
            f"Mosaic: {cls.class_id} -> {total} line part(s), saved to {os.path.relpath(shp_path, self._project_root()) if self._project_root() else shp_path}."
        )
        return layer

    # ------------------------------------------------------------------
    # Geometry utilities

    def _resolve_hex_layer(self) -> Optional[QgsVectorLayer]:
        layer_id = self.cbo_mosaic_hex_layer.currentData()
        layer = QgsProject.instance().mapLayer(layer_id) if layer_id else None
        if isinstance(layer, QgsVectorLayer) and QgsWkbTypes.geometryType(layer.wkbType()) == QgsWkbTypes.PolygonGeometry:
            return layer
        return None
    def _resolve_layers(self, ids: Iterable[str], expected_geometry: int) -> List[QgsVectorLayer]:
        layers: List[QgsVectorLayer] = []
        for lid in ids:
            layer = QgsProject.instance().mapLayer(lid)
            if not isinstance(layer, QgsVectorLayer):
                continue
            if QgsWkbTypes.geometryType(layer.wkbType()) != expected_geometry:
                continue
            layers.append(layer)
        return layers

    def _prepare_polygon_sources(
        self,
        layers: Sequence[QgsVectorLayer],
        target_crs: QgsCoordinateReferenceSystem,
    ) -> List[Tuple[List[QgsGeometry], QgsSpatialIndex]]:
        sources: List[Tuple[List[QgsGeometry], QgsSpatialIndex]] = []
        transform_context = QgsProject.instance().transformContext()
        for layer in layers:
            geoms: List[QgsGeometry] = []
            index = QgsSpatialIndex()
            transformer = None
            if layer.crs() != target_crs:
                transformer = QgsCoordinateTransform(layer.crs(), target_crs, transform_context)
            for feature in layer.getFeatures():
                geom = feature.geometry()
                if geom is None or geom.isEmpty():
                    continue
                geom = QgsGeometry(geom)
                try:
                    if transformer:
                        geom.transform(transformer)
                except Exception:
                    continue
                geom = geom.makeValid()
                if geom.isEmpty() or geom.type() != QgsWkbTypes.PolygonGeometry:
                    continue
                fid = len(geoms)
                tmp = QgsFeature(fid)
                tmp.setGeometry(geom)
                index.addFeature(tmp)
                geoms.append(geom)
            if geoms:
                sources.append((geoms, index))
        return sources




    def _polygon_overlap_area(
        self,
        hex_geom: QgsGeometry,
        bbox: QgsRectangle,
        sources: Sequence[Tuple[List[QgsGeometry], QgsSpatialIndex]],
    ) -> float:
        total = 0.0
        for geoms, index in sources:
            for idx in index.intersects(bbox):
                candidate = geoms[idx]
                if hex_geom.intersects(candidate):
                    inter = hex_geom.intersection(candidate)
                    if inter and not inter.isEmpty():
                        total += inter.area()
        return total

    def _centroid_hits_sources(
        self,
        centroid: QgsPointXY,
        sources: Sequence[Tuple[List[QgsGeometry], QgsSpatialIndex]],
    ) -> bool:
        point = QgsGeometry.fromPointXY(centroid)
        if point.isEmpty():
            return False
        rect = QgsRectangle(centroid.x(), centroid.y(), centroid.x(), centroid.y())
        for geoms, index in sources:
            for idx in index.intersects(rect):
                candidate = geoms[idx]
                if candidate.contains(point) or candidate.intersects(point):
                    return True
        return False

    def _drop_existing_output_layer(self, path: str) -> None:
        """Remove any loaded layer that currently points at the output path."""
        proj = QgsProject.instance()
        target = os.path.normcase(os.path.abspath(path))
        for layer in list(proj.mapLayers().values()):
            if not isinstance(layer, QgsVectorLayer):
                continue
            source = layer.dataProvider().dataSourceUri() if layer.dataProvider() else layer.source()
            if not source:
                continue
            src_path = source.split('|', 1)[0]
            try:
                src_norm = os.path.normcase(os.path.abspath(src_path))
            except Exception:
                continue
            if src_norm == target:
                proj.removeMapLayer(layer.id())

    def _write_vector_to_shp(self, layer: QgsVectorLayer, path: str) -> None:
        self._drop_existing_output_layer(path)
        directory = os.path.dirname(path)
        os.makedirs(directory, exist_ok=True)
        base, _ = os.path.splitext(path)
        for ext in (".shp", ".shx", ".dbf", ".prj", ".cpg", ".qix", ".qmd"):
            candidate = base + ext
            if os.path.exists(candidate):
                try:
                    os.remove(candidate)
                except Exception:
                    pass
        result = QgsVectorFileWriter.writeAsVectorFormat(
            layer,
            path,
            "UTF-8",
            layer.crs(),
            "ESRI Shapefile",
            onlySelected=False,
            layerOptions=["ENCODING=UTF-8"],
        )
        if isinstance(result, tuple):
            err, msg = result
        else:
            err, msg = result, ""
        if err != QgsVectorFileWriter.NoError:
            raise RuntimeError(f"failed to write shapefile (error code {err}): {msg}")

    def _finalize_output_layer(self, layer: QgsVectorLayer, hex_layer: QgsVectorLayer, cls: MosaicClass) -> None:
        proj = QgsProject.instance()
        base_label = hex_layer.name().split("(")[0].strip()
        target_group = self._ensure_nested_groups(["Mosaic", base_label])
        for child in list(target_group.children()):
            if child.nodeType() == child.NodeLayer and child.layer() and child.layer().name() == layer.name():
                proj.removeMapLayer(child.layer().id())
        proj.addMapLayer(layer, False)
        target_group.addLayer(layer)
        self._apply_style_for_class(layer, cls)
        try:
            qml_path = os.path.splitext(self._mosaic_output_path(layer.name()))[0] + '.qml'
            layer.saveNamedStyle(qml_path)
        except Exception:
            pass

    def _apply_style_for_class(self, layer: QgsVectorLayer, cls: MosaicClass) -> None:
        style_entry = self._style_catalog.get(cls.target_layer)
        if style_entry:
            if self._apply_style(layer, style_entry[1]):
                return
            builtin_qml = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'styles', style_entry[1])
            if os.path.isfile(builtin_qml):
                res, _ = layer.loadNamedStyle(builtin_qml)
                if res:
                    layer.triggerRepaint()
                    return
            self.log(f"Mosaic: style preset {style_entry[1]} unavailable; using fallback renderer.")
        if cls.mode == "polygon":
            from qgis.core import QgsFillSymbol, QgsSingleSymbolRenderer

            color = "189,183,107,200" if "field" in cls.class_id else "64,130,255,180"
            symbol = QgsFillSymbol.createSimple(
                {
                    "color": color,
                    "outline_color": "60,60,60,120",
                    "outline_width": "0.4",
                    "outline_width_unit": "MM",
                }
            )
            layer.setRenderer(QgsSingleSymbolRenderer(symbol))
        else:
            from qgis.core import QgsLineSymbol, QgsSingleSymbolRenderer

            color = "255,0,0,200" if "road" in cls.class_id else "70,130,180,220"
            symbol = QgsLineSymbol.createSimple(
                {
                    "line_color": color,
                    "line_width": "0.8",
                    "line_width_unit": "MM",
                }
            )
            layer.setRenderer(QgsSingleSymbolRenderer(symbol))
        layer.triggerRepaint()

    def _mosaic_output_path(self, layer_name: str) -> str:
        safe = self._safe_filename(layer_name.replace(" ", "_"))
        return os.path.join(self._layers_mosaic_dir(), f"{safe}.shp")


class _HexCache:
    """Caches hex geometries and spatial index for fast lookups."""

    def __init__(self, hex_layer: QgsVectorLayer):
        self.layer = hex_layer
        self.index = QgsSpatialIndex()
        self.features: List[QgsFeature] = []
        self.geometries: Dict[int, QgsGeometry] = {}
        self.centroids: Dict[int, QgsPointXY] = {}
        self._edge_cache: Dict[Tuple[int, int], Optional[QgsGeometry]] = {}

        for feature in hex_layer.getFeatures():
            geom = feature.geometry()
            if geom is None or geom.isEmpty():
                continue
            geom = geom.makeValid()
            if geom.isEmpty():
                continue
            self.index.addFeature(feature)
            self.features.append(feature)
            self.geometries[feature.id()] = geom
            self.centroids[feature.id()] = geom.centroid().asPoint()

        self.hex_step = self._estimate_hex_step()

    def _estimate_hex_step(self) -> float:
        if not self.features:
            return 200.0
        geom = self.geometries[self.features[0].id()]
        bbox = geom.boundingBox()
        return max(bbox.width(), bbox.height())

    def trace_line(
        self,
        line: QgsGeometry,
        behavior: str,
        buffered: Optional[QgsGeometry],
        step_dist: float,
    ) -> Optional[QgsGeometry]:
        length = line.length()
        if length <= 0:
            return None
        step = max(step_dist, self.hex_step * 0.3)
        ids: List[int] = []
        dist = 0.0
        while dist <= length:
            point = line.interpolate(dist)
            if point.isEmpty():
                dist += step
                continue
            hid = self._hex_id_for_point(point.asPoint(), fallback_to_nearest=True)
            if hid is not None and (not ids or ids[-1] != hid):
                ids.append(hid)
            dist += step
        end_point = line.interpolate(length)
        if not end_point.isEmpty():
            end_hex = self._hex_id_for_point(end_point.asPoint(), fallback_to_nearest=True)
            if end_hex is not None and (not ids or ids[-1] != end_hex):
                ids.append(end_hex)
        if len(ids) < 2:
            return None

        if behavior == "edge":
            segments: List[QgsGeometry] = []
            for a, b in zip(ids, ids[1:]):
                if a == b:
                    continue
                shared = self._shared_edge(a, b)
                if shared is not None and not shared.isEmpty():
                    segments.append(shared)
            if buffered is not None and not buffered.isEmpty():
                segments.append(buffered)
            if not segments:
                return None
            return QgsGeometry.unaryUnion(segments)
        else:
            points = [self.centroids[i] for i in ids if i in self.centroids]
            if len(points) < 2:
                return None
            return QgsGeometry.fromPolylineXY(points)

    def _hex_id_for_point(self, point: QgsPointXY, fallback_to_nearest: bool = False) -> Optional[int]:
        rect = QgsRectangle(point.x(), point.y(), point.x(), point.y())
        candidates = self.index.intersects(rect)
        for fid in candidates:
            geom = self.geometries.get(fid)
            if geom and (geom.contains(QgsGeometry.fromPointXY(point)) or geom.distance(QgsGeometry.fromPointXY(point)) < 1e-6):
                return fid
        if fallback_to_nearest:
            nearest = self.index.nearestNeighbor(point, 1)
            if nearest:
                return nearest[0]
        return None

    def _shared_edge(self, a: int, b: int) -> Optional[QgsGeometry]:
        key = (min(a, b), max(a, b))
        if key in self._edge_cache:
            return self._edge_cache[key]
        geom_a = self.geometries.get(a)
        geom_b = self.geometries.get(b)
        if not geom_a or not geom_b:
            self._edge_cache[key] = None
            return None
        shared = geom_a.intersection(geom_b)
        if not shared or shared.isEmpty():
            shared = geom_a.boundary().intersection(geom_b.boundary())
        if shared and not shared.isEmpty():
            if shared.type() == QgsWkbTypes.PolygonGeometry:
                shared = shared.boundary()
            self._edge_cache[key] = shared
            return shared
        self._edge_cache[key] = None
        return None

