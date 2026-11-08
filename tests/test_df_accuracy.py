"""Regression tests for direction-finding accuracy formulas."""

from __future__ import annotations

import math
import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt5.QtWidgets import QApplication

from radar_tool.calc_panel import _DFAccuracyCalc, calculate_df_accuracy


class DirectionFindingAccuracyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_zero_angle_matches_previous_interferometer_result(self):
        result = calculate_df_accuracy(
            baseline_lam=0.5,
            element_count=4,
            snr_db=20,
            snapshots=100,
            theta_deg=0,
            algorithm='相位干涉仪',
        )

        snr = 10 ** (20 / 10)
        expected_rad = 1 / (2 * math.pi * 0.5 * math.sqrt(2 * snr))
        self.assertAlmostEqual(
            result['sigma_interfer_rad'], expected_rad, places=12)
        self.assertAlmostEqual(
            result['estimated_rmse_deg'],
            math.degrees(expected_rad),
            places=12,
        )
        self.assertAlmostEqual(result['crb_deg'], result['crb_deg'])

    def test_error_diverges_as_angle_approaches_side_fire(self):
        broadside = calculate_df_accuracy(
            0.5, 4, 20, 100, 0, '相位干涉仪')
        near_side_fire = calculate_df_accuracy(
            0.5, 4, 20, 100, 89.9, '相位干涉仪')

        self.assertGreater(
            near_side_fire['sigma_interfer_deg'],
            broadside['sigma_interfer_deg'] * 100,
        )
        self.assertTrue(near_side_fire['side_fire_warning'])
        self.assertGreater(near_side_fire['crb_deg'], broadside['crb_deg'])

    def test_negative_angle_is_valid_and_out_of_range_is_rejected(self):
        positive = calculate_df_accuracy(
            0.5, 4, 20, 100, 30, '相位干涉仪')
        negative = calculate_df_accuracy(
            0.5, 4, 20, 100, -30, '相位干涉仪')
        self.assertAlmostEqual(
            positive['sigma_interfer_deg'],
            negative['sigma_interfer_deg'],
            places=12,
        )

        for angle in (90, -90, 95, -95):
            with self.assertRaisesRegex(ValueError, '-90.*theta.*90'):
                calculate_df_accuracy(
                    0.5, 4, 20, 100, angle, '相位干涉仪')

    def test_music_gain_is_only_applied_when_model_conditions_hold(self):
        applicable = calculate_df_accuracy(
            0.5, 4, 10, 100, 0, 'MUSIC算法')
        self.assertTrue(applicable['music_applicable'])
        self.assertAlmostEqual(
            applicable['estimated_rmse_deg'],
            applicable['sigma_interfer_deg'] / 2,
            places=12,
        )

        too_few_snapshots = calculate_df_accuracy(
            0.5, 4, 10, 7, 0, 'MUSIC算法')
        self.assertFalse(too_few_snapshots['music_applicable'])
        self.assertEqual(too_few_snapshots['music_gain'], 1.0)
        self.assertAlmostEqual(
            too_few_snapshots['estimated_rmse_deg'],
            too_few_snapshots['sigma_interfer_deg'],
            places=12,
        )

    def test_ui_reports_invalid_angle_and_near_side_fire_warning(self):
        widget = _DFAccuracyCalc()
        widget.spins['theta'].setValue(95)
        self.assertFalse(widget._on_calc())
        self.assertIn('-90', widget.result_text.toPlainText())
        self.assertIn('90', widget.result_text.toPlainText())

        widget.spins['theta'].setValue(89.9)
        self.assertTrue(widget._on_calc())
        self.assertIn('接近正侧射', widget.result_text.toPlainText())
        widget.close()


if __name__ == '__main__':
    unittest.main()
