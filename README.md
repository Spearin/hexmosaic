# HexMosaic — User Guide

This plugin helps you build Flashpoint Campaigns map projects in QGIS with a predictable folder/group structure, easy area of interest (AOI) creation, accurate hex grid generation, automated elevation data downloads, and one-click export.

---

## Requirements

* QGIS 3.22+ (Processing “native” provider enabled)
* Internet access for basemap tiles & DEM downloads
* (Optional) OpenTopography API key

---

## Quick Start

1. Open **HexMosaic** (Plugins ▶ HexMosaic ▶ Open).
2. In **1. Setup**, set:

   * **Project directory** → where to create `/Layers` and `/Export`.
   * **Styles directory** → folder with your `.qml` styles (see “Styles” below).
   * **Hex scale (m)** → base hex size (e.g., `500`).
   * **OpenTopography API key** (optional, for DEM downloads).
     Click **Save Settings**.
3. Click **Generate Project Structure**:

   * Creates folders: `<Project>/Layers` and `<Project>/Export`.
   * Creates/Orders groups **Mosaic**, **OSM**, **Base**, **Elevation**, **Reference** (top→bottom).
   * Adds **OpenTopoMap** basemap to **Reference** (if not present).
4. Set an anchor & correct CRS (recommended):

   * **Set Anchor at Canvas Center** → saves a WGS84 “Project Anchor”.
   * **Set Project CRS from Anchor** → sets a UTM CRS based on anchor location.
5. Go to **2. Map Area**:

   * Choose **meters** or **hexes**.
   * Enter Width/Height → **Create AOI**. (Saved to `/Layers`, loaded under **Base**.)
6. Go to **3. Generate Grid**:

   * Pick your AOI → **Build Hex Grid**.
   * Creates shapefiles under `Layers/Base/Base_Grid/<AOI Name>` and loads:
     **Hex Tiles**, **Hex Grid Edges**, **Intersection Helpers**, **Centroid Helpers**.
7. (Optional) **4. Set Elevation Heightmap**:

   * **Download SRTM for AOI** (OpenTopography) - auto-adds to **Elevation** and styles it.
   * Browse **DEM file** and **Apply Style to Layer** if you already have a raster on disk.

8. (Optional) **5. Generate Hex Elevation Layer**:

   * Pick the DEM and **Hex Tiles** layers in the Elevation tab.
   * Click **Generate Hex Elevation Layer** to sample the DEM under each hex, save a new polygon layer, and reuse the DEM palette.
   * Confirm the new layer appears under **Elevation > Hex Palette** with `elev_value` and `elev_bucket` attributes ready for export.

9. **7. Export Map**:

   * **Refresh Layers** to mirror the layer tree.
   * Check the groups/layers to export.
   * Pick AOI (Export) - **Compute** - **Export PNG (direct)**.
     PNG is written to `<Project>/Export`.

---

## 1) Setup

### Fields & Buttons

* **Project name / Author**: metadata (optional).
* **Project directory**: where **/Layers** and **/Export** live.
* **Styles directory**: folder containing `.qml` style files.
* **Hex scale (m)**: size for snapping & grid spacing.
* **OpenTopography API key**: needed to download DEMs.

### Helpers

* **Generate Project Structure**
  Creates folders and the following top-level groups in this exact order:

  1. **Mosaic**
  2. **OSM**
  3. **Base** (also makes **Base Grid** sub-group)
  4. **Elevation**
  5. **Reference** (OpenTopoMap added if missing)

* **Add OpenTopoMap to Reference**
  Adds the XYZ basemap (no external plugin needed).

* **Set Anchor at Canvas Center**
  Creates/updates a WGS84 point layer “Project Anchor” at the current map center.

* **Set Project CRS from Anchor**
  Reads the anchor’s lon/lat → computes UTM zone → sets project CRS.

> Tip: Use the anchor+CRS buttons first, so your AOI and grid are in meters.

---

## 2) Map Area (AOI)

* Choose **meters** or **hexes**.
* **Use Canvas Extent** or **Use Anchor as Center** to prefill.
* Sizes snap to the hex scale.
* Toggle **Allow experimental AOI sizes** to bypass the 99×99 hex guard when you need oversized test areas. Expect heavier shapefiles and slower exports while enabled.
* Click **Create AOI**:

  * Saves a polygon shapefile to `<Project>/Layers`.
  * Adds it under **Base** and zooms to it.
  * If `aoi.qml` exists in **Styles directory**, it’s applied automatically.

* Pick a **Points of interest** layer to drive AOI centroids, then click **Create AOIs from POIs** to batch-generate AOIs centered on each feature (selected features are honored when present).

* Use **Segment AOI** to split an existing area of interest into an equal grid:

  * Pick the parent AOI from the dropdown, set **Rows × Columns**, and click **Segment AOI**.
  * Click **Preview Segments** to build a temporary, in-memory layer that visualizes the grid before any shapefiles are written.
  * Segments are saved to `<Project>/Layers/Base/Base_Grid/<AOI>/Segments/Segment_<row>_<col>.shp` and loaded under **Base ▸ Base Grid ▸ <AOI> ▸ Segments**.
  * Segment layers inherit AOI styling (or fall back to an outline) and appear in AOI selectors across the plugin.
  * Click **Delete Segments** to remove generated shapefiles and clear stored metadata if you need to re-run the segmentation.

---

## 3) Generate Grid

* Pick an AOI in the dropdown → **Build Hex Grid**:

  * Creates:

    * **Hex Tiles** (polygons) — named with hex size.
    * **Hex Grid Edges** (lines)
    * **Intersection Helpers** (points)
    * **Centroid Helpers** (points)
  * Saved to `Layers/Base/Base_Grid/<AOI Name>/…`
  * Loaded into **Base ▸ Base Grid ▸ <AOI Name>**.
  * Styles:

    * If `.qml` files are found (`hex_tiles.qml`, `hex_edges.qml`, `hex_vertices.qml`, `hex_centroids.qml`) they’re used.
    * Otherwise, sensible fallback symbology is applied.

---

## 4) Set Elevation Heightmap

### Option A — Download SRTM for AOI (OpenTopography)

* Click **Download SRTM for AOI**.
  The plugin:

  * Reads your selected AOI’s extent.
  * Pads **+1 km** on all sides to avoid corner cutoffs.
  * Calls OpenTopography (SRTM) and streams a GeoTIFF directly into:
    `Layers/Elevation/<AOI>_SRTM.tif`
  * Adds it to **Elevation**.
  * Auto-styles it by reading band 1 minimum elevation, rounding **down to the nearest 50**, and loading the elevation `.qml` whose filename begins with that base (e.g., `100.qml`, `-50.qml`).

> Dataset: defaults to SRTM (global). We’ll add a dataset dropdown (e.g., SRTMGL3 \~90 m, SRTMGL1 \~30 m) in a future iteration. The default will be **SRTMGL3 (90 m)**, with a fallback to SRTMGL1 if needed.

### Option B — Use an existing DEM

* **DEM file**: browse to a raster (GeoTIFF).
* **Apply Style to Layer**:

  * Uses the same **min-elevation → base 50** logic to auto-select the correct elevation style.
  * If no match, falls back to the style chosen in the dropdown (if any).

### CRS & Alignment Notes

* DEMs are typically delivered in geographic CRS (EPSG:4326). QGIS will reproject on-the-fly.
* Don’t manually change a DEM’s native CRS. If you need a project-CRS raster, *reproject* the DEM (Raster ▶ Projections ▶ Warp) **or** simply rely on OTF reprojection.
* The +1 km buffer around the AOI helps ensure DEM coverage fully overlaps your AOI in projected coordinates.

---

## 5) Generate Hex Elevation Layer (Hex Mosaic Palette phase 1)

The Hex Elevation layer converts the pixel-based DEM into a hex-aligned heightmap that matches the palette the game expects. Every hex receives a single representative elevation value and is rendered with the same colour ramp as the source DEM, eliminating noisy transitions.

### Requirements
- A generated **Hex Tiles** layer for the active AOI.
- A DEM layer loaded under **Elevation** and already styled with the desired palette.
- Project CRS in meters so zonal statistics operate on consistent geometry.

### Workflow
1. Open the **4. Set Elevation Heightmap** tab and locate the **Generate Hex Elevation Layer** controls.
2. Choose the DEM raster and **Hex Tiles** layer (defaults apply when only one candidate is found).
3. Select the sampling method (default: mean of DEM values clipped to each hex) and the elevation bucket size (default: 1).
4. Click **Generate Hex Elevation Layer**. The plugin samples the DEM, writes `<Project>/Layers/Elevation/HexPalette/<AOI>_hex_elevation.shp`, and loads it under **Elevation > Hex Palette**.
5. Review the attributes: `elev_value` (floating point sample), `elev_bucket` (rounded bucket), `dem_source` (raster id), and `bucket_method`.

### Styling and usage
- The layer inherits symbology from the DEM via `QgsMapLayerStyle`; if that fails, the fallback `styles/elevation_hex.qml` is applied.
- Toggle the new layer on/off to compare against the raw DEM.
- Use this layer when exporting palette-friendly heightmaps or when transferring data to the game editor.

### Troubleshooting
- **Missing DEM or hex tiles**: the action is disabled until both layers exist; load them and try again.
- **Mixed CRS warning**: reproject the DEM or regenerate the grid so both layers share the project CRS.
- **Unexpected flat values**: confirm the DEM covers the full AOI and adjust the bucket size if you need finer gradations.

---

## 6) Import OSM (Design Preview — upcoming)

> *This panel is a design preview so we can iterate before development.*

Planned workflow:

1. **AOI** dropdown + **Buffer (m)** (default 1000 m).
2. **Theme presets** (toggle any):

   * Roads (motorway→track), Rail
   * Water (rivers, lakes)
   * Landcover (landuse, natural)
   * Buildings
   * POI (selected categories)
3. **Download** via Overpass API:

   * Clip to AOI + buffer.
   * Save to `Layers/OSM/<theme>.gpkg` (one GPKG per theme; multiple layers inside).
   * Load under **OSM** group with theme-specific sub-groups.
4. **Styles**: apply `.qml` from `Styles/osm/<theme>/*.qml` if present; otherwise use curated defaults.
5. **Regenerate**: Re-running updates existing GPKGs.

We’ll also include a **“Refresh from OSM”** action to re-pull and re-clip with the same options.

---

## 7) Hex Mosaic Palette (Design Preview — upcoming)

Phase 1 delivers the hex-aligned elevation layer documented above; the interactive painting tools below remain in planning while we validate the palette workflow with real projects.




> *Design preview.*

Goals:

* Paint the **Hex Tiles** layer with a palette for scenario design & export.

Planned UI:

* **Palette** panel: named swatches (color + label), add/remove, import/export `.json`.
* **Tools**:

  * **Paintbrush** (single click)
  * **Fill by selection** (apply to all selected tiles)
  * **Fill by filter** (expression)
  * **Eyedropper** (pick color from tile)
* **Storage**:

  * Writes attributes on `Hex Tiles`:

    * `palette_id` (string), `palette_color` (rgba or hex), `palette_label` (string)
  * Renderer based on `palette_color`; optional label using `palette_label`.
* **Export helpers**:

  * Generate a legend for the current palette.
  * Save `.qml` style snapshot.

---

## 7) Export Map

* **Refresh Layers** to mirror the current layer tree.
* Check or uncheck groups/layers to include in the render.
* Pick **AOI** (Export), **Compute** to see:

  * **Pixels**: computed as **64 px per 500 m** (i.e., **0.128 px/m**).
  * **Page size** shown as reference (calculated at 128 dpi).
* **Export PNG (direct)** writes `<name>_<w>x<h>.png` to `<Project>/Export`.

> Tip: If results look off-scale, check (1) your **Project CRS** is projected (e.g. UTM), and (2) your AOI is in the same CRS.

---

## 8) Log

Everything the plugin does is logged here (download status, saved paths, errors, etc.).

---

## Styles

Put `.qml` files in your **Styles directory**.

**Names the plugin looks for:**

* AOI polygon: `aoi.qml`
* Grid:

  * `hex_tiles.qml`
  * `hex_edges.qml`
  * `hex_vertices.qml`
  * `hex_centroids.qml`
* Elevation:

  * Files beginning with a **base elevation** integer, e.g. `-50.qml`, `0.qml`, `100.qml`, `150.qml`, …
  * The plugin reads the DEM’s minimum elevation, rounds **down** to the nearest 50, and loads the matching file.

> If a style is missing, the plugin applies a clear, readable fallback.

---

## Project Configuration File (optional; recommended)

To keep project-specific settings with your QGIS project, the plugin can read/write a YAML/JSON file at your project root (planned to be automatic):

`<Project>/hexmosaic.yml` (example)

```yaml
project_name: MapName
author: Your Name
hex_scale_m: 500
paths:
  out_dir: "C:/Path/To/Maps/MapName"
  styles_dir: "C:/Path/To/Plugin/_styles"
opentopo:
  api_key: "…"
aoi:
  last_selected: "AOI 1 42000m x 27500m"
download:
  dem_dataset: "SRTMGL3"   # planned: default 90 m
  aoi_padding_m: 1000
```

On project open, HexMosaic will look for this file and hydrate the UI; on **Save Settings**, it will update the file.

---

## Troubleshooting

* **“Generate Project Structure” error / groups not ordered**
  Update the plugin to the version that uses clone-insert-remove for layer tree moves (works across QGIS bindings).
* **Basemap didn’t appear**
  Check internet access. Try **Add OpenTopoMap to Reference** again. Ensure **Reference** group exists.
* **DEM download failed**
  Verify your OpenTopography API key and AOI selection. Some corporate networks/proxies block downloads.
* **DEM added but style didn’t change**
  Ensure elevation styles exist and begin with a leading integer (e.g., `100.qml`). The plugin logs which base it looked for.
* **After adding DEM the view zooms oddly**
  Use **Export AOI** combo + **Compute** to confirm dimensions. If needed, zoom to the AOI layer manually. The download step tries to keep the map focused on your AOI.
* **PNG export size wrong**
  Make sure your **Project CRS** is projected in meters (e.g., UTM). AOI should be in that CRS too.

---

## Credits & Attribution

* Designed & Developed by Andrew Spearin, Producer, On Target Simulations Ltd.
* **OpenTopoMap** tiles: © OpenStreetMap contributors, SRTM | CC-BY-SA. Follow their attribution & usage terms.
* **Elevation**: SRTM (via OpenTopography.org). Check OpenTopography’s usage and API terms.

---

## Roadmap (high level)

* OSM Import (themes, clip to AOI+buffer, styling, re-pull)
* Hex Mosaic Palette (painting tools, palettes, legends)
* DEM dataset selector (default SRTMGL3 90 m)
* Project config auto-load/save (YAML/JSON)

## TODO — Prioritized (pragmatic, code-aligned)

This list was compiled by cross-checking the README's planned features with the current implementation in `hexmosaic_dockwidget.py`. Items marked "High" are blockers for a usable core workflow or important bug fixes; "Medium" are UX/robustness improvements; "Low" are polish or future enhancements.

High priority

* Implement OSM Import: the UI panel exists as a placeholder but the import/Overpass workflow is not implemented. Required: AOI+buffer clipping, theme presets, save per-theme GPKG, and style application.

* Implement Hex Mosaic Palette (basic): the palette UI is a placeholder. Required: persistent palette storage, paintbrush (single-tile), fill-by-selection, basic exportable legend, and writing palette attributes to the Hex Tiles layer.

* Fix duplicate/contradictory project helpers: `hexmosaic_dockwidget.py` defines `_project_root` and `_export_dir` more than once and with inconsistent folder name casing ("Export" vs "export"). Consolidate these helpers and pick a single canonical export folder path to avoid unexpected behavior on save/export.

* Make DEM download padding metric and robust: `download_dem_from_opentopo` currently pads the AOI in degrees (pad ~= 0.01). Switch to using the existing `_bbox_wgs84_with_margin` helper (or compute a +1 km margin in a meter CRS) so downloads are reliable across latitudes.

* Add defensive tests for export & grid generation: write small unit/integration tests that cover `_compute_export_dims`, `export_png_direct` (happy path with a tiny synthetic AOI), and `build_hex_grid` (memory path). These catch regressions and make refactors safer.

Medium priority

* Allow experimental AOI sizes: add a Map Area checkbox to bypass the current 99-hex width/height guard for large test projects, while logging performance and export caveats.
* Provide AOI segmentation tools: let users split oversized AOIs into map-ready subareas (equal grid tiling and POI-driven segmentation using OSM POI data), generating the necessary AOI and export metadata.

* Improve elevation styling fallbacks: `_apply_best_elevation_style` is implemented, but enhance logging when candidates are missing and offer a configurable fallback style location. Add a UI affordance to show which style was chosen.

* Improve error handling & retries for OpenTopography downloads: add timeouts, retry policy, and clearer user messages in the Log panel when the network or API returns transient errors.

* OSM/DEM UX: enable progress feedback in the UI (progress bar or spinner) during long operations such as create grid, DEM download, reprojection (warp), and export.

* Consistent style discovery: ensure `_refresh_elevation_styles` and `_apply_style` consistently respect the `Styles directory` setting and handle relative vs absolute paths robustly on Windows.

Low priority

* Advanced palette features: eyedropper, import/export palettes (JSON), fill-by-filter expression editor, and renderer snapshot exports.

* Export helpers: auto-generate legend images and a small JSON manifest describing exported layers, palette metadata and export parameters.

* Packaging, CI and lint: add formatting/linting checks and CI pipelines (unit tests, flake/pylint) to prevent regressions across contributors.

Implemented / Completed (from `hexmosaic_dockwidget.py`)

* Setup UI with project and styles paths, save/load settings (QSettings + per-project JSON), and a settings dialog.
* Generate Project Structure: creates `Layers` and `Export` folders and ensures layer groups (Mosaic, OSM, Base, Elevation, Reference); adds OpenTopoMap.
* Anchor + CRS helpers: set anchor at canvas center and compute UTM project CRS from anchor.
* AOI creation: Create AOI shapefile, apply `aoi.qml` if present, add to `Base` group.
* Hex grid generation: create grid, clip to AOI, build helpers (edges, vertices, centroids), save shapefiles, build spatial indexes and style layers (QML or programmatic fallback).
* DEM download (OpenTopography) and reprojection attempt (warp); apply best elevation style by scanning `styles/elevation`.
* Export: compute pixel/page size and render checked layers to a PNG at exact pixel dimensions.

---

## Automated Mosaic Cleanup Pass — design

Purpose
* Perform an initial, automated cleanup of the Mosaic (Hex Tiles) using data from the OSM layers and the Elevation raster so the mosaic tiles reflect sensible, standardized terrain & features before manual editing.

Success criteria
* Each Hex Tile has a deterministic class (tile_type) and elevation bucket (elevation_tier).
* Edge artifacts (tiny slivers, isolated single-tile noise) are reduced.
* Clear, repeatable rules (config-driven) so runs are idempotent.

Inputs
* Hex Tiles layer (polygons) with centroids and tile IDs.
* OSM-derived vector layers (under Layers/OSM): roads, waterways, water polygons, landcover/buildings, rail, industrial, etc.
* Elevation raster(s) in Layers/Elevation.
* Project config (hex size, thresholds, priority_order, mosaic_rules) — uses hexmosaic.config.json and profile.

Outputs
* Updated Hex Tiles layer with attributes:
  - tile_type (string) — primary class from priority rules (e.g., Water, Urban, Fields, Forest, Bare, Mixed, Industrial, Marsh).
  - elevation_tier (int) — bucket index or base elevation (rounded down to nearest 50).
  - confidence (float 0–1) — classification score.
  - source_summary (json) — small summary (counts/percentages) of features supporting the decision.
* Optional: an audit layer (point per hex) with before/after values for QA.
* Log entries with counts, runtime, and error details.

High-level algorithm
1. Preparation
   - Ensure AOI/project CRS is projected (meters).
   - Load hex tile centroids (for sampling) and compute hex area.
   - Index OSM layers spatially (in-memory) for fast intersection queries.

2. Per-hex sampling & feature scoring
   - For each hex:
     a. Sample the elevation raster (mean, min, max) within the hex; compute elevation_tier = floor(min / 50) * 50.
     b. Compute area overlap fraction per OSM polygon class (e.g., landuse=forest % of hex area).
     c. Count/intersect line features by proximity rules (snap_to settings, center-to-edge, edge).
     d. Run "probes" (centroid and N slice points) if configured; each probe votes for a class.
   - Combine evidence into scores using config weights:
     score[class] = w_area * area_frac + w_centroid * centroid_vote + w_probes * probe_votes + w_edge * edge_presence
   - Apply priority_order as tiebreaker; require majority threshold (config polygon_coverage_majority) to select a tile_type; otherwise set Mixed or leave as Unknown.

3. Elevation tiling
   - Use elevation_tier to tag tiles. Optionally create separate elevation tiles (layers) or style rules keyed to elevation_tier.
   - Where elevation varies wildly inside the hex (min→max delta > threshold), flag for manual review and set confidence low.

4. Post-processing cleanup (morphological rules)
   - Remove tiny isolated islands: identify single-tile runs of a class surrounded by a different class and reassign to neighbor if confidence low and neighbor majority exceeds threshold.
   - Merge adjacent tiles with identical tile_type and elevation_tier for reporting (not geometry change).
   - Snap roads/water to centroids/edges according to mosaic_rules; promote long river corridors to Water tiles where configured.

5. Persist updates
   - Write attribute updates to Hex Tiles layer (transactional where possible).
   - Optionally export an audit GPKG with per-hex diagnostics.

Scoring & config-driven weights (suggested defaults)
* Area fraction weight: 0.6
* Centroid vote weight: 0.25
* Probe sampling weight: 0.1
* Edge/line feature boost: 0.05
* Minimum dominant threshold: 0.6 (use polygon_coverage_majority from config)
Make these configurable via hexmosaic.config.json or profile.

Edge cases & rules
* Multi-class ties: prefer higher-priority class from priority_order.
* Sparse OSM data: fallback to probes + elevation if area fractions insufficient.
* Water dominance: if water polygon area > 0.4 of hex area OR a river line crosses hex center, mark Water with high confidence.
* Urban/Industrial adjacency: where industrial polygon overlaps but surrounding hexes are urban/fields, use priority order + confidence smoothing to avoid checkerboarding.
* No-data elevation: mark elevation_tier as Null and set confidence lower; attempt to re-run when DEM becomes available.

Testing & validation
* Unit tests:
  - Scoring aggregation tests with synthetic area/probe inputs.
  - Elevation bucketing tests (min, negative, high values).
  - Island removal logic (small synthetic grids).
* Integration tests:
  - Run cleanup on a tiny synthetic AOI with known OSM features and a small raster (e.g., ten-by-ten sample) and assert expected tile_types.
* QA outputs:
  - Summary report: counts per tile_type, confidence histogram, flagged tiles list.
  - Exportable audit GPKG for manual review.

Performance considerations
* Batch-process tiles (vectorized queries) and reuse spatial indexes.
* Parallelize per-hex scoring where safe (thread/process pool), but persist writes single-threaded or transactional.
* Provide a progress indicator in the UI and ability to cancel.

Implementation roadmap (phased)
1. Core utilities (utils/mosaic_cleanup.py)
   - Functions: sample_elevation_in_polygon, area_fraction_by_attribute, probe_point_votes, compute_scores, choose_tile_type, assign_elevation_tier.
   - Unit tests for each function.
2. Classifier engine
   - Config-driven weights, priority handling, probe strategies.
   - Integrate with hexmosaic.config.json and profile defaults.
3. Orchestration & persistence
   - Background task runner (QGIS task) and UI hook "Run Mosaic Cleanup".
   - Transactional writes to Hex Tiles attributes and optional audit GPKG writer.
4. Elevation integration & styles
   - Auto-create or assign elevation_tier QML styles; optional generation of per-elevation tile layers.
5. QA, logging, and UI polish
   - Progress bar, cancel, summary report, and sample viewer.
   - Add "Preview" mode (do not write) and "Apply" mode.

Operational notes
* Expose a "dry-run" / "preview" toggle that outputs the audit layer only.
* Make thresholds and weights editable (settings dialog or per-project config).
* Encourage running cleanup after initial OSM import and DEM download.

Change proposal
* Append this section to README.md and add a new module file utils/mosaic_cleanup.py with unit tests under tests/test_mosaic_cleanup.py. I can create the initial utils module and a small unit test scaffold next — confirm and I will write the




