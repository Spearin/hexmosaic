# HexMosaic NATO Map Style Guide

This document defines the **styling standards** for rendering layers in the HexMosaic plugin to resemble NATO topographic maps. It is based on NATO STANAGs, U.S. Army map reading doctrine, and allied mapping practices (UK, Canada, Belgium, Baltic states). The intended outcome is to allow HexMosaic to assign these styles automatically to shape layers and generate raster images that replicate the look of an official NATO map.

---

## 1. Projection & Grid

- **Datum:** WGS84 (per NATO STANAG 2211).  
- **Projection:** Universal Transverse Mercator (UTM).  
- **Grid System:** Military Grid Reference System (MGRS).  
- **Grid Lines:**  
  - Drawn every 1,000 m at 1:50k scale (adjust accordingly for other scales).  
  - Thin black or grey lines, labelled at map edges.  
- **Sheet Alignment:**  
  - **1:250k maps:** 1° × 1° (lat/long).  
  - **1:50k maps:** 15′ × 15′.  
  - **1:25k maps:** 7.5′ × 7.5′.

---

## 2. Color Palette

NATO maps use a limited palette of **five core colors**:

| Color  | Features                                    |
|--------|---------------------------------------------|
| **Black** | Man-made features (roads, railways, buildings, boundaries, text). |
| **Blue**  | Hydrography (rivers, lakes, marshes, coastlines). |
| **Green** | Vegetation (woods, orchards, vineyards). |
| **Brown** | Relief (contour lines, landforms, spot elevations). |
| **Red** / **Red-Brown** | Major roads, built-up areas, cultural features. Combined “red-brown” improves night readability under red light. |

> **Implementation:** Define these colors as hex codes in a shared palette (e.g., `#000000`, `#0072bc`, `#228B22`, `#8B4513`, `#A52A2A`).

---

## 3. Symbology

Follow **STANAG 3675** for basic symbols. Key examples:

- **Roads:**  
  - Primary roads: double red-brown lines with center fill.  
  - Secondary: thinner double lines.  
  - Tracks/trails: dashed lines.

- **Railroads:** black line with cross-tick marks.  
- **Buildings:** solid black rectangles or outlines.  
- **Powerlines:** line with tower symbols at intervals.  
- **Vegetation:** green tint fill with optional tree symbols.  
- **Contours:** thin brown lines; every 5th contour index in thicker brown with elevation label.  
- **Water:** blue lines/polygons with labels in blue italics.

---

## 4. Typography

- **Font:** Sans-serif, high legibility (e.g., Helvetica/Arial/Univers).  
- **Case:** All-uppercase for names and features.  
- **Color:**  
  - Black for cultural features and place names.  
  - Blue italics for water features.  
  - Brown or black italics for relief/elevations.  
- **Size hierarchy:** Larger for cities/towns, smaller for villages/landmarks.  

---

## 5. Marginal Information (Future Extension)

While HexMosaic may not generate full map margins immediately, design should anticipate:

- **Legend:** Standard NATO symbology.  
- **Scale bars:** In km, meters, and optionally miles.  
- **Declination diagram:** True North, Grid North, Magnetic North.  
- **Adjoining sheet diagram:** Neighbor map codes.  
- **Map title & sheet number.**

---

## 6. Raster Export Guidelines

When converting styled layers into raster images:

- Use **CMYK or military-approved RGB values** for consistency.  
- Ensure **symbology is not anti-aliased excessively** (crisp linework).  
- Retain **grid lines and labels** at target resolution.  
- Test exports at **300 dpi** for print and **96/150 dpi** for digital display.

---

## 7. Example Layer Mapping (HexMosaic)

| HexMosaic Layer | NATO Style |
|-----------------|------------|
| Roads layer     | Red-brown double/single lines per hierarchy. |
| Hydro layer     | Blue lines/polygons, italic blue labels. |
| Vegetation layer| Green fills with tree symbols. |
| Elevation layer | Brown contour lines, 5th index heavier. |
| Settlements     | Black polygons for buildings; red-brown fills for urban areas. |
| Grid overlay    | 1000 m UTM/MGRS grid, thin black lines. |

---

## References

- STANAG 2211 — Geodetic Datums, Projections, Grids.  
- STANAG 3675 — NATO Symbology for Topographic Maps.  
- U.S. Army FM 3-25.26 — Map Reading and Land Navigation.  
- NATO MGCP / DGIWG Topographic Map Standards.

