# coding=utf-8
"""DockWidget test.

.. note:: This program is free software; you can redistribute it and/or modify
     it under the terms of the GNU General Public License as published by
     the Free Software Foundation; either version 2 of the License, or
     (at your option) any later version.

"""

__author__ = 'aspearin@ontargetsimulations.com'
__date__ = '2025-08-26'
__copyright__ = 'Copyright 2025, Andrew Spearin / On Target Simulations'

import os
import tempfile
import unittest

from qgis.PyQt.QtGui import QDockWidget

from hexmosaic_dockwidget import HexMosaicDockWidget

from utilities import get_qgis_app

from qgis.core import QgsProject, QgsVectorLayer, QgsFeature, QgsGeometry, QgsPointXY

QGIS_APP = get_qgis_app()


class HexMosaicDockWidgetTest(unittest.TestCase):
    """Test dockwidget works."""

    def setUp(self):
        """Runs before each test."""
        self.dockwidget = HexMosaicDockWidget(None)

    def tearDown(self):
        """Runs after each test."""
        QgsProject.instance().clear()
        self.dockwidget = None

    def test_dockwidget_ok(self):
        """Test we can click OK."""
        pass

    def test_experimental_aoi_toggle_enables_large_sizes(self):
        """Oversized AOIs stay disabled until experimental mode is enabled."""
        dw = self.dockwidget

        # Switch to hex units for predictable rounding and request an oversized AOI.
        dw.unit_h.setChecked(True)
        dw.width_input.setText("120")
        dw.height_input.setText("120")
        dw._recalc_aoi_info()

        self.assertFalse(dw.chk_experimental_aoi.isChecked())
        self.assertFalse(dw.btn_aoi.isEnabled())

    def test_segment_aoi_creates_equal_grid_and_cleanup(self):
        dw = self.dockwidget

        with tempfile.TemporaryDirectory() as tmpdir:
            dw.out_dir_edit.setText(tmpdir)
            os.makedirs(dw._layers_dir(), exist_ok=True)

            aoi_layer = QgsVectorLayer("Polygon?crs=EPSG:3857", "AOI 1 Synthetic", "memory")
            provider = aoi_layer.dataProvider()
            feat = QgsFeature()
            feat.setGeometry(QgsGeometry.fromPolygonXY([[
                QgsPointXY(0, 0),
                QgsPointXY(0, 4000),
                QgsPointXY(4000, 4000),
                QgsPointXY(4000, 0)
            ]]))
            provider.addFeature(feat)
            aoi_layer.updateExtents()

            QgsProject.instance().addMapLayer(aoi_layer)
            dw._populate_aoi_combo()

            idx = dw.cboAOI_segment.findData(aoi_layer.id())
            self.assertNotEqual(idx, -1)
            dw.cboAOI_segment.setCurrentIndex(idx)

            dw.seg_rows_spin.setValue(2)
            dw.seg_cols_spin.setValue(2)

            dw.segment_selected_aoi()

            parent_safe = dw._safe_filename(aoi_layer.name().replace(" ", "_"))
            seg_dir = os.path.join(tmpdir, "Layers", "Base", "Base_Grid", parent_safe, "Segments")
            self.assertTrue(os.path.isdir(seg_dir))

            shp_files = [f for f in os.listdir(seg_dir) if f.lower().endswith(".shp")]
            self.assertEqual(4, len(shp_files))

            key = dw._metadata_key_for_layer(aoi_layer)
            self.assertIn(key, dw._segment_metadata)
            meta = dw._segment_metadata[key]
            self.assertEqual(2, meta.get("rows"))
            self.assertEqual(2, meta.get("cols"))
            self.assertEqual(4, len(meta.get("segments", [])))

            segment_items = [dw.cboAOI.itemText(i) for i in range(dw.cboAOI.count()) if "Segment" in dw.cboAOI.itemText(i)]
            self.assertGreaterEqual(len(segment_items), 1)

            dw.clear_segments_for_selected_aoi()

            self.assertFalse(os.path.isdir(seg_dir))
            self.assertNotIn(key, dw._segment_metadata)

        # Enabling the experimental toggle should allow the button while surfacing a warning.
        dw.chk_experimental_aoi.setChecked(True)
        dw._recalc_aoi_info()

        self.assertTrue(dw.btn_aoi.isEnabled())
        self.assertTrue(dw.lbl_experimental_warning.isVisible())
        self.assertIn("Experimental AOI", dw.lbl_experimental_warning.text())

        # Turning the toggle back off should return to the guarded state.
        dw.chk_experimental_aoi.setChecked(False)
        dw._recalc_aoi_info()

        self.assertFalse(dw.btn_aoi.isEnabled())

    def test_segment_preview_creates_memory_layer(self):
        dw = self.dockwidget

        with tempfile.TemporaryDirectory() as tmpdir:
            dw.out_dir_edit.setText(tmpdir)
            os.makedirs(dw._layers_dir(), exist_ok=True)

            aoi_layer = QgsVectorLayer("Polygon?crs=EPSG:3857", "AOI Preview", "memory")
            provider = aoi_layer.dataProvider()
            feat = QgsFeature()
            feat.setGeometry(QgsGeometry.fromPolygonXY([[
                QgsPointXY(0, 0),
                QgsPointXY(0, 2000),
                QgsPointXY(2000, 2000),
                QgsPointXY(2000, 0)
            ]]))
            provider.addFeature(feat)
            aoi_layer.updateExtents()

            QgsProject.instance().addMapLayer(aoi_layer)
            dw._populate_aoi_combo()

            idx = dw.cboAOI_segment.findData(aoi_layer.id())
            self.assertNotEqual(idx, -1)
            dw.cboAOI_segment.setCurrentIndex(idx)

            dw.seg_rows_spin.setValue(2)
            dw.seg_cols_spin.setValue(2)

            dw.preview_segments_for_selected_aoi()

            key = dw._metadata_key_for_layer(aoi_layer)
            self.assertIn(key, dw._segment_preview_layers)
            preview_id = dw._segment_preview_layers[key]
            preview_layer = QgsProject.instance().mapLayer(preview_id)
            self.assertIsNotNone(preview_layer)
            self.assertEqual(preview_layer.providerType(), "memory")

            seg_dir = dw._segment_directory_for_layer(aoi_layer)
            if os.path.isdir(seg_dir):
                shp_files = [f for f in os.listdir(seg_dir) if f.lower().endswith(".shp")]
                self.assertEqual([], shp_files)

            dw.segment_selected_aoi()
            self.assertNotIn(key, dw._segment_preview_layers)

    def test_create_aois_from_poi_layer(self):
        dw = self.dockwidget

        with tempfile.TemporaryDirectory() as tmpdir:
            dw.out_dir_edit.setText(tmpdir)
            os.makedirs(dw._layers_dir(), exist_ok=True)

            poi_layer = QgsVectorLayer("Point?crs=EPSG:3857", "POI Seeds", "memory")
            provider = poi_layer.dataProvider()
            f1 = QgsFeature()
            f1.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(1000, 1000)))
            f1.setAttributes([])
            f2 = QgsFeature()
            f2.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(3000, 3000)))
            f2.setAttributes([])
            provider.addFeatures([f1, f2])
            poi_layer.updateExtents()

            QgsProject.instance().addMapLayer(poi_layer)

            dw.width_input.setText("1000")
            dw.height_input.setText("1000")
            dw.hex_scale_edit.setText("500")
            dw.unit_m.setChecked(True)

            dw._populate_poi_combo()
            idx = dw.cbo_poi_layer.findData(poi_layer.id())
            self.assertNotEqual(idx, -1)
            dw.cbo_poi_layer.setCurrentIndex(idx)

            dw.create_aois_from_poi()

            layers_dir = os.path.join(tmpdir, "Layers")
            shp_files = [f for f in os.listdir(layers_dir) if f.lower().endswith(".shp")]
            self.assertGreaterEqual(len(shp_files), 2)

            aoi_layers = [lyr for lyr in QgsProject.instance().mapLayers().values() if lyr.name().startswith("AOI ")]
            self.assertGreaterEqual(len(aoi_layers), 2)

if __name__ == "__main__":
    suite = unittest.makeSuite(HexMosaicDialogTest)
    runner = unittest.TextTestRunner(verbosity=2)
    runner.run(suite)

