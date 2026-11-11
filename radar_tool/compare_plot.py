"""Comparison rendering and plotting helpers."""
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
from .plotting import style_axes_legend
from .compare_core import (
    MAX_PLOT_POINTS, METRIC_BY_KEY, METRIC_COLUMN_ALIASES, METRIC_DEFINITIONS, TruthReviewWorker, _compute_truth_review, _decimate_plot_arrays, _estimate_fixed_scale_alignment, _normalize_column_name, _paired_outlier_mask, _sample_mapping, find_metric_column, resample_gps_to_radar_cadence
)
logger = get_logger("compare_analysis")

class ComparePlotMixin:
    def _render_compare_results(
        self, radar_sample, truth_sample, gps_interpolated_sample, results,
        mapping, alignment_candidates,
    ):
        self._plot_raw_data(radar_sample, truth_sample, results)
        self._plot_range_comparison(results)
        self._plot_interpolation_comparison(
            truth_sample, gps_interpolated_sample, results
        )
        self._plot_coarse_difference(results, radar_sample, title='精对齐后差值')
        self._plot_metric_grid('overview', results, radar_sample, mode='overview')
        self._plot_metric_grid('error', results, radar_sample, mode='error')
        self._plot_metric_grid('distribution', results, radar_sample, mode='distribution')
        self._plot_trajectory(results)
        self._plot_algorithm_comparison(alignment_candidates)
        self._fill_metrics_table(results)
        lines = [
            '阶段: 精对齐（已应用修正并同步剔除野点）',
            f"对齐方法: {mapping['method']}",
            f"样点映射: i_truth = {mapping['query_scale']:.8g} × i_radar "
            f"{mapping['query_offset_samples']:+.8g} 样点",
            f"参考维度: {METRIC_BY_KEY[self.combo_cmp_reference.currentData()]['label']}",
            f"插值方式: {self.combo_cmp_interpolation.currentText()}",
            f"雷达采样间隔: {self.spin_cmp_radar_interval.value():.6g} ms",
        ]
        outlier = (self.compare_last_metrics or {}).get('outlier_removal')
        if outlier:
            for dimension in outlier.get('dimensions', ()):
                mode = (
                    '自动 MAD' if dimension['mode'] == 'auto_mad' else '手动阈值'
                )
                lines.append(
                    f"{dimension['metric_label']}野点判断: {mode}, "
                    f"阈值={dimension['threshold']:.6g} {dimension['unit']}, "
                    f"本维度判除={dimension['removed']} 点"
                )
            lines.append(
                f"多维度合并后同步保留={outlier['kept']} 点, "
                f"不保留={outlier['removed']} 点"
            )
        if 'lag_samples' in mapping:
            lines.append(f"互相关平移: {mapping['lag_samples']} 样点")
        if 'fit_score' in mapping:
            lines.append(f"标准化拟合损失: {mapping['fit_score']:.6g}")
        if len(alignment_candidates) > 1:
            lines.append('算法比较: 已按参考维度 RMSE 自动选择最优结果')
        lines.append('')
        for item in results.values():
            metrics = item['metrics']
            lines.append(f"{item['config']['label']}: RMSE={metrics['rmse']:.6g} MAE={metrics['mae']:.6g} P95={metrics['p95_abs']:.6g}")
        self.txt_cmp_stats.setPlainText('\n'.join(lines))
    def _render_coarse_results(self, output):
        results = output['metric_results']
        self._plot_raw_data(output['radar_sample'], output['truth_sample'], results)
        self._plot_range_comparison(results)
        self._plot_interpolation_comparison(
            output['truth_sample'], output['gps_interpolated_sample'], results
        )
        self._plot_metric_grid(
            'overview', results, output['radar_sample'], mode='overview'
        )
        self._plot_coarse_difference(results, output['radar_sample'])
        self._fill_metrics_table(results)
        mapping = output['mapping']
        reference = results[output['metrics_summary']['reference_metric']]
        lines = [
            '阶段: 粗对齐（尚未应用雷达/GPS修正）',
            f"雷达采样间隔: {output['metrics_summary']['radar_interval_ms']:.6g} ms",
            f"GPS时间列: {output['metrics_summary']['gps_time_column']}",
            f"固定样点比例: {mapping['query_scale']:.6g}（禁止时长拉伸）",
            f"粗对齐偏移: {mapping['query_offset_samples']:+.6g} 样点",
            f"参考维度平均差值: {reference['metrics']['mean_error']:.6g} "
            f"{reference['config']['unit']}",
            '',
            '请根据“粗对齐差值”图设置雷达修正，然后运行第 2 步精对齐。',
        ]
        self.txt_cmp_stats.setPlainText('\n'.join(lines))
        self.tabs_cmp_results.setCurrentIndex(3)
    def plot_compare_raw_data(self, checked=False, show_errors=True):
        del checked
        if self.compare_test_df is None or self.compare_truth_df is None:
            if show_errors:
                QMessageBox.information(self, '数据未就绪', '请先加载雷达数据与真值数据')
            return
        try:
            radar_df = self._current_compare_radar_df()
            if radar_df is None or radar_df.empty:
                raise ValueError('当前雷达截取范围没有数据')
            configs = self._enabled_metric_configs()
            source_indices = self._current_compare_radar_source_indices().astype(float)
            radar_sample = source_indices - source_indices[0]
            time_column = self.combo_cmp_truth_time.currentData()
            if time_column is None:
                raise ValueError('请选择 GPS 时间列')
            gps_time = pd.to_numeric(
                self.compare_truth_df[time_column], errors='coerce'
            ).to_numpy(dtype=float)
            factors = {'s': 1000.0, 'ms': 1.0, 'us': 0.001}
            gps_time_ms = gps_time * factors[self.combo_cmp_truth_time_unit.currentData()]
            first_time = gps_time_ms[np.isfinite(gps_time_ms)]
            if len(first_time) < 2:
                raise ValueError('GPS 时间列的有效值不足（至少需要 2 个）')
            truth_sample = (
                gps_time_ms - first_time[0]
            ) / float(self.spin_cmp_radar_interval.value())
            raw_results = {}
            for config in configs:
                raw_results[config['key']] = {
                    'config': config,
                    'raw_radar': pd.to_numeric(
                        radar_df[config['radar_col']], errors='coerce'
                    ).to_numpy(dtype=float),
                    'raw_truth': pd.to_numeric(
                        self.compare_truth_df[config['truth_col']], errors='coerce'
                    ).to_numpy(dtype=float),
                }
            self._plot_raw_data(radar_sample, truth_sample, raw_results)
            self._plot_range_comparison(raw_results)
            self.tabs_cmp_results.setCurrentIndex(0)
            self.status_label.setText('已按真实 GPS 时间位置绘制未对齐、未修正的原始数据')
        except Exception as exc:
            if show_errors:
                handle_ui_exception(
                self, logger, '绘制原始数据', exc
            )
            else:
                raise
    def _plot_raw_data(self, radar_sample, truth_sample, results):
        figure = self.compare_figures['raw']
        figure.clear()
        count = len(results)
        columns = 2 if count > 1 else 1
        rows = int(math.ceil(count / columns))
        for index, item in enumerate(results.values(), 1):
            ax = figure.add_subplot(rows, columns, index)
            config = item['config']
            radar_plot_sample, radar_values = _decimate_plot_arrays(
                radar_sample, item['raw_radar']
            )
            truth_plot_sample, truth_values = _decimate_plot_arrays(
                truth_sample, item['raw_truth']
            )
            ax.plot(radar_plot_sample, radar_values, color='#2563eb', linewidth=1.2, label='雷达原始')
            ax.plot(truth_plot_sample, truth_values, color='#dc2626', linewidth=1.1, linestyle='--', label='真值原始')
            ax.set_title(config['label'], fontsize=10, fontweight='bold')
            ax.set_xlabel('样点位置（GPS 由时间列 / 雷达周期换算）')
            ax.set_ylabel(config['unit'])
            style_axes_legend(ax)
            ax.grid(True, linestyle='--', alpha=0.22)
        figure.tight_layout(pad=1.1)
        self.compare_canvases['raw'].draw_idle()
    def _plot_range_comparison(self, results):
        figure = self.compare_figures['range']
        figure.clear()
        original = getattr(self, 'compare_test_original_df', None)
        if original is None:
            original = self.compare_test_df
        selected_indices = self._current_compare_radar_source_indices()
        count = len(results)
        columns = 2 if count > 1 else 1
        rows = int(math.ceil(count / columns))
        for index, item in enumerate(results.values(), 1):
            axis = figure.add_subplot(rows, columns, index)
            config = item['config']
            original_values = pd.to_numeric(
                original[config['radar_col']], errors='coerce'
            ).to_numpy(dtype=float)
            original_indices = np.arange(len(original_values), dtype=float)
            current_values = np.asarray(item['raw_radar'], dtype=float)
            original_x, original_y = _decimate_plot_arrays(
                original_indices, original_values
            )
            current_x, current_y = _decimate_plot_arrays(
                selected_indices, current_values
            )
            axis.plot(
                original_x, original_y, color='#94a3b8', linewidth=1.0,
                label='截取前（雷达原始）',
            )
            axis.plot(
                current_x, current_y, color='#2563eb', linewidth=1.35,
                label='截取/过滤后',
            )
            axis.set_title(config['label'], fontsize=10, fontweight='bold')
            axis.set_xlabel('雷达原始样点索引')
            axis.set_ylabel(config['unit'])
            style_axes_legend(axis)
            axis.grid(True, linestyle='--', alpha=0.22)
        figure.tight_layout(pad=1.1)
        self.compare_canvases['range'].draw_idle()
    def _plot_interpolation_comparison(
        self, truth_sample, gps_interpolated_sample, results,
    ):
        figure = self.compare_figures['interpolation']
        figure.clear()
        count = len(results)
        columns = 2 if count > 1 else 1
        rows = int(math.ceil(count / columns))
        for index, item in enumerate(results.values(), 1):
            axis = figure.add_subplot(rows, columns, index)
            config = item['config']
            raw_x, raw_truth = _decimate_plot_arrays(
                truth_sample, item['raw_truth']
            )
            interpolated_x, interpolated_truth = _decimate_plot_arrays(
                gps_interpolated_sample, item['gps_interpolated']
            )
            axis.plot(
                raw_x, raw_truth, color='#94a3b8', linewidth=1.0,
                label='GPS 原始点（按真实时间定位）',
            )
            axis.plot(
                interpolated_x, interpolated_truth, color='#dc2626', linewidth=1.25,
                linestyle='--', label='GPS 时间插值后（雷达采样周期）',
            )
            axis.set_title(config['label'], fontsize=10, fontweight='bold')
            axis.set_xlabel('样点位置（每点为一个雷达采样周期）')
            axis.set_ylabel(config['unit'])
            style_axes_legend(axis)
            axis.grid(True, linestyle='--', alpha=0.22)
        figure.tight_layout(pad=1.1)
        self.compare_canvases['interpolation'].draw_idle()
    def _plot_coarse_difference(self, results, sample_axis,
                                title='粗对齐后雷达 - GPS 差值'):
        figure = self.compare_figures['coarse_difference']
        figure.clear()
        count = len(results)
        columns = 2 if count > 1 else 1
        rows = int(math.ceil(count / columns))
        for index, item in enumerate(results.values(), 1):
            axis = figure.add_subplot(rows, columns, index)
            plot_sample, error = _decimate_plot_arrays(sample_axis, item['error'])
            axis.plot(plot_sample, error, color='#0f766e', linewidth=1.15)
            finite = np.asarray(item['error'])[np.isfinite(item['error'])]
            if len(finite):
                mean_error = float(np.mean(finite))
                axis.axhline(
                    mean_error, color='#dc2626', linewidth=1.0,
                    linestyle='--', label=f'平均差值 {mean_error:.6g}',
                )
                style_axes_legend(axis)
            axis.axhline(0.0, color='#94a3b8', linewidth=0.8)
            axis.set_title(f"{item['config']['label']} - {title}", fontsize=10,
                           fontweight='bold')
            axis.set_xlabel('雷达样点索引')
            axis.set_ylabel(f"差值 ({item['config']['unit']})")
            axis.grid(True, linestyle='--', alpha=0.22)
        figure.tight_layout(pad=1.1)
        self.compare_canvases['coarse_difference'].draw_idle()
    def _plot_metric_grid(self, figure_key, results, sample_axis, mode):
        figure = self.compare_figures[figure_key]
        figure.clear()
        count = len(results)
        columns = 2 if count > 1 else 1
        rows = int(math.ceil(count / columns))
        for index, item in enumerate(results.values(), 1):
            ax = figure.add_subplot(rows, columns, index)
            config = item['config']
            if mode == 'overview':
                plot_sample, radar, truth = _decimate_plot_arrays(
                    sample_axis, item['radar'], item['truth']
                )
                ax.plot(plot_sample, radar, color='#2563eb', linewidth=1.4, label='雷达数据')
                ax.plot(
                    plot_sample, truth, color='#dc2626', linewidth=1.2,
                    linestyle='--', label='对齐后 GPS 真值',
                )
                ax.set_ylabel(config['unit'])
                style_axes_legend(ax)
            elif mode == 'error':
                plot_sample, error = _decimate_plot_arrays(sample_axis, item['error'])
                ax.plot(plot_sample, error, color='#0f766e', linewidth=1.2)
                ax.axhline(0.0, color='#94a3b8', linewidth=0.8)
                ax.set_ylabel(f"误差 ({config['unit']})")
            else:
                error = item['error'][np.isfinite(item['error'])]
                error, = _decimate_plot_arrays(error)
                bins = min(50, max(10, int(np.sqrt(len(error)))))
                ax.hist(error, bins=bins, color='#2563eb', alpha=0.78, edgecolor='white')
                ax.axvline(0.0, color='#dc2626', linewidth=1.0)
                ax.set_xlabel(f"误差 ({config['unit']})")
                ax.set_ylabel('样点数')
            ax.set_title(config['label'], fontsize=10, fontweight='bold')
            if mode != 'distribution':
                ax.set_xlabel('对齐后雷达样点索引')
            ax.grid(True, linestyle='--', alpha=0.22)
        figure.tight_layout(pad=1.1)
        self.compare_canvases[figure_key].draw_idle()
    def _plot_trajectory(self, results):
        figure = self.compare_figures['trajectory']
        figure.clear()
        distance = results.get('distance')
        azimuth = results.get('azimuth')
        elevation = results.get('elevation')
        if distance is None or azimuth is None:
            ax = figure.add_subplot(111)
            ax.text(0.5, 0.5, '启用“距离”和“方位角”后可生成轨迹对比', ha='center', va='center', transform=ax.transAxes)
            ax.set_axis_off()
        else:
            rd_el = elevation['radar'] if elevation else np.zeros_like(distance['radar'])
            gt_el = elevation['truth'] if elevation else np.zeros_like(distance['truth'])
            rd_xyz = self._spherical_to_cartesian(distance['radar'], azimuth['radar'], rd_el)
            gt_xyz = self._spherical_to_cartesian(distance['truth'], azimuth['truth'], gt_el)
            rd_xyz = _decimate_plot_arrays(*rd_xyz)
            gt_xyz = _decimate_plot_arrays(*gt_xyz)
            if elevation:
                ax = figure.add_subplot(111, projection='3d')
                ax.plot(*rd_xyz, color='#2563eb', linewidth=1.3, label='雷达轨迹')
                ax.plot(*gt_xyz, color='#dc2626', linewidth=1.2, linestyle='--', label='真值轨迹')
                ax.set_zlabel('Z (m)')
            else:
                ax = figure.add_subplot(111)
                ax.plot(rd_xyz[0], rd_xyz[1], color='#2563eb', linewidth=1.3, label='雷达轨迹')
                ax.plot(gt_xyz[0], gt_xyz[1], color='#dc2626', linewidth=1.2, linestyle='--', label='真值轨迹')
                ax.set_aspect('equal', adjustable='datalim')
            ax.set_xlabel('X (m)')
            ax.set_ylabel('Y (m)')
            ax.set_title('雷达与真值轨迹', fontsize=11, fontweight='bold')
            style_axes_legend(ax)
            ax.grid(True, linestyle='--', alpha=0.22)
        figure.tight_layout(pad=1.1)
        self.compare_canvases['trajectory'].draw_idle()
    def _plot_algorithm_comparison(self, candidates):
        figure = self.compare_figures['algorithms']
        figure.clear()
        ax = figure.add_subplot(111)
        labels = [item['method'] for item in candidates]
        x = np.arange(len(labels))
        width = 0.36
        ax.bar(x - width / 2, [item['rmse'] for item in candidates], width, label='RMSE', color='#2563eb')
        ax.bar(x + width / 2, [item['mae'] for item in candidates], width, label='MAE', color='#0f766e')
        ax.set_xticks(x)
        ax.set_xticklabels(labels)
        ax.set_ylabel(METRIC_BY_KEY[self.combo_cmp_reference.currentData()]['unit'])
        ax.set_title('参考维度的对齐算法误差比较', fontsize=11, fontweight='bold')
        style_axes_legend(ax)
        ax.grid(True, axis='y', linestyle='--', alpha=0.22)
        figure.tight_layout(pad=1.1)
        self.compare_canvases['algorithms'].draw_idle()
    @staticmethod
    def _spherical_to_cartesian(distance, azimuth_deg, elevation_deg):
        azimuth = np.deg2rad(azimuth_deg)
        elevation = np.deg2rad(elevation_deg)
        horizontal = distance * np.cos(elevation)
        return horizontal * np.cos(azimuth), horizontal * np.sin(azimuth), distance * np.sin(elevation)
    def _fill_metrics_table(self, results):
        self.table_cmp_metrics.setRowCount(len(results))
        keys = ('count', 'mean_error', 'std_error', 'mae', 'rmse', 'max_abs', 'p95_abs', 'corr', 'r2')
        for row, item in enumerate(results.values()):
            self.table_cmp_metrics.setItem(row, 0, QTableWidgetItem(item['config']['label']))
            for column, key in enumerate(keys, 1):
                value = item['metrics'][key]
                text = str(value) if key == 'count' else ('--' if not np.isfinite(value) else f'{value:.6g}')
                cell = QTableWidgetItem(text)
                cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table_cmp_metrics.setItem(row, column, cell)
    def preview_compare_data(self):
        if self.compare_test_df is None and self.compare_truth_df is None:
            QMessageBox.information(self, '预览', '尚未加载数据')
            return
        dialog = QDialog(self)
        dialog.setWindowTitle('数据预览')
        dialog.resize(1100, 620)
        layout = QVBoxLayout(dialog)
        tabs = QTabWidget(dialog)
        if self.compare_test_df is not None:
            original = getattr(self, 'compare_test_original_df', None)
            if original is not None:
                tabs.addTab(self._dataframe_preview_widget(original), '雷达原始数据')
            current = self._current_compare_radar_df()
            tabs.addTab(self._dataframe_preview_widget(current), '雷达当前范围')
        if self.compare_truth_df is not None:
            tabs.addTab(self._dataframe_preview_widget(self.compare_truth_df), '真值数据')
        layout.addWidget(tabs)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec_()
    @staticmethod
    def _dataframe_preview_widget(dataframe):
        page = QWidget()
        layout = QVBoxLayout(page)
        numeric_count = int(dataframe.notna().sum().sum())
        layout.addWidget(QLabel(
            f'{len(dataframe)} 行 × {dataframe.shape[1]} 列，'
            f'有效数值 {numeric_count} 个；下表显示前 100 行'
        ))
        preview = dataframe.head(100)
        table = QTableWidget(len(preview), preview.shape[1])
        table.setHorizontalHeaderLabels([str(column) for column in preview.columns])
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setAlternatingRowColors(True)
        for row in range(len(preview)):
            for column in range(preview.shape[1]):
                value = preview.iat[row, column]
                text = 'NaN' if pd.isna(value) else f'{value:.10g}'
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                table.setItem(row, column, item)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        layout.addWidget(table)
        return page
