"""Data truth review: sample alignment, multi-field evaluation, and export."""

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

logger = get_logger('compare_analysis')






















from .compare_data import CompareDataMixin
from .compare_export import CompareExportMixin
from .compare_plot import ComparePlotMixin
from .compare_workers import CompareWorkerMixin

from .compare_core import (
    MAX_PLOT_POINTS, METRIC_BY_KEY, METRIC_COLUMN_ALIASES, METRIC_DEFINITIONS, TruthReviewWorker, _compute_truth_review, _decimate_plot_arrays, _estimate_fixed_scale_alignment, _normalize_column_name, _paired_outlier_mask, _sample_mapping, find_metric_column, resample_gps_to_radar_cadence
)

class CompareAnalysisMixin(CompareDataMixin, CompareWorkerMixin, ComparePlotMixin, CompareExportMixin):
    """Mixin providing the data truth review page for ``MainWindow``."""

    def _create_compare_analysis_page(self):
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(8)

        splitter = QSplitter(Qt.Horizontal)
        self.compare_splitter = splitter
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(QScrollArea.NoFrame)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(2)
        left_layout.addWidget(self._create_compare_data_group())
        left_layout.addWidget(self._create_compare_mapping_group())
        left_layout.addWidget(self._create_compare_preprocessing_group())
        left_layout.addWidget(self._create_compare_alignment_group())
        left_layout.addStretch(1)
        left_scroll.setWidget(left)
        left_scroll.setMinimumWidth(680)
        self.compare_left_scroll = left_scroll
        self.compare_left_panel = left

        splitter.addWidget(left_scroll)
        splitter.addWidget(self._create_compare_result_tabs())
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, False)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([720, 680])
        root.addWidget(splitter, 1)
        QTimer.singleShot(0, self._initialize_compare_splitter_sizes)

        self._refresh_compare_column_combos()
        logger.debug('数据真值复核页签UI已创建')
        return page

    def _initialize_compare_splitter_sizes(self):
        """Set the initial split after lazy tab layout has its real width."""
        splitter = getattr(self, 'compare_splitter', None)
        if splitter is None:
            return
        available = splitter.width()
        if available <= 100:
            splitter.setSizes([720, 680])
            return
        desired_left = max(
            700,
            self.compare_left_panel.minimumSizeHint().width() + 24,
        )
        # Preserve a useful plot area on smaller screens while prioritizing a
        # complete control panel at the normal 1400 px application width.
        desired_left = min(desired_left, max(680, available - 420))
        splitter.setSizes([desired_left, max(1, available - desired_left)])

    def _create_compare_data_group(self):
        group = QGroupBox('数据导入')
        layout = QGridLayout(group)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setVerticalSpacing(4)

        self.btn_cmp_load_test = QPushButton('加载雷达数据')
        self.btn_cmp_load_test.clicked.connect(self.load_compare_test_data)
        set_button_icon(self.btn_cmp_load_test, 'open')
        style_primary_button(self.btn_cmp_load_test)
        layout.addWidget(self.btn_cmp_load_test, 0, 0)
        self.lbl_cmp_test = QLabel('雷达数据: 未加载')
        self.lbl_cmp_test.setStyleSheet('color: #64748b;')
        layout.addWidget(self.lbl_cmp_test, 0, 1)

        self.btn_cmp_load_meta = QPushButton('加载雷达列名')
        self.btn_cmp_load_meta.clicked.connect(self.load_compare_metadata)
        set_button_icon(self.btn_cmp_load_meta, 'file')
        layout.addWidget(self.btn_cmp_load_meta, 1, 0)
        self.lbl_cmp_meta = QLabel('雷达列名: 未加载')
        self.lbl_cmp_meta.setStyleSheet('color: #64748b;')
        layout.addWidget(self.lbl_cmp_meta, 1, 1)

        self.btn_cmp_load_truth = QPushButton('加载真值数据')
        self.btn_cmp_load_truth.clicked.connect(self.load_compare_truth_data)
        set_button_icon(self.btn_cmp_load_truth, 'open')
        style_primary_button(self.btn_cmp_load_truth)
        layout.addWidget(self.btn_cmp_load_truth, 2, 0)
        self.lbl_cmp_truth = QLabel('真值数据: 未加载')
        self.lbl_cmp_truth.setStyleSheet('color: #64748b;')
        layout.addWidget(self.lbl_cmp_truth, 2, 1)

        self.btn_cmp_preview = QPushButton('预览已加载数据')
        self.btn_cmp_preview.clicked.connect(self.preview_compare_data)
        set_button_icon(self.btn_cmp_preview, 'file')
        layout.addWidget(self.btn_cmp_preview, 3, 0)
        self.btn_cmp_plot_raw = QPushButton('绘制原始数据')
        self.btn_cmp_plot_raw.clicked.connect(self.plot_compare_raw_data)
        set_button_icon(self.btn_cmp_plot_raw, 'apply')
        layout.addWidget(self.btn_cmp_plot_raw, 3, 1)
        layout.setColumnStretch(1, 1)
        return group

    def _create_compare_alignment_group(self):
        group = QGroupBox('时间插值、两步对齐与数据统计')
        layout = QGridLayout(group)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setVerticalSpacing(4)

        group.setToolTip('GPS按时间列插值到雷达周期；插值后仅在样点轴上进行粗对齐和精对齐')

        layout.addWidget(QLabel('雷达采样间隔'), 1, 0)
        self.spin_cmp_radar_interval = QDoubleSpinBox()
        self.spin_cmp_radar_interval.setRange(0.001, 1e9)
        self.spin_cmp_radar_interval.setDecimals(3)
        self.spin_cmp_radar_interval.setValue(128.0)
        self.spin_cmp_radar_interval.setSuffix(' ms')
        self.spin_cmp_radar_interval.valueChanged.connect(self._invalidate_compare_result)
        layout.addWidget(self.spin_cmp_radar_interval, 1, 1)

        layout.addWidget(QLabel('GPS 时间列'), 1, 2)
        self.combo_cmp_truth_time = QComboBox()
        self.combo_cmp_truth_time.currentIndexChanged.connect(self._invalidate_compare_result)
        layout.addWidget(self.combo_cmp_truth_time, 1, 3)

        layout.addWidget(QLabel('GPS 时间单位'), 2, 0)
        self.combo_cmp_truth_time_unit = QComboBox()
        self.combo_cmp_truth_time_unit.addItem('毫秒 (ms)', 'ms')
        self.combo_cmp_truth_time_unit.addItem('秒 (s)', 's')
        self.combo_cmp_truth_time_unit.addItem('微秒 (us)', 'us')
        self.combo_cmp_truth_time_unit.setCurrentIndex(
            self.combo_cmp_truth_time_unit.findData('s')
        )
        self.combo_cmp_truth_time_unit.currentIndexChanged.connect(self._invalidate_compare_result)
        layout.addWidget(self.combo_cmp_truth_time_unit, 2, 1)

        layout.addWidget(QLabel('GPS 插值方式'), 2, 2)
        self.combo_cmp_interpolation = QComboBox()
        self.combo_cmp_interpolation.addItem('线性插值', 'linear')
        self.combo_cmp_interpolation.addItem('最近邻插值', 'nearest')
        self.combo_cmp_interpolation.addItem('三次样条插值', 'cubic')
        self.combo_cmp_interpolation.currentIndexChanged.connect(self._invalidate_compare_result)
        layout.addWidget(self.combo_cmp_interpolation, 2, 3)

        layout.addWidget(QLabel('粗对齐样点偏移'), 3, 0)
        self.spin_cmp_manual_offset = QDoubleSpinBox()
        self.spin_cmp_manual_offset.setRange(-1e9, 1e9)
        self.spin_cmp_manual_offset.setDecimals(3)
        self.spin_cmp_manual_offset.setSuffix(' 样点')
        self.spin_cmp_manual_offset.setToolTip('正值表示将真值样点轴向后平移')
        self.spin_cmp_manual_offset.valueChanged.connect(self._invalidate_compare_result)
        layout.addWidget(self.spin_cmp_manual_offset, 3, 1)

        layout.addWidget(QLabel('对齐方法'), 3, 2)
        self.combo_cmp_method = QComboBox()
        self.combo_cmp_method.addItem('多算法比较并优选', 'compare_all')
        self.combo_cmp_method.addItem('单点/手动偏移', 'single_point')
        self.combo_cmp_method.addItem('基线重采样', 'resample')
        self.combo_cmp_method.addItem('互相关平移对齐', 'xcorr')
        self.combo_cmp_method.addItem('最小二乘样点对齐', 'least_squares_time')
        self.combo_cmp_method.addItem('稳健互相关对齐', 'robust_xcorr')
        self.combo_cmp_method.setCurrentIndex(self.combo_cmp_method.findData('xcorr'))
        self.combo_cmp_method.currentIndexChanged.connect(self._invalidate_compare_result)
        layout.addWidget(self.combo_cmp_method, 3, 3)
        layout.addWidget(QLabel('参考维度'), 4, 0)
        self.combo_cmp_reference = QComboBox()
        for metric in METRIC_DEFINITIONS:
            self.combo_cmp_reference.addItem(metric['label'], metric['key'])
        self.combo_cmp_reference.currentIndexChanged.connect(
            self._on_compare_reference_changed
        )
        layout.addWidget(self.combo_cmp_reference, 4, 1)

        layout.addWidget(QLabel('最大平移比例'), 4, 2)
        self.spin_cmp_max_shift_ratio = QDoubleSpinBox()
        self.spin_cmp_max_shift_ratio.setRange(0.01, 0.80)
        self.spin_cmp_max_shift_ratio.setSingleStep(0.01)
        self.spin_cmp_max_shift_ratio.setDecimals(2)
        self.spin_cmp_max_shift_ratio.setValue(0.25)
        self.spin_cmp_max_shift_ratio.valueChanged.connect(self._invalidate_compare_result)
        layout.addWidget(self.spin_cmp_max_shift_ratio, 4, 3)
        self.spin_cmp_scale_span = QDoubleSpinBox()
        self.spin_cmp_scale_span.setValue(0.30)
        self.spin_cmp_scale_span.hide()

        layout.addWidget(QLabel('主维度野点阈值'), 5, 0)
        self.spin_cmp_outlier_threshold = QDoubleSpinBox()
        self.spin_cmp_outlier_threshold.setRange(0.0, 1e9)
        self.spin_cmp_outlier_threshold.setDecimals(6)
        self.spin_cmp_outlier_threshold.setValue(0.0)
        self.spin_cmp_outlier_threshold.setSpecialValueText('自动 MAD')
        self.spin_cmp_outlier_threshold.setToolTip('按参考维度的粗对齐差值识别野点；0 使用 6 倍 MAD 自动阈值')
        self.spin_cmp_outlier_threshold.valueChanged.connect(self._invalidate_fine_compare_result)
        layout.addWidget(self.spin_cmp_outlier_threshold, 5, 1)

        self.compare_additional_outlier_settings = {}
        self.btn_cmp_outlier_dimensions = QPushButton('设置备选维度')
        self.btn_cmp_outlier_dimensions.clicked.connect(
            self.configure_compare_outlier_dimensions
        )
        self.btn_cmp_outlier_dimensions.setToolTip(
            '从已启用的复核维度中选择多个维度联合剔除野点'
        )
        set_button_icon(self.btn_cmp_outlier_dimensions, 'apply')
        layout.addWidget(self.btn_cmp_outlier_dimensions, 5, 2)
        self.lbl_cmp_outlier_dimensions = QLabel('备选: 未启用')
        self.lbl_cmp_outlier_dimensions.setStyleSheet('color: #475569;')
        self.lbl_cmp_outlier_dimensions.setToolTip(
            '任一启用维度判为野点，均同步剔除雷达与对应 GPS 点'
        )
        layout.addWidget(self.lbl_cmp_outlier_dimensions, 5, 3)
        self._refresh_compare_additional_outlier_options()
        actions = QWidget()
        actions_layout = QHBoxLayout(actions)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        self.btn_cmp_run = QPushButton('第 1 步：粗对齐')
        self.btn_cmp_run.clicked.connect(self.run_compare_coarse_alignment)
        set_button_icon(self.btn_cmp_run, 'play')
        style_primary_button(self.btn_cmp_run)
        actions_layout.addWidget(self.btn_cmp_run)
        self.btn_cmp_run_fine = QPushButton('第 2 步：精对齐')
        self.btn_cmp_run_fine.clicked.connect(self.run_compare_fine_alignment)
        self.btn_cmp_run_fine.setEnabled(False)
        set_button_icon(self.btn_cmp_run_fine, 'play')
        style_primary_button(self.btn_cmp_run_fine)
        actions_layout.addWidget(self.btn_cmp_run_fine)
        self.btn_cmp_export = QPushButton('导出完整批次')
        self.btn_cmp_export.clicked.connect(self.export_compare_result)
        self.btn_cmp_export.setEnabled(False)
        set_button_icon(self.btn_cmp_export, 'save')
        actions_layout.addWidget(self.btn_cmp_export)
        layout.addWidget(actions, 6, 0, 1, 4)

        stats_title = QLabel('数据统计')
        stats_title.setStyleSheet('font-weight: 600; color: #334155;')
        layout.addWidget(stats_title, 7, 0)
        self.lbl_cmp_stat_radar_original = QLabel('雷达原始: 0 点')
        self.lbl_cmp_stat_radar_filtered = QLabel('雷达过滤后: 0 点')
        self.lbl_cmp_stat_radar_selected = QLabel('雷达过滤截取后: 0 点')
        self.lbl_cmp_stat_truth_original = QLabel('GPS 插值前: 0 点')
        self.lbl_cmp_stat_truth_aligned = QLabel('GPS 插值后: --')
        self.lbl_cmp_stat_truth_aligned.setToolTip('插值后仍为 GPS 数据和 GPS 插值样点')
        self.lbl_cmp_stat_alignment_valid = QLabel('GPS 对齐后有效: --')
        self.lbl_cmp_stat_paired = QLabel('精对齐同步保留: --')
        self.lbl_cmp_stat_alignment_valid.setStyleSheet('color: #475569;')
        layout.addWidget(self.lbl_cmp_stat_alignment_valid, 7, 2, 1, 2)
        for row, column, column_span, label in (
            (8, 0, 2, self.lbl_cmp_stat_radar_original),
            (8, 2, 2, self.lbl_cmp_stat_radar_filtered),
            (9, 0, 2, self.lbl_cmp_stat_radar_selected),
            (9, 2, 2, self.lbl_cmp_stat_truth_original),
            (10, 0, 2, self.lbl_cmp_stat_truth_aligned),
            (10, 2, 2, self.lbl_cmp_stat_paired),
        ):
            label.setStyleSheet('color: #475569;')
            layout.addWidget(label, row, column, 1, column_span)
        layout.setColumnStretch(1, 1)
        layout.setColumnStretch(3, 1)
        return group

    def _create_compare_preprocessing_group(self):
        group = QGroupBox('雷达对齐前处理：过滤与截取')
        layout = QGridLayout(group)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setVerticalSpacing(4)

        layout.addWidget(QLabel('原始起始样点'), 0, 0)
        self.spin_cmp_range_start = QSpinBox()
        self.spin_cmp_range_start.setRange(0, 0)
        self.spin_cmp_range_start.valueChanged.connect(self._on_compare_range_changed)
        layout.addWidget(self.spin_cmp_range_start, 0, 1)

        layout.addWidget(QLabel('原始结束样点'), 0, 2)
        self.spin_cmp_range_end = QSpinBox()
        self.spin_cmp_range_end.setRange(0, 0)
        self.spin_cmp_range_end.setSpecialValueText('末尾')
        self.spin_cmp_range_end.valueChanged.connect(self._on_compare_range_changed)
        layout.addWidget(self.spin_cmp_range_end, 0, 3)

        self.lbl_cmp_range_count = QLabel('当前范围: 0 / 0 样点')
        self.lbl_cmp_range_count.setStyleSheet('color: #475569;')
        layout.addWidget(self.lbl_cmp_range_count, 1, 2, 1, 2)

        layout.addWidget(QLabel('过滤列'), 1, 0)
        self.combo_cmp_filter_col = QComboBox()
        layout.addWidget(self.combo_cmp_filter_col, 1, 1)
        layout.addWidget(QLabel('最小值'), 2, 0)
        self.edit_cmp_filter_min = QLineEdit()
        self.edit_cmp_filter_min.setPlaceholderText('不限制')
        layout.addWidget(self.edit_cmp_filter_min, 2, 1)
        layout.addWidget(QLabel('最大值'), 2, 2)
        self.edit_cmp_filter_max = QLineEdit()
        self.edit_cmp_filter_max.setPlaceholderText('不限制')
        layout.addWidget(self.edit_cmp_filter_max, 2, 3)

        self.btn_cmp_apply_filter = QPushButton('应用过滤')
        self.btn_cmp_apply_filter.clicked.connect(self.apply_compare_filter)
        set_button_icon(self.btn_cmp_apply_filter, 'apply')
        layout.addWidget(self.btn_cmp_apply_filter, 3, 0, 1, 2)
        self.btn_cmp_clear_filter = QPushButton('清除过滤')
        self.btn_cmp_clear_filter.clicked.connect(self.clear_compare_filter)
        set_button_icon(self.btn_cmp_clear_filter, 'clear')
        layout.addWidget(self.btn_cmp_clear_filter, 3, 2, 1, 2)
        layout.setColumnStretch(1, 1)
        return group

    def _create_compare_mapping_group(self):
        group = QGroupBox('复核项目与字段映射')
        self.group_cmp_mapping = group
        layout = QGridLayout(group)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setVerticalSpacing(4)
        for column, text in enumerate(('复核项目', '雷达字段', 'GPS 字段', '雷达修正', 'GPS 修正')):
            header = QLabel(text)
            header.setStyleSheet('color: #64748b; font-size: 12px;')
            layout.addWidget(header, 0, column)
        self.compare_mapping_widgets = {}
        for row, metric in enumerate(METRIC_DEFINITIONS):
            enabled = QCheckBox(f"{metric['label']} ({metric['unit']})")
            enabled.setToolTip(f"启用或停用{metric['label']}真值复核")
            radar_combo = QComboBox()
            truth_combo = QComboBox()
            radar_bias = self._make_bias_spin(metric['unit'])
            truth_bias = self._make_bias_spin(metric['unit'])
            radar_bias.setToolTip(
                '仅在精对齐中应用。粗对齐差值定义为“雷达 - GPS”，'
                '校零时通常输入该平均差值的相反数。'
            )
            truth_bias.setToolTip('仅在精对齐中应用到 GPS 真值。')
            layout.addWidget(enabled, row + 1, 0)
            layout.addWidget(radar_combo, row + 1, 1)
            layout.addWidget(truth_combo, row + 1, 2)
            layout.addWidget(radar_bias, row + 1, 3)
            layout.addWidget(truth_bias, row + 1, 4)
            self.compare_mapping_widgets[metric['key']] = {
                'row': row, 'enabled': enabled, 'radar': radar_combo, 'truth': truth_combo,
                'radar_bias': radar_bias, 'truth_bias': truth_bias,
            }
            enabled.toggled.connect(self._invalidate_compare_result)
            enabled.toggled.connect(self._refresh_compare_additional_outlier_options)
            radar_bias.valueChanged.connect(self._invalidate_fine_compare_result)
            truth_bias.valueChanged.connect(self._invalidate_fine_compare_result)
            radar_combo.currentIndexChanged.connect(
                lambda _index, key=metric['key']: self._on_compare_mapping_changed(key)
            )
            truth_combo.currentIndexChanged.connect(
                lambda _index, key=metric['key']: self._on_compare_mapping_changed(key)
            )
        layout.setColumnStretch(1, 1)
        layout.setColumnStretch(2, 1)
        return group

    @staticmethod
    def _make_bias_spin(unit):
        spin = QDoubleSpinBox()
        spin.setRange(-1e9, 1e9)
        spin.setDecimals(6)
        spin.setSingleStep(0.1)
        spin.setSuffix(f' {unit}')
        spin.setMinimumWidth(88)
        return spin

    def _create_compare_result_tabs(self):
        self.tabs_cmp_results = QTabWidget()
        self.compare_figures = {}
        self.compare_canvases = {}
        for key, title in (
            ('raw', '原始数据'), ('range', '截取前后'),
            ('interpolation', 'GPS 时间插值'), ('coarse_difference', '粗对齐差值'),
            ('overview', '精对齐后对比'),
            ('error', '误差曲线'), ('distribution', '误差分布'),
            ('trajectory', '轨迹对比'), ('algorithms', '算法对比'),
        ):
            widget = QWidget()
            layout = QVBoxLayout(widget)
            layout.setContentsMargins(0, 0, 0, 0)
            figure = Figure(figsize=(11, 5.5), dpi=110, facecolor='white')
            canvas = FigureCanvas(figure)
            layout.addWidget(NavigationToolbar(canvas, self))
            layout.addWidget(canvas, 1)
            self.compare_figures[key] = figure
            self.compare_canvases[key] = canvas
            self.tabs_cmp_results.addTab(widget, title)

        metrics_page = QWidget()
        metrics_layout = QHBoxLayout(metrics_page)
        self.table_cmp_metrics = QTableWidget(0, 10)
        self.table_cmp_metrics.setHorizontalHeaderLabels(
            ['维度', '样点数', '均值误差', '标准差', 'MAE', 'RMSE', '最大绝对误差', 'P95', '相关系数', 'R²']
        )
        self.table_cmp_metrics.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table_cmp_metrics.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        metrics_layout.addWidget(self.table_cmp_metrics, 4)
        self.txt_cmp_stats = QTextEdit()
        self.txt_cmp_stats.setReadOnly(True)
        self.txt_cmp_stats.setFont(QFont('Consolas', 9))
        self.txt_cmp_stats.setText('加载雷达数据与真值数据，配置字段映射后运行复核。')
        metrics_layout.addWidget(self.txt_cmp_stats, 2)
        self.tabs_cmp_results.addTab(metrics_page, '统计结果')
        return self.tabs_cmp_results

    # ---------- Data loading ----------





























    # ---------- Analysis ----------























    # ---------- Preview and export ----------
