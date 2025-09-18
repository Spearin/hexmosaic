# Testing Guide

## Unit Tests

* `test/test_hexmosaic_dockwidget.py`
  * `test_experimental_aoi_toggle_enables_large_sizes` confirms the AOI guard behaves correctly when the experimental toggle is active.
  * `test_segment_aoi_creates_equal_grid_and_cleanup` builds a synthetic AOI, runs the new segmentation helper, asserts that the expected shapefiles and metadata entries are produced, and verifies the cleanup path removes both.
  * `test_segment_preview_creates_memory_layer` validates the preview workflow adds a dashed, memory-based layer without touching on-disk data and that running the full segmentation clears the preview state.
  * `test_create_aois_from_poi_layer` feeds a synthetic point layer through the POI workflow to ensure AOIs are generated for each feature and registered in the project tree.

Run the full suite with:

```bash
pytest
```

or limit execution to the dock widget tests while iterating on UI changes:

```bash
pytest test/test_hexmosaic_dockwidget.py
```
