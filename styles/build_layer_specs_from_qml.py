#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Scan the current directory for QML files named fc*.qml and emit layer_specs.csv
with columns: name,type,FC Southern Storm style,comment

- name:  "manual_" + <qml_stem sans fcss_/fcs_/fc_ prefix>
- type:  inferred from filename keywords (line/polygon); "UNKNOWN" if unsure
- style: original QML filename
- comment: blank, or a TODO if type is UNKNOWN
"""

import csv
import os
import re
from pathlib import Path

# ---- Inference rules (edit as needed) ----
LINE_HINTS = [
    "road", "stream", "bank", "airstrip", "runway", "rail", "river_bank", "coast"
]
POLY_HINTS = [
    "lake", "river_", "builtup", "terrain", "forest", "field", "swamp",
    "orchard", "vineyard", "urban", "industry", "elevation", "contour", "water_"
]

def find_qml_files(root_dir: Path):
    """Return fc*.qml files in root_dir (non-recursive), case-insensitive."""
    return sorted(
        [p for p in root_dir.iterdir()
         if p.is_file() and p.suffix.lower() == ".qml" and p.name.lower().startswith("fc")],
        key=lambda p: p.name.lower()
    )

def stem_for_name(qml_filename: str) -> str:
    """Return normalized stem for building 'manual_<stem>'."""
    stem = Path(qml_filename).stem
    stem = re.sub(r"^(fcss?_?)", "", stem, flags=re.IGNORECASE)  # drop fcss_ / fcs_ / fc_
    stem = stem.strip().lower()
    stem = re.sub(r"\s+", "_", stem)
    return stem

def infer_type_from_name(stem: str) -> str:
    """Infer 'line' or 'polygon' from filename stem; return 'UNKNOWN' if ambiguous."""
    s = stem.lower()
    in_line = any(h in s for h in LINE_HINTS)
    in_poly = any(h in s for h in POLY_HINTS)
    if in_line and not in_poly:
        return "line"
    if in_poly and not in_line:
        return "polygon"
    # tie-breakers:
    if "stream" in s or "road" in s or s.endswith("_bank"):
        return "line"
    if "lake" in s or "builtup" in s or "terrain" in s or "elevation" in s:
        return "polygon"
    return "UNKNOWN"

def make_layer_name(stem: str) -> str:
    """Prefix with manual_ and ensure safe chars."""
    name = "manual_" + stem
    name = re.sub(r"[^a-z0-9_]+", "_", name)
    name = re.sub(r"__+", "_", name).strip("_")
    return name

def build_rows(qml_paths):
    rows = []
    for qml_path in qml_paths:
        qml = qml_path.name
        stem = stem_for_name(qml)
        layer_name = make_layer_name(stem)
        layer_type = infer_type_from_name(stem)
        rows.append({
            "name": layer_name,
            "type": layer_type,
            "FC Southern Storm style": qml,
            "comment": "" if layer_type != "UNKNOWN" else "TODO: set correct type (line/polygon)"
        })
    return rows

def write_csv(rows, out_path: Path):
    header = ["name", "type", "FC Southern Storm style", "comment"]
    # Python 3: text mode, newline='' to avoid blank lines on Windows; UTF-8 encoding.
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=header)
        w.writeheader()
        for r in rows:
            w.writerow(r)

def main():
    root = Path(os.getcwd())
    qmls = find_qml_files(root)
    if not qmls:
        print("No QML files matching 'fc*.qml' in:", root)
        return
    rows = build_rows(qmls)
    out_csv = root / "layer_specs.csv"
    write_csv(rows, out_csv)

    unknowns = [r for r in rows if r["type"] == "UNKNOWN"]
    print("Wrote %d rows to %s" % (len(rows), out_csv))
    if unknowns:
        print("Note: %d row(s) need manual type selection:" % len(unknowns))
        for r in unknowns:
            print(" - %-35s  style=%s" % (r["name"], r["FC Southern Storm style"]))

if __name__ == "__main__":
    main()
