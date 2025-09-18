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

---

Keep this document current after each recipe is executed. Outdated steps slow agents down and create duplicate work.
