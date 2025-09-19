"""OSM import helpers for HexMosaic."""
from __future__ import annotations

import json
import os
import pathlib
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from qgis.PyQt import QtWidgets
from qgis.PyQt.QtCore import QVariant
from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeature,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
    QgsUnitTypes,
    QgsVectorLayer,
    QgsWkbTypes,
)

from .settings_dialog import get_persistent_setting


@dataclass(frozen=True)
class OsmLayerSpec:
    storage_name: str
    display_name: str
    geometry: str  # 'point' | 'line' | 'polygon'
    query: str     # Overpass snippet with {bbox} placeholder


@dataclass(frozen=True)
class OsmTheme:
    key: str
    label: str
    layers: Sequence[OsmLayerSpec]


class OsmImportMixin:
    """Provides Overpass + offline import helpers for OSM layers."""

    OVERPASS_URL = "https://overpass-api.de/api/interpreter"

    OSM_THEMES: Sequence[OsmTheme] = (
        OsmTheme(
            key="roads",
            label="Roads & Rail",
            layers=(
                OsmLayerSpec(
                    storage_name="roads_highways",
                    display_name="Roads - Highways",
                    geometry="line",
                    query='way["highway"~"^(motorway|trunk)(_|;|$)|motorway|trunk|primary|primary_link|motorway_link|trunk_link"]({bbox});',
                ),
                OsmLayerSpec(
                    storage_name="roads_primary",
                    display_name="Roads - Primary",
                    geometry="line",
                    query='way["highway"~"^(primary|secondary)(_|;|$)|secondary|secondary_link"]({bbox});',
                ),
                OsmLayerSpec(
                    storage_name="roads_minor",
                    display_name="Roads - Minor",
                    geometry="line",
                    query='way["highway"~"^(tertiary|unclassified|residential)(_|;|$)|tertiary|unclassified|residential|living_street|service"]({bbox});',
                ),
                OsmLayerSpec(
                    storage_name="roads_tracks",
                    display_name="Roads - Tracks & Paths",
                    geometry="line",
                    query='way["highway"~"^(track|path)(_|;|$)|track|path|footway|cycleway|bridleway"]({bbox});',
                ),
                OsmLayerSpec(
                    storage_name="rail_lines",
                    display_name="Rail",
                    geometry="line",
                    query='way["railway"~"^(rail|light_rail|tram)(_|;|$)|rail|light_rail|tram"]({bbox});',
                ),
                OsmLayerSpec(
                    storage_name="airstrips",
                    display_name="Aeroways",
                    geometry="line",
                    query='way["aeroway"~"^(runway|taxiway)(_|;|$)|runway|taxiway"]({bbox});',
                ),
            ),
        ),
        OsmTheme(
            key="water",
            label="Water",
            layers=(
                OsmLayerSpec(
                    storage_name="water_major",
                    display_name="Water - Major Rivers",
                    geometry="line",
                    query='way["waterway"~"^(river|tidal_channel)(_|;|$)|river|tidal_channel"]({bbox});',
                ),
                OsmLayerSpec(
                    storage_name="water_minor",
                    display_name="Water - Streams",
                    geometry="line",
                    query='way["waterway"~"^(stream|ditch|drain|canal)(_|;|$)|stream|ditch|drain|canal"]({bbox});',
                ),
                OsmLayerSpec(
                    storage_name="water_polygons",
                    display_name="Water - Polygons",
                    geometry="polygon",
                    query='way["natural"~"^(water|wetland)(_|;|$)|water|wetland|reservoir"]({bbox});',
                ),
                OsmLayerSpec(
                    storage_name="water_riverbank",
                    display_name="Water - Riverbanks",
                    geometry="polygon",
                    query='way["waterway"="riverbank"]({bbox});',
                ),
            ),
        ),
        OsmTheme(
            key="landcover",
            label="Landcover",
            layers=(
                OsmLayerSpec(
                    storage_name="landcover_forest",
                    display_name="Landcover - Forest",
                    geometry="polygon",
                    query='way["landuse"="forest"]({bbox});way["natural"="wood"]({bbox});',
                ),
                OsmLayerSpec(
                    storage_name="landcover_fields",
                    display_name="Landcover - Fields",
                    geometry="polygon",
                    query='way["landuse"~"^(farmland|meadow|orchard|vineyard|grass)(_|;|$)|farmland|meadow|orchard|vineyard|grass"]({bbox});',
                ),
                OsmLayerSpec(
                    storage_name="landcover_industrial",
                    display_name="Landcover - Industrial",
                    geometry="polygon",
                    query='way["landuse"~"^(industrial|commercial)(_|;|$)|industrial|commercial"]({bbox});',
                ),
                OsmLayerSpec(
                    storage_name="landcover_wetland",
                    display_name="Landcover - Wetlands",
                    geometry="polygon",
                    query='way["natural"="wetland"]({bbox});',
                ),
            ),
        ),
        OsmTheme(
            key="buildings",
            label="Buildings",
            layers=(
                OsmLayerSpec(
                    storage_name="buildings",
                    display_name="Buildings",
                    geometry="polygon",
                    query='way["building"]({bbox});',
                ),
            ),
        ),
        OsmTheme(
            key="poi",
            label="Points of Interest",
            layers=(
                OsmLayerSpec(
                    storage_name="poi_transport",
                    display_name="POI - Transport",
                    geometry="point",
                    query='node["amenity"~"^(bus_station|ferry_terminal|fuel)(_|;|$)|bus_station|ferry_terminal|fuel|airport"]({bbox});',
                ),
                OsmLayerSpec(
                    storage_name="poi_military",
                    display_name="POI - Military",
                    geometry="point",
                    query='node["military"]({bbox});',
                ),
                OsmLayerSpec(
                    storage_name="poi_industrial",
                    display_name="POI - Industrial",
                    geometry="point",
                    query='node["man_made"~"^(works|plant|mine|adit)(_|;|$)|works|plant|mine|adit"]({bbox});',
                ),
            ),
        ),
    )

    def _theme_lookup(self) -> Dict[str, OsmTheme]:
        return {theme.key: theme for theme in self.OSM_THEMES}

    def _sync_aoi_combo_to_osm(self, layers=None):
        if not hasattr(self, "cboAOI_osm"):
            return
        # Guard against Qt signals passing a boolean (clicked(bool)) or other
        # unexpected types into this method. Ensure we always work with an
        # iterable list of layers.
        if layers is None:
            layers = self._gather_aoi_layers()
        else:
            # If a boolean was passed (e.g. from a clicked signal), coerce to []
            if isinstance(layers, bool):
                self.log("_sync_aoi_combo_to_osm: received boolean instead of layers; ignoring.")
                layers = []
            else:
                try:
                    iter(layers)
                except TypeError:
                    self.log(f"_sync_aoi_combo_to_osm: received non-iterable {type(layers)}; treating as empty.")
                    layers = []
        prev = self.cboAOI_osm.currentData() if self.cboAOI_osm.count() else None
        self.cboAOI_osm.blockSignals(True)
        self.cboAOI_osm.clear()
        for lyr in layers:
            self.cboAOI_osm.addItem(lyr.name(), lyr.id())
        if prev is not None:
            idx = self.cboAOI_osm.findData(prev)
            if idx >= 0:
                self.cboAOI_osm.setCurrentIndex(idx)
        self.cboAOI_osm.blockSignals(False)

    def _selected_aoi_layer_for_osm(self):
        if not hasattr(self, "cboAOI_osm"):
            return None
        lyr_id = self.cboAOI_osm.currentData()
        return QgsProject.instance().mapLayer(lyr_id) if lyr_id else None

    def download_osm_layers(self):
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
        summary = []
        for key in selected:
            theme = lookup.get(key)
            if not theme:
                continue
            try:
                created = self._download_and_store_theme(theme, bbox_str, clip_geom, target_crs)
                summary.append(f"{theme.label}: {created}")
            except Exception as exc:
                self.log(f"OSM import: Failed theme '{theme.label}': {exc}")
        if summary:
            self._osm_last_params = {
                "aoi_id": aoi_layer.id(),
                "buffer_m": buffer_m,
                "themes": selected,
            }
            self.log("OSM import complete -> " + "; ".join(summary))
        else:
            self.log("OSM import finished with no layers created.")

    def refresh_osm_layers(self):
        params = getattr(self, "_osm_last_params", None)
        if not params:
            self.log("OSM import: Nothing to refresh yet.")
            return
        aoi = QgsProject.instance().mapLayer(params.get("aoi_id", ""))
        if not aoi:
            self.log("OSM import: Previous AOI not found. Re-run download with a current AOI.")
            return
        if hasattr(self, "spin_osm_buffer"):
            self.spin_osm_buffer.setValue(float(params.get("buffer_m", 1000.0)))
        for key, chk in getattr(self, "osm_theme_checks", {}).items():
            chk.setChecked(key in params.get("themes", []))
        self.download_osm_layers()

    def import_osm_from_local(self):
        lookup = self._theme_lookup()
        theme_key = self.cbo_osm_local_theme.currentData() if hasattr(self, "cbo_osm_local_theme") else None
        theme = lookup.get(theme_key) if theme_key else None
        if not theme:
            self.log("OSM import: Select a theme for local import.")
            return
        path = self.osm_local_path_edit.text().strip() if hasattr(self, "osm_local_path_edit") else ""
        if not path:
            self.log("OSM import: Choose a local file to import.")
            return
        src = pathlib.Path(path)
        if not src.exists():
            self.log(f"OSM import: Local file not found -> {path}")
            return

        aoi_layer = self._selected_aoi_layer_for_osm() or self._selected_aoi_layer()
        if not aoi_layer:
            self.log("OSM import: Select an AOI before importing local data.")
            return
        buffer_m = float(self.spin_osm_buffer.value()) if hasattr(self, "spin_osm_buffer") else 1000.0
        try:
            clip_geom, _, target_crs = self._prepare_osm_clip_geometry(aoi_layer, buffer_m)
        except RuntimeError as exc:
            self.log(f"OSM import: {exc}")
            return

        try:
            created = self._import_local_theme(theme, str(src), clip_geom, target_crs)
            self.log(f"OSM import: Local theme '{theme.label}' -> {created} features written.")
        except Exception as exc:
            self.log(f"OSM import: Local import failed: {exc}")

    def browse_osm_local_source(self):
        base = self._project_root()
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Select local OSM dataset",
            base,
            "Vector data (*.gpkg *.geojson *.json *.shp);;All files (*)",
        )
        if path and hasattr(self, "osm_local_path_edit"):
            self.osm_local_path_edit.setText(path)

    def _prepare_osm_clip_geometry(self, aoi_layer, buffer_m: float):
        features = [f for f in aoi_layer.getFeatures() if f.hasGeometry()]
        if not features:
            raise RuntimeError("AOI layer has no geometry to clip with.")
        geom = features[0].geometry().makeValid()
        for feat in features[1:]:
            geom = geom.combine(feat.geometry().makeValid())
        target_crs = aoi_layer.crs()
        # make a copy of the working geometry
        clip_geom = QgsGeometry(geom)
        if buffer_m > 0:
            clip_geom = self._buffer_in_meters(clip_geom, buffer_m, target_crs)
        wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        to_wgs = QgsCoordinateTransform(target_crs, wgs84, QgsProject.instance().transformContext())
        clip_wgs = QgsGeometry(clip_geom)
        clip_wgs.transform(to_wgs)
        return clip_geom, clip_wgs, target_crs

    def _buffer_in_meters(self, geom: QgsGeometry, buffer_m: float, crs: QgsCoordinateReferenceSystem) -> QgsGeometry:
        if buffer_m <= 0:
            return geom
        if crs.mapUnits() == QgsUnitTypes.DistanceMeters:
            return geom.buffer(buffer_m, 24)
        wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        to_wgs = QgsCoordinateTransform(crs, wgs84, QgsProject.instance().transformContext())
        centroid = geom.centroid()
        centroid.transform(to_wgs)
        lon, lat = centroid.asPoint().x(), centroid.asPoint().y()
        epsg = self._utm_epsg_for_lonlat(lon, lat)
        utm = QgsCoordinateReferenceSystem.fromEpsgId(epsg)
        if not utm.isValid():
            return geom
        to_utm = QgsCoordinateTransform(crs, utm, QgsProject.instance().transformContext())
        to_src = QgsCoordinateTransform(utm, crs, QgsProject.instance().transformContext())
        utm_geom = QgsGeometry(geom)
        utm_geom.transform(to_utm)
        utm_geom = utm_geom.buffer(buffer_m, 24)
        utm_geom.transform(to_src)
        return utm_geom

    def _download_and_store_theme(self, theme: OsmTheme, bbox: str, clip_geom: QgsGeometry, target_crs: QgsCoordinateReferenceSystem) -> int:
        layers = []
        total = 0
        for spec in theme.layers:
            elements = self._fetch_overpass_elements(spec, bbox)
            layer = self._elements_to_layer(spec, elements, clip_geom, target_crs)
            if layer and layer.featureCount():
                layers.append((layer, spec.storage_name))
                total += layer.featureCount()
        if not layers:
            self._remove_theme_layers_from_project(theme)
            return 0
        gpkg_path = self._osm_theme_path(theme.key)
        self._write_theme_to_gpkg(gpkg_path, layers)
        self._load_theme_layers(theme, gpkg_path)
        return total

    def _fetch_overpass_elements(self, spec: OsmLayerSpec, bbox: str) -> List[dict]:
        query = f"[out:json][timeout:180];(\n{spec.query.format(bbox=bbox)}\n);\nout geom;"
        data = query.encode("utf-8")
        request = urllib.request.Request(self.OVERPASS_URL, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"})
        try:
            with urllib.request.urlopen(request, timeout=180) as resp:
                payload = resp.read()
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Overpass request failed: {exc}")
        try:
            parsed = json.loads(payload.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Invalid response from Overpass: {exc}")
        return parsed.get("elements", [])

    def _elements_to_layer(self, spec: OsmLayerSpec, elements: Sequence[dict], clip_geom: QgsGeometry, target_crs: QgsCoordinateReferenceSystem) -> Optional[QgsVectorLayer]:
        if not elements:
            return None
        wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        to_target = QgsCoordinateTransform(wgs84, target_crs, QgsProject.instance().transformContext())
        mem_layer = self._create_memory_layer(spec.display_name, spec.geometry, wgs84)

        tag_keys = set()
        for element in elements:
            tags = element.get("tags", {})
            tag_keys.update(tags.keys())
        fields = QgsFields()
        fields.append(QgsField("osm_id", QVariant.String))
        for key in sorted(tag_keys):
            fields.append(QgsField(key, QVariant.String))
        provider = mem_layer.dataProvider()
        provider.addAttributes(fields)
        mem_layer.updateFields()
        fields = mem_layer.fields()

        added = 0
        for element in elements:
            geom = self._element_geometry(spec.geometry, element)
            if geom is None or geom.isEmpty():
                continue
            geom.transform(to_target)
            geom = geom.intersection(clip_geom)
            if geom.isEmpty():
                continue
            geom = self._ensure_multi(geom)
            feat = QgsFeature(fields)
            feat.setGeometry(geom)
            attrs = [str(element.get("id", ""))]
            tags = element.get("tags", {})
            for key in sorted(tag_keys):
                value = tags.get(key)
                if isinstance(value, (dict, list)):
                    value = json.dumps(value)
                attrs.append("" if value is None else str(value))
            feat.setAttributes(attrs)
            provider.addFeature(feat)
            added += 1

        if added == 0:
            return None
        mem_layer.setCrs(target_crs)
        mem_layer.updateExtents()
        return mem_layer

    def _element_geometry(self, geometry_kind: str, element: dict) -> Optional[QgsGeometry]:
        coords = element.get("geometry")
        if geometry_kind == "point":
            if element.get("type") == "node":
                lat = element.get("lat")
                lon = element.get("lon")
                if lat is None or lon is None:
                    return None
                return QgsGeometry.fromPointXY(QgsPointXY(lon, lat))
            if coords:
                pt = coords[0]
                return QgsGeometry.fromPointXY(QgsPointXY(pt["lon"], pt["lat"]))
            return None
        if not coords:
            return None
        pts = [QgsPointXY(c["lon"], c["lat"]) for c in coords]
        if geometry_kind == "line":
            return QgsGeometry.fromPolylineXY(pts)
        if geometry_kind == "polygon":
            if not pts:
                return None
            if pts[0] != pts[-1]:
                pts.append(pts[0])
            return QgsGeometry.fromPolygonXY([pts])
        return None

    def _create_memory_layer(self, name: str, geometry_kind: str, crs: QgsCoordinateReferenceSystem) -> QgsVectorLayer:
        if geometry_kind == "point":
            uri = f"Point?crs={crs.authid()}"
        elif geometry_kind == "line":
            uri = f"LineString?crs={crs.authid()}"
        elif geometry_kind == "polygon":
            uri = f"Polygon?crs={crs.authid()}"
        else:
            uri = f"Unknown?crs={crs.authid()}"
        return QgsVectorLayer(uri, name, "memory")

    def _ensure_multi(self, geom: QgsGeometry) -> QgsGeometry:
        if geom.wkbType() in (QgsWkbTypes.LineString, QgsWkbTypes.Polygon):
            geom.convertToMultiType()
        return geom

    def _import_local_theme(self, theme: OsmTheme, source_path: str, clip_geom: QgsGeometry, target_crs: QgsCoordinateReferenceSystem) -> int:
        layers = []
        total = 0
        sublayers = []
        if source_path.lower().endswith(".gpkg"):
            probe = QgsVectorLayer(source_path, "", "ogr")
            if probe.isValid():
                sublayers = [s.split(":")[-1] for s in probe.dataProvider().subLayers()]
        for spec in theme.layers:
            layer = self._load_local_layer(source_path, spec, sublayers)
            if not layer:
                continue
            prepared = self._clip_and_prepare_layer(layer, spec.geometry, clip_geom, target_crs)
            if prepared and prepared.featureCount():
                layers.append((prepared, spec.storage_name))
                total += prepared.featureCount()
        if layers:
            gpkg_path = self._osm_theme_path(theme.key)
            self._write_theme_to_gpkg(gpkg_path, layers)
            self._load_theme_layers(theme, gpkg_path)
        else:
            self._remove_theme_layers_from_project(theme)
        return total

    def _load_local_layer(self, path: str, spec: OsmLayerSpec, sublayers: Sequence[str]) -> Optional[QgsVectorLayer]:
        uri = path
        if path.lower().endswith(".gpkg"):
            if spec.storage_name in sublayers:
                uri = f"{path}|layername={spec.storage_name}"
        layer = QgsVectorLayer(uri, spec.display_name, "ogr")
        if not layer.isValid():
            self.log(f"OSM import: Local layer '{spec.storage_name}' missing in {path}")
            return None
        return layer

    def _clip_and_prepare_layer(self, layer: QgsVectorLayer, geometry_kind: str, clip_geom: QgsGeometry, target_crs: QgsCoordinateReferenceSystem) -> Optional[QgsVectorLayer]:
        src_crs = layer.crs()
        transform = QgsCoordinateTransform(src_crs, target_crs, QgsProject.instance().transformContext()) if src_crs != target_crs else None
        mem = self._create_memory_layer(layer.name(), geometry_kind, target_crs)
        provider = mem.dataProvider()
        provider.addAttributes(layer.fields())
        mem.updateFields()
        fields = mem.fields()
        for feat in layer.getFeatures():
            if not feat.hasGeometry():
                continue
            geom = feat.geometry().makeValid()
            if transform:
                geom.transform(transform)
            geom = geom.intersection(clip_geom)
            if geom.isEmpty():
                continue
            geom = self._ensure_multi(geom)
            new_feat = QgsFeature(fields)
            new_feat.setGeometry(geom)
            new_feat.setAttributes(feat.attributes())
            provider.addFeature(new_feat)
        mem.updateExtents()
        return mem

    def _write_theme_to_gpkg(self, gpkg_path: str, layers: Sequence[Tuple[QgsVectorLayer, str]]):
        directory = os.path.dirname(gpkg_path)
        os.makedirs(directory, exist_ok=True)
        try:
            if os.path.exists(gpkg_path):
                os.remove(gpkg_path)
        except Exception:
            pass
        from qgis.core import QgsVectorFileWriter
        for lyr, name in layers:
            err = QgsVectorFileWriter.writeAsVectorFormat(
                lyr,
                gpkg_path,
                "UTF-8",
                lyr.crs(),
                "GPKG",
                layerOptions=[f"LAYER_NAME={name}", "SPATIAL_INDEX=YES"],
            )
            if err != QgsVectorFileWriter.NoError:
                raise RuntimeError(f"Failed to write layer {name} to {gpkg_path}")

    def _load_theme_layers(self, theme: OsmTheme, gpkg_path: str):
        proj = QgsProject.instance()
        osm_group = self._ensure_group("OSM")
        theme_group = next((g for g in osm_group.findGroups() if g.name() == theme.label), None)
        if theme_group is None:
            theme_group = osm_group.addGroup(theme.label)
        self._remove_theme_layers_from_project(theme)
        for spec in theme.layers:
            uri = f"{gpkg_path}|layername={spec.storage_name}"
            layer = QgsVectorLayer(uri, spec.display_name, "ogr")
            if not layer.isValid():
                self.log(f"OSM import: Failed to load {spec.storage_name} from {gpkg_path}")
                continue
            proj.addMapLayer(layer, False)
            theme_group.addLayer(layer)
            self._apply_osm_style(theme.key, spec, layer)

    def _remove_theme_layers_from_project(self, theme: OsmTheme):
        proj = QgsProject.instance()
        osm_group = self._ensure_group("OSM")
        theme_group = next((g for g in osm_group.findGroups() if g.name() == theme.label), None)
        if not theme_group:
            return
        for child in list(theme_group.children()):
            if child.nodeType() == child.NodeLayer:
                layer = child.layer()
                if layer:
                    proj.removeMapLayer(layer.id())
        if not theme_group.children():
            parent = theme_group.parent()
            if parent:
                parent.removeChildNode(theme_group)

    def _apply_osm_style(self, theme_key: str, spec: OsmLayerSpec, layer: QgsVectorLayer):
        styles_dir = get_persistent_setting("paths/styles_dir", "").strip()
        if styles_dir:
            qml = os.path.join(styles_dir, "osm", theme_key, f"{spec.storage_name}.qml")
            if os.path.isfile(qml):
                res, _ = layer.loadNamedStyle(qml)
                if res:
                    layer.triggerRepaint()
                    return
        from qgis.core import QgsFillSymbol, QgsLineSymbol, QgsMarkerSymbol, QgsSingleSymbolRenderer
        if spec.geometry == "polygon":
            sym = QgsFillSymbol.createSimple({"color": "146,196,125,120", "outline_color": "60,120,60"})
            layer.setRenderer(QgsSingleSymbolRenderer(sym))
        elif spec.geometry == "line":
            sym = QgsLineSymbol.createSimple({"line_color": "52,101,164", "line_width": "0.8", "line_width_unit": "MM"})
            layer.setRenderer(QgsSingleSymbolRenderer(sym))
        else:
            sym = QgsMarkerSymbol.createSimple({"name": "circle", "color": "200,74,26", "size": "2.2", "size_unit": "MM"})
            layer.setRenderer(QgsSingleSymbolRenderer(sym))
        layer.triggerRepaint()

    def _ensure_group(self, name):
        raise NotImplementedError

    def _selected_aoi_layer(self):
        raise NotImplementedError

    def log(self, msg: str):
        raise NotImplementedError

    def _osm_theme_path(self, theme_key: str) -> str:
        raise NotImplementedError

    def _project_root(self) -> str:
        raise NotImplementedError
