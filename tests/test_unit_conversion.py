"""Regression tests for unit conversions and calculator input domains."""

from __future__ import annotations

import itertools
import math
import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt5.QtWidgets import QApplication

from radar_tool.calc_panel import (
    _AntennaGainCalc,
    _RadarRangeCalc,
    _SNRCalc,
    _UnitConverter,
    convert_unit,
)


class UnitConversionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _assert_roundtrip(self, category, units, value):
        for source, target in itertools.product(units, repeat=2):
            converted = convert_unit(category, value, source, target)
            restored = convert_unit(category, converted, target, source)
            self.assertTrue(math.isfinite(converted))
            self.assertAlmostEqual(restored, value, places=8)

    def test_all_angle_power_frequency_and_temperature_combinations_roundtrip(self):
        self._assert_roundtrip(2, ('°', 'rad', 'mrad'), 12.5)
        self._assert_roundtrip(1, ('W', 'mW', 'dBm', 'dBW'), 10)
        self._assert_roundtrip(
            0, ('Hz', 'kHz', 'MHz', 'GHz', 'm', 'cm', 'mm'), 10)
        self._assert_roundtrip(4, ('℃', '℉', 'K'), 20)
        self._assert_roundtrip(3, ('dB', '倍数'), 10)
        self._assert_roundtrip(
            5, ('m', 'cm', 'mm', 'km', '英寸', '英尺'), 10)

    def test_invalid_physical_inputs_are_rejected(self):
        invalid_values = (0, -1, float('nan'), float('inf'))
        for category, units in (
            (0, ('Hz', 'm')),
            (1, ('W', 'mW')),
            (3, ('倍数',)),
            (5, ('m', 'cm')),
        ):
            for value in invalid_values:
                with self.assertRaises(ValueError):
                    convert_unit(category, value, units[0], units[-1])

        for value in (0, -1, float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                convert_unit(4, value, 'K', '℃')

        for value in (float('nan'), float('inf')):
            with self.assertRaises(ValueError):
                convert_unit(2, value, '°', 'rad')

    def test_rad_mrad_conversion_is_available_in_ui(self):
        widget = _UnitConverter()
        widget.combo_type.setCurrentIndex(2)
        widget.combo_from.setCurrentText('rad')
        widget.combo_to.setCurrentText('mrad')
        widget.input_val.setText('1')
        self.assertTrue(widget._on_calc())
        self.assertIn('1000', widget.result_text.toPlainText())
        widget.close()

    def test_nonpositive_ratio_does_not_return_zero_db(self):
        widget = _UnitConverter()
        widget.combo_type.setCurrentIndex(3)
        widget.combo_from.setCurrentText('倍数')
        widget.combo_to.setCurrentText('dB')
        widget.input_val.setText('0')
        self.assertFalse(widget._on_calc())
        self.assertIn('必须大于 0', widget.result_text.toPlainText())
        widget.close()

    def test_calc_callbacks_show_errors_instead_of_raising(self):
        antenna = _AntennaGainCalc()
        antenna.spin_freq.setRange(-100, 1000)
        antenna.spin_freq.setValue(0)
        self.assertFalse(antenna._on_calc())
        self.assertIn('频率', antenna.result_text.toPlainText())
        antenna.close()

        radar = _RadarRangeCalc()
        radar.spins['power'].setRange(-100, 1000)
        radar.spins['power'].setValue(0)
        self.assertFalse(radar._on_calc())
        self.assertIn('功率', radar.result_text.toPlainText())
        radar.close()

        snr = _SNRCalc()
        snr.spins['bw'].setRange(-200, 200)
        snr.spins['bw'].setValue(0)
        self.assertFalse(snr._on_calc())
        self.assertIn('带宽', snr.result_text.toPlainText())
        snr.close()


if __name__ == '__main__':
    unittest.main()
