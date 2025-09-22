# Profiles Directory

Profiles capture per-game classification presets used by the Hex Mosaic Palette. They live alongside the plugin so that automation and documentation share the same source of truth.

- `hexmosaic_profile.json` – FC: Southern Storm defaults. Each entry under `classes` lists the palette `id`, the target layer name (`manual_*`), whether it expects polygons or lines, priority, matching OSM tags, and any special line snapping behaviour (`center_to_edge`, `edge`).
- `snapping_rules` and `classification` sections provide global defaults (probe counts, tie breakers, line snapping tolerances).

When editing profiles:
1. Keep class `target_layer` names aligned with entries in `styles/layer_specs.csv` so the correct `.qml` style can be applied automatically.
2. After modifying the profile, reload the Hex Mosaic Palette tab or restart QGIS to pick up the changes.
3. Document new classes in the README so users understand which OSM layers to associate with each preset.
