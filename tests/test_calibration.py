"""Regression tests for direction-finding calibration."""

from __future__ import annotations

import csv
import json
import os
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from radar_tool import calibration_batch_store
from radar_tool.calibration_batch_store import (
    DEFAULT_FIXED_PARAMS,
    DEFAULT_INIT_PARAMS,
    CalibrationBatchStore,
    create_default_profile,
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

    def test_corrupt_file_is_quarantined_and_recoverable(self):
        with tempfile.TemporaryDirectory() as directory:
            filepath = os.path.join(directory, 'batch_configs.json')
            with open(filepath, 'w', encoding='utf-8') as handle:
                handle.write('{broken json')

            store = CalibrationBatchStore(filepath)

            corrupt_files = [
                name for name in os.listdir(directory)
                if name.startswith('batch_configs.json.corrupt-')
            ]
            self.assertEqual(len(corrupt_files), 1)
            corrupt_path = os.path.join(directory, corrupt_files[0])
            with open(corrupt_path, encoding='utf-8') as handle:
                self.assertEqual(handle.read(), '{broken json')
            self.assertTrue(os.path.isfile(filepath))
            self.assertEqual(len(store.list_profiles()), 1)

    def test_single_invalid_profile_is_skipped_and_valid_profile_loads(self):
        with tempfile.TemporaryDirectory() as directory:
            filepath = os.path.join(directory, 'batch_configs.json')
            valid = create_default_profile('合法配置')
            valid['id'] = 'valid-id'
            invalid = create_default_profile('非法配置')
            invalid['id'] = 'invalid-id'
            invalid['fixed_params']['matrixZT2ANT'][0][0] = float('nan')
            payload = {
                'version': CalibrationBatchStore.VERSION,
                'profiles': [valid, invalid],
            }
            with open(filepath, 'w', encoding='utf-8') as handle:
                json.dump(payload, handle, ensure_ascii=False)

            with self.assertLogs(
                'radar_tool.calibration_batch_store', level='WARNING'
            ):
                store = CalibrationBatchStore(filepath)

            profiles = store.list_profiles()
            self.assertEqual([item['name'] for item in profiles], ['合法配置'])
            self.assertTrue(os.path.exists(filepath))

    def test_duplicate_profile_ids_are_skipped(self):
        with tempfile.TemporaryDirectory() as directory:
            filepath = os.path.join(directory, 'batch_configs.json')
            first = create_default_profile('第一项')
            second = create_default_profile('第二项')
            first['id'] = second['id'] = 'duplicate-id'
            payload = {
                'version': CalibrationBatchStore.VERSION,
                'profiles': [first, second],
            }
            with open(filepath, 'w', encoding='utf-8') as handle:
                json.dump(payload, handle, ensure_ascii=False)

            with self.assertLogs(
                'radar_tool.calibration_batch_store', level='WARNING'
            ):
                store = CalibrationBatchStore(filepath)

            self.assertEqual(len(store.list_profiles()), 1)
            self.assertEqual(store.list_profiles()[0]['name'], '第一项')

    def test_profile_validation_rejects_nonfinite_and_unknown_parameters(self):
        with tempfile.TemporaryDirectory() as directory:
            store = CalibrationBatchStore(
                os.path.join(directory, 'batch_configs.json')
            )
            base = create_default_profile('待校验')
            for field, value in (
                ('name', 123),
                ('fixed_params', []),
                ('init_params', None),
            ):
                invalid = dict(base)
                invalid[field] = value
                with self.assertRaises(ValueError):
                    store.save_profile(invalid)

            invalid_matrix = dict(base)
            invalid_matrix['fixed_params'] = {
                'matrixZT2ANT': [
                    [float('nan'), 0.0, 0.0],
                    [0.0, 1.0, 0.0],
                    [0.0, 0.0, 1.0],
                ]
            }
            with self.assertRaises(ValueError):
                store.save_profile(invalid_matrix)

            unknown = dict(base)
            unknown['fixed_params'] = {'unknown_param': 1.0}
            with self.assertRaises(ValueError):
                store.save_profile(unknown)

    def test_successful_save_keeps_previous_valid_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            filepath = os.path.join(directory, 'batch_configs.json')
            store = CalibrationBatchStore(filepath)
            first = store.list_profiles()[0]
            first['name'] = '第一次保存'
            store.save_profile(first, first['id'])
            self.assertTrue(os.path.exists(filepath + '.bak'))

            second = dict(first)
            second['name'] = '第二次保存'
            store.save_profile(second, first['id'])

            with open(filepath, encoding='utf-8') as handle:
                current = json.load(handle)
            with open(filepath + '.bak', encoding='utf-8') as handle:
                backup = json.load(handle)
            self.assertEqual(current['profiles'][0]['name'], '第二次保存')
            self.assertEqual(backup['profiles'][0]['name'], '第一次保存')

    def test_json_size_and_depth_limits_quarantine_file(self):
        with tempfile.TemporaryDirectory() as directory:
            filepath = os.path.join(directory, 'batch_configs.json')
            with open(filepath, 'w', encoding='utf-8') as handle:
                handle.write('{"version": 1, "profiles": []}')
            with patch.object(
                calibration_batch_store, 'MAX_JSON_FILE_SIZE', 10
            ):
                CalibrationBatchStore(filepath)
            self.assertTrue(os.path.isfile(filepath))
            self.assertTrue(any(
                name.startswith('batch_configs.json.corrupt-')
                for name in os.listdir(directory)
            ))

        with tempfile.TemporaryDirectory() as directory:
            filepath = os.path.join(directory, 'batch_configs.json')
            nested = {
                'version': 1,
                'profiles': [
                    {
                        'name': '深度',
                        'fixed_params': {'nested': {'a': {'b': {'c': 1}}}},
                    }
                ],
            }
            with open(filepath, 'w', encoding='utf-8') as handle:
                json.dump(nested, handle)
            with patch.object(
                calibration_batch_store, 'MAX_JSON_NESTING_DEPTH', 3
            ):
                CalibrationBatchStore(filepath)
            self.assertTrue(os.path.isfile(filepath))
            self.assertTrue(any(
                name.startswith('batch_configs.json.corrupt-')
                for name in os.listdir(directory)
            ))

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
