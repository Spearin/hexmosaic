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

import unittest

from qgis.PyQt.QtGui import QDockWidget

from hexmosaic_dockwidget import HexMosaicDockWidget

from utilities import get_qgis_app

QGIS_APP = get_qgis_app()


class HexMosaicDockWidgetTest(unittest.TestCase):
    """Test dockwidget works."""

    def setUp(self):
        """Runs before each test."""
        self.dockwidget = HexMosaicDockWidget(None)

    def tearDown(self):
        """Runs after each test."""
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

if __name__ == "__main__":
    suite = unittest.makeSuite(HexMosaicDialogTest)
    runner = unittest.TextTestRunner(verbosity=2)
    runner.run(suite)

