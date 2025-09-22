# HexMosaic

HexMosaic is a QGIS plugin that streamlines Flashpoint Campaigns map production. It assembles project folders, generates hex-aligned AOIs, downloads elevation data, imports OSM content, and produces styled mosaic layers ready for export.

## Requirements

- QGIS Desktop 3.22 or newer with the Processing "native" provider enabled.
- Internet access for OpenTopoMap tiles and OpenTopography DEM downloads.
- Optional: OpenTopography API key for higher DEM rate limits.

## Key Capabilities

- Guided setup that creates `Layers/` and `Export/` folders, populates layer groups, and stores per-project metadata.
- AOI creation and segmentation tools, including equal grid splits and map tile presets aligned to MGRS boundaries.
- Hex grid builder that outputs tile, edge, centroid, and helper layers with reusable styles.
- Elevation pipeline that downloads or reuses DEM rasters and converts them into hex-based elevation palettes.
- OSM importer with curated themes and automatic styling for hex mosaic automation.
- Mosaic palette automation that generates game-facing layers from OSM sources and manual touch-ups.
- Export tools that render selected layers to pixel-perfect PNGs and track dimensions for hand-off.

## Repository Layout

- `hexmosaic.py`, `hexmosaic_dockwidget.py` - plugin entry points that wire the dock widget together.
- `dockwidget/` - per-tab mixins (setup, AOI, segmentation, elevation, OSM, mosaic, export, project state).
- `utils/` - reusable helpers such as hex elevation generation and configuration writers.
- `profiles/` - palette configuration (`hexmosaic_profile.json`) and documentation describing class metadata.
- `styles/` - curated `.qml` symbology and catalog metadata (`layer_specs.csv`).
- `data/`, `scripts/`, `docs/` - supporting assets, automation scripts, and documentation scaffolding.
- `test/` - pytest suite with QGIS interface shims, fixtures, and unit tests.

## Quick Start

1. Launch QGIS and open **Plugins > HexMosaic > Open**.
2. In **1. Setup**, set the project output folder, styles folder, hex scale, and optional metadata; click **Save Settings**.
3. Run **Generate Project Structure** to create `Layers/`, `Export/`, and the root layer groups.
4. Use **Set Anchor at Canvas Center** followed by **Set Project CRS from Anchor** to lock the project into a UTM meter-based CRS.
5. On **2. Map Area**, define an AOI (by meters or hex counts) and click **Create AOI**. Segment it if you need smaller map tiles.
6. In **3. Generate Grid**, choose the AOI and build the hex grid to populate tiles, edges, centroids, and helper layers.
7. In **4. Elevation**, either download a DEM for the AOI or point to an existing raster, then generate the optional hex elevation layer.
8. Use **5. Import OSM** to fetch road, water, land cover, and building data into `Layers/OSM/`.
9. On **6. Hex Mosaic Palette**, select the classes to automate and generate the mosaic outputs under `Layers/Mosaic/`.
10. Open **7. Export Map**, refresh the layer list, choose what to render, and produce the final PNG in `Export/`.

## Workflow Reference

### 1. Setup

- Fields capture project name, author, output directory, styles directory, hex scale (meters), and OpenTopography API key.
- Helpers:
  - **Generate Project Structure** creates `Layers/` and `Export/` folders and layer groups (Mosaic, OSM, Base, Elevation, Reference).
  - **Add OpenTopoMap to Reference** ensures a base map tile layer is loaded.
  - **Set Anchor at Canvas Center** stores a WGS84 point used for CRS alignment.
  - **Set Project CRS from Anchor** computes the nearest UTM CRS and applies it to the project.
- Settings persist per project in `hexmosaic.project.json` and globally via QGIS `QSettings`.

### 2. Map Area and Segmentation

- AOI creation supports dimensions in meters or hex counts, canvas extent seeding, and center-on-anchor workflows.
- Experimental AOI sizes can be enabled for oversized studies; the plugin warns about performance impacts.
- Generated AOIs are saved to `Layers/Base/` and styled with `aoi.qml` when available.
- Segmentation tools:
  - **Segment AOI** splits the AOI into an equal grid (rows x columns) with an optional preview layer.
  - **Map Tile Grid** builds tiles aligned to preset map scales (1:25k-1:250k) and optional MGRS alignment or offsets.
  - Segment outputs live under `Layers/Base/Base_Grid/<AOI>/Segments/` and are tracked in `hexmosaic.project.json`.
  - **Delete Segments** removes generated shapefiles and clears metadata when you need to redo the split.

### 3. Hex Grid Generation

- **Build Hex Grid** writes:
  - `Hex Tiles` polygon layer sized to the configured hex scale.
  - `Hex Grid Edges`, `Intersection Helpers`, and `Centroid Helpers` supporting QA and automation.
- Each layer is saved under `Layers/Base/Base_Grid/<AOI>/` and loaded beneath **Base > Base Grid > <AOI>**.
- Styles are applied from the styles directory (`hex_tiles.qml`, `hex_edges.qml`, etc.) with programmatic fallbacks.

### 4. Elevation and Hex Heightmaps

- **Download DEM for AOI** talks to OpenTopography (SRTM, Copernicus, ALOS, ASTER) using a +1 km buffered extent, writes GeoTIFFs under `Layers/Elevation/`, and applies the best matching `styles/elevation/*.qml`.
- When offline, **DEM file** lets you browse to an existing raster and apply stored styles.
- **Generate Hex Elevation Layer** samples the DEM per hex, writes `Layers/Elevation/HexPalette/<AOI>_hex_elevation.shp`, and reuses the DEM palette so elevation buckets align with game expectations.
- Attributes include `elev_value`, `elev_bucket`, `dem_source`, and sampling metadata.

### 5. OSM Import

- Choose an AOI, buffer distance, and the preset themes (Roads and Rail, Water, Landcover, Buildings, Points of Interest).
- **Preview** shows the assembled Overpass query for inspection.
- **Download & Save** clips results to the buffered AOI, writes per-theme GPKGs (`Layers/OSM/<theme>.gpkg`), and reloads layers into the project.
- **Refresh Last** repeats the previous run, while **Import Local** registers existing data files.
- Theme styles are resolved from `styles/osm/<theme>/<layer>.qml`; missing styles use curated defaults.

### 6. Hex Mosaic Palette

- Loads the palette profile (`profiles/hexmosaic_profile.json`) and matching style catalog (`styles/layer_specs.csv`).
- The class list shows every palette option with checkboxes to automate or hold for manual edits.
- Detail pane lets you map polygon and line OSM layers, tweak area thresholds, buffers, and sampling steps.
- Actions:
  - **Generate Selected Classes** or **Generate All Classes** build layers under `Layers/Mosaic/<AOI>/` with correct naming and styles.
  - **Apply Style to Sources** restyles contributing OSM layers to match game symbology.
  - **Create Manual Layer** scaffolds a blank layer for hand digitizing when automation is inappropriate.
- Line classes support centerline and edge-following behaviors to keep features aligned to the hex grid.

### 7. Export and Logging

- **Refresh Layers** mirrors the project tree so you can toggle folders or individual layers for export.
- **Compute** displays pixel dimensions (0.128 px per meter at 500 m hexes) and reference page sizes at 128 dpi.
- **Export PNG (direct)** writes `<project>_<width>x<height>.png` to `Export/`.
- The **Log** tab records folder creation, downloads, automation runs, errors, and links to generated files for troubleshooting.

## Styles, Profiles, and Configuration

### Styles

- Place `.qml` files in the configured styles directory.
- Expected names: `aoi.qml`, `aoi_segment.qml`, `hex_tiles.qml`, `hex_edges.qml`, `hex_vertices.qml`, `hex_centroids.qml`.
- Elevation styles should be named with their base elevation (for example `-50.qml`, `0.qml`, `100.qml`) so automatic matching works.

### Profiles

- `profiles/hexmosaic_profile.json` defines palette classes, priorities, geometry types, and matching rules.
- Keep `target_layer` names aligned with `styles/layer_specs.csv` to guarantee style application.
- Reload the palette tab or restart QGIS after editing profiles.

### Persistence

- Per-project settings live in `hexmosaic.project.json` alongside `Layers/` and `Export/`.
- Global defaults (recent paths, API keys) are stored via QGIS `QSettings`.
- Use the settings dialog to inspect or reset persisted values without editing JSON manually.

## Development Notes

- Read `CONTRIBUTING.md` for detailed setup guidance, tooling expectations, and coding standards.
- Recommended workflow:
  - Create a Python virtual environment that matches the Python build bundled with QGIS.
  - Install development dependencies (`pip install -r requirements-dev.txt`) and pb_tool if you package the plugin.
  - Use `pb_tool deploy` or `make deploy` to link the plugin into your QGIS profile during development.
- Testing and quality:
  - Run `python -m pytest test` (or `make test`) before pushing changes.
  - Optional linters are wired through `make pylint` and `make pep8`.
  - Fixtures under `test/fixtures/` and `test/qgis_interface.py` stub QGIS APIs for headless runs.
- Regenerate assets with `make compile` (resources) and `make doc` (Sphinx help) when assets or docs change.

## In-Progress Features

### Automated Mosaic Cleanup Engine

- **Target user experience**
  - Provide a single action that scans the active hex grid, classifies each tile using OSM and elevation evidence, and flags unsure areas for review.
  - Allow users to run the cleanup in preview mode to inspect proposed changes before writing to disk.
  - Surface a summary (counts per class, confidence ranges) so planners know how much manual work remains.
- **Development requirements**
  - Implement sampling utilities (`utils/mosaic_cleanup.py`) to combine raster statistics, polygon overlaps, and line proximity scores per hex.
  - Add a scoring engine driven by profile weights (area, centroid, probe votes, edge boosts) with configurable thresholds.
  - Write transactional updates back to the Hex Tiles layer, preserving undo history and emitting audit GeoPackages for QA.
  - Integrate the workflow into the Mosaic tab with progress reporting, cancel support, and dry-run toggles.
  - Cover new utilities with unit tests (scoring, elevation bucketing, island cleanup) and an integration test using synthetic AOIs.

### Cleanup Preview and QA Reporting

- **Target user experience**
  - Offer a comparison view showing proposed tile classifications versus the current mosaic, highlighting conflicts.
  - Generate an audit package (GeoPackage + CSV) listing low-confidence tiles, islands, and anomalies for manual review.
  - Present a concise dashboard in the Log tab with statistics, elapsed time, and saved file locations.
- **Development requirements**
  - Extend the cleanup task to branch between preview and apply modes without duplicating logic.
  - Build lightweight report writers that summarise per-class counts, confidence histograms, and flagged tiles.
  - Add hooks in the logging subsystem to hyperlink generated reports and DEM/OSM sources.
  - Ensure outputs clean up gracefully when the user cancels or reruns the process with different settings.

### Scoring Profile Management

- **Target user experience**
  - Let advanced users adjust class priorities, polygon coverage thresholds, and probe weights without editing JSON by hand.
  - Store cleanup presets alongside existing palette profiles so teams can share tuned configurations.
  - Surface validation warnings when a configuration is incomplete or refers to missing styles or OSM layers.
- **Development requirements**
  - Expand the profile schema to capture cleanup weights, tile priority orders, and probe strategies.
  - Build a minimal editor (dialog or JSON loader) that reads and writes profiles and updates the cleanup engine live.
  - Validate configurations against the style catalog and available OSM themes before a run starts.
  - Document the profile format and extend automated tests to cover parsing edge cases.

## Troubleshooting

- **Layer order incorrect after setup** - upgrade to the release that uses clone-insert-remove for layer tree moves; earlier QGIS APIs sometimes miss reordering.
- **OpenTopoMap missing** - verify internet access and rerun **Add OpenTopoMap to Reference** after confirming the Reference group exists.
- **DEM download fails** - confirm the OpenTopography API key, inspect the AOI extent, and retry on a different network if behind a restrictive proxy.
- **DEM style not applied** - ensure elevation styles exist in the styles directory and begin with the minimum elevation value of the raster.
- **Export PNG size off** - make sure both the project and AOI layers use a projected CRS (for example UTM) before computing export dimensions.

## Credits

- Designed and developed by Andrew Spearin, On Target Simulations Ltd.
- OpenTopoMap tiles (c) OpenStreetMap contributors, SRTM; observe their attribution and usage terms.
- Elevation data provided through OpenTopography; respect the API usage policy.
