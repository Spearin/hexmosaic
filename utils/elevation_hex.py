"""Sampling helpers for generating hex-aligned elevation layers."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from qgis.analysis import QgsZonalStatistics  # type: ignore
from qgis.core import (  # type: ignore
    QgsCoordinateTransform,
    QgsFeature,
    QgsFields,
    QgsField,
    QgsGeometry,
    QgsProject,
    QgsRasterLayer,
    QgsVectorFileWriter,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.PyQt.QtCore import QVariant  # type: ignore


@dataclass(frozen=True)
class HexSample:
    """A sampled elevation value for a single hex feature."""

    feature_id: int
    elev_value: Optional[float]
    elev_bucket: Optional[float]
    pixel_count: int


@dataclass(frozen=True)
class SamplingResult:
    """Container for sampled results and summary statistics."""

    samples: List[HexSample]
    method: str
    bucket_size: float
    total_features: int
    count_with_data: int
    min_value: Optional[float]
    max_value: Optional[float]
    min_bucket: Optional[float]
    max_bucket: Optional[float]
    warnings: List[str]

    def sample_by_feature(self) -> Dict[int, HexSample]:
        """Return a lookup dictionary keyed by feature id."""

        return {s.feature_id: s for s in self.samples}


class ElevationSamplingError(RuntimeError):
    """Raised when zonal statistics cannot be computed."""


def _geometry_string_for_layer(layer: QgsVectorLayer) -> str:
    geom_type = QgsWkbTypes.geometryType(layer.wkbType())
    if geom_type != QgsWkbTypes.PolygonGeometry:
        raise ValueError("Hex layer must contain polygonal features.")

    if QgsWkbTypes.isMultiType(layer.wkbType()):
        return "MultiPolygon"
    return "Polygon"


def _copy_hex_features(
    hex_layer: QgsVectorLayer, raster_layer: QgsRasterLayer
) -> QgsVectorLayer:
    """Copy hex polygons to a memory layer in the raster CRS for sampling."""

    geom_string = _geometry_string_for_layer(hex_layer)
    crs = raster_layer.crs()
    mem_layer = QgsVectorLayer(f"{geom_string}?crs={crs.authid()}", "hex_temp", "memory")
    provider = mem_layer.dataProvider()
    provider.addAttributes([QgsField("src_fid", QVariant.LongLong)])
    mem_layer.updateFields()

    transform: Optional[QgsCoordinateTransform] = None
    if hex_layer.crs() != raster_layer.crs():
        transform = QgsCoordinateTransform(
            hex_layer.crs(),
            raster_layer.crs(),
            QgsProject.instance().transformContext(),
        )

    features: List[QgsFeature] = []
    for feat in hex_layer.getFeatures():
        geom = QgsGeometry(feat.geometry())
        if transform is not None:
            geom.transform(transform)

        new_feat = QgsFeature(mem_layer.fields())
        new_feat.setGeometry(geom)
        new_feat.setAttribute("src_fid", int(feat.id()))
        features.append(new_feat)

    if features:
        provider.addFeatures(features)
        mem_layer.updateExtents()

    return mem_layer


def _stat_field_name(prefix: str, suffix: str) -> str:
    return f"{prefix}{suffix}"


def _bucket_for_value(value: float, bucket_size: float) -> float:
    if bucket_size <= 0:
        raise ValueError("Bucket size must be positive.")

    bucket_value = math.floor(value / bucket_size) * bucket_size
    # Normalise rounding noise so downstream styling works with ints.
    if math.isclose(bucket_value, round(bucket_value), rel_tol=0.0, abs_tol=1e-6):
        return float(int(round(bucket_value)))
    return bucket_value


def sample_hex_elevations(
    raster_layer: QgsRasterLayer,
    hex_layer: QgsVectorLayer,
    *,
    method: str = "mean",
    bucket_size: float = 1.0,
    prefix: str = "hm_",
) -> SamplingResult:
    """Sample DEM values within each hex polygon using zonal statistics."""

    if raster_layer is None or not raster_layer.isValid():
        raise ValueError("Raster layer is invalid.")
    if hex_layer is None or not hex_layer.isValid():
        raise ValueError("Hex layer is invalid.")
    if bucket_size <= 0:
        raise ValueError("Bucket size must be greater than zero.")

    method_key = (method or "mean").lower()
    stat_flags = {
        "mean": (QgsZonalStatistics.Mean, "mean"),
        "median": (QgsZonalStatistics.Median, "median"),
        "min": (QgsZonalStatistics.Min, "min"),
    }
    if method_key not in stat_flags:
        raise ValueError(f"Unsupported sampling method: {method}")

    temp_layer = _copy_hex_features(hex_layer, raster_layer)
    stat_flag, suffix = stat_flags[method_key]
    # Include count so we can gracefully handle nodata polygons.
    stat_flag |= QgsZonalStatistics.Count

    zonal = QgsZonalStatistics(temp_layer, raster_layer, f"{prefix}", 1, stat_flag)
    status = zonal.calculateStatistics(None)
    if status != 0:
        raise ElevationSamplingError("QgsZonalStatistics failed for the supplied layers.")

    value_field = _stat_field_name(prefix, suffix)
    count_field = _stat_field_name(prefix, "count")

    idx_val = temp_layer.fields().indexOf(value_field)
    if idx_val < 0:
        raise ElevationSamplingError(f"Statistic field '{value_field}' not found.")

    idx_count = temp_layer.fields().indexOf(count_field)

    samples: List[HexSample] = []
    warnings: List[str] = []
    min_val: Optional[float] = None
    max_val: Optional[float] = None
    min_bucket: Optional[float] = None
    max_bucket: Optional[float] = None
    count_with_data = 0

    for feat in temp_layer.getFeatures():
        src_fid_value: Optional[object] = None

        try:
            src_fid_value = feat.attribute("src_fid")
        except AttributeError:
            src_fid_value = None

        if src_fid_value is None:
            fields = getattr(feat, "fields", lambda: None)()
            field_index: Optional[int] = None
            if fields is not None:
                lookup = getattr(fields, "lookupField", None)
                if callable(lookup):
                    field_index = lookup("src_fid")
                else:
                    index_of = getattr(fields, "indexOf", None)
                    if callable(index_of):
                        field_index = index_of("src_fid")

            if field_index is not None and field_index >= 0:
                try:
                    attrs = feat.attributes()
                    if 0 <= field_index < len(attrs):
                        src_fid_value = attrs[field_index]
                except Exception:
                    src_fid_value = None

        if src_fid_value is None:
            src_fid = int(feat.id())
        else:
            try:
                src_fid = int(src_fid_value)
            except (TypeError, ValueError):
                src_fid = int(feat.id())

        count_val = 0
        if idx_count >= 0:
            try:
                count_val = int(feat.attributes()[idx_count])
            except Exception:
                count_val = 0

        raw_val = feat.attributes()[idx_val]
        if raw_val is None or (isinstance(raw_val, float) and math.isnan(raw_val)) or count_val <= 0:
            samples.append(HexSample(src_fid, None, None, count_val))
            if count_val <= 0:
                warnings.append(f"Hex feature {src_fid} has no raster coverage.")
            continue

        elev_val = float(raw_val)
        bucket_val = _bucket_for_value(elev_val, bucket_size)

        samples.append(HexSample(src_fid, elev_val, bucket_val, count_val))
        count_with_data += 1

        min_val = elev_val if min_val is None else min(min_val, elev_val)
        max_val = elev_val if max_val is None else max(max_val, elev_val)
        min_bucket = bucket_val if min_bucket is None else min(min_bucket, bucket_val)
        max_bucket = bucket_val if max_bucket is None else max(max_bucket, bucket_val)

    return SamplingResult(
        samples=samples,
        method=method_key,
        bucket_size=float(bucket_size),
        total_features=len(samples),
        count_with_data=count_with_data,
        min_value=min_val,
        max_value=max_val,
        min_bucket=min_bucket,
        max_bucket=max_bucket,
        warnings=warnings,
    )


def write_hex_elevation_layer(
    hex_layer: QgsVectorLayer,
    sampling: SamplingResult,
    output_path: str,
    *,
    dem_source: str,
    bucket_method: str,
    generated_at: Optional[str] = None,
) -> Tuple[bool, Optional[str]]:
    """Persist sampled results to a shapefile alongside original attributes."""

    if sampling.total_features == 0:
        return False, "No features to save."

    fields = QgsFields()
    for field in hex_layer.fields():
        fields.append(field)

    fields.append(QgsField("elev_value", QVariant.Double))
    fields.append(QgsField("elev_bucket", QVariant.Double))
    fields.append(QgsField("dem_source", QVariant.String, len=120))
    fields.append(QgsField("bucket_method", QVariant.String, len=32))
    fields.append(QgsField("generated_at", QVariant.String, len=32))

    writer = QgsVectorFileWriter(
        output_path,
        "UTF-8",
        fields,
        hex_layer.wkbType(),
        hex_layer.crs(),
        "ESRI Shapefile",
    )
    try:
        if writer.hasError() != QgsVectorFileWriter.NoError:
            message = getattr(writer, "errorMessage", lambda: "Unknown error")()
            return False, message

        lookup = sampling.sample_by_feature()
        stamp = generated_at or datetime.utcnow().replace(microsecond=0).isoformat() + "Z"

        for src_feat in hex_layer.getFeatures():
            new_feat = QgsFeature(fields)
            new_feat.setGeometry(src_feat.geometry())

            base_attrs = list(src_feat.attributes())
            sample = lookup.get(src_feat.id())

            elev_value = sample.elev_value if sample else None
            elev_bucket = sample.elev_bucket if sample else None
            if elev_bucket is not None and math.isclose(elev_bucket, round(elev_bucket), abs_tol=1e-6):
                elev_bucket = float(int(round(elev_bucket)))

            new_attrs = base_attrs + [
                elev_value,
                elev_bucket,
                (dem_source or "")[:120],
                (bucket_method or "")[:32],
                stamp[:32],
            ]
            new_feat.setAttributes(new_attrs)
            writer.addFeature(new_feat)
    finally:
        del writer

    return True, None


def format_sampling_summary(result: SamplingResult) -> str:
    """Return a concise summary string for logging."""

    if result.count_with_data == 0:
        return f"0/{result.total_features} hexes sampled"

    bucket_part = ""
    if result.min_bucket is not None and result.max_bucket is not None:
        if math.isclose(result.min_bucket, result.max_bucket, abs_tol=1e-6):
            bucket_part = f", bucket {result.min_bucket:g}"
        else:
            bucket_part = f", bucket {result.min_bucket:g}–{result.max_bucket:g}"

    return f"{result.count_with_data}/{result.total_features} hexes sampled{bucket_part}"


__all__ = [
    "ElevationSamplingError",
    "HexSample",
    "SamplingResult",
    "format_sampling_summary",
    "sample_hex_elevations",
    "write_hex_elevation_layer",
]

