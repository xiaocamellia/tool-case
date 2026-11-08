"""Regression tests for the link-budget calculator."""

from __future__ import annotations

import math
import os
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt5.QtWidgets import QApplication

from radar_tool.calc_panel import _LinkBudgetCalc, calculate_link_budget


class LinkBudgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_hand_calculation_uses_explicit_bandwidth_and_rate(self):
        result = calculate_link_budget(
            pt_dbm=30,
            gt_dbi=20,
            lt_db=2,
            freq_ghz=10,
            distance_km=10,
            gr_dbi=20,
            lr_db=2,
            nf_db=3,
            bandwidth_mhz=10,
            ebn0_req_db=10,
            rate_bps=5_000_000,
        )

        wavelength = 3e8 / 10e9
        loss = 20 * math.log10(4 * math.pi * 10_000 / wavelength)
        expected_pr = 30 + 20 - 2 - loss + 20 - 2
        expected_pn = -174 + 10 * math.log10(10e6) + 3
        expected_cn = expected_pr - expected_pn
        expected_ebn0 = expected_cn - 10 * math.log10(10e6 / 5e6)

        self.assertAlmostEqual(result['free_space_loss_db'], loss, places=8)
        self.assertAlmostEqual(result['receive_power_dbm'], expected_pr, places=8)
        self.assertAlmostEqual(result['noise_power_dbm'], expected_pn, places=8)
        self.assertAlmostEqual(result['carrier_to_noise_db'], expected_cn, places=8)
        self.assertAlmostEqual(result['eb_to_n0_db'], expected_ebn0, places=8)
        self.assertAlmostEqual(
            result['margin_db'], expected_ebn0 - 10, places=8)
        self.assertAlmostEqual(
            result['receive_power_dbw'], expected_pr - 30, places=8)

    def test_rate_equal_to_bandwidth_preserves_carrier_to_noise(self):
        common = dict(
            pt_dbm=30,
            gt_dbi=20,
            lt_db=2,
            freq_ghz=10,
            distance_km=10,
            gr_dbi=20,
            lr_db=2,
            nf_db=3,
            bandwidth_mhz=10,
            ebn0_req_db=10,
        )
        at_rate = calculate_link_budget(rate_bps=10_000_000, **common)
        self.assertAlmostEqual(
            at_rate['eb_to_n0_db'], at_rate['carrier_to_noise_db'], places=8)

        slower_rate = calculate_link_budget(rate_bps=5_000_000, **common)
        self.assertLess(
            slower_rate['eb_to_n0_db'], slower_rate['carrier_to_noise_db'])

    def test_ui_rejects_nonpositive_frequency_distance_bandwidth_and_rate(self):
        widget = _LinkBudgetCalc()
        cases = (
            ('freq', '频率'),
            ('dist', '距离'),
            ('bw', '带宽'),
            ('rb', '码率'),
        )
        for key, label in cases:
            original = widget.spins[key].value()
            widget.spins[key].setValue(0)
            self.assertFalse(widget._on_calc())
            self.assertIn(label, widget.result_text.toPlainText())
            self.assertIn('必须大于', widget.result_text.toPlainText())
            widget.spins[key].setValue(original)
        widget.close()


if __name__ == '__main__':
    unittest.main()
