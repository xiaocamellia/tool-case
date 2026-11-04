"""Regression tests for direction-finding calibration."""

from __future__ import annotations

import csv
import os
import tempfile
import unittest

import numpy as np
import pandas as pd

from radar_tool.calibration_batch_store import (
    DEFAULT_FIXED_PARAMS,
    DEFAULT_INIT_PARAMS,
    CalibrationBatchStore,
)
from radar_tool.calibration_data_loader import load_calibration_data
from radar_tool.calibration_model import simulate_angles
from radar_tool.calibration_optimizer import run_calibration


class CalibrationAlgorithmTests(unittest.TestCase):
    def test_optimizer_recovers_known_offsets(self):
        az_true = np.linspace(-50.0, 50.0, 121)
        el_true = np.linspace(-20.0, 20.0, 121)
        az_meas, el_meas = simulate_angles(
            24.5, -13.25, az_true, el_true, DEFAULT_FIXED_PARAMS)
        result = run_calibration(
            {
                'az_true': az_true,
                'el_true': el_true,
                'az_meas': az_meas,
                'el_meas': el_meas,
            },
            DEFAULT_FIXED_PARAMS,
            DEFAULT_INIT_PARAMS,
        )

        self.assertTrue(result['success'])
        self.assertAlmostEqual(result['optimized_params']['yy_r4_ZT'], 24.5, places=5)
        self.assertAlmostEqual(result['optimized_params']['zz_r4_ZT'], -13.25, places=5)
        self.assertLess(result['final_cost'], result['initial_cost'])


class CalibrationDataLoaderTests(unittest.TestCase):
    def test_loader_accepts_excel_columns(self):
        with tempfile.TemporaryDirectory() as directory:
            filepath = os.path.join(directory, 'MeasData.xlsx')
            pd.DataFrame({
                'az_true': [10, 20],
                'el_true': [2, 3],
                'az_meas': [10.1, 20.2],
                'el_meas': [1.9, 2.8],
            }).to_excel(filepath, index=False)
            data = load_calibration_data(filepath)

        self.assertEqual(data['sample_count'], 2)
        np.testing.assert_allclose(data['az_true'], [10, 20])

    def test_loader_accepts_named_csv_columns(self):
        with tempfile.TemporaryDirectory() as directory:
            filepath = os.path.join(directory, 'measurements.csv')
            with open(filepath, 'w', newline='', encoding='utf-8') as file:
                writer = csv.writer(file)
                writer.writerow(['az_true', 'el_true', 'az_meas', 'el_meas'])
                writer.writerow([10, 2, 10.1, 1.9])
                writer.writerow([20, 3, 20.2, 2.8])
            data = load_calibration_data(filepath)

        self.assertEqual(data['sample_count'], 2)
        np.testing.assert_allclose(data['az_meas'], [10.1, 20.2])

    def test_loader_accepts_headerless_csv(self):
        with tempfile.TemporaryDirectory() as directory:
            filepath = os.path.join(directory, 'measurements.csv')
            with open(filepath, 'w', newline='', encoding='utf-8') as file:
                writer = csv.writer(file)
                writer.writerow([10, 2, 10.1, 1.9])
                writer.writerow([20, 3, 20.2, 2.8])
            data = load_calibration_data(filepath)

        self.assertEqual(data['sample_count'], 2)
        np.testing.assert_allclose(data['el_true'], [2, 3])

    def test_loader_rejects_partially_invalid_first_data_row(self):
        with tempfile.TemporaryDirectory() as directory:
            filepath = os.path.join(directory, 'measurements.csv')
            with open(filepath, 'w', newline='', encoding='utf-8') as file:
                writer = csv.writer(file)
                writer.writerow([10, 2, 'invalid', 1.9])
                writer.writerow([20, 3, 20.2, 2.8])
            with self.assertRaises(ValueError):
                load_calibration_data(filepath)


class CalibrationBatchStoreTests(unittest.TestCase):
    def test_profile_create_update_and_delete(self):
        with tempfile.TemporaryDirectory() as directory:
            filepath = os.path.join(directory, 'batch_configs.json')
            store = CalibrationBatchStore(filepath)
            self.assertEqual(len(store.list_profiles()), 1)

            profile = {
                'name': '暗室 A01',
                'data_path': 'D:/calibration/a01.xlsx',
                'fixed_params': DEFAULT_FIXED_PARAMS,
                'init_params': DEFAULT_INIT_PARAMS,
                'notes': '首次装调',
            }
            created = store.save_profile(profile)
            created['fixed_params']['rho_obj'] = 16000.0
            updated = store.save_profile(created, created['id'])

            reloaded = CalibrationBatchStore(filepath)
            saved = reloaded.get_profile(created['id'])
            self.assertEqual(saved['fixed_params']['rho_obj'], 16000.0)
            self.assertEqual(saved['notes'], '首次装调')
            self.assertTrue(reloaded.delete_profile(updated['id']))
            self.assertIsNone(reloaded.get_profile(updated['id']))

    def test_duplicate_profile_names_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            store = CalibrationBatchStore(os.path.join(directory, 'batch_configs.json'))
            profile = {
                'name': '重复批次',
                'fixed_params': DEFAULT_FIXED_PARAMS,
                'init_params': DEFAULT_INIT_PARAMS,
            }
            store.save_profile(profile)
            with self.assertRaises(ValueError):
                store.save_profile(profile)


if __name__ == '__main__':
    unittest.main()
