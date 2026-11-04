"""Offscreen integration tests for responsive truth review analysis."""

import os
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import numpy as np
import pandas as pd
from PyQt5.QtCore import QEventLoop, QTimer, Qt
from PyQt5.QtWidgets import QApplication, QLabel, QMainWindow

from radar_tool.compare_analysis import (
    CompareAnalysisMixin, MAX_PLOT_POINTS, find_metric_column,
)
from radar_tool.main_window import MainWindow
from radar_tool.run import configure_matplotlib


class TruthReviewHost(QMainWindow, CompareAnalysisMixin):
    def __init__(self):
        super().__init__()
        self.compare_test_df = None
        self.compare_test_original_df = None
        self.compare_truth_df = None
        self.compare_test_filepath = ''
        self.compare_truth_filepath = ''
        self.compare_meta_cols = None
        self.compare_last_result = None
        self.compare_last_metrics = None
        self.status_label = QLabel()
        self.setCentralWidget(self._create_compare_analysis_page())


class TruthReviewPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        configure_matplotlib()
        cls.app = QApplication.instance() or QApplication([])

    def _wait_for_worker(self, host):
        thread = host._compare_thread
        completed = []
        thread.finished.connect(lambda: completed.append(True))
        deadline = time.monotonic() + 10
        while not completed and time.monotonic() < deadline:
            self.app.processEvents(QEventLoop.AllEvents, 50)
            time.sleep(0.001)
        self.app.processEvents()
        self.assertTrue(
            completed,
            "数据真值复核后台任务超过 10 秒仍未结束",
        )

    def _run_two_stages(self, host):
        host.run_compare_coarse_alignment()
        self._wait_for_worker(host)
        self.assertIsNotNone(host.compare_coarse_mapping)
        host.run_compare_fine_alignment()
        self._wait_for_worker(host)

    def test_analysis_runs_in_background_and_decimates_plots(self):
        host = TruthReviewHost()
        radar_time = np.arange(20_000, dtype=float) * 0.128
        truth_time = np.arange(5_000, dtype=float) * 0.512
        host.compare_test_df = pd.DataFrame({
            'distance': 100.0 + np.sin(0.01 * radar_time),
            'speed': np.cos(0.01 * radar_time),
            'elevation': 2.0 * np.sin(0.005 * radar_time),
            'azimuth': 5.0 * np.cos(0.004 * radar_time),
        })
        host.compare_truth_df = pd.DataFrame({
            'time': truth_time,
            'x': np.zeros(len(truth_time)),
            'y': np.zeros(len(truth_time)),
            'z': np.zeros(len(truth_time)),
            'distance': 100.0 + np.sin(0.01 * truth_time),
            'speed': np.cos(0.01 * truth_time),
            'azimuth': 5.0 * np.cos(0.004 * truth_time),
            'elevation': 2.0 * np.sin(0.005 * truth_time),
        })
        host._refresh_compare_column_combos()

        host.run_compare_analysis()
        self.assertTrue(host._compare_thread.isRunning())
        self.assertFalse(host.btn_cmp_run.isEnabled())
        self.assertTrue(host.spin_cmp_range_start.isEnabled())
        self.assertTrue(host.btn_cmp_apply_filter.isEnabled())

        responsive = []
        QTimer.singleShot(0, lambda: responsive.append(True))
        self._wait_for_worker(host)

        self.assertTrue(responsive)
        self.assertIsNotNone(host.compare_coarse_mapping)
        self.assertIsNone(host.compare_last_result)
        self.assertTrue(host.btn_cmp_run_fine.isEnabled())
        host.run_compare_fine_alignment()
        self._wait_for_worker(host)
        self.assertEqual(len(host.compare_last_result), 20_000)
        np.testing.assert_array_equal(
            host.compare_last_result['radar_sample_index'].to_numpy(),
            np.arange(20_000),
        )
        self.assertNotIn('aligned_time_s', host.compare_last_result.columns)
        self.assertTrue(host.btn_cmp_run.isEnabled())
        self.assertEqual(host.tabs_cmp_results.count(), 10)
        plotted_lengths = [
            len(line.get_xdata())
            for axis in host.compare_figures['overview'].axes
            for line in axis.lines
        ]
        self.assertLessEqual(max(plotted_lengths), MAX_PLOT_POINTS)
        host.close()
        self.app.processEvents()

    def test_initial_split_shows_complete_left_control_panel(self):
        host = TruthReviewHost()
        host.resize(1400, 900)
        host.show()
        self.app.processEvents()
        QTimer.singleShot(0, lambda: None)
        self.app.processEvents()

        left_width, _right_width = host.compare_splitter.sizes()
        self.assertGreaterEqual(left_width, 680)
        self.assertEqual(host.compare_left_scroll.verticalScrollBar().maximum(), 0)
        self.assertEqual(host.compare_left_scroll.horizontalScrollBar().maximum(), 0)
        host.close()

    def test_radar_load_matches_visualization_flow_and_auto_maps_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            data_path = os.path.join(directory, 'RADAR.txt')
            columns_path = os.path.join(directory, 'RADAR列名.txt')
            np.savetxt(data_path, np.arange(60, dtype=float).reshape(10, 6))
            with open(columns_path, 'w', encoding='utf-8') as handle:
                handle.write('时间\n目标距离\n目标速度\n目标俯仰角\n目标方位角\n方位角速度\n')

            host = TruthReviewHost()
            truth_time = np.arange(10, dtype=float)
            host.compare_truth_df = pd.DataFrame({
                f'列--{index + 1}': values
                for index, values in enumerate([
                    truth_time, np.zeros(10), np.zeros(10), np.zeros(10),
                    np.arange(10), np.arange(10), np.arange(10), np.arange(10),
                ])
            })
            with patch(
                'radar_tool.compare_analysis.QFileDialog.getOpenFileName',
                return_value=(data_path, ''),
            ):
                host.load_compare_test_data()

            self.assertEqual(host.compare_meta_filepath, columns_path)
            self.assertEqual(
                list(host.compare_test_df.columns),
                ['时间', '目标距离', '目标速度', '目标俯仰角', '目标方位角', '方位角速度'],
            )
            expected = {
                'distance': '目标距离', 'speed': '目标速度',
                'azimuth': '目标方位角', 'elevation': '目标俯仰角',
            }
            for key, column in expected.items():
                widgets = host.compare_mapping_widgets[key]
                self.assertEqual(widgets['radar'].currentData(), column)
                self.assertEqual(
                    widgets['enabled'].isChecked(), True,
                )
            host.close()

    def test_only_checked_distance_is_analyzed(self):
        host = TruthReviewHost()
        radar_time = np.arange(100, dtype=float) * 0.128
        truth_time = np.arange(50, dtype=float) * 0.256
        host.compare_test_df = pd.DataFrame({
            '目标距离': 100.0 + np.sin(radar_time),
            '目标速度': np.cos(radar_time),
            '目标方位角': np.sin(radar_time),
            '目标俯仰角': np.cos(radar_time),
        })
        host.compare_truth_df = pd.DataFrame({
            '时间': truth_time,
            '距离': 100.0 + np.sin(truth_time),
            '速度': np.cos(truth_time),
            '方位角': np.sin(truth_time),
            '俯仰角': np.cos(truth_time),
        })
        host._refresh_compare_column_combos()
        for key in ('speed', 'azimuth', 'elevation'):
            widgets = host.compare_mapping_widgets[key]
            widgets['enabled'].setChecked(False)

        self._run_two_stages(host)

        self.assertEqual(
            list(host.compare_last_result.columns),
            [
                'radar_sample_index', 'paired_sample_kept', 'radar_distance',
                'gps_aligned_distance', 'error_distance',
            ],
        )
        self.assertEqual(set(host.compare_last_metrics['metrics']), {'distance'})
        self.assertEqual(host.table_cmp_metrics.rowCount(), 1)
        host.close()

    def test_additional_outlier_settings_accept_all_enabled_non_reference_metrics(self):
        host = TruthReviewHost()
        sample = np.arange(20, dtype=float)
        host.compare_test_df = pd.DataFrame({
            '目标距离': sample,
            '目标速度': sample * 0.5,
            '目标方位角': sample * 0.2,
            '目标俯仰角': sample * 0.1,
        })
        host.compare_truth_df = pd.DataFrame({
            '时间': sample * 0.128,
            '距离': sample,
            '速度': sample * 0.5,
            '方位角': sample * 0.2,
            '俯仰角': sample * 0.1,
        })
        host._refresh_compare_column_combos()

        self.assertEqual(host.combo_cmp_reference.currentData(), 'distance')
        self.assertTrue(host.btn_cmp_outlier_dimensions.isEnabled())
        self.assertEqual(host.lbl_cmp_outlier_dimensions.text(), '备选: 未启用')
        with patch(
            'radar_tool.compare_analysis.QDialog.exec_', return_value=0
        ):
            host.configure_compare_outlier_dimensions()
        host._set_compare_additional_outlier_settings({
            'speed': {'enabled': True, 'threshold': 1.5},
            'azimuth': {'enabled': True, 'threshold': 2.5},
            'elevation': {'enabled': True, 'threshold': 0.0},
        })
        self.assertEqual(
            [item['key'] for item in host._selected_compare_additional_outlier_dimensions()],
            ['speed', 'azimuth', 'elevation'],
        )
        self.assertIn('速度', host.lbl_cmp_outlier_dimensions.text())
        self.assertIn('方位角', host.lbl_cmp_outlier_dimensions.text())
        self.assertIn('俯仰角', host.lbl_cmp_outlier_dimensions.text())
        self.assertEqual(host.spin_cmp_outlier_threshold.suffix(), ' m')
        host.close()

    def test_raw_plot_uses_irregular_gps_timestamps(self):
        host = TruthReviewHost()
        sample = np.arange(12, dtype=float)
        host.compare_test_df = pd.DataFrame({'目标距离': sample})
        host.compare_truth_df = pd.DataFrame({
            '时间': [0.0, 100.0, 101.0, 900.0, 901.0, 5000.0],
            '距离': np.arange(6, dtype=float) * 2.0,
        })
        host._refresh_compare_column_combos()
        for key in ('speed', 'azimuth', 'elevation'):
            widgets = host.compare_mapping_widgets[key]
            widgets['enabled'].setChecked(False)

        host.plot_compare_raw_data()
        axis = host.compare_figures['raw'].axes[0]
        np.testing.assert_array_equal(axis.lines[0].get_xdata(), np.arange(12))
        np.testing.assert_allclose(
            axis.lines[1].get_xdata(),
            np.asarray([0.0, 100.0, 101.0, 900.0, 901.0, 5000.0]) * 1000 / 128,
        )
        self.assertIn('GPS 由时间列', axis.get_xlabel())
        self.assertEqual(host.combo_cmp_truth_time.currentData(), '时间')
        host.close()

    def test_radar_filter_and_range_are_applied_and_can_be_reset(self):
        host = TruthReviewHost()
        host.compare_test_df = pd.DataFrame({
            '目标距离': [-100.0, 10.0, 20.0, 30.0, 40.0, 999.0],
            '目标速度': np.arange(6, dtype=float),
        })
        host.compare_truth_df = pd.DataFrame({'距离': np.arange(10, dtype=float)})
        host._refresh_compare_column_combos()

        host.combo_cmp_filter_col.setCurrentIndex(
            host.combo_cmp_filter_col.findData('目标距离')
        )
        host.edit_cmp_filter_min.setText('0')
        host.edit_cmp_filter_max.setText('100')
        host.apply_compare_filter()
        self.assertEqual(host.compare_test_df['目标距离'].tolist(), [10.0, 20.0, 30.0, 40.0])
        self.assertEqual(len(host.compare_test_original_df), 6)
        self.assertEqual(host.lbl_cmp_stat_radar_original.text(), '雷达原始: 6 点')
        self.assertEqual(host.lbl_cmp_stat_radar_filtered.text(), '雷达过滤后: 4 点')
        self.assertEqual(
            host.lbl_cmp_stat_radar_selected.text(), '雷达过滤截取后: 4 点'
        )

        host.spin_cmp_range_start.setValue(1)
        host.spin_cmp_range_end.setValue(3)
        self.assertEqual(host._current_compare_radar_df()['目标距离'].tolist(), [10.0, 20.0])
        self.assertIn('2 / 原始 6', host.lbl_cmp_range_count.text())
        self.assertEqual(
            host.lbl_cmp_stat_radar_selected.text(), '雷达过滤截取后: 2 点'
        )

        host.plot_compare_raw_data()
        range_axis = host.compare_figures['range'].axes[0]
        np.testing.assert_array_equal(range_axis.lines[0].get_xdata(), np.arange(6))
        np.testing.assert_array_equal(range_axis.lines[1].get_xdata(), [1, 2])

        host.clear_compare_filter()
        self.assertEqual(host.compare_test_df['目标距离'].tolist(), [-100.0, 10.0, 20.0, 30.0, 40.0, 999.0])
        self.assertEqual(host.spin_cmp_range_start.value(), 1)
        self.assertEqual(host.spin_cmp_range_end.value(), 3)
        self.assertEqual(
            host.lbl_cmp_stat_radar_selected.text(), '雷达过滤截取后: 2 点'
        )
        host.close()

    def test_selected_range_controls_analysis_length(self):
        host = TruthReviewHost()
        radar = np.sin(np.arange(20, dtype=float) / 3.0)
        truth = np.sin(np.arange(10, dtype=float) * 2.0 / 3.0)
        host.compare_test_df = pd.DataFrame({'目标距离': radar})
        host.compare_truth_df = pd.DataFrame({
            '时间': np.arange(10, dtype=float) * 0.256,
            '距离': truth,
        })
        host._refresh_compare_column_combos()
        for key in ('speed', 'azimuth', 'elevation'):
            widgets = host.compare_mapping_widgets[key]
            widgets['enabled'].setChecked(False)
        host.spin_cmp_range_start.setValue(4)
        host.spin_cmp_range_end.setValue(14)

        self._run_two_stages(host)

        self.assertEqual(len(host.compare_last_result), 10)
        np.testing.assert_array_equal(
            host.compare_last_result['radar_sample_index'].to_numpy(), np.arange(10)
        )
        self.assertNotIn('aligned_time_s', host.compare_last_result.columns)
        overview_axis = host.compare_figures['overview'].axes[0]
        np.testing.assert_array_equal(overview_axis.lines[0].get_xdata(), np.arange(10))
        self.assertEqual(overview_axis.get_xlabel(), '对齐后雷达样点索引')
        alignment = host.compare_last_metrics['alignment']
        self.assertIn('query_offset_samples', alignment)
        self.assertIn('manual_offset_samples', alignment)
        self.assertNotIn('query_offset_s', alignment)
        self.assertNotIn('manual_offset_s', alignment)
        self.assertEqual(host.lbl_cmp_stat_truth_original.text(), 'GPS 插值前: 10 点')
        interpolated = host.compare_last_metrics['truth_samples_after_interpolation']
        interpolated_valid = host.compare_last_metrics[
            'truth_valid_samples_after_interpolation'
        ]
        self.assertEqual(
            host.lbl_cmp_stat_truth_aligned.text(),
            f'GPS 插值后: {interpolated} 点（有效 {interpolated_valid}）',
        )
        aligned_valid = host.compare_last_metrics['truth_valid_samples_after_alignment']
        self.assertEqual(
            host.lbl_cmp_stat_alignment_valid.text(),
            f'GPS 对齐后有效: {aligned_valid} 点',
        )
        interpolation_axis = host.compare_figures['interpolation'].axes[0]
        self.assertEqual(len(interpolation_axis.lines), 2)
        self.assertIn('GPS 时间插值后', interpolation_axis.lines[1].get_label())
        np.testing.assert_allclose(
            interpolation_axis.lines[0].get_xdata(), np.arange(10) * 2
        )
        np.testing.assert_array_equal(
            interpolation_axis.lines[1].get_xdata(), np.arange(19)
        )
        host.close()

    def test_radar_filter_is_applied_before_alignment(self):
        host = TruthReviewHost()
        host.compare_test_df = pd.DataFrame({
            '目标距离': [-999.0, 10.0, 20.0, 30.0, 999.0],
        })
        host.compare_truth_df = pd.DataFrame({
            '时间': np.arange(3, dtype=float) * 0.128,
            '距离': [10.0, 20.0, 30.0],
        })
        host._refresh_compare_column_combos()
        for key in ('speed', 'azimuth', 'elevation'):
            host.compare_mapping_widgets[key]['enabled'].setChecked(False)
        host.combo_cmp_filter_col.setCurrentIndex(
            host.combo_cmp_filter_col.findData('目标距离')
        )
        host.edit_cmp_filter_min.setText('0')
        host.edit_cmp_filter_max.setText('100')
        host.apply_compare_filter()

        self._run_two_stages(host)

        np.testing.assert_array_equal(
            host.compare_last_result['radar_distance'].to_numpy(),
            [10.0, 20.0, 30.0],
        )
        self.assertEqual(len(host.compare_last_result), 3)

        host.spin_cmp_range_end.setValue(2)
        self.assertIsNone(host.compare_last_result)
        self.assertEqual(len(host.compare_figures['overview'].axes[0].lines), 0)
        self.assertIn('重新执行', host.txt_cmp_stats.toPlainText())
        host.close()

    def test_filter_does_not_reset_original_sample_range(self):
        host = TruthReviewHost()
        host.compare_test_df = pd.DataFrame({
            '目标距离': [-999.0, 10.0, 20.0, 30.0, 40.0, 999.0],
        })
        host.compare_truth_df = pd.DataFrame({'距离': [20.0, 30.0, 40.0]})
        host._refresh_compare_column_combos()
        host.spin_cmp_range_start.setValue(2)
        host.spin_cmp_range_end.setValue(5)
        host.combo_cmp_filter_col.setCurrentIndex(
            host.combo_cmp_filter_col.findData('目标距离')
        )
        host.edit_cmp_filter_min.setText('0')
        host.edit_cmp_filter_max.setText('100')

        host.apply_compare_filter()

        self.assertEqual(host.spin_cmp_range_start.value(), 2)
        self.assertEqual(host.spin_cmp_range_end.value(), 5)
        self.assertEqual(
            host._current_compare_radar_df()['目标距离'].tolist(),
            [20.0, 30.0, 40.0],
        )
        self.assertEqual(host.lbl_cmp_stat_radar_original.text(), '雷达原始: 6 点')
        self.assertEqual(host.lbl_cmp_stat_radar_filtered.text(), '雷达过滤后: 4 点')
        self.assertEqual(
            host.lbl_cmp_stat_radar_selected.text(), '雷达过滤截取后: 3 点'
        )
        host.close()

    def test_truth_review_and_visualization_keep_independent_data_state(self):
        with tempfile.TemporaryDirectory() as directory:
            data_path = os.path.join(directory, 'RADAR.txt')
            np.savetxt(data_path, np.arange(40, dtype=float).reshape(10, 4))

            window = MainWindow()
            visualization = window._tab_panels[0]
            window._lazy_create_or_get_panel(1)
            with patch(
                'radar_tool.compare_analysis.QFileDialog.getOpenFileName',
                return_value=(data_path, ''),
            ):
                window.load_compare_test_data()

            self.assertIsNotNone(window.compare_test_df)
            self.assertEqual(visualization.datasets, {})
            self.assertIsNone(visualization.current_df)
            window.close()

    def test_complete_export_creates_named_batch_with_bilingual_csv_headers(self):
        with tempfile.TemporaryDirectory() as directory:
            host = TruthReviewHost()
            sample = np.arange(20, dtype=float)
            host.compare_test_filepath = os.path.join(directory, 'RADAR_A.txt')
            host.compare_truth_filepath = os.path.join(directory, 'GPS_A.txt')
            utc_time = 1_700_000_000.0 + sample * 0.128
            host.compare_test_df = pd.DataFrame({
                '目标距离': 100.0 + sample,
                '目标速度': sample * 0.5,
            })
            host.compare_truth_df = pd.DataFrame({
                '时间': utc_time,
                '距离': 100.0 + sample,
                '速度': sample * 0.5,
            })
            host._refresh_compare_column_combos()
            host.compare_mapping_widgets['speed']['enabled'].setChecked(False)
            host.combo_cmp_method.setCurrentIndex(
                host.combo_cmp_method.findData('single_point')
            )
            self._run_two_stages(host)

            export_root = os.path.join(directory, '完整结果')
            os.makedirs(export_root)
            with patch(
                'radar_tool.compare_analysis.QFileDialog.getExistingDirectory',
                return_value=export_root,
            ):
                host.export_compare_result()

            batches = [
                os.path.join(export_root, name)
                for name in os.listdir(export_root)
                if os.path.isdir(os.path.join(export_root, name))
            ]
            self.assertEqual(len(batches), 1)
            batch = batches[0]
            self.assertRegex(os.path.basename(batch), r'^\d{8}_\d{6}_RADAR_A_真值复核$')
            expected_files = {
                '01_真值复核结果.csv', '02_真值复核有效配对.csv',
                '03_雷达测量数据.csv', '04_GPS原始真值数据.csv',
                '05_GPS时间插值数据.csv', '06_粗对齐结果.csv',
                '07_误差指标.csv', '08_对齐算法比较.csv',
                '09_复核配置.json', '图件_04_粗对齐差值.png',
                '图件_05_精对齐曲线.png',
            }
            self.assertTrue(expected_files.issubset(set(os.listdir(batch))))

            final_table = pd.read_csv(
                os.path.join(batch, '01_真值复核结果.csv'), encoding='utf-8-sig'
            )
            self.assertIn('雷达距离原始(radar_distance_raw)', final_table.columns)
            self.assertIn(
                'GPS距离粗对齐(gps_distance_coarse_aligned)', final_table.columns
            )
            self.assertIn(
                'GPS距离精对齐(gps_distance_fine_aligned)', final_table.columns
            )
            self.assertIn(
                'GPS精对齐UTC时间(gps_fine_aligned_utc_time)', final_table.columns
            )
            self.assertIn('GPS UTC时间单位(gps_utc_time_unit)', final_table.columns)
            np.testing.assert_allclose(
                final_table['GPS精对齐UTC时间(gps_fine_aligned_utc_time)'],
                utc_time,
            )
            self.assertEqual(
                set(final_table['GPS UTC时间单位(gps_utc_time_unit)']), {'s'}
            )
            self.assertTrue(all('(' in column and ')' in column for column in final_table.columns))

            radar_table = pd.read_csv(
                os.path.join(batch, '03_雷达测量数据.csv'), encoding='utf-8-sig'
            )
            self.assertIn('雷达距离原始(radar_distance_raw)', radar_table.columns)
            self.assertIn(
                'GPS精对齐UTC时间(gps_fine_aligned_utc_time)', radar_table.columns
            )
            self.assertFalse(any('speed' in column for column in radar_table.columns))

            gps_raw_table = pd.read_csv(
                os.path.join(batch, '04_GPS原始真值数据.csv'), encoding='utf-8-sig'
            )
            np.testing.assert_allclose(
                gps_raw_table['GPS原始UTC时间(gps_utc_time_raw)'], utc_time
            )
            gps_interpolated_table = pd.read_csv(
                os.path.join(batch, '05_GPS时间插值数据.csv'), encoding='utf-8-sig'
            )
            np.testing.assert_allclose(
                gps_interpolated_table['GPS插值UTC时间(gps_interpolated_utc_time)'],
                utc_time,
            )
            host.close()


class MetricColumnMatchingTests(unittest.TestCase):
    def test_angle_columns_do_not_match_angular_velocity(self):
        columns = ['目标距离', '目标速度', '方位角速度', '俯仰角速度', '目标方位角', '目标俯仰角']
        self.assertEqual(find_metric_column(columns, 'distance'), '目标距离')
        self.assertEqual(find_metric_column(columns, 'speed'), '目标速度')
        self.assertEqual(find_metric_column(columns, 'azimuth'), '目标方位角')
        self.assertEqual(find_metric_column(columns, 'elevation'), '目标俯仰角')


if __name__ == '__main__':
    unittest.main()
