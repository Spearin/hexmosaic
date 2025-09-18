# Data Flow

## AOI Segmentation Pipeline

1. **User input**  The Map Area panel exposes a segmentation picker. Users select a parent AOI layer, choose the number of rows and columns, and click **Segment AOI**. The UI state is persisted in `hexmosaic.project.json` so preferences survive across project reloads.
2. **Geometry prep**  `segment_selected_aoi` (and the preview helper) union the AOI geometry, snap the bounding box to the configured hex spacing, and derive equal-width column and row boundaries. The routine expands the snapped extent when necessary so each subdivision aligns with the underlying grid.
3. **Preview (optional)**  **Preview Segments** runs the same computation but writes the intersections to an in-memory layer styled with a dashed outline so planners can inspect the grid before committing anything to disk. Triggering the full segmentation clears any existing preview for the AOI.
4. **Segment creation**  For every grid cell, the plugin intersects the rectangle with the AOI polygon, validates the result, and writes a shapefile to `<Project>/Layers/Base/Base_Grid/<AOI Safe Name>/Segments/Segment_<row>_<col>.shp`. A metadata record capturing the parent name, row/column counts, and segment layer names is written to `hexmosaic.project.json`.
5. **Layer registration**  Newly written shapefiles are loaded into the QGIS project under **Base ▸ Base Grid ▸ <AOI> ▸ Segments**. Styles from `aoi_segment.qml` (or `aoi.qml` as a fallback) are applied; otherwise a default outline is used. AOI dropdowns across the dock widget refresh so segments are immediately selectable for grid building, elevation downloads, or exports.
6. **Cleanup**  The **Delete Segments** action removes both on-disk shapefiles and any loaded segment or preview layers, then clears the related metadata entry. The UI disables the cleanup button automatically when no segments exist for the selected AOI.

Other workflows (grid generation, elevation download, export) continue to function unchanged, but they now benefit from the richer AOI list that includes generated segments.
