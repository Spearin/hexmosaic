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

   * **Download SRTM for AOI** (OpenTopography) → auto-adds to **Elevation** and styles it.
     – or –
   * Browse **DEM file** and **Apply Style to Layer**.
8. **7. Export Map**:

   * **Refresh Layers** to mirror the layer tree.
   * Check the groups/layers to export.
   * Pick AOI (Export) → **Compute** → **Export PNG (direct)**.
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
* Click **Create AOI**:

  * Saves a polygon shapefile to `<Project>/Layers`.
  * Adds it under **Base** and zooms to it.
  * If `aoi.qml` exists in **Styles directory**, it’s applied automatically.

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

## 5) Import OSM (Design Preview — upcoming)

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

## 6) Hex Mosaic Palette (Design Preview — upcoming)

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
