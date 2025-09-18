# Agent Task Recipes

These playbooks outline end-to-end flows the automation agent can follow. Always cross-check `docs/dev-setup/` for environment prep and `docs/agent/cheatsheet.md` for quick commands before starting.

## How To Use These Recipes
- Confirm you are on a clean branch (`git status`) and sync with `master` before modifying files.
- Each recipe lists the primary code touchpoints, configs, and expected outputs. If you see unexpected local changes in those files, stop and ask for human guidance.
- Validation steps are mandatory unless the repository state prevents them (note the reason in the PR description).
- Run `python scripts/check-qgis.py` before any QGIS-dependent validation; if it exits non-zero, skip those steps and record `QGIS unavailable` in your notes/PR template.
- When encountering missing context, search the repository (`rg`, `git grep`, or IDE search) and review the linked files before escalating.

## Recipe Template (for future entries)
1. **Prep** - files to inspect, configs to load, existing behaviour to understand.
2. **Implementation** - ordered tasks (UI wiring, utilities, data updates, tests, docs).
3. **Validation** - commands and manual checks required before opening a PR.
4. **Escalation triggers** - when to stop and ask for clarification.

---

## Hex Elevation Palette Layer (Current Priority)
Goal: Deliver the first milestone of the Hex Mosaic Palette initiative by creating a hex-aligned elevation layer that mirrors DEM styling and exposes per-hex values for downstream exports.

### Context
- README quick start items 7-9 and `## 5) Generate Hex Elevation Layer` describe the expected workflow.
- UI hooks live under the Elevation tab in `hexmosaic_dockwidget.py` (look near existing DEM download handlers).
- Hex sampling utilities should live in a new module (`utils/elevation_hex.py` or similar) with unit coverage.
- Output shapefiles belong in `<Project>/Layers/Elevation/HexPalette/` and must load into the layer tree under **Elevation > Hex Palette**.

### Recipe 1 - Surface the UI entry point

**Prep**
- Review existing Elevation tab widgets and signals in `hexmosaic_dockwidget.py`.
- Identify how DEM selection and hex layer selection are currently exposed (combos populated via `_populate_layers`).

**Implementation**
1. Add controls for selecting the DEM raster, hex layer, sampling method (mean/median/min), bucket size, and output overwrite toggle.
2. Wire the **Generate Hex Elevation Layer** button to a new slot that validates selections and kicks off a `QgsTask` for background processing.
3. Ensure the task dialog surfaces progress, cancellation, and user-facing error messages.
4. Persist last-used options in project settings via `_collect_ui_settings` / `_apply_ui_settings`.

**Validation**
- Manual: create a small AOI, build the grid, download a DEM, and confirm the button enables/disables appropriately.
- Automated: add a UI smoke test (e.g., using `QTest`) that verifies the controls appear and validation blocks empty selections. When running in a cloud workspace, call `python scripts/check-qgis.py` first and fall back to `pytest -m "not qgis_required"` if the guard passes; otherwise log that QGIS validation was skipped.

**Escalation**
- If the UI layout overflows the current tab, capture a screenshot and ask for layout direction before rearranging other controls.

### Recipe 2 - Implement the elevation sampler

**Prep**
- Inspect existing raster sampling helpers (search for `sample_raster` or zonal statistics usage).
- Decide on raster aggregation defaults (mean, floor, bucket size) and how to handle nodata pixels.

**Implementation**
1. Create a helper module (e.g., `utils/elevation_hex.py`) that accepts a raster layer, feature iterator, sampling method, and bucket size.
2. Use `QgsZonalStatistics` or manual `QgsRasterDataProvider` sampling to compute per-hex elevation summaries.
3. Quantize samples into integer buckets (`elev_bucket`) while keeping the raw floating value (`elev_value`).
4. Return structured results with error handling for nodata coverage, mixed CRS, or failed providers.
5. Add unit tests with synthetic raster/hex fixtures to cover mean vs median behaviour, nodata cases, and bucket rounding.

**Validation**
- Unit tests pass locally (`pytest test/test_elevation_hex.py`). In cloud environments gate this with `python scripts/check-qgis.py`; when it fails, document the skipped marker instead of attempting to run QGIS-backed tests.
- Manual spot-check: compare a few sampled hexes against the DEM using the identify tool.

**Escalation**
- Significant performance issues (>2s per 1k hexes) after basic optimisation - capture profiling info before pausing.

### Recipe 3 - Persist, style, and register outputs

**Prep**
- Review `hexmosaic_dockwidget.py` for existing shapefile writers and style application helpers.
- Locate DEM styling logic (`_apply_style`) to reuse palette/colour ramp metadata.

**Implementation**
1. Write the sampled hex features to `<Project>/Layers/Elevation/HexPalette/<AOI>_hex_elevation.shp`, overwriting only when the user opts in.
2. Add metadata attributes: `elev_value`, `elev_bucket`, `dem_source`, `bucket_method`, `generated_at`.
3. Load the layer into the project under **Elevation > Hex Palette** and apply DEM-derived styling (fallback to `styles/elevation_hex.qml`).
4. Update export helpers so this layer can be toggled alongside other elevation products.
5. Log a concise summary (hex count, min/max bucket, duration) to assist QA.

**Validation**
- Manual: run end-to-end with a real DEM and confirm the layer appears with uniform colour per hex.
- Automated: extend integration tests, but gate them with `python scripts/check-qgis.py` and the `qgis_required` marker so they only run when a QGIS runtime is present; otherwise record that the check was skipped.

**Escalation**
- Style cloning fails across QGIS versions - capture layer XML dumps and request design input.

### Supporting Tasks
- Add a lightweight guard (`scripts/check-qgis.py`) and mark QGIS-bound tests with `@pytest.mark.qgis_required` so agents can run `pytest -m "not qgis_required"` when QGIS is unavailable.
- Update `docs/howtos/` with a focused "Generate Hex Elevation Layer" walkthrough once the feature stabilises.
- Add regression fixtures (small raster + hex grid) under `test/fixtures/elevation_hex/`.
- Coordinate with design on palette quantisation thresholds before finalising defaults.

---


### Recipe 3 - Manage secrets, caching, and data dependencies

**Prep**
- Inventory required secrets (`OPENTOPOGRAPHY_API_KEY`, map service tokens, etc.) and determine which jobs need them.
- Identify large downloads (pip cache, QGIS packages, sample datasets) worth caching between runs.
- Review the platform's secret and cache policies for retention and size limits.

**Implementation**
1. Register required secrets in the CI platform and map them to environment variables without echoing values in logs.
2. Configure dependency caching (e.g., `~/.cache/pip`, apt/dnf caches, generated datasets) with cache keys tied to `requirements` hashes and QGIS package versions.
3. Persist large artifacts that downstream jobs need (packaged plugins, generated docs) and prune them after use when storage is limited.
4. Update `docs/dev-setup/cloud.md` or workflow README comments with any platform-specific nuances uncovered.

**Validation**
- Successful pipeline runs demonstrate cache hits (`Cache restored` style logs) and reduced execution time compared to cold runs.
- Workflows that require secrets can access them without leaking values; rerun with debug logging disabled to confirm.
- Artifact downloads succeed for reviewers or deployment jobs.

**Escalation**
- Secrets cannot be stored due to policy or legal constraints�stop and request guidance.
- Cache restores become unstable or corrupted; gather logs before purging caches and escalating.

---

## AOI Segmentation Feature (Backlog)
Goal: Extend the Map Area tab so oversized AOIs can be subdivided into game-ready child maps either by equal grid tiling or by clustering around points of interest (POIs).

### Context
- UI lives in `hexmosaic_dockwidget.py` (`pg_aoi` section around lines 170-220).
- AOIs are persisted as shapefiles under `<Project>/Layers/Base/` (`create_aoi` method ~1860ff).
- README high-level description: `README.md` > "2) Map Area (AOI)" and TODO backlog (Medium priority, AOI segmentation bullet).
- Any segmentation metadata should align with forthcoming export workflows (see `export_png_direct` around line 1600).


### Recipe 1 - Enable "Experimental AOI Sizes" Toggle
This unlocks AOIs wider/taller than 99 hexes to support segmentation workflows.

**Prep**
- Inspect `_recalc_aoi_info` (`hexmosaic_dockwidget.py:1702-1776`) to understand current validation logic.
- Review README instructions for AOI creation to mirror terminology.

**Implementation**
1. Add a checkbox (e.g., `self.chk_experimental_aoi`) beneath the Map Area sizing controls with explanatory tooltip.
2. Modify `_recalc_aoi_info` so the 99-hex guard only applies when the checkbox is unchecked; when checked, display a warning label instead of disabling "Create AOI".
3. Persist the checkbox state in per-project settings (`hexmosaic.project.json`) via `_collect_ui_settings` / `_apply_ui_settings`.
4. Update `README.md` (Map Area section) and `docs/dev-setup/local.md` warning tables to mention the experimental mode.

**Validation**
- Manual: create an AOI of 150x150 hexes with the checkbox enabled; ensure the shapefile writes successfully and log shows a caution.
- Automated: run `pytest test/test_hexmosaic_dockwidget.py` (add/update tests if feasible), but only after `python scripts/check-qgis.py` succeeds; otherwise log that QGIS validations were skipped.

**Escalation**
- If widening the AOI causes memory errors or layout glitches, pause and consult maintainers.

### Recipe 2 - Equal Grid Segmentation
Split a large AOI into seamless tiles based on user-specified rows/columns that honour the hex grid.

**Prep**
- Determine how child AOIs should be stored: proposed path `<Project>/Layers/Base/Base_Grid/<Parent_AOI>/Segments/Segment_<row>_<col>.shp`.
- Decide on naming convention and metadata (embed parent AOI name, row/col indices, resulting hex counts).
- Review QGIS geometry APIs for slicing polygons (`QgsGeometry.splitGeometry`, `QgsGeometry.boundingBox`, or grid processing algorithms`).

**Implementation**
1. Extend Map Area UI with segmentation controls (e.g., a "Segment AOI" button and inputs for rows/columns). Consider a modal dialog to collect options.
2. Add a new method (e.g., `segment_aoi_equal_grid(self, aoi_layer, rows, cols)`) that:
   - Validates rows/columns > 0.
   - Computes segment boundaries aligned to the AOI extent snapped to hex multiples.
   - Creates new polygon geometries for each segment.
   - Writes each segment to disk and loads into a Layer group (`Base > Segments > <Parent>`).
   - Captures metadata (JSON) stored alongside the AOI or in `hexmosaic.project.json` for later export.
3. Ensure generated segments update the AOI dropdowns (`_populate_aoi_combo`) if they should be selectable elsewhere.
4. Provide undo/cleanup: allow the user to delete all generated segments from the UI.
5. Add docstrings and comments to help future agents navigate the logic.

**Validation**
- Manual: create a 200x200 hex AOI, segment into 2x2 grid, confirm four shapefiles appear and align without gaps/overlap.
- Automated: add unit tests under `test/` using synthetic AOIs and verifying segment counts and extents; skip automatically when `python scripts/check-qgis.py` reports QGIS unavailable.

**Escalation**
- If geometry splitting fails for concave AOIs, document the limitation and ask for human guidance before proceeding.

### Recipe 3 - POI-Aware Segmentation
Break an oversized AOI into child maps that prioritize coverage of important POIs (cities, landmarks) from OSM.

**Prep**
- Identify POI data source: leverage existing OSM import (future) or fetch via Overpass. Start with city/town points (`place=city|town`) stored under `Layers/OSM/`.
- Determine heuristics: target # of child maps, max hex width/height per map, acceptable overlap percentage.
- Decide on data structures to store POI assignments (e.g., new JSON section in `hexmosaic.project.json`).

**Implementation**
1. Build/extend a helper to fetch POIs within the AOI (processing algorithm: `native:extractbylocation` or direct layer filter).
2. Implement clustering logic (e.g., k-means on POI coordinates, constrained by hex capacity) to propose segment centers.
3. For each cluster, derive a segment polygon sized to allowed hex limits, optionally allowing small overlaps to include edge POIs.
4. Reuse the shapefile-writing pipeline from Recipe 2 to persist segments and register metadata about included POIs.
5. Update the UI to present POI statistics (POIs included per segment) and allow the user to tweak target map count.
6. Document configuration hooks (e.g., default POI layers, max map size) in `data/hexmosaic.config.json` and README.

**Validation**
- Manual: use a sample AOI with known city points; verify generated segments include listed POIs and stay within size limits.
- Automated: create synthetic POI datasets in `test/fixtures` and assert segment counts and membership, but only run these when `python scripts/check-qgis.py` passes; otherwise capture the skip.

**Escalation**
- If POI data is unavailable or incomplete, provide a graceful fallback (equal grid) and log guidance; escalate only if both modes fail.

### Supporting Tasks
- Update `docs/architecture/data_flow.md` with the new segmentation pipeline once implemented.
- Add how-to content under `docs/howtos/` ("Segment AOI into child maps").
- Expand `docs/tests.md` to describe new test coverage (unit + integration).
- Ensure changelog entries and README sections are refreshed when the feature ships.

---

Keep this document current after each recipe is executed. Outdated steps slow agents down and create duplicate work.
