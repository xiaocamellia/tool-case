"""Background comparison analysis orchestration."""
import json
import math
import os
import re
from datetime import datetime
import numpy as np
import pandas as pd
from PyQt5.QtCore import QObject, QThread, QTimer, Qt, pyqtSignal, pyqtSlot
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog,
    QGridLayout, QDialog, QDialogButtonBox, QGroupBox, QHBoxLayout,
    QHeaderView, QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea,
    QSpinBox, QSplitter, QTableWidget, QTableWidgetItem, QTabWidget, QTextEdit,
    QVBoxLayout, QWidget,
)
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
from matplotlib.figure import Figure
from .alignment import (
    apply_time_mapping, calculate_error_metrics, estimate_time_mapping,
    interpolate_at,
)
from .data_loader import DataLoader, read_numeric_table
from .error_ui import handle_ui_exception
from .errors import ExportError, safe_exception_message
from .schemas import TruthReviewConfig
from .logger import get_logger
from .ui_theme import set_button_icon, style_primary_button
from .background_tasks import (
    ensure_task_can_start, register_background_task, task_result_is_current,
)
from .compare_core import (
    MAX_PLOT_POINTS, METRIC_BY_KEY, METRIC_COLUMN_ALIASES, METRIC_DEFINITIONS, TruthReviewWorker, _compute_truth_review, _decimate_plot_arrays, _estimate_fixed_scale_alignment, _normalize_column_name, _paired_outlier_mask, _sample_mapping, find_metric_column, resample_gps_to_radar_cadence
)
logger = get_logger("compare_analysis")

class CompareWorkerMixin:
    def run_compare_analysis(self):
        """Backward-compatible entry point: execute the required coarse stage."""
        self.run_compare_coarse_alignment()
    def run_compare_coarse_alignment(self):
        self._run_compare_stage('coarse')
    def run_compare_fine_alignment(self):
        self._run_compare_stage('fine')
    def _run_compare_stage(self, stage):
        if getattr(self, '_compare_thread', None) is not None:
            if self._compare_thread.isRunning():
                self.status_label.setText('数据真值复核仍在后台计算')
                return
        if self.compare_test_df is None or self.compare_truth_df is None:
            QMessageBox.information(self, '数据未就绪', '请先加载雷达数据与真值数据')
            return
        try:
            if stage == 'fine' and getattr(self, 'compare_coarse_mapping', None) is None:
                raise ValueError('请先运行第 1 步粗对齐')
            radar_df = self._current_compare_radar_df()
            if radar_df is None or len(radar_df) < 3:
                raise ValueError('当前雷达截取范围的有效样点不足（至少需要 3 个点）')
            configs = self._enabled_metric_configs()
            reference_key = self.combo_cmp_reference.currentData()
            reference = next((item for item in configs if item['key'] == reference_key), None)
            if reference is None:
                reference = configs[0]
                reference_key = reference['key']
                self.combo_cmp_reference.setCurrentIndex(
                    self.combo_cmp_reference.findData(reference_key)
                )

            source_indices = self._current_compare_radar_source_indices().astype(float)
            radar_sample = source_indices - source_indices[0]
            time_column = self.combo_cmp_truth_time.currentData()
            if time_column is None:
                raise ValueError('GPS 时间列未选择；默认应为真值文件第一列')
            gps_time = pd.to_numeric(
                self.compare_truth_df[time_column], errors='coerce'
            ).to_numpy(dtype=float)
            ref_radar = pd.to_numeric(radar_df[reference['radar_col']], errors='coerce').to_numpy(dtype=float)
            ref_truth = pd.to_numeric(self.compare_truth_df[reference['truth_col']], errors='coerce').to_numpy(dtype=float)
            radar_valid = int(np.count_nonzero(np.isfinite(ref_radar)))
            truth_valid = int(np.count_nonzero(np.isfinite(ref_truth)))
            if radar_valid < 3 or truth_valid < 3:
                raise ValueError(
                    f"参考维度“{reference['label']}”有效样点不足："
                    f"雷达列“{reference['radar_col']}”有 {radar_valid} 个，"
                    f"真值列“{reference['truth_col']}”有 {truth_valid} 个。"
                    '请在“原始数据”页检查曲线，并确认字段映射、截取范围与过滤条件。'
                )

            series = {}
            for config in configs:
                radar_source = pd.to_numeric(radar_df[config['radar_col']], errors='coerce').to_numpy(dtype=float)
                truth_source = pd.to_numeric(self.compare_truth_df[config['truth_col']], errors='coerce').to_numpy(dtype=float)
                series[config['key']] = {
                    'config': config,
                    'radar_source': radar_source,
                    'truth_source': truth_source,
                }
            payload = {
                'stage': stage,
                'radar_sample': radar_sample,
                'gps_time': gps_time,
                'gps_time_column': str(time_column),
                'gps_time_unit': self.combo_cmp_truth_time_unit.currentData(),
                'radar_interval_ms': float(self.spin_cmp_radar_interval.value()),
                'series': series,
                'reference_key': reference_key,
                'reference_angular': bool(reference['angular']),
                'method': self.combo_cmp_method.currentData(),
                'interpolation': self.combo_cmp_interpolation.currentData(),
                'max_shift_ratio': float(self.spin_cmp_max_shift_ratio.value()),
                'scale_span': float(self.spin_cmp_scale_span.value()),
                # The alignment module uses generic historical "time" names;
                # values passed here are deliberately in sample units.
                'manual_offset_s': float(self.spin_cmp_manual_offset.value()),
                'outlier_threshold': float(self.spin_cmp_outlier_threshold.value()),
                'additional_outlier_dimensions': (
                    self._selected_compare_additional_outlier_dimensions()
                ),
                'coarse_mapping': getattr(self, 'compare_coarse_mapping', None),
                'preprocess_revision': getattr(
                    self, 'compare_preprocess_revision', 0
                ),
            }
            self._start_compare_worker(payload)
        except Exception as exc:
            handle_ui_exception(
                self, logger, '执行真值复核', exc
            )
    def _start_compare_worker(self, payload):
        task_name = (
            '数据真值复核（粗对齐）' if payload['stage'] == 'coarse'
            else '数据真值复核（精对齐）'
        )
        ensure_task_can_start(self, task_name)
        self._set_compare_busy(True)
        self.status_label.setText('正在后台执行数据真值复核，可继续使用其它子模块')
        thread = QThread(self)
        worker = TruthReviewWorker(payload)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.succeeded.connect(self._on_compare_analysis_succeeded)
        worker.failed.connect(self._on_compare_analysis_failed)
        worker.cancelled.connect(self._on_compare_analysis_cancelled)
        worker.succeeded.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.cancelled.connect(thread.quit)
        worker.succeeded.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        worker.cancelled.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._on_compare_thread_finished)
        self._compare_thread = thread
        self._compare_worker = worker
        self._compare_task_name = task_name
        self._compare_task_version = register_background_task(
            self,
            task_name,
            thread,
            worker,
            worker.cancel,
        )
        thread.start()
    def _set_compare_busy(self, busy):
        self.btn_cmp_run.setEnabled(not busy)
        self.btn_cmp_run.setText('正在后台计算...' if busy else '第 1 步：粗对齐')
        self.btn_cmp_run_fine.setEnabled(
            not busy and getattr(self, 'compare_coarse_mapping', None) is not None
        )
        for widget in (
            self.btn_cmp_load_test, self.btn_cmp_load_meta,
            self.btn_cmp_load_truth, self.btn_cmp_plot_raw,
            self.combo_cmp_method, self.combo_cmp_reference,
            self.combo_cmp_interpolation,
            self.combo_cmp_truth_time, self.combo_cmp_truth_time_unit,
            self.spin_cmp_radar_interval, self.spin_cmp_outlier_threshold,
            self.btn_cmp_outlier_dimensions,
            self.spin_cmp_manual_offset, self.spin_cmp_max_shift_ratio,
            self.group_cmp_mapping,
        ):
            widget.setEnabled(not busy)
        if not busy:
            self.btn_cmp_outlier_dimensions.setEnabled(
                bool(self._available_compare_additional_outlier_metrics())
            )
        if busy:
            self.btn_cmp_export.setEnabled(False)
    def _on_compare_analysis_succeeded(self, output):
        if not task_result_is_current(
            self, self._compare_task_name, self._compare_task_version
        ):
            return
        try:
            if output['preprocess_revision'] != getattr(
                self, 'compare_preprocess_revision', 0
            ):
                self.status_label.setText(
                    '雷达预处理在复核期间已变化，已丢弃旧结果，请重新运行'
                )
                return
            self.compare_last_interpolated_count = output['truth_interpolated_count']
            self.compare_last_interpolated_valid_count = output['truth_interpolated_valid_count']
            self.compare_last_aligned_valid_count = output['truth_aligned_valid_count']
            if output['stage'] == 'coarse':
                self.compare_coarse_output = output
                self.compare_coarse_mapping = output['mapping']
                self.compare_last_result = None
                self.compare_last_output = None
                self.compare_last_metrics = None
                self.compare_last_paired_count = None
                self._render_coarse_results(output)
                reference = output['metric_results'][
                    output['metrics_summary']['reference_metric']
                ]
                mean_error = reference['metrics']['mean_error']
                self.status_label.setText(
                    f"粗对齐完成: {reference['config']['label']}平均差值 "
                    f"{mean_error:.4f} {reference['config']['unit']}；"
                    '请设置雷达修正后执行精对齐'
                )
                self.btn_cmp_run_fine.setEnabled(True)
                self.btn_cmp_export.setEnabled(False)
                self._update_compare_statistics()
                return

            self.compare_last_result = output['result']
            self.compare_last_output = output
            self.compare_last_metrics = output['metrics_summary']
            self.compare_last_paired_count = output[
                'paired_samples_after_outlier_removal'
            ]
            self._update_compare_statistics()
            self._render_compare_results(
                output['radar_sample'],
                output['truth_sample'],
                output['gps_interpolated_sample'],
                output['metric_results'],
                output['mapping'],
                output['alignment_candidates'],
            )
            reference_key = self.compare_last_metrics['reference_metric']
            reference = output['metric_results'][reference_key]
            metrics = reference['metrics']
            self.status_label.setText(
                f"精对齐完成: {reference['config']['label']} "
                f"RMSE={metrics['rmse']:.4f}, 有效样点={metrics['count']}"
            )
            self.btn_cmp_export.setEnabled(True)
            logger.info(
                f"用户操作: [数据真值复核] 后台计算完成 — "
                f"方法={output['mapping']['method']}, 维度={len(output['metric_results'])}"
            )
        except Exception as exc:
            handle_ui_exception(
                self, logger, '绘制复核结果', exc
            )
        finally:
            self._set_compare_busy(False)
    def _on_compare_analysis_failed(self, message):
        if not task_result_is_current(
            self, self._compare_task_name, self._compare_task_version
        ):
            return
        self._set_compare_busy(False)
        self.status_label.setText('数据真值复核失败')
        QMessageBox.warning(self, '复核失败', message)

    def _on_compare_analysis_cancelled(self, _message):
        if not task_result_is_current(
            self, self._compare_task_name, self._compare_task_version
        ):
            return
        self._set_compare_busy(False)
        self.status_label.setText('数据真值复核已取消')
    def _on_compare_thread_finished(self):
        self._compare_thread = None
        self._compare_worker = None
