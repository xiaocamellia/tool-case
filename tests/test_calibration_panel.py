"""Offscreen integration test for the calibration panel workflow."""

from __future__ import annotations

import os
import tempfile
import time
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import numpy as np
import pandas as pd
from PyQt5.QtCore import QEventLoop
from PyQt5.QtWidgets import QApplication

from radar_tool.calibration_batch_store import CalibrationBatchStore, DEFAULT_FIXED_PARAMS
from radar_tool.calibration_model import simulate_angles
from radar_tool.calibration_panel import CalibrationPanel
from radar_tool.run import configure_matplotlib


class CalibrationPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        configure_matplotlib()
        cls.app = QApplication.instance() or QApplication([])

    def test_load_run_and_render_results(self):
        with tempfile.TemporaryDirectory() as directory:
            az_true = np.linspace(-45.0, 45.0, 60)
            el_true = np.linspace(-15.0, 15.0, 60)
            az_meas, el_meas = simulate_angles(
                18.25, -7.5, az_true, el_true, DEFAULT_FIXED_PARAMS)
            data_path = os.path.join(directory, 'MeasData.csv')
            pd.DataFrame({
                'az_true': az_true,
                'el_true': el_true,
                'az_meas': az_meas,
                'el_meas': el_meas,
            }).to_csv(data_path, index=False)

            store = CalibrationBatchStore(os.path.join(directory, 'batch_configs.json'))
            panel = CalibrationPanel(batch_store=store)
            panel.resize(1380, 820)
            panel.show()
            panel.edit_data_path.setText(data_path)
            panel._start_calibration()

            completed = []
            panel._calibration_thread.finished.connect(
                lambda: completed.append(True)
            )
            deadline = time.monotonic() + 10
            while not completed and time.monotonic() < deadline:
                self.app.processEvents(QEventLoop.AllEvents, 50)
                time.sleep(0.001)
            self.app.processEvents()
            self.assertTrue(
                completed,
                "测向校准后台任务超过 10 秒仍未结束",
            )

            self.assertIsNotNone(panel.result)
            self.assertAlmostEqual(
                panel.result['optimized_params']['yy_r4_ZT'], 18.25, places=4)
            self.assertAlmostEqual(
                panel.result['optimized_params']['zz_r4_ZT'], -7.5, places=4)
            self.assertTrue(panel.btn_export.isEnabled())
            self.assertTrue(panel.btn_apply_result.isEnabled())
            self.assertEqual(panel.metrics_table.rowCount(), 8)
            panel.close()
            self.app.processEvents()


if __name__ == '__main__':
    unittest.main()
