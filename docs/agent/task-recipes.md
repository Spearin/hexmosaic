# Agent Task Recipes

These playbooks outline end-to-end flows the automation agent can follow. Always cross-check `docs/dev-setup/` for environment prep and `docs/agent/cheatsheet.md` for quick commands before starting.

## How To Use These Recipes
- Confirm you are on a clean branch (`git status`) and sync with `master` before modifying files.
- Each recipe lists the primary code touchpoints, configs, and expected outputs. If you see unexpected local changes in those files, stop and ask for human guidance.
- Validation steps are mandatory unless the repository state prevents them (note the reason in the PR description).
- When encountering missing context, search the repository (`rg`, `git grep`, or IDE search) and review the linked files before escalating.

## Recipe Template (for future entries)
1. **Prep** - files to inspect, configs to load, existing behaviour to understand.
2. **Implementation** - ordered tasks (UI wiring, utilities, data updates, tests, docs).
3. **Validation** - commands and manual checks required before opening a PR.
4. **Escalation triggers** - when to stop and ask for clarification.

---

## Cloud Workspace Automation (Current Priority)
Goal: Ensure automation agents can provision and operate HexMosaic from cloud-hosted environments (CI runners, devcontainers, disposable workspaces).

### Context
- Cloud setup reference: `docs/dev-setup/cloud.md`.
- Pipelines rely on `Makefile` targets (`make pylint`, `make test`, `make doc`) and `pb_tool.cfg` for packaging.
- Container or workflow definitions should live in version control (e.g., `.ci/`, `.devcontainer/` when introduced) for reviewability.
- Protect API keys and tokens; keep secrets out of logs and artifacts.

### Recipe 1 - Build a QGIS-enabled base image

**Prep**
- Review the base image options table in `docs/dev-setup/cloud.md` and choose the scenario that matches the target platform.
- Collect QGIS version requirements and confirm any corporate proxy or registry constraints.
- Identify where the resulting Dockerfile or image definition will live in the repo.

**Implementation**
1. Start from the recommended image (`mcr.microsoft.com/devcontainers/python:3.11`, `qgis/qgis:release-3_34`, or similar) and add a label describing the HexMosaic revision.
2. Install QGIS packages following the Debian/Ubuntu or Fedora snippets in `docs/dev-setup/cloud.md`, including build tooling and Qt extras (`qttools5-dev-tools` or `qt5-qttools`).
3. Pre-install Python tooling (`pip`, `wheel`, `pb_tool`, `pytest`, `pylint`) and bake in any repository-specific requirements files when available.
4. Export `QGIS_PREFIX_PATH`, `PYTHONPATH`, and `QT_QPA_PLATFORM=offscreen` inside the image (e.g., `ENV` directives or `/etc/profile.d/qgis.sh`).
5. Check the definition into version control and document how to rebuild/push the image.

**Validation**
- `docker build` (or platform equivalent) succeeds and `qgis --version` reports the expected build.
- `python -c "import qgis"` runs inside the container without raising `ImportError`.
- `pytest test --maxfail=1 -k smoke` passes when executed with the baked-in environment variables.

**Escalation**
- QGIS repositories are unreachable or require credentials you cannot provision.
- Package installs break due to distro conflicts; capture logs and pause for human input before hacking around them.

### Recipe 2 - Wire CI workflows to the base image

**Prep**
- Locate or create the workflow/pipeline files (`.github/workflows/`, Azure Pipelines, etc.).
- Decide which branches and triggers should run the cloud build.
- Confirm which make targets or scripts constitute the minimum gating suite.

**Implementation**
1. Pull the published base image (or build it in the workflow) and set it as the job container/executor.
2. Export the required environment variables (`QGIS_PREFIX_PATH`, `PYTHONPATH`, `QT_QPA_PLATFORM=offscreen`) at the job level.
3. Add sequential steps for lint (`make pylint`), style (`make pep8` if used), tests (`pytest test`), docs (`make doc` when needed), and packaging (`pb_tool package`) as appropriate for the branch.
4. Wrap GUI-touching steps with `xvfb-run -s "-screen 0 1024x768x24"` when headless execution is required.
5. Publish artifacts (e.g., `reports/junit.xml`, coverage, `hexmosaic.zip`, `help/build/html`) and surface failures with clear log sections.

**Validation**
- Dry-run the workflow locally (e.g., `act`) or trigger it on a feature branch and verify all stages pass.
- Confirm artifacts upload and secrets stay masked in logs.
- Ensure pipeline duration meets expectations; if not, profile and adjust caching (next recipe).

**Escalation**
- Workflow runners lack permissions to pull the image or store artifacts.
- Headless Qt steps still fail after setting `QT_QPA_PLATFORM=offscreen` and using `xvfb-run`.

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
- Secrets cannot be stored due to policy or legal constraints—stop and request guidance.
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
- Automated: run `pytest test/test_hexmosaic_dockwidget.py` (add/update tests if feasible).

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
- Automated: add unit tests under `test/` using synthetic AOIs and verifying segment counts and extents.

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
- Automated: create synthetic POI datasets in `test/fixtures` and assert segment counts and membership.

**Escalation**
- If POI data is unavailable or incomplete, provide a graceful fallback (equal grid) and log guidance; escalate only if both modes fail.

### Supporting Tasks
- Update `docs/architecture/data_flow.md` with the new segmentation pipeline once implemented.
- Add how-to content under `docs/howtos/` ("Segment AOI into child maps").
- Expand `docs/tests.md` to describe new test coverage (unit + integration).
- Ensure changelog entries and README sections are refreshed when the feature ships.

---

Keep this document current after each recipe is executed. Outdated steps slow agents down and create duplicate work.
