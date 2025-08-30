import json
import pandas as pd

# ---- edit paths ----
XLSX_PATH = r"MapDataTypes_Pro.xls"   # your workbook
OUT_JSON  = r"hexmosaic.config.json"  # write next to the project

# Column name hints — change if needed
COL = dict(
    name="Name",
    typ="Type",
    vis="Visibility",
    cov="Cover",
    mob="Mobility",
    hgt="Height m",
    scan="Scanning Weight",
    desc="Description",
    r_low="R - Low",
    r_high="R - High",
    g_low="G - Low",
    g_high="G - High",
    b_low="B - Low",
    b_high="B - High"
)

df = pd.read_excel(XLSX_PATH)

def val(row, key, default=None):
    v = row.get(key)
    return default if pd.isna(v) else v

classes = []
for _, r in df.iterrows():
    name = val(r, COL["name"])
    typ  = str(val(r, COL["typ"], "")).strip().lower()  # elevation/hex/road/edge
    if not name or not typ:
        continue

    gameplay = {
        "visibility": float(val(r, COL["vis"], 0)),
        "cover": float(val(r, COL["cov"], 0)),
        "mobility": float(val(r, COL["mob"], 0)),
        "height_m": float(val(r, COL["hgt"], 0)),
        "scan_weight": float(val(r, COL["scan"], 0))
    }
    style = {
        "rgb_low":  [int(val(r, COL["r_low"], 0)), int(val(r, COL["g_low"], 0)), int(val(r, COL["b_low"], 0))],
        "rgb_high": [int(val(r, COL["r_high"], 255)), int(val(r, COL["g_high"], 255)), int(val(r, COL["b_high"], 255))]
    }
    classes.append({
        "name": str(name),
        "category": typ,            # "hex" | "road" | "edge" | "elevation"
        "gameplay": gameplay,
        "style": style,
        "description": str(val(r, COL["desc"], "")),
        "aliases": []               # you can manually fill later
    })

config = {
    "schema_version": 1,
    "units": {"hex_size_m": 500},
    "thresholds": {"polygon_coverage_majority": 0.60, "min_polygon_area_hex_fraction": 0.25, "snap_tolerance_px": 20},
    "priority_order": ["Water","Urban","Industrial","Marsh","Forest","Fields","Bare","Mixed"],
    "osm_to_classes": {"polygons": [], "lines": []},   # fill per project or keep defaults
    "mosaic_rules": {
        "tile_assignment": {"method":"centroid_majority","majority_weight":0.6,"centroid_weight":0.4},
        "edge_features": {"use_edge_graph":True,"snap_to":"edge_or_centroid","promote_major_river_to_water_tile":True},
        "road_rules": {"snap_roads_to":"centroids","allow_diagonals":False,"min_road_length_m":150}
    },
    "classes": classes,
    "outputs": {"folders": {"osm": "Layers/OSM", "mosaic": "Layers/Mosaic"},
                "layer_names": {"tiles":"Hex Tiles","edges":"Hex Grid Edges","vertices":"Intersection Helpers","centroids":"Centroid Helpers"}}
}

with open(OUT_JSON, "w", encoding="utf-8") as f:
    json.dump(config, f, indent=2, ensure_ascii=False)

print(f"Wrote {OUT_JSON} with {len(classes)} classes")
