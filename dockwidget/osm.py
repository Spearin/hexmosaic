# -*- coding: utf-8 -*-
"""OSM import helpers for HexMosaic.

This mixin is consumed by HexMosaicDockWidget. It provides:
- Overpass planning (AOI+buffer → WGS84 bbox)
- Query composition and tiling
- Robust POST with mirrors, headers, and retry/backoff
- JSON → memory layer conversion
- Shapefile writing + project loading per theme
- Preview / Download / Refresh / Local import entrypoints

Assumptions:
- Consumer implements: log(), _project_root(), _ensure_group(name),
  _utm_epsg_for_lonlat(lon, lat)
- Consumer wires the UI controls used here (see dock init).

"""
from __future__ import annotations

import json
import os
import pathlib
import time
import urllib.error
import urllib.request
import urllib.parse
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
    QgsApplication,
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


@dataclass(frozen=True)
class OsmRequestPlan:
    aoi_layer: QgsVectorLayer
    buffer_m: float
    clip_geom: QgsGeometry
    clip_wgs84: QgsGeometry
    target_crs: QgsCoordinateReferenceSystem
    bbox_str: str
    themes: Sequence[OsmTheme]
    theme_keys: Sequence[str]


class OsmImportMixin:
    """Provides Overpass + offline import helpers for OSM layers."""

    # Overpass mirrors we rotate through on failure.
    OVERPASS_URLS = (
        "https://overpass-api.de/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter",
        "https://overpass.openstreetmap.fr/api/interpreter",
    )

    # Backwards-compat alias for code that references a single URL
    # (e.g., preview text). Points to the currently selected mirror.
    @property
    def OVERPASS_URL(self) -> str:
        idx = getattr(self, "_overpass_url_index", 0)
        return self.OVERPASS_URLS[idx % len(self.OVERPASS_URLS)]

    # ----- Themes (same structure you uploaded; feel free to edit) -----

    OSM_THEMES: Sequence[OsmTheme] = (
        OsmTheme(
            key="roads",
            label="Roads & Rail",
            layers=(
                OsmLayerSpec(
                    storage_name="roads_highways",
                    display_name="Roads - Highways",
                    geometry="line",
                    query='way["highway"~"motorway|trunk|primary|motorway_link|trunk_link|primary_link"]({bbox});',
                ),
                OsmLayerSpec(
                    storage_name="roads_primary",
                    display_name="Roads - Primary",
                    geometry="line",
                    query='way["highway"~"primary|secondary|primary_link|secondary_link"]({bbox});',
                ),
                OsmLayerSpec(
                    storage_name="roads_minor",
                    display_name="Roads - Minor",
                    geometry="line",
                    query='way["highway"~"tertiary|unclassified|residential|living_street|service"]({bbox});',
                ),
                OsmLayerSpec(
                    storage_name="roads_tracks",
                    display_name="Roads - Tracks & Paths",
                    geometry="line",
                    query='way["highway"~"track|path|footway|cycleway|bridleway"]({bbox});',
                ),
                OsmLayerSpec(
                    storage_name="rail_lines",
                    display_name="Rail",
                    geometry="line",
                    query='way["railway"~"rail|light_rail|tram"]({bbox});',
                ),
                OsmLayerSpec(
                    storage_name="airstrips",
                    display_name="Aeroways",
                    geometry="line",
                    query='way["aeroway"~"runway|taxiway"]({bbox});',
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
                    query='way["waterway"~"river|tidal_channel"]({bbox});',
                ),
                OsmLayerSpec(
                    storage_name="water_minor",
                    display_name="Water - Streams",
                    geometry="line",
                    query='way["waterway"~"stream|ditch|drain|canal"]({bbox});',
                ),
                OsmLayerSpec(
                    storage_name="water_polygons",
                    display_name="Water - Polygons",
                    geometry="polygon",
                    query=(
                        'way["natural"="water"]({bbox});\n'
                        'relation["natural"="water"]({bbox});\n'
                        'way["natural"="wetland"]({bbox});\n'
                        'relation["natural"="wetland"]({bbox});\n'
                        'way["landuse"="reservoir"]({bbox});\n'
                        'relation["landuse"="reservoir"]({bbox});\n'
                        'way["natural"="water"]["water"="reservoir"]({bbox});\n'
                        'relation["natural"="water"]["water"="reservoir"]({bbox});'
                    ),
                ),
                OsmLayerSpec(
                    storage_name="water_riverbank",
                    display_name="Water - Riverbanks",
                    geometry="polygon",
                    query=(
                        'way["waterway"="riverbank"]({bbox});\n'
                        'relation["waterway"="riverbank"]({bbox});\n'
                        'way["natural"="water"]["water"="river"]({bbox});\n'
                        'relation["natural"="water"]["water"="river"]({bbox});'
                    ),
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
                    query=(
                        'way["landuse"="forest"]({bbox});\n'
                        'relation["landuse"="forest"]({bbox});\n'
                        'way["natural"="wood"]({bbox});\n'
                        'relation["natural"="wood"]({bbox});'
                    ),
                ),
                OsmLayerSpec(
                    storage_name="landcover_fields",
                    display_name="Landcover - Fields",
                    geometry="polygon",
                    query=(
                        'way["landuse"~"farmland|meadow|orchard|vineyard|grass"]({bbox});\n'
                        'relation["landuse"~"farmland|meadow|orchard|vineyard|grass"]({bbox});'
                    ),
                ),
                OsmLayerSpec(
                    storage_name="landcover_industrial",
                    display_name="Landcover - Industrial",
                    geometry="polygon",
                    query=(
                        'way["landuse"~"industrial|commercial"]({bbox});\n'
                        'relation["landuse"~"industrial|commercial"]({bbox});'
                    ),
                ),
                OsmLayerSpec(
                    storage_name="landcover_wetland",
                    display_name="Landcover - Wetlands",
                    geometry="polygon",
                    query=(
                        'way["natural"="wetland"]({bbox});\n'
                        'relation["natural"="wetland"]({bbox});'
                    ),
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
                    query='way["building"]({bbox});\nrelation["building"]({bbox});',
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
                    query='node["amenity"~"bus_station|ferry_terminal|fuel|airport"]({bbox});',
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
                    query='node["man_made"~"works|plant|mine|adit"]({bbox});',
                ),
            ),
        ),
    )

    # -------------------- UI wiring helpers --------------------

    def _theme_lookup(self) -> Dict[str, OsmTheme]:
        return {theme.key: theme for theme in self.OSM_THEMES}

    def _sync_aoi_combo_to_osm(self, layers=None):
        if not hasattr(self, "cboAOI_osm"):
            return
        # Defensive: clicked(bool) and other weird signal payloads have hit this.
        if layers is None:
            layers = self._gather_aoi_layers()
        else:
            if isinstance(layers, bool):
                self.log("_sync_aoi_combo_to_osm: received boolean; ignoring.")
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

    # -------------------- Plan / Preview / Actions --------------------

    def _collect_osm_request_plan(self) -> Optional[OsmRequestPlan]:
        aoi_layer = self._selected_aoi_layer_for_osm() or self._selected_aoi_layer()
        if not aoi_layer:
            self.log("OSM import: Select an AOI to clip against.")
            return None

        buffer_m = float(self.spin_osm_buffer.value()) if hasattr(self, "spin_osm_buffer") else 1000.0
        selected_keys = [key for key, chk in getattr(self, "osm_theme_checks", {}).items() if chk.isChecked()]
        if not selected_keys:
            self.log("OSM import: Choose at least one theme.")
            return None

        try:
            clip_geom, clip_wgs84, target_crs = self._prepare_osm_clip_geometry(aoi_layer, buffer_m)
        except RuntimeError as exc:
            self.log(f"OSM import: {exc}")
            return None

        bbox = clip_wgs84.boundingBox()
        bbox_str = f"{bbox.yMinimum():.8f},{bbox.xMinimum():.8f},{bbox.yMaximum():.8f},{bbox.xMaximum():.8f}"

        lookup = self._theme_lookup()
        themes: List[OsmTheme] = []
        matched_keys: List[str] = []
        missing: List[str] = []
        for key in selected_keys:
            theme = lookup.get(key)
            if theme:
                themes.append(theme)
                matched_keys.append(key)
            else:
                missing.append(key)

        if missing:
            self.log("OSM import: Ignoring unknown themes -> " + ", ".join(missing))

        if not themes:
            self.log("OSM import: No valid themes selected.")
            return None

        return OsmRequestPlan(
            aoi_layer=aoi_layer,
            buffer_m=buffer_m,
            clip_geom=clip_geom,
            clip_wgs84=clip_wgs84,
            target_crs=target_crs,
            bbox_str=bbox_str,
            themes=tuple(themes),
            theme_keys=tuple(matched_keys),
        )

    def download_osm_layers(self):
        plan = self._collect_osm_request_plan()
        if not plan:
            return

        summary = []
        for theme in plan.themes:
            try:
                created = self._download_and_store_theme(theme, plan.bbox_str, plan.clip_geom, plan.target_crs)
                summary.append(f"{theme.label}: {created}")
            except Exception as exc:
                self.log(f"OSM import: Failed theme '{theme.label}': {exc}")
        if summary:
            self._osm_last_params = {
                "aoi_id": plan.aoi_layer.id(),
                "buffer_m": plan.buffer_m,
                "themes": list(plan.theme_keys),
            }
            self.log("OSM import complete -> " + "; ".join(summary))
        else:
            self.log("OSM import finished with no layers created.")

    def preview_osm_request(self):
        plan = self._collect_osm_request_plan()
        if not plan:
            self._set_osm_preview_text("OSM preview unavailable. Check the log for details.")
            return

        target_authid = plan.target_crs.authid() or "unknown"
        buffer_text = f"{plan.buffer_m:g}"

        lines = [
            "OSM Request Preview",
            "-------------------",
            f"AOI layer: {plan.aoi_layer.name()} (CRS {target_authid})",
            f"Buffer (m): {buffer_text}",
            f"Bounding box (WGS84): {plan.bbox_str}",
            "",
            f"HTTP POST {self.OVERPASS_URL}",
            "Themes:",
        ]

        for theme in plan.themes:
            theme_dir = self._osm_theme_path(theme.key)
            lines.append(f"- {theme.label} ({theme.key}) -> {theme_dir}")
            for spec in theme.layers:
                lines.append(f"    - {spec.display_name} [{spec.geometry}] -> layer '{spec.storage_name}'")
                query = self._compose_overpass_query(spec, plan.bbox_str).strip()
                lines.append("      Overpass query:")
                for qline in query.splitlines():
                    lines.append(f"        {qline}")
        self._set_osm_preview_text("\n".join(lines))

    def _set_osm_preview_text(self, text: str):
        widget = getattr(self, "osm_preview_edit", None)
        if widget is None:
            self.log(text)
        else:
            widget.setPlainText(text)

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

    # -------------------- Geometry helpers --------------------

    def _prepare_osm_clip_geometry(self, aoi_layer, buffer_m: float):
        features = [f for f in aoi_layer.getFeatures() if f.hasGeometry()]
        if not features:
            raise RuntimeError("AOI layer has no geometry to clip with.")
        geom = features[0].geometry().makeValid()
        for feat in features[1:]:
            geom = geom.combine(feat.geometry().makeValid())
        target_crs = aoi_layer.crs()
        # Work on a copy
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
        # Reproject to a local UTM for a meter buffer
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

    # -------------------- Overpass building & download --------------------

    def _compose_overpass_query(self, spec: OsmLayerSpec, bbox: str) -> str:
        body = spec.query.format(bbox=bbox).strip()
        indented = "\n".join(f"  {line}" for line in body.splitlines())
        return (
            "[out:json][timeout:180];\n"
            "(\n"
            f"{indented}\n"
            ");\n"
            "(._;>;);\n"
            "out geom;\n"
        )

    def _tile_bbox(self, bbox: str, max_span: float = 0.25) -> List[str]:
        # split large bbox into <= max_span degree tiles
        try:
            y_min, x_min, y_max, x_max = map(float, bbox.split(','))
        except ValueError:
            return [bbox]
        if y_max <= y_min or x_max <= x_min:
            return [bbox]
        lat_span = y_max - y_min
        lon_span = x_max - x_min
        if lat_span <= max_span and lon_span <= max_span:
            return [bbox]
        tiles: List[str] = []
        lat = y_min
        eps = 1e-9
        while lat < y_max - eps:
            next_lat = min(lat + max_span, y_max)
            lon = x_min
            while lon < x_max - eps:
                next_lon = min(lon + max_span, x_max)
                tiles.append(f"{lat:.8f},{lon:.8f},{next_lat:.8f},{next_lon:.8f}")
                lon = next_lon
            lat = next_lat
        return tiles or [bbox]

    def _download_and_store_theme(
        self,
        theme: OsmTheme,
        bbox: str,
        clip_geom: QgsGeometry,
        target_crs: QgsCoordinateReferenceSystem,
    ) -> int:
        layers: List[Tuple[QgsVectorLayer, str]] = []
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
        theme_dir = self._osm_theme_path(theme.key)
        self._write_theme_to_gpkg(theme_dir, layers)
        self._load_theme_layers(theme, theme_dir)
        return total

    def _fetch_overpass_elements(self, spec: OsmLayerSpec, bbox: str) -> List[dict]:
        if not hasattr(self, "_overpass_url_index"):
            self._overpass_url_index = 0
        tiles = self._tile_bbox(bbox)
        combined: Dict[Tuple[str, int], dict] = {}
        for tile in tiles:
            query = self._compose_overpass_query(spec, tile)
            payload = self._download_overpass_payload(query, tile)
            try:
                parsed = json.loads(payload.decode("utf-8"))
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"Invalid response from Overpass for bbox {tile}: {exc}") from exc
            for element in parsed.get("elements", []):
                elem_type = element.get("type")
                elem_id = element.get("id")
                if elem_type is None or elem_id is None:
                    continue
                combined[(elem_type, elem_id)] = element
        return list(combined.values())

    def _download_overpass_payload(self, query: str, tile: str) -> bytes:
        retryable = {429, 502, 503, 504}
        max_attempts = 3

        # Try both urlencoded and raw payloads; some mirrors prefer one or the other.
        form_payload = urllib.parse.urlencode({"data": query}).encode("utf-8")
        raw_payload = query.encode("utf-8")
        payloads = [
            ("application/x-www-form-urlencoded; charset=utf-8", form_payload),
            ("text/plain; charset=utf-8", raw_payload),
        ]
        last_error: Optional[Exception] = None
        start_index = getattr(self, "_overpass_url_index", 0)

        for offset in range(len(self.OVERPASS_URLS)):
            idx = (start_index + offset) % len(self.OVERPASS_URLS)
            url = self.OVERPASS_URLS[idx]
            for attempt in range(max_attempts):
                should_retry = False
                for content_type, data in payloads:
                    headers = self._overpass_headers(content_type)
                    request = urllib.request.Request(url, data=data, headers=headers)
                    try:
                        with urllib.request.urlopen(request, timeout=180) as resp:
                            # lock in the successful mirror for previews
                            self._overpass_url_index = idx
                            return resp.read()
                    except urllib.error.HTTPError as exc:
                        last_error = exc
                        if exc.code in retryable:
                            retry_after = exc.headers.get("Retry-After")
                            delay = None
                            if retry_after:
                                try:
                                    delay = float(retry_after)
                                except ValueError:
                                    delay = None
                            if delay is None:
                                delay = min(2 ** attempt, 60.0)
                            time.sleep(delay)
                            should_retry = True
                            break  # break out of payload loop, keep same attempt number
                        elif content_type == payloads[0][0]:
                            # try the raw payload before giving up this attempt
                            continue
                        else:
                            raise RuntimeError(
                                f"Overpass request failed for {tile} via {url}: HTTP {exc.code} {exc.reason}"
                            ) from exc
                    except urllib.error.URLError as exc:
                        last_error = exc
                        time.sleep(min(2 ** attempt, 30.0))
                        should_retry = True
                        break
                if not should_retry:
                    break
            # if we get here, either non-retryable or exhausted attempts; try next mirror or raise below
            if last_error is None:
                raise RuntimeError(f"Overpass request failed for bbox {tile}: unknown error")
            if not isinstance(last_error, (urllib.error.HTTPError, urllib.error.URLError)) or getattr(last_error, "code", None) not in retryable:
                raise RuntimeError(f"Overpass request failed for bbox {tile} via {url}: {last_error}") from last_error

        # All mirrors failed
        raise RuntimeError(f"Overpass request failed for bbox {tile}: {last_error}")

    def _overpass_headers(self, content_type: str) -> Dict[str, str]:
        # Build a helpful User-Agent and include contact if configured.
        agent_cfg = get_persistent_setting("network/user_agent", "").strip()
        contact = get_persistent_setting("network/contact_email", "").strip()
        if agent_cfg:
            agent = agent_cfg
        else:
            try:
                qv = QgsApplication.applicationVersion()
            except Exception:
                qv = "QGIS"
            agent = f"HexMosaic/{qv} (QGIS plugin)"
            if contact:
                agent = f"{agent} contact:{contact}"

        headers = {
            "Content-Type": content_type,
            "User-Agent": agent,
            "Accept": "application/json",
        }
        # Overpass encourages a From header
        if contact:
            headers["From"] = contact
        return headers

    # -------------------- JSON → layer --------------------

    def _elements_to_layer(
        self,
        spec: OsmLayerSpec,
        elements: Sequence[dict],
        clip_geom: QgsGeometry,
        target_crs: QgsCoordinateReferenceSystem,
    ) -> Optional[QgsVectorLayer]:
        if not elements:
            return None
        wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        transform_context = QgsProject.instance().transformContext()
        to_target = None
        if target_crs.isValid() and target_crs.authid() != wgs84.authid():
            to_target = QgsCoordinateTransform(wgs84, target_crs, transform_context)
        mem_layer = self._create_memory_layer(spec.display_name, spec.geometry, target_crs)

        # Brute-collect tag keys across all features to build a stable schema.
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
            if to_target:
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

    # -------------------- Local source import --------------------

    def _import_local_theme(
        self,
        theme: OsmTheme,
        source_path: str,
        clip_geom: QgsGeometry,
        target_crs: QgsCoordinateReferenceSystem,
    ) -> int:
        layers: List[Tuple[QgsVectorLayer, str]] = []
        total = 0
        sublayers: List[str] = []
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
            theme_dir = self._osm_theme_path(theme.key)
            self._write_theme_to_gpkg(theme_dir, layers)
            self._load_theme_layers(theme, theme_dir)
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

    def _clip_and_prepare_layer(
        self,
        layer: QgsVectorLayer,
        geometry_kind: str,
        clip_geom: QgsGeometry,
        target_crs: QgsCoordinateReferenceSystem,
    ) -> Optional[QgsVectorLayer]:
        src_crs = layer.crs()
        transform = (
            QgsCoordinateTransform(src_crs, target_crs, QgsProject.instance().transformContext())
            if src_crs != target_crs
            else None
        )
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

    # -------------------- Write / Load into project --------------------

    def _remove_layers_for_path(self, path: str) -> None:
        """Drop any loaded vector layers backed by the given dataset path."""
        proj = QgsProject.instance()
        target = os.path.normcase(os.path.abspath(path))
        for layer in list(proj.mapLayers().values()):
            if not isinstance(layer, QgsVectorLayer):
                continue
            source = layer.dataProvider().dataSourceUri() if layer.dataProvider() else layer.source()
            if not source:
                continue
            src_path = source.split("|", 1)[0]
            try:
                src_norm = os.path.normcase(os.path.abspath(src_path))
            except Exception:
                continue
            if src_norm == target:
                proj.removeMapLayer(layer.id())

    def _write_theme_to_gpkg(self, theme_dir: str, layers: Sequence[Tuple[QgsVectorLayer, str]]):
        # We currently write ESRI Shapefiles per layer name inside theme_dir.
        # (Kept as-is to match your existing loader and styles.)
        os.makedirs(theme_dir, exist_ok=True)
        from qgis.core import QgsVectorFileWriter
        for lyr, name in layers:
            safe_name = self._sanitize_layer_name(name)
            shp_path = os.path.join(theme_dir, f"{safe_name}.shp")
            self._remove_layers_for_path(shp_path)
            base, _ = os.path.splitext(shp_path)
            # Clean previous artifacts
            for ext in (".shp", ".shx", ".dbf", ".prj", ".cpg", ".qix", ".qmd"):
                candidate = base + ext
                if os.path.exists(candidate):
                    try:
                        os.remove(candidate)
                    except Exception:
                        pass
            result = QgsVectorFileWriter.writeAsVectorFormat(
                lyr,
                shp_path,
                "UTF-8",
                lyr.crs(),
                "ESRI Shapefile",
                onlySelected=False,
                layerOptions=["ENCODING=UTF-8"],
            )
            if isinstance(result, tuple):
                err, msg = result
            else:
                err, msg = result, ""
            if err != QgsVectorFileWriter.NoError:
                raise RuntimeError(f"Failed to write layer {name} to {shp_path}: {msg}")

    def _load_theme_layers(self, theme: OsmTheme, theme_dir: str):
        proj = QgsProject.instance()
        osm_group = self._ensure_group("OSM")
        theme_group = next((g for g in osm_group.findGroups() if g.name() == theme.label), None)
        if theme_group is None:
            theme_group = osm_group.addGroup(theme.label)
        self._remove_theme_layers_from_project(theme)
        for spec in theme.layers:
            safe_name = self._sanitize_layer_name(spec.storage_name)
            shp_path = os.path.join(theme_dir, f"{safe_name}.shp")
            layer = QgsVectorLayer(shp_path, spec.display_name, "ogr")
            if not layer.isValid():
                self.log(f"OSM import: Failed to load {spec.storage_name} from {shp_path}")
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

    # -------------------- Styles --------------------

    def _sanitize_layer_name(self, name: str) -> str:
        return "".join(c if c.isalnum() or c in ("_", "-", ".") else "_" for c in name)

    def _apply_osm_style(self, theme_key: str, spec: OsmLayerSpec, layer: QgsVectorLayer):
        # First try user-configured styles dir
        styles_dir = get_persistent_setting("paths/styles_dir", "").strip()
        if styles_dir:
            qml = os.path.join(styles_dir, "osm", theme_key, f"{spec.storage_name}.qml")
            if os.path.isfile(qml):
                res, _ = layer.loadNamedStyle(qml)
                if res:
                    layer.triggerRepaint()
                    return
        # Fallback simple renderer per geometry (visual sanity)
        from qgis.core import QgsFillSymbol, QgsLineSymbol, QgsMarkerSymbol, QgsSingleSymbolRenderer
        if spec.geometry == "polygon":
            sym = QgsFillSymbol.createSimple({"color": "146,196,125,120", "outline_color": "60,120,60"})
            layer.setRenderer(QgsSingleSymbolRenderer(sym))
        elif spec.geometry == "line":
            sym = QgsLineSymbol.createSimple({"line_color": "52,101,164", "line_width": "0.8", "line_width_unit": "MM"})
            layer.setRenderer(QgsSingleSymbolRenderer(sym))
        else:
            sym = QgsMarkerSymbol.createSimple({"name": "circle", "color": "52,101,164", "size": "2"})
            layer.setRenderer(QgsSingleSymbolRenderer(sym))
        layer.triggerRepaint()

    # -------------------- Abstract hooks provided by Dock --------------------

    def _ensure_group(self, name: str):
        """Return (or create) a QgsLayerTreeGroup named 'name' under the project root."""
        raise NotImplementedError

    def _project_root(self) -> str:
        """Return the project root directory where /OSM/ and styles live."""
        raise NotImplementedError

    def _utm_epsg_for_lonlat(self, lon: float, lat: float) -> int:
        """Return a UTM EPSG code for the provided lon/lat."""
        raise NotImplementedError

    # -------------------- Path helpers --------------------

    def _osm_theme_path(self, theme_key: str) -> str:
        root = self._project_root()
        out_dir = os.path.join(root, "OSM", theme_key)
        os.makedirs(out_dir, exist_ok=True)
        return out_dir
