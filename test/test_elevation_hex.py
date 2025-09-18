"""Unit tests for the elevation hex sampling helpers."""

import os

import pytest

from .utilities import get_qgis_app

# Require the QGIS Python bindings for these integration tests.  When the
# bindings are unavailable (e.g., lightweight CI containers), skip the module
# so the rest of the suite can still run.
pytest.importorskip("qgis")

from qgis.core import QgsProject, QgsRasterLayer, QgsVectorLayer  # type: ignore

from utils.elevation_hex import (  # type: ignore
    format_sampling_summary,
    sample_hex_elevations,
    write_hex_elevation_layer,
)

QGIS_APP, CANVAS, IFACE, PARENT = get_qgis_app()
if QGIS_APP is None:  # pragma: no cover - depends on local QGIS install
    pytest.skip("QGIS Python bindings are not available", allow_module_level=True)


def _fixture_path(name: str) -> str:
    return os.path.join(os.path.dirname(__file__), name)


def _load_layers():
    raster_path = _fixture_path("tenbytenraster.asc")
    raster = QgsRasterLayer(raster_path, "tenbyten", "gdal")
    assert raster is not None and raster.isValid(), "Raster fixture failed to load"

    hex_path = _fixture_path("fixtures/elevation_hex/hexes.geojson")
    vector = QgsVectorLayer(hex_path, "hexes", "ogr")
    assert vector is not None and vector.isValid(), "Hex fixture failed to load"

    QgsProject.instance().addMapLayer(raster)
    QgsProject.instance().addMapLayer(vector)

    return raster, vector


def test_sample_mean_assigns_expected_buckets():
    raster, hex_layer = _load_layers()

    result = sample_hex_elevations(raster, hex_layer, method="mean", bucket_size=2)

    assert result.total_features == hex_layer.featureCount()
    assert result.count_with_data == 2
    assert pytest.approx(result.min_value, rel=0.0, abs=0.1) == 2.0
    assert pytest.approx(result.max_value, rel=0.0, abs=0.1) == 7.0
    assert result.min_bucket == 2
    assert result.max_bucket == 6

    samples = result.sample_by_feature()
    for feature in hex_layer.getFeatures():
        sample = samples[feature.id()]
        if feature["hex_id"] == 3:
            assert sample.elev_value is None
            assert sample.elev_bucket is None
        elif feature["hex_id"] == 1:
            assert pytest.approx(sample.elev_value, rel=0.0, abs=0.1) == 2.0
            assert sample.elev_bucket == 2
        else:
            assert pytest.approx(sample.elev_value, rel=0.0, abs=0.1) == 7.0
            assert sample.elev_bucket == 6

    summary = format_sampling_summary(result)
    assert "2/3" in summary


def test_sample_median_and_warnings():
    raster, hex_layer = _load_layers()

    result = sample_hex_elevations(raster, hex_layer, method="median", bucket_size=5)

    assert result.method == "median"
    assert result.bucket_size == pytest.approx(5.0)
    assert any("no raster coverage" in warn for warn in result.warnings)


def test_write_hex_elevation_layer(tmp_path):
    raster, hex_layer = _load_layers()

    result = sample_hex_elevations(raster, hex_layer, method="mean", bucket_size=1)

    out_path = tmp_path / "hex_elev.shp"
    ok, err = write_hex_elevation_layer(
        hex_layer,
        result,
        str(out_path),
        dem_source="tenbyten.asc",
        bucket_method="mean",
        generated_at="2025-01-01T00:00:00Z",
    )
    assert ok, err or "Failed to write hex elevation shapefile"

    output_layer = QgsVectorLayer(str(out_path), "hex elev", "ogr")
    assert output_layer is not None and output_layer.isValid()

    field_names = {field.name() for field in output_layer.fields()}
    assert "elev_value" in field_names
    assert "dem_source" in field_names
    assert any(name.startswith("elev_b") for name in field_names)

    features = {feat["hex_id"]: feat for feat in output_layer.getFeatures()}
    assert len(features) == 3
    assert pytest.approx(features[1]["elev_value"], rel=0.0, abs=0.1) == 2.0
    assert features[1]["dem_source"].startswith("tenbyten")
    assert features[3]["elev_value"] is None


def teardown_function(function):
    QgsProject.instance().clear()
