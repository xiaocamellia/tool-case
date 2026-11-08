"""Comparison data loading, filtering, and statistics."""
import json
import math
import os
import re
import threading
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
from .background_tasks import (
    ensure_task_can_start, register_background_task, task_result_is_current,
)
from .data_loader import DataLoader, read_numeric_table
from .error_ui import handle_ui_exception
from .errors import ExportError, safe_exception_message
from .schemas import TruthReviewConfig
from .logger import get_logger
from .ui_theme import set_button_icon, style_primary_button
from .compare_core import (
    MAX_PLOT_POINTS, METRIC_BY_KEY, METRIC_COLUMN_ALIASES, METRIC_DEFINITIONS, TruthReviewWorker, _compute_truth_review, _decimate_plot_arrays, _estimate_fixed_scale_alignment, _normalize_column_name, _paired_outlier_mask, _sample_mapping, find_metric_column, resample_gps_to_radar_cadence
)
logger = get_logger("compare_analysis")


ASYNC_COMPARE_LOAD_BYTES = 2 * 1024 * 1024


def _load_compare_radar_payload(filepath):
    column_filepath = DataLoader.auto_find_column_file(filepath)
    if column_filepath and os.path.isfile(column_filepath):
        column_names = DataLoader.load_column_names(column_filepath)
    else:
        column_names = None
        column_filepath = ''
    dataframe = DataLoader.load_data(
        filepath, column_names, validate_limits=False
    )
    return {
        'kind': 'radar',
        'filepath': filepath,
        'column_filepath': column_filepath,
        'column_names': column_names,
        'dataframe': dataframe,
    }


def _load_compare_truth_payload(filepath):
    return {
        'kind': 'truth',
        'filepath': filepath,
        'dataframe': read_numeric_table(filepath, validate_limits=False),
    }


class CompareDataLoadWorker(QObject):
    succeeded = pyqtSignal(dict)
    failed = pyqtSignal(str)
    cancelled = pyqtSignal(str)
    progress = pyqtSignal(int, str)

    def __init__(self, kind, filepath):
        super().__init__()
        self.kind = kind
        self.filepath = filepath
        self._cancel_event = threading.Event()

    def cancel(self):
        self._cancel_event.set()

    def run(self):
        label = '雷达数据' if self.kind == 'radar' else '真值数据'
        try:
            self.progress.emit(5, f'正在加载{label}')
            if self._cancel_event.is_set():
                raise RuntimeError(f'{label}加载已取消')
            payload = (
                _load_compare_radar_payload(self.filepath)
                if self.kind == 'radar'
                else _load_compare_truth_payload(self.filepath)
            )
            if self._cancel_event.is_set():
                raise RuntimeError(f'{label}加载已取消')
            self.progress.emit(100, f'{label}加载完成')
            self.succeeded.emit(payload)
        except Exception as exc:
            if self._cancel_event.is_set():
                self.cancelled.emit(f'{label}加载已取消')
            else:
                self.failed.emit(safe_exception_message(exc))


class CompareDataMixin:
    def _apply_compare_radar_payload(self, payload):
        dataframe = payload['dataframe']
        self.compare_meta_cols = payload['column_names']
        self.compare_meta_filepath = payload['column_filepath']
        self.compare_test_df = dataframe
        self.compare_test_original_df = dataframe
        self.compare_test_source_indices = np.arange(len(dataframe))
        self.compare_test_filepath = payload['filepath']
        if self.compare_meta_filepath and self.compare_meta_cols is not None:
            self.lbl_cmp_meta.setText(
                f'雷达列名: {os.path.basename(self.compare_meta_filepath)} '
                f'({len(self.compare_meta_cols)} 列，自动匹配)'
            )
            self.lbl_cmp_meta.setStyleSheet('color: #0f766e;')
        else:
            self.lbl_cmp_meta.setText('雷达列名: 未自动找到，可手动加载')
            self.lbl_cmp_meta.setStyleSheet('color: #b45309;')
        self.lbl_cmp_test.setText(
            f'雷达数据: {os.path.basename(self.compare_test_filepath)} '
            f'({len(dataframe)} 行)'
        )
        self.lbl_cmp_test.setStyleSheet('color: #334155;')
        self._refresh_compare_column_combos(reset_preprocessing=True)
        self._invalidate_compare_result()

    def _apply_compare_truth_payload(self, payload):
        dataframe = payload['dataframe']
        self.compare_truth_df = dataframe
        self.compare_truth_filepath = payload['filepath']
        self.lbl_cmp_truth.setText(
            f'真值数据: {os.path.basename(self.compare_truth_filepath)} '
            f'({len(dataframe)} 行)'
        )
        self.lbl_cmp_truth.setStyleSheet('color: #334155;')
        self._refresh_compare_column_combos()
        self._invalidate_compare_result()

    def _set_compare_loading(self, loading):
        analysis_busy = getattr(self, '_compare_thread', None) is not None
        enabled = not loading and not analysis_busy
        for name in (
            'btn_cmp_load_test', 'btn_cmp_load_meta', 'btn_cmp_load_truth',
            'btn_cmp_run', 'btn_cmp_run_fine', 'btn_cmp_export',
        ):
            widget = getattr(self, name, None)
            if widget is not None:
                widget.setEnabled(enabled)
        if enabled:
            if hasattr(self, 'btn_cmp_run_fine'):
                self.btn_cmp_run_fine.setEnabled(
                    getattr(self, 'compare_coarse_mapping', None) is not None
                )
            if hasattr(self, 'btn_cmp_export'):
                self.btn_cmp_export.setEnabled(
                    getattr(self, 'compare_last_result', None) is not None
                )

    def _start_compare_file_load(self, kind, filepath):
        try:
            is_async = os.path.getsize(filepath) >= ASYNC_COMPARE_LOAD_BYTES
        except OSError:
            is_async = False
        if not is_async:
            return False
        if getattr(self, '_compare_load_thread', None) is not None:
            self.status_label.setText('已有数据加载任务正在运行')
            return True

        label = '雷达数据' if kind == 'radar' else '真值数据'
        task_name = f'数据真值复核：加载{label}'
        ensure_task_can_start(self, task_name)
        self._set_compare_loading(True)
        thread = QThread(self)
        worker = CompareDataLoadWorker(kind, filepath)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.succeeded.connect(self._on_compare_file_load_succeeded)
        worker.failed.connect(self._on_compare_file_load_failed)
        worker.cancelled.connect(self._on_compare_file_load_cancelled)
        worker.succeeded.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.cancelled.connect(thread.quit)
        worker.succeeded.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        worker.cancelled.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._on_compare_file_load_thread_finished)
        self._compare_load_thread = thread
        self._compare_load_worker = worker
        self._compare_load_task_name = task_name
        self._compare_load_task_version = register_background_task(
            self, task_name, thread, worker, worker.cancel
        )
        self.status_label.setText(f'正在后台加载{label}，可继续使用其它子模块')
        thread.start()
        return True

    def _load_compare_file(self, kind, filepath):
        if self._start_compare_file_load(kind, filepath):
            return
        label = '雷达数据' if kind == 'radar' else '真值数据'
        action = f'加载{label}'
        try:
            payload = (
                _load_compare_radar_payload(filepath)
                if kind == 'radar'
                else _load_compare_truth_payload(filepath)
            )
            if kind == 'radar':
                self._apply_compare_radar_payload(payload)
            else:
                self._apply_compare_truth_payload(payload)
            self.status_label.setText(f'已加载{label}')
            logger.info(
                f'用户操作: [数据真值复核] {action} — '
                f'{os.path.basename(filepath)}'
            )
        except Exception as exc:
            handle_ui_exception(self, logger, action, exc)

    def _on_compare_file_load_succeeded(self, payload):
        if not task_result_is_current(
            self,
            getattr(self, '_compare_load_task_name', ''),
            getattr(self, '_compare_load_task_version', 0),
        ):
            return
        try:
            if payload['kind'] == 'radar':
                self._apply_compare_radar_payload(payload)
            else:
                self._apply_compare_truth_payload(payload)
            label = '雷达数据' if payload['kind'] == 'radar' else '真值数据'
            self.status_label.setText(f'已加载{label}')
            logger.info(
                f'用户操作: [数据真值复核] 加载{label} — '
                f'{os.path.basename(payload["filepath"])}'
            )
        except Exception as exc:
            handle_ui_exception(self, logger, '加载数据', exc)
        finally:
            self._set_compare_loading(False)

    def _on_compare_file_load_failed(self, message):
        if not task_result_is_current(
            self,
            getattr(self, '_compare_load_task_name', ''),
            getattr(self, '_compare_load_task_version', 0),
        ):
            return
        self._set_compare_loading(False)
        self.status_label.setText('数据加载失败')
        QMessageBox.warning(self, '数据加载失败', message)

    def _on_compare_file_load_cancelled(self, message):
        if not task_result_is_current(
            self,
            getattr(self, '_compare_load_task_name', ''),
            getattr(self, '_compare_load_task_version', 0),
        ):
            return
        self._set_compare_loading(False)
        self.status_label.setText(message)

    def _on_compare_file_load_thread_finished(self):
        self._compare_load_thread = None
        self._compare_load_worker = None
        self._set_compare_loading(False)

    def load_compare_test_data(self):
        filepath, _ = QFileDialog.getOpenFileName(
            self, '选择雷达数据文件', '',
            '支持的数据 (*.txt *.csv *.dat *.xlsx *.xls);;所有文件 (*.*)'
        )
        if not filepath:
            return
        self._load_compare_file('radar', filepath)

    def load_compare_metadata(self):
        if not self.compare_test_filepath:
            QMessageBox.information(self, '提示', '请先加载雷达数据，再单独加载列名文件')
            return
        filepath, _ = QFileDialog.getOpenFileName(
            self, '选择雷达列名文件', '', '文本文件 (*.txt);;所有文件 (*.*)'
        )
        if not filepath:
            return
        try:
            self.compare_meta_cols = DataLoader.load_column_names(filepath)
            self.compare_meta_filepath = filepath
            self.lbl_cmp_meta.setText(f'雷达列名: {os.path.basename(filepath)} ({len(self.compare_meta_cols)} 列)')
            self.lbl_cmp_meta.setStyleSheet('color: #334155;')
            if self.compare_test_filepath:
                source = (
                    self.compare_test_original_df
                    if self.compare_test_original_df is not None
                    else self.compare_test_df
                )
                if source is None:
                    raise ValueError('雷达数据尚未加载')
                renamed = source.copy(deep=False)
                renamed.columns = DataLoader.normalize_column_names(
                    self.compare_meta_cols, renamed.shape[1]
                )
                self.compare_test_df = renamed
                self.compare_test_original_df = renamed
                self.compare_test_source_indices = np.arange(len(renamed))
                self.lbl_cmp_test.setText(
                    f'雷达数据: {os.path.basename(self.compare_test_filepath)} ({len(renamed)} 行)'
                )
            self._refresh_compare_column_combos(reset_preprocessing=True)
            self._invalidate_compare_result()
            self.status_label.setText('已加载雷达列名')
        except Exception as exc:
            handle_ui_exception(
                self, logger, '加载雷达列名', exc
            )
    def load_compare_truth_data(self):
        filepath, _ = QFileDialog.getOpenFileName(
            self, '选择 GPS/惯导真值数据文件', '',
            '支持的数据 (*.txt *.csv *.dat *.xlsx *.xls);;所有文件 (*.*)'
        )
        if not filepath:
            return
        self._load_compare_file('truth', filepath)

    def _refresh_compare_column_combos(self, reset_preprocessing=False):
        radar_cols = [] if self.compare_test_df is None else [str(c) for c in self.compare_test_df.columns]
        truth_cols = [] if self.compare_truth_df is None else [str(c) for c in self.compare_truth_df.columns]
        if reset_preprocessing and hasattr(self, 'compare_additional_outlier_settings'):
            self.compare_additional_outlier_settings.clear()
        if hasattr(self, 'combo_cmp_truth_time'):
            selected_time = self.combo_cmp_truth_time.currentData()
            self._fill_column_combo(
                self.combo_cmp_truth_time, truth_cols, include_empty=True
            )
            if selected_time in truth_cols:
                self.combo_cmp_truth_time.setCurrentIndex(
                    self.combo_cmp_truth_time.findData(selected_time)
                )
            elif truth_cols:
                # The GPS file contract defines its first column as timestamp.
                self.combo_cmp_truth_time.setCurrentIndex(
                    self.combo_cmp_truth_time.findData(truth_cols[0])
                )
        initialized_original = False
        if self.compare_test_df is not None and getattr(self, 'compare_test_original_df', None) is None:
            self.compare_test_original_df = self.compare_test_df
            self.compare_test_source_indices = np.arange(len(self.compare_test_df))
            initialized_original = True
        if hasattr(self, 'combo_cmp_filter_col'):
            selected_filter = self.combo_cmp_filter_col.currentData()
            self._fill_column_combo(self.combo_cmp_filter_col, radar_cols, include_empty=True)
            if selected_filter in radar_cols:
                self.combo_cmp_filter_col.setCurrentIndex(
                    self.combo_cmp_filter_col.findData(selected_filter)
                )
            if reset_preprocessing:
                self.edit_cmp_filter_min.clear()
                self.edit_cmp_filter_max.clear()
            self._refresh_compare_range_controls(
                reset=reset_preprocessing or initialized_original
            )
        for metric in METRIC_DEFINITIONS:
            widgets = self.compare_mapping_widgets[metric['key']]
            self._fill_column_combo(widgets['radar'], radar_cols, include_empty=True)
            self._fill_column_combo(widgets['truth'], truth_cols, include_empty=True)
            radar_found = self._select_suggested_column(
                widgets['radar'], metric, fallback_pos=None
            )
            truth_found = self._select_suggested_column(
                widgets['truth'], metric, fallback_pos=metric['truth_pos']
            )
            widgets['enabled'].setChecked(bool(radar_found and truth_found))
    @staticmethod
    def _fill_column_combo(combo, columns, include_index=False, include_empty=False):
        combo.blockSignals(True)
        combo.clear()
        if include_index:
            combo.addItem('[按行号生成]', None)
        elif include_empty:
            combo.addItem('[请选择]', None)
        for column in columns:
            combo.addItem(column, column)
        combo.blockSignals(False)
    @staticmethod
    def _select_suggested_column(combo, metric, fallback_pos=None):
        columns = [combo.itemData(index) for index in range(combo.count())]
        columns = [column for column in columns if column is not None]
        matched = find_metric_column(columns, metric['key'])
        if matched is not None:
            index = combo.findData(matched)
            combo.setCurrentIndex(index)
            return True
        if fallback_pos is not None and fallback_pos < len(columns):
            index = combo.findData(columns[fallback_pos])
            combo.setCurrentIndex(index)
            return True
        combo.setCurrentIndex(0)
        return False
    def _invalidate_compare_result(self, *_args):
        self.compare_coarse_output = None
        self.compare_coarse_mapping = None
        self.compare_last_result = None
        self.compare_last_output = None
        self.compare_last_metrics = None
        self.compare_last_interpolated_count = None
        self.compare_last_interpolated_valid_count = None
        self.compare_last_aligned_valid_count = None
        if hasattr(self, 'btn_cmp_export'):
            self.btn_cmp_export.setEnabled(False)
        if hasattr(self, 'btn_cmp_run_fine'):
            self.btn_cmp_run_fine.setEnabled(False)
        self._update_compare_statistics()
        self._set_compare_figure_message(
            'range', '点击“绘制原始数据”查看雷达截取前后对比'
        )
        self._set_compare_figure_message(
            'interpolation', '完成第 1 步粗对齐后显示 GPS 时间插值结果'
        )
        self._set_compare_figure_message(
            'coarse_difference', '完成第 1 步粗对齐后显示雷达 - GPS 差值'
        )
    def _invalidate_fine_compare_result(self, *_args):
        """Keep a valid coarse result while invalidating fine correction."""
        self.compare_last_result = None
        self.compare_last_output = None
        self.compare_last_metrics = None
        self.compare_last_aligned_valid_count = None
        self.compare_last_paired_count = None
        if hasattr(self, 'btn_cmp_export'):
            self.btn_cmp_export.setEnabled(False)
        if hasattr(self, 'btn_cmp_run_fine'):
            self.btn_cmp_run_fine.setEnabled(
                getattr(self, 'compare_coarse_mapping', None) is not None
            )
        if getattr(self, 'compare_coarse_mapping', None) is not None:
            for key in ('overview', 'error', 'distribution', 'trajectory', 'algorithms'):
                self._set_compare_figure_message(
                    key, '修正或野点参数已变化，请重新运行第 2 步精对齐'
                )
            if hasattr(self, 'table_cmp_metrics'):
                self.table_cmp_metrics.setRowCount(0)
            if hasattr(self, 'txt_cmp_stats'):
                self.txt_cmp_stats.setPlainText(
                    '粗对齐结果仍然有效；修正或野点参数已变化，请运行第 2 步精对齐。'
                )
        self._update_compare_statistics()
    def _set_compare_figure_message(self, figure_key, message):
        if not hasattr(self, 'compare_figures') or figure_key not in self.compare_figures:
            return
        figure = self.compare_figures[figure_key]
        figure.clear()
        axis = figure.add_subplot(111)
        axis.text(0.5, 0.5, message, ha='center', va='center', transform=axis.transAxes)
        axis.set_axis_off()
        self.compare_canvases[figure_key].draw_idle()
    def _clear_compare_plots_after_preprocessing(self):
        for key, message in (
            ('raw', '雷达预处理已变化，请重新绘制原始数据'),
            ('coarse_difference', '雷达预处理已变化，请重新执行粗对齐'),
            ('overview', '雷达预处理已变化，请重新执行粗对齐'),
            ('error', '雷达预处理已变化，请重新执行粗对齐'),
            ('distribution', '雷达预处理已变化，请重新执行粗对齐'),
            ('trajectory', '雷达预处理已变化，请重新执行粗对齐'),
            ('algorithms', '雷达预处理已变化，请重新执行粗对齐'),
        ):
            self._set_compare_figure_message(key, message)
        if hasattr(self, 'table_cmp_metrics'):
            self.table_cmp_metrics.setRowCount(0)
        if hasattr(self, 'txt_cmp_stats'):
            self.txt_cmp_stats.setPlainText('雷达预处理已变化，请重新执行第 1 步粗对齐。')
    def _mark_compare_preprocessing_changed(self):
        self.compare_preprocess_revision = (
            getattr(self, 'compare_preprocess_revision', 0) + 1
        )
        self._invalidate_compare_result()
        self._clear_compare_plots_after_preprocessing()
    def _refresh_compare_range_controls(self, reset=False):
        if not hasattr(self, 'spin_cmp_range_start'):
            return
        original = getattr(self, 'compare_test_original_df', None)
        total = 0 if original is None else len(original)
        maximum = max(0, total)
        for spin in (self.spin_cmp_range_start, self.spin_cmp_range_end):
            spin.blockSignals(True)
            spin.setRange(0, maximum)
        if reset:
            self.spin_cmp_range_start.setValue(0)
            self.spin_cmp_range_end.setValue(0)
        else:
            self.spin_cmp_range_start.setValue(min(self.spin_cmp_range_start.value(), maximum))
            end = self.spin_cmp_range_end.value()
            self.spin_cmp_range_end.setValue(0 if end == 0 else min(end, maximum))
        for spin in (self.spin_cmp_range_start, self.spin_cmp_range_end):
            spin.blockSignals(False)
        self._update_compare_range_label()
    def _compare_range_bounds(self):
        original = getattr(self, 'compare_test_original_df', None)
        total = 0 if original is None else len(original)
        start = min(self.spin_cmp_range_start.value(), total)
        requested_end = self.spin_cmp_range_end.value()
        end = total if requested_end == 0 else min(requested_end, total)
        if end < start:
            raise ValueError('结束样点不能小于起始样点')
        return start, end
    def _current_compare_radar_df(self):
        if self.compare_test_df is None:
            return None
        start, end = self._compare_range_bounds()
        indices = getattr(self, 'compare_test_source_indices', None)
        if indices is None or len(indices) != len(self.compare_test_df):
            indices = np.arange(len(self.compare_test_df))
        selected = (indices >= start) & (indices < end)
        return self.compare_test_df.loc[selected].reset_index(drop=True)
    def _current_compare_radar_source_indices(self):
        if self.compare_test_df is None:
            return np.array([], dtype=int)
        indices = getattr(self, 'compare_test_source_indices', None)
        if indices is None or len(indices) != len(self.compare_test_df):
            indices = np.arange(len(self.compare_test_df))
        start, end = self._compare_range_bounds()
        selected = (indices >= start) & (indices < end)
        return np.asarray(indices[selected], dtype=int)
    def _update_compare_statistics(self):
        if not hasattr(self, 'lbl_cmp_stat_radar_original'):
            return
        original = getattr(self, 'compare_test_original_df', None)
        radar_original = 0 if original is None else len(original)
        radar_filtered = 0 if self.compare_test_df is None else len(self.compare_test_df)
        try:
            current = self._current_compare_radar_df()
            radar_selected = 0 if current is None else len(current)
        except ValueError:
            radar_selected = 0
        truth_original = 0 if self.compare_truth_df is None else len(self.compare_truth_df)
        aligned = getattr(self, 'compare_last_interpolated_count', None)
        interpolated_valid = getattr(self, 'compare_last_interpolated_valid_count', None)
        aligned_valid = getattr(self, 'compare_last_aligned_valid_count', None)
        paired_count = getattr(self, 'compare_last_paired_count', None)
        self.lbl_cmp_stat_radar_original.setText(f'雷达原始: {radar_original} 点')
        self.lbl_cmp_stat_radar_filtered.setText(f'雷达过滤后: {radar_filtered} 点')
        self.lbl_cmp_stat_radar_selected.setText(
            f'雷达过滤截取后: {radar_selected} 点'
        )
        self.lbl_cmp_stat_truth_original.setText(f'GPS 插值前: {truth_original} 点')
        if aligned is None:
            self.lbl_cmp_stat_truth_aligned.setText('GPS 插值后: --')
            self.lbl_cmp_stat_alignment_valid.setText('GPS 对齐后有效: --')
            self.lbl_cmp_stat_paired.setText('精对齐同步保留: --')
        else:
            self.lbl_cmp_stat_truth_aligned.setText(
                f'GPS 插值后: {aligned} 点（有效 {interpolated_valid}）'
            )
            self.lbl_cmp_stat_alignment_valid.setText(
                f'GPS 对齐后有效: {aligned_valid} 点'
            )
            self.lbl_cmp_stat_paired.setText(
                '精对齐同步保留: --' if paired_count is None
                else f'精对齐同步保留: {paired_count} 点'
            )
    def _update_compare_range_label(self):
        if not hasattr(self, 'lbl_cmp_range_count'):
            return
        original = getattr(self, 'compare_test_original_df', None)
        total = 0 if original is None else len(original)
        try:
            start, end = self._compare_range_bounds()
            current = self._current_compare_radar_df()
            selected = 0 if current is None else len(current)
            self.lbl_cmp_range_count.setText(
                f'交集保留: {selected} / 原始 {total} 样点'
            )
            self.lbl_cmp_range_count.setStyleSheet('color: #475569;')
        except ValueError:
            self.lbl_cmp_range_count.setText(f'当前范围无效 / {total} 样点')
            self.lbl_cmp_range_count.setStyleSheet('color: #b91c1c;')
    def _on_compare_range_changed(self):
        had_result = self.compare_last_result is not None
        self._update_compare_range_label()
        self._mark_compare_preprocessing_changed()
        if had_result:
            self.status_label.setText('雷达截取范围已变化，请重新执行粗对齐')
    def apply_compare_filter(self):
        original = getattr(self, 'compare_test_original_df', None)
        if original is None:
            QMessageBox.information(self, '提示', '请先加载雷达数据')
            return
        column = self.combo_cmp_filter_col.currentData()
        if column is None:
            QMessageBox.information(self, '提示', '请选择过滤列')
            return
        minimum_text = self.edit_cmp_filter_min.text().strip()
        maximum_text = self.edit_cmp_filter_max.text().strip()
        try:
            minimum = float(minimum_text) if minimum_text else None
            maximum = float(maximum_text) if maximum_text else None
            if minimum is not None and maximum is not None and minimum > maximum:
                raise ValueError('过滤最小值不能大于最大值')
            values = pd.to_numeric(original[column], errors='coerce')
            mask = values.notna()
            if minimum is not None:
                mask &= values >= minimum
            if maximum is not None:
                mask &= values <= maximum
            self.compare_test_df = original.loc[mask].reset_index(drop=True).copy()
            self.compare_test_source_indices = np.flatnonzero(mask.to_numpy())
            removed = len(original) - len(self.compare_test_df)
            self._refresh_compare_range_controls(reset=False)
            self._mark_compare_preprocessing_changed()
            processed_count = len(self._current_compare_radar_df())
            self.lbl_cmp_test.setText(
                f'雷达数据: {os.path.basename(self.compare_test_filepath) or "已加载"} '
                f'({len(self.compare_test_df)} / {len(original)} 行)'
            )
            self.status_label.setText(
                f'雷达对齐前过滤完成: 移除 {removed} 行，保留 '
                f'{len(self.compare_test_df)} 行；与截取范围合并后 '
                f'{processed_count} 行，请执行粗对齐'
            )
        except Exception as exc:
            handle_ui_exception(self, logger, '过滤数据', exc)
    def clear_compare_filter(self):
        original = getattr(self, 'compare_test_original_df', None)
        if original is None:
            return
        self.compare_test_df = original.copy()
        self.compare_test_source_indices = np.arange(len(original))
        self.edit_cmp_filter_min.clear()
        self.edit_cmp_filter_max.clear()
        self._refresh_compare_range_controls(reset=False)
        self._mark_compare_preprocessing_changed()
        self.lbl_cmp_test.setText(
            f'雷达数据: {os.path.basename(self.compare_test_filepath) or "已加载"} '
            f'({len(self.compare_test_df)} 行)'
        )
        self.status_label.setText('已恢复雷达原始数据，请重新执行粗对齐')
    def _on_compare_mapping_changed(self, metric_key):
        del metric_key
        self._invalidate_compare_result()
    def _on_compare_reference_changed(self, *_args):
        self._refresh_compare_additional_outlier_options()
        self._invalidate_compare_result()
    def _refresh_compare_additional_outlier_options(self, *_args):
        button = getattr(self, 'btn_cmp_outlier_dimensions', None)
        if button is None:
            return
        available = self._available_compare_additional_outlier_metrics()
        button.setEnabled(bool(available))
        selected_labels = [
            metric['label'] for metric in available
            if self.compare_additional_outlier_settings.get(
                metric['key'], {}
            ).get('enabled', False)
        ]
        self.lbl_cmp_outlier_dimensions.setText(
            '备选: ' + ('、'.join(selected_labels) if selected_labels else '未启用')
        )
        self._update_compare_outlier_units()
    def _available_compare_additional_outlier_metrics(self):
        reference_key = self.combo_cmp_reference.currentData()
        return [
            metric for metric in METRIC_DEFINITIONS
            if metric['key'] != reference_key
            and self.compare_mapping_widgets[metric['key']]['enabled'].isChecked()
        ]
    def _update_compare_outlier_units(self):
        reference_key = self.combo_cmp_reference.currentData()
        reference = METRIC_BY_KEY.get(reference_key)
        if reference is not None:
            self.spin_cmp_outlier_threshold.setSuffix(f" {reference['unit']}")
    def _selected_compare_additional_outlier_dimensions(self):
        dimensions = []
        for metric in self._available_compare_additional_outlier_metrics():
            setting = self.compare_additional_outlier_settings.get(metric['key'], {})
            if setting.get('enabled', False):
                dimensions.append({
                    'key': metric['key'],
                    'threshold': float(setting.get('threshold', 0.0)),
                })
        return dimensions
    def _set_compare_additional_outlier_settings(self, settings):
        for key, setting in settings.items():
            if key not in METRIC_BY_KEY:
                continue
            self.compare_additional_outlier_settings[key] = {
                'enabled': bool(setting.get('enabled', False)),
                'threshold': max(0.0, float(setting.get('threshold', 0.0))),
            }
        self._refresh_compare_additional_outlier_options()
        self._invalidate_fine_compare_result()
    def configure_compare_outlier_dimensions(self):
        available = self._available_compare_additional_outlier_metrics()
        if not available:
            QMessageBox.information(self, '备选维度', '当前没有可用的其它复核维度')
            return
        dialog = QDialog(self)
        dialog.setWindowTitle('设置备选野点维度')
        dialog.setMinimumWidth(480)
        layout = QGridLayout(dialog)
        select_all = QCheckBox('启用全部可用维度')
        layout.addWidget(select_all, 0, 0, 1, 3)
        for column, text in enumerate(('启用', '维度', '野点阈值')):
            header = QLabel(text)
            header.setStyleSheet('color: #64748b; font-weight: 600;')
            layout.addWidget(header, 1, column)
        row_widgets = {}
        for row, metric in enumerate(available, 2):
            setting = self.compare_additional_outlier_settings.get(
                metric['key'], {'enabled': False, 'threshold': 0.0}
            )
            enabled = QCheckBox()
            enabled.setChecked(bool(setting.get('enabled', False)))
            layout.addWidget(enabled, row, 0, alignment=Qt.AlignCenter)
            layout.addWidget(QLabel(f"{metric['label']} ({metric['unit']})"), row, 1)
            threshold = QDoubleSpinBox()
            threshold.setRange(0.0, 1e9)
            threshold.setDecimals(6)
            threshold.setSpecialValueText('自动 MAD')
            threshold.setSuffix(f" {metric['unit']}")
            threshold.setValue(float(setting.get('threshold', 0.0)))
            threshold.setEnabled(enabled.isChecked())
            enabled.toggled.connect(threshold.setEnabled)
            layout.addWidget(threshold, row, 2)
            row_widgets[metric['key']] = (enabled, threshold)
        select_all.setChecked(all(enabled.isChecked() for enabled, _ in row_widgets.values()))
        select_all.toggled.connect(
            lambda checked: [
                enabled.setChecked(checked)
                for enabled, _threshold in row_widgets.values()
            ]
        )
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons, len(available) + 2, 0, 1, 3)
        layout.setColumnStretch(1, 1)
        if dialog.exec_() != QDialog.Accepted:
            return
        self._set_compare_additional_outlier_settings({
            key: {
                'enabled': enabled.isChecked(),
                'threshold': threshold.value(),
            }
            for key, (enabled, threshold) in row_widgets.items()
        })
    def _enabled_metric_configs(self):
        configs = []
        for metric in METRIC_DEFINITIONS:
            widgets = self.compare_mapping_widgets[metric['key']]
            if not widgets['enabled'].isChecked():
                continue
            radar_col = widgets['radar'].currentData()
            truth_col = widgets['truth'].currentData()
            if radar_col is None or truth_col is None:
                raise ValueError(f"请为{metric['label']}选择雷达列和真值列")
            configs.append({
                **metric, 'radar_col': radar_col, 'truth_col': truth_col,
                'radar_bias': float(widgets['radar_bias'].value()),
                'truth_bias': float(widgets['truth_bias'].value()),
            })
        if not configs:
            raise ValueError('请至少启用一个复核维度')
        return configs
