"""Regression tests for configuration-specific array parameter formulas."""

from __future__ import annotations

import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt5.QtWidgets import QApplication

from radar_tool.calc_panel import _ArrayParamCalc, calculate_array_parameters


class ArrayParameterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_ula_uses_linear_array_formula(self):
        result = calculate_array_parameters(
            '均匀线阵(ULA)', 8, 0.5, 10e9, 5)
        self.assertEqual(result['array_type'], 'ULA')
        self.assertAlmostEqual(result['beamwidth_deg'], 50.8 / 4.0)
        self.assertAlmostEqual(result['aperture'], 3.5)
        self.assertIn('50.8/(N', result['formula'])

    def test_rectangle_uses_rows_columns_and_two_spacings(self):
        result = calculate_array_parameters(
            '矩形面阵', 8, 0.5, 10e9, 5,
            rows=2, cols=4, dx_lam=0.5, dy_lam=0.75)
        self.assertEqual(result['array_type'], 'RECT')
        self.assertEqual(result['element_count'], 8)
        self.assertAlmostEqual(
            result['beamwidth_az_deg'], 50.8 / (4 * 0.5))
        self.assertAlmostEqual(
            result['beamwidth_el_deg'], 50.8 / (2 * 0.75))
        self.assertAlmostEqual(result['aperture_x'], 1.5)
        self.assertAlmostEqual(result['aperture_y'], 0.75)
        self.assertIn('方位', result['formula'])
        self.assertIn('俯仰', result['formula'])

    def test_uca_uses_radius_formula_without_linear_grating_result(self):
        result = calculate_array_parameters(
            '均匀圆阵(UCA)', 8, 0.5, 10e9, 5, radius_lam=2.0)
        self.assertEqual(result['array_type'], 'UCA')
        self.assertAlmostEqual(result['beamwidth_deg'], 50.8 / 4.0)
        self.assertAlmostEqual(result['aperture'], 4.0)
        self.assertIsNone(result['grating_angle_deg'])
        self.assertIn('2R', result['formula'])

    def test_ui_switches_visible_inputs_and_returns_domain_errors(self):
        widget = _ArrayParamCalc()
        widget.combo_config.setCurrentIndex(1)
        self.assertFalse(widget.spin_rows.isHidden())
        self.assertFalse(widget.rect_rows_label.isHidden())
        widget.spin_rows.setValue(3)
        widget.spin_cols.setValue(3)
        widget.spin_dx.setValue(1.5)
        self.assertTrue(widget._on_calc())
        self.assertEqual(widget.last_result['element_count'], 9)
        self.assertIsNotNone(widget.last_result['grating_angle_deg'])

        with self.assertRaisesRegex(ValueError, '间距'):
            calculate_array_parameters(
                '矩形面阵', 9, 0.5, 10e9, 5,
                rows=3, cols=3, dx_lam=0, dy_lam=0.5)
        widget.close()


if __name__ == '__main__':
    unittest.main()
