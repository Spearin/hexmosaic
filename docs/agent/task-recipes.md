# Agent Task Recipes

These playbooks outline end-to-end flows the automation agent can follow. Always cross-check `docs/dev-setup/` for environment prep and `docs/agent/cheatsheet.md` for quick commands before starting.

## How To Use These Recipes
- Confirm you are on a clean branch (`git status`) and sync with `master` before modifying files.
- Each recipe lists the primary code touchpoints, configs, and expected outputs. If you see unexpected local changes in those files, stop and ask for human guidance.
- Validation steps are mandatory unless the repository state prevents them (note the reason in the PR description).
- When encountering missing context, search the repository (`rg`, `git grep`, or IDE search) and review the linked files before escalating.

## Recipe Template (for future entries)
1. **Prep** – files to inspect, configs to load, existing behaviour to understand.
2. **Implementation** – ordered tasks (UI wiring, utilities, data updates, tests, docs).
3. **Validation** – commands and manual checks required before opening a PR.
4. **Escalation triggers** – when to stop and ask for clarification.

---

## AOI Segmentation Feature (Next Priority)
Goal: Extend the Map Area tab so oversized AOIs can be subdivided into game-ready child maps either by equal grid tiling or by clustering around points of interest (POIs).

### Context
- UI lives in `hexmosaic_dockwidget.py` (`pg_aoi` section around lines 170–220).
- AOIs are persisted as shapefiles under `<Project>/Layers/Base/` (`create_aoi` method ~1860ff).
- README high-level description: `README.md` > “2) Map Area (AOI)” and TODO backlog (Medium priority, AOI segmentation bullet).
- Any segmentation metadata should align with forthcoming export workflows (see `export_png_direct` around line 1600).

### Recipe 1 – Enable “Experimental AOI Sizes” Toggle
This unlocks AOIs wider/taller than 99 hexes to support segmentation workflows.

**Prep**
- Inspect `_recalc_aoi_info` (`hexmosaic_dockwidget.py:1702-1776`) to understand current validation logic.
- Review README instructions for AOI creation to mirror terminology.

**Implementation**
1. Add a checkbox (e.g., `self.chk_experimental_aoi`) beneath the Map Area sizing controls with explanatory tooltip.
2. Modify `_recalc_aoi_info` so the 99-hex guard only applies when the checkbox is unchecked; when checked, display a warning label instead of disabling “Create AOI”.
3. Persist the checkbox state in per-project settings (`hexmosaic.project.json`) via `_collect_ui_settings` / `_apply_ui_settings`.
4. Update `README.md` (Map Area section) and `docs/dev-setup/local.md` warning tables to mention the experimental mode.

**Validation**
- Manual: create an AOI of 150x150 hexes with the checkbox enabled; ensure the shapefile writes successfully and log shows a caution.
- Automated: run `pytest test/test_hexmosaic_dockwidget.py` (add/update tests if feasible).

**Escalation**
- If widening the AOI causes memory errors or layout glitches, pause and consult maintainers.

### Recipe 2 – Equal Grid Segmentation
Split a large AOI into seamless tiles based on user-specified rows/columns that honour the hex grid.

**Prep**
- Determine how child AOIs should be stored: proposed path `<Project>/Layers/Base/Base_Grid/<Parent_AOI>/Segments/Segment_<row>_<col>.shp`.
- Decide on naming convention and metadata (embed parent AOI name, row/col indices, resulting hex counts).
- Review QGIS geometry APIs for slicing polygons (`QgsGeometry.splitGeometry`, `QgsGeometry.boundingBox`, or grid processing algorithms).

**Implementation**
1. Extend Map Area UI with segmentation controls (e.g., a “Segment AOI” button and inputs for rows/columns). Consider a modal dialog to collect options.
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
- Automated: add unit tests under `test/` using synthetic AOIs and verifying segment counts and extents.

**Escalation**
- If geometry splitting fails for concave AOIs, document the limitation and ask for human guidance before proceeding.

### Recipe 3 – POI-Aware Segmentation
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
- Automated: create synthetic POI datasets in `test/fixtures` and assert segment counts and membership.

**Escalation**
- If POI data is unavailable or incomplete, provide a graceful fallback (equal grid) and log guidance; escalate only if both modes fail.

### Supporting Tasks
- Update `docs/architecture/data_flow.md` with the new segmentation pipeline once implemented.
- Add how-to content under `docs/howtos/` (“Segment AOI into child maps”).
- Expand `docs/tests.md` to describe new test coverage (unit + integration).
- Ensure changelog entries and README sections are refreshed when the feature ships.

---

Keep this document current after each recipe is executed. Outdated steps slow agents down and create duplicate work.
