"""Regression tests for array pattern and metric calculations."""

from __future__ import annotations

import math
import os
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import numpy as np
from PyQt5.QtWidgets import QApplication, QTableWidget, QTableWidgetItem

from radar_tool.array_designer import ArrayDesignerPanel, _validate_elements


class ArrayDesignerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_element_phase_steers_ula_beam_predictably(self):
        panel = ArrayDesignerPanel()
        panel.combo_template.setCurrentIndex(0)
        panel.combo_cut.setCurrentIndex(0)
        d_lam = panel.spin_d.value()
        lam = 3e8 / panel.fc
        target_deg = 20.0
        target_rad = math.radians(target_deg)
        for index, element in enumerate(panel.elements):
            x = (index - (len(panel.elements) - 1) / 2) * d_lam * lam
            phase_rad = -2 * math.pi / lam * x * math.sin(target_rad)
            element['phase'] = math.degrees(phase_rad)

        angles = np.arange(-90, 90.01, 0.1)
        gains = panel._calc_pattern(angles)
        self.assertAlmostEqual(angles[int(np.argmax(gains))], target_deg, delta=0.5)

        for element in panel.elements:
            element['phase'] = 0.0
        baseline = panel._calc_pattern(angles)
        self.assertAlmostEqual(angles[int(np.argmax(baseline))], 0.0, delta=0.5)
        panel.close()

    def test_symmetric_array_reports_left_and_right_sidelobes(self):
        panel = ArrayDesignerPanel()
        panel.combo_template.setCurrentIndex(0)
        angles = np.arange(-90, 90.01, 0.5)
        metrics = panel._extract_metrics(angles, panel._calc_pattern(angles))

        self.assertGreater(metrics['left_sll'], -90)
        self.assertGreater(metrics['right_sll'], -90)
        self.assertLess(abs(metrics['left_sll'] - metrics['right_sll']), 1.0)
        self.assertLess(metrics['main_left'], 0)
        self.assertGreater(metrics['main_right'], 0)
        panel.close()

    def test_uca_and_rectangle_use_configuration_specific_formulas(self):
        panel = ArrayDesignerPanel()

        panel.combo_template.setCurrentIndex(1)
        uca = panel._extract_metrics(
            np.arange(-90, 90.01, 0.5),
            panel._calc_pattern(np.arange(-90, 90.01, 0.5)),
        )
        self.assertEqual(uca['array_type'], 'UCA')
        self.assertIn('2R', uca['beamwidth_formula'])
        self.assertIn('圆阵', uca['grating_formula'])

        panel.combo_template.setCurrentIndex(2)
        rect = panel._extract_metrics(
            np.arange(-90, 90.01, 0.5),
            panel._calc_pattern(np.arange(-90, 90.01, 0.5)),
        )
        self.assertEqual(rect['array_type'], 'RECT')
        self.assertIn('方位', rect['beamwidth_formula'])
        self.assertIn('俯仰', rect['beamwidth_formula'])
        self.assertGreater(rect['aperture_x'], 0)
        self.assertGreater(rect['aperture_y'], 0)
        panel.close()

    def test_table_edit_applies_amplitude_and_phase_immediately(self):
        panel = ArrayDesignerPanel()
        panel.combo_template.setCurrentIndex(0)
        baseline = panel._calc_pattern(np.array([-30.0, 0.0, 30.0]))
        panel.table.item(0, 2).setText('0.25')
        panel.table.item(0, 3).setText('90')
        panel._on_table_edit()
        changed = panel._calc_pattern(np.array([-30.0, 0.0, 30.0]))
        self.assertFalse(np.allclose(baseline, changed))
        panel.close()

    def test_custom_array_requires_two_finite_nonzero_amplitude_elements(self):
        with self.assertRaisesRegex(ValueError, '至少需要 2'):
            _validate_elements([{'x': 0, 'y': 0, 'amp': 1, 'phase': 0}])
        with self.assertRaisesRegex(ValueError, '有限数值'):
            _validate_elements([
                {'x': 0, 'y': 0, 'amp': 1, 'phase': 0},
                {'x': float('nan'), 'y': 0, 'amp': 1, 'phase': 0},
            ])
        with self.assertRaisesRegex(ValueError, '幅度不能为零'):
            _validate_elements([
                {'x': 0, 'y': 0, 'amp': 1, 'phase': 0},
                {'x': 1, 'y': 0, 'amp': 0, 'phase': 0},
            ])

    def test_custom_dialog_apply_preserves_amplitude_and_phase(self):
        panel = ArrayDesignerPanel()
        panel.combo_template.setCurrentIndex(5)
        table = QTableWidget(2, 4)
        values = (
            (0.0, 0.0, 1.0, 0.0),
            (0.5, 0.0, 0.4, 45.0),
        )
        for row, values_row in enumerate(values):
            for column, value in enumerate(values_row):
                table.setItem(row, column, QTableWidgetItem(str(value)))
        panel.custom_coords_table = table

        class Dialog:
            accepted = False

            def accept(self):
                self.accepted = True

        dialog = Dialog()
        with patch('radar_tool.array_designer.QMessageBox.information'):
            self.assertTrue(panel._custom_apply(dialog))
        self.assertTrue(dialog.accepted)
        self.assertEqual(panel.elements[1]['amp'], 0.4)
        self.assertEqual(panel.elements[1]['phase'], 45.0)
        panel.close()

    def test_custom_frequency_parsing_accepts_values_and_units(self):
        self.assertAlmostEqual(ArrayDesignerPanel._parse_custom_freq('1500'), 1500.0)
        self.assertAlmostEqual(
            ArrayDesignerPanel._parse_custom_freq('2.4e9'), 2.4e9)
        self.assertAlmostEqual(
            ArrayDesignerPanel._parse_custom_freq('3.5 GHz'), 3.5e9)
        self.assertAlmostEqual(
            ArrayDesignerPanel._parse_custom_freq('900MHz'), 0.9e9)
        self.assertAlmostEqual(
            ArrayDesignerPanel._parse_custom_freq('1,500'), 1500.0)

    def test_custom_frequency_parsing_rejects_invalid_text(self):
        for bad in ('', 'abc', '-3 GHz', '0', '1e400'):
            with self.assertRaises(ValueError):
                ArrayDesignerPanel._parse_custom_freq(bad)

    def test_custom_frequency_selection_updates_fc(self):
        panel = ArrayDesignerPanel()
        panel.combo_freq.setCurrentIndex(panel.combo_freq.count() - 1)
        panel.edit_freq_custom.setText('7.5 GHz')
        panel._on_freq_change()
        self.assertAlmostEqual(panel.fc, 7.5e9)
        panel.edit_freq_custom.setText('bad')
        panel._on_freq_change()
        self.assertAlmostEqual(panel.fc, 7.5e9)  # 非法输入保持上次有效值
        panel.close()


if __name__ == '__main__':
    unittest.main()
