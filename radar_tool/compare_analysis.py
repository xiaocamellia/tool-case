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
from .logger import get_logger
from .ui_theme import set_button_icon, style_primary_button

logger = get_logger('compare_analysis')

METRIC_DEFINITIONS = (
    {'key': 'distance', 'label': '距离', 'unit': 'm', 'truth_pos': 4, 'angular': False},
    {'key': 'speed', 'label': '速度', 'unit': 'm/s', 'truth_pos': 5, 'angular': False},
    {'key': 'azimuth', 'label': '方位角', 'unit': 'deg', 'truth_pos': 6, 'angular': True},
    {'key': 'elevation', 'label': '俯仰角', 'unit': 'deg', 'truth_pos': 7, 'angular': True},
)
METRIC_BY_KEY = {item['key']: item for item in METRIC_DEFINITIONS}
MAX_PLOT_POINTS = 6000

METRIC_COLUMN_ALIASES = {
    'distance': ('距离', '目标距离', '斜距', '目标斜距', 'dist', 'distance', 'range'),
    'speed': ('速度', '目标速度', '径向速度', 'speed', 'velocity', 'radialspeed'),
    'azimuth': ('方位角', '目标方位角', '方位', 'azi', 'azimuth'),
    'elevation': ('俯仰角', '目标俯仰角', '俯仰', 'elv', 'elev', 'elevation', 'pitch'),
}


def _normalize_column_name(name):
    return re.sub(r'[\s_\-—()（）\[\]【】/]+', '', str(name).strip().lower())


def find_metric_column(columns, metric_key):
    """Find a measurement column by its semantic name, never by radar position."""
    aliases = tuple(_normalize_column_name(alias) for alias in METRIC_COLUMN_ALIASES[metric_key])
    if metric_key in ('azimuth', 'elevation'):
        excluded = ('速度', '速率', 'rate', 'velocity', 'speed')
    elif metric_key == 'speed':
        excluded = ('方位', '俯仰', '角速度', '角速率', 'azimuth', 'elevation')
    elif metric_key == 'distance':
        excluded = ('分辨率', '分辨力', 'resolution')
    else:
        excluded = ()
    best = None
    for index, column in enumerate(columns):
        normalized = _normalize_column_name(column)
        if excluded and any(token in normalized for token in excluded):
            continue
        scores = []
        for alias_index, alias in enumerate(aliases):
            if normalized == alias:
                scores.append(10_000 - alias_index)
            elif alias and alias in normalized:
                scores.append(100 + len(alias) * 10 - len(normalized) - alias_index)
        if scores:
            candidate = (max(scores), -len(normalized), -index, str(column))
            if best is None or candidate > best:
                best = candidate
    return None if best is None else best[3]


def _decimate_plot_arrays(*arrays, max_points=MAX_PLOT_POINTS):
    if not arrays:
        return arrays
    length = len(arrays[0])
    if length <= max_points:
        return tuple(np.asarray(array) for array in arrays)
    indices = np.linspace(0, length - 1, max_points).astype(int)
    return tuple(np.asarray(array)[indices] for array in arrays)


def resample_gps_to_radar_cadence(gps_time, values, radar_interval_ms,
                                  time_unit='ms', method='linear'):
    """Resample GPS values from real timestamps onto the radar cadence."""
    factors = {'s': 1000.0, 'ms': 1.0, 'us': 0.001}
    if time_unit not in factors:
        raise ValueError(f'不支持的 GPS 时间单位: {time_unit}')
    interval = float(radar_interval_ms)
    if not np.isfinite(interval) or interval <= 0:
        raise ValueError('雷达采样间隔必须大于 0 ms')
    raw_time = np.asarray(gps_time, dtype=float) * factors[time_unit]
    finite_time = raw_time[np.isfinite(raw_time)]
    if len(finite_time) < 2:
        raise ValueError('GPS 时间列的有效值不足（至少需要 2 个）')
    elapsed_ms = raw_time - float(finite_time[0])
    duration_ms = float(np.nanmax(elapsed_ms))
    if duration_ms <= 0:
        raise ValueError('GPS 时间列必须包含至少两个不同的时间值')
    grid_ms = np.arange(int(np.floor(duration_ms / interval)) + 1, dtype=float) * interval
    interpolated = interpolate_at(elapsed_ms, values, grid_ms, method)
    return elapsed_ms / interval, grid_ms / interval, interpolated


def _sample_mapping(item):
    normalized = dict(item)
    if normalized.get('method') == '最小二乘时间对齐':
        normalized['method'] = '最小二乘样点对齐（固定比例）'
    if 'query_offset_s' in normalized:
        normalized['query_offset_samples'] = normalized.pop('query_offset_s')
    if 'manual_offset_s' in normalized:
        normalized['manual_offset_samples'] = normalized.pop('manual_offset_s')
    if 'time_shift_s' in normalized:
        normalized['shift_samples'] = normalized.pop('time_shift_s')
    return normalized


def _estimate_fixed_scale_alignment(radar_sample, radar_values, gps_sample,
                                    gps_values, payload):
    methods = (
        ('resample', 'xcorr', 'least_squares_time', 'robust_xcorr')
        if payload['method'] == 'compare_all' else (payload['method'],)
    )
    candidates = []
    for method in methods:
        mapping = estimate_time_mapping(
            radar_sample, radar_values, gps_sample, gps_values,
            method=method, max_shift_ratio=payload['max_shift_ratio'],
            scale_span=payload['scale_span'],
            manual_offset_s=payload['manual_offset_s'],
            interpolation=payload['interpolation'], fixed_scale=1.0,
        )
        aligned = apply_time_mapping(
            radar_sample, gps_sample, gps_values, mapping, payload['interpolation']
        )
        metrics = calculate_error_metrics(
            radar_values, aligned, payload.get('reference_angular', False)
        )
        candidates.append({
            **mapping, 'rmse': metrics['rmse'], 'mae': metrics['mae'],
            'corr': metrics['corr'], 'count': metrics['count'],
        })
    best = min(candidates, key=lambda item: item['rmse'])
    mapping = {
        key: value for key, value in best.items()
        if key not in ('rmse', 'mae', 'corr', 'count')
    }
    return mapping, candidates


def _paired_outlier_mask(radar, truth, threshold, angular=False):
    residual = np.asarray(radar, dtype=float) - np.asarray(truth, dtype=float)
    if angular:
        residual = (residual + 180.0) % 360.0 - 180.0
    valid = np.isfinite(residual)
    if np.count_nonzero(valid) < 3:
        raise ValueError('粗对齐后的有效重叠样点不足（至少需要 3 个）')
    center = float(np.median(residual[valid]))
    deviation = np.abs(residual - center)
    if threshold > 0:
        used_threshold = float(threshold)
        mode = 'manual'
    else:
        mad = float(np.median(deviation[valid]))
        radar_valid = np.asarray(radar, dtype=float)[valid]
        signal_span = float(np.percentile(radar_valid, 95) - np.percentile(radar_valid, 5))
        # A tiny MAD is common after good interpolation. The span floor keeps
        # normal interpolation residuals while still rejecting radar spikes.
        used_threshold = max(6.0 * 1.4826 * mad, 0.01 * signal_span, 1e-12)
        mode = 'auto_mad'
    keep = valid & (deviation <= used_threshold)
    if np.count_nonzero(keep) < 3:
        raise ValueError('同步剔除野点后有效样点不足（至少需要 3 个）')
    return keep, {
        'mode': mode, 'center': center, 'threshold': used_threshold,
        'removed': int(np.count_nonzero(valid & ~keep)),
        'kept': int(np.count_nonzero(keep)),
    }


def _compute_truth_review(payload):
    """Run coarse or fine review without changing the GPS time scale."""
    radar_sample = np.asarray(payload['radar_sample'], dtype=float)
    gps_time = np.asarray(payload['gps_time'], dtype=float)
    reference_key = payload['reference_key']
    series = {}
    truth_sample = gps_interpolated_sample = None
    for key, item in payload['series'].items():
        truth_sample, gps_interpolated_sample, gps_interpolated = (
            resample_gps_to_radar_cadence(
                gps_time, item['truth_source'], payload['radar_interval_ms'],
                payload['gps_time_unit'], payload['interpolation'],
            )
        )
        series[key] = {**item, 'gps_interpolated': gps_interpolated}

    reference = series[reference_key]
    stage = payload.get('stage', 'coarse')
    if stage == 'coarse':
        mapping, candidates = _estimate_fixed_scale_alignment(
            radar_sample, reference['radar_source'], gps_interpolated_sample,
            reference['gps_interpolated'], payload,
        )
        pair_mask = np.ones(len(radar_sample), dtype=bool)
        outlier_info = None
    elif stage == 'fine':
        public_coarse = payload.get('coarse_mapping')
        if not public_coarse:
            raise ValueError('请先完成粗对齐，再运行精对齐')
        coarse_mapping = dict(public_coarse)
        if 'query_offset_samples' in coarse_mapping:
            coarse_mapping['query_offset_s'] = coarse_mapping['query_offset_samples']
        ref_radar = reference['radar_source'] + reference['config']['radar_bias']
        coarse_truth = apply_time_mapping(
            radar_sample, gps_interpolated_sample,
            reference['gps_interpolated'] + reference['config']['truth_bias'],
            coarse_mapping, payload['interpolation'],
        )
        pair_mask, primary_outlier_info = _paired_outlier_mask(
            ref_radar, coarse_truth, payload['outlier_threshold'],
            reference['config']['angular'],
        )
        primary_outlier_info.update({
            'metric_key': reference_key,
            'metric_label': reference['config']['label'],
            'unit': reference['config']['unit'],
        })
        dimension_outliers = [primary_outlier_info]
        additional_dimensions = payload.get('additional_outlier_dimensions')
        if additional_dimensions is None:
            secondary_key = payload.get('secondary_outlier_key')
            additional_dimensions = ([{
                'key': secondary_key,
                'threshold': payload.get('secondary_outlier_threshold', 0.0),
            }] if secondary_key else [])
        processed_keys = {reference_key}
        for dimension_spec in additional_dimensions:
            dimension_key = dimension_spec.get('key')
            if not dimension_key or dimension_key in processed_keys:
                continue
            dimension = series.get(dimension_key)
            if dimension is None:
                raise ValueError(
                    f'野点维度“{dimension_key}”必须先在复核项目中启用并完成字段映射'
                )
            dimension_radar = (
                dimension['radar_source'] + dimension['config']['radar_bias']
            )
            dimension_truth = apply_time_mapping(
                radar_sample, gps_interpolated_sample,
                dimension['gps_interpolated'] + dimension['config']['truth_bias'],
                coarse_mapping, payload['interpolation'],
            )
            dimension_mask, dimension_info = _paired_outlier_mask(
                dimension_radar, dimension_truth,
                float(dimension_spec.get('threshold', 0.0)),
                dimension['config']['angular'],
            )
            dimension_info.update({
                'metric_key': dimension_key,
                'metric_label': dimension['config']['label'],
                'unit': dimension['config']['unit'],
            })
            pair_mask &= dimension_mask
            dimension_outliers.append(dimension_info)
            processed_keys.add(dimension_key)
        if np.count_nonzero(pair_mask) < 3:
            raise ValueError('多维度合并剔除后有效样点不足（至少需要 3 个）')
        outlier_info = {
            'dimensions': dimension_outliers,
            'removed': int(len(pair_mask) - np.count_nonzero(pair_mask)),
            'kept': int(np.count_nonzero(pair_mask)),
        }
        fine_payload = {**payload, 'manual_offset_s': 0.0}
        fine_mapping, candidates = _estimate_fixed_scale_alignment(
            radar_sample, np.where(pair_mask, ref_radar, np.nan),
            radar_sample, np.where(pair_mask, coarse_truth, np.nan), fine_payload,
        )
        mapping = {
            **fine_mapping,
            'query_offset_s': (
                float(coarse_mapping.get('query_offset_s', 0.0))
                + float(fine_mapping.get('query_offset_s', 0.0))
            ),
            'method': f"{fine_mapping['method']}（粗对齐后精调）",
        }
    else:
        raise ValueError(f'不支持的复核阶段: {stage}')

    result = pd.DataFrame({
        'radar_sample_index': radar_sample.astype(np.int64),
        'paired_sample_kept': pair_mask,
    })
    metric_results = {}
    for key, item in series.items():
        config = item['config']
        apply_bias = stage == 'fine'
        radar = item['radar_source'] + (config['radar_bias'] if apply_bias else 0.0)
        gps_interpolated = item['gps_interpolated'] + (
            config['truth_bias'] if apply_bias else 0.0
        )
        aligned_truth = apply_time_mapping(
            radar_sample, gps_interpolated_sample, gps_interpolated,
            mapping, payload['interpolation'],
        )
        if stage == 'fine':
            radar = np.where(pair_mask, radar, np.nan)
            aligned_truth = np.where(pair_mask, aligned_truth, np.nan)
        error = radar - aligned_truth
        if config['angular']:
            error = (error + 180.0) % 360.0 - 180.0
        metrics = calculate_error_metrics(radar, aligned_truth, config['angular'])
        metric_results[key] = {
            'config': config, 'radar': radar, 'truth': aligned_truth,
            'raw_radar': item['radar_source'], 'raw_truth': item['truth_source'],
            'gps_interpolated': gps_interpolated, 'error': error,
            'metrics': metrics,
        }
        result[f'radar_{key}'] = radar
        result[f'gps_aligned_{key}'] = aligned_truth
        result[f'error_{key}'] = error

    public_mapping = _sample_mapping(mapping)
    public_candidates = [_sample_mapping(item) for item in candidates]
    interpolated_valid = int(np.count_nonzero(
        np.isfinite(metric_results[reference_key]['gps_interpolated'])
    ))
    aligned_valid = int(metric_results[reference_key]['metrics']['count'])
    paired_count = int(np.count_nonzero(pair_mask))
    metrics_summary = {
        'stage': stage, 'alignment': public_mapping,
        'reference_metric': reference_key,
        'alignment_candidates': public_candidates,
        'radar_interval_ms': float(payload['radar_interval_ms']),
        'gps_time_unit': payload['gps_time_unit'],
        'gps_time_column': payload['gps_time_column'],
        'truth_samples_before_interpolation': int(len(gps_time)),
        'truth_samples_after_interpolation': int(len(gps_interpolated_sample)),
        'truth_valid_samples_after_interpolation': interpolated_valid,
        'truth_valid_samples_after_alignment': aligned_valid,
        'paired_samples_after_outlier_removal': paired_count,
        'outlier_removal': outlier_info,
        'interpolation': payload['interpolation'],
        'metrics': {key: value['metrics'] for key, value in metric_results.items()},
        'fields': {
            key: {
                name: item['config'][name]
                for name in ('label', 'unit', 'radar_col', 'truth_col',
                             'radar_bias', 'truth_bias')
            }
            for key, item in metric_results.items()
        },
    }
    return {
        'stage': stage, 'radar_sample': radar_sample,
        'truth_sample': truth_sample,
        'gps_interpolated_sample': gps_interpolated_sample,
        'result': result, 'metric_results': metric_results,
        'metrics_summary': metrics_summary, 'mapping': public_mapping,
        'alignment_candidates': public_candidates,
        'truth_interpolated_count': int(len(gps_interpolated_sample)),
        'truth_interpolated_valid_count': interpolated_valid,
        'truth_aligned_valid_count': aligned_valid,
        'paired_samples_after_outlier_removal': paired_count,
        'preprocess_revision': payload['preprocess_revision'],
    }


class TruthReviewWorker(QObject):
    succeeded = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, payload):
        super().__init__()
        self.payload = payload

    @pyqtSlot()
    def run(self):
        try:
            self.succeeded.emit(_compute_truth_review(self.payload))
        except Exception as exc:
            logger.exception('[数据真值复核] 后台分析失败')
            self.failed.emit(str(exc))


class CompareAnalysisMixin:
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

    def load_compare_test_data(self):
        filepath, _ = QFileDialog.getOpenFileName(
            self, '选择雷达数据文件', '',
            '支持的数据 (*.txt *.csv *.dat *.xlsx *.xls);;所有文件 (*.*)'
        )
        if not filepath:
            return
        try:
            column_filepath = DataLoader.auto_find_column_file(filepath)
            if column_filepath and os.path.isfile(column_filepath):
                self.compare_meta_cols = DataLoader.load_column_names(column_filepath)
                self.compare_meta_filepath = column_filepath
                self.lbl_cmp_meta.setText(
                    f'雷达列名: {os.path.basename(column_filepath)} '
                    f'({len(self.compare_meta_cols)} 列，自动匹配)'
                )
                self.lbl_cmp_meta.setStyleSheet('color: #0f766e;')
            else:
                self.compare_meta_cols = None
                self.compare_meta_filepath = ''
                self.lbl_cmp_meta.setText('雷达列名: 未自动找到，可手动加载')
                self.lbl_cmp_meta.setStyleSheet('color: #b45309;')
            self.compare_test_df = DataLoader.load_data(
                filepath, self.compare_meta_cols
            )
            self.compare_test_original_df = self.compare_test_df.copy()
            self.compare_test_source_indices = np.arange(len(self.compare_test_df))
            self.compare_test_filepath = filepath
            self.lbl_cmp_test.setText(f'雷达数据: {os.path.basename(filepath)} ({len(self.compare_test_df)} 行)')
            self.lbl_cmp_test.setStyleSheet('color: #334155;')
            self._refresh_compare_column_combos(reset_preprocessing=True)
            self._invalidate_compare_result()
            self.status_label.setText('已加载雷达数据')
            logger.info(f'用户操作: [数据真值复核] 加载雷达数据 — {os.path.basename(filepath)}')
        except Exception as exc:
            logger.exception('[数据真值复核] 雷达数据加载失败')
            QMessageBox.warning(self, '加载失败', str(exc))

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
                self.compare_test_df = DataLoader.load_data(self.compare_test_filepath, self.compare_meta_cols)
                self.compare_test_original_df = self.compare_test_df.copy()
                self.compare_test_source_indices = np.arange(len(self.compare_test_df))
                self.lbl_cmp_test.setText(
                    f'雷达数据: {os.path.basename(self.compare_test_filepath)} ({len(self.compare_test_df)} 行)'
                )
            self._refresh_compare_column_combos(reset_preprocessing=True)
            self._invalidate_compare_result()
            self.status_label.setText('已加载雷达列名')
        except Exception as exc:
            logger.exception('[数据真值复核] 雷达列名加载失败')
            QMessageBox.warning(self, '加载失败', str(exc))

    def load_compare_truth_data(self):
        filepath, _ = QFileDialog.getOpenFileName(
            self, '选择 GPS/惯导真值数据文件', '',
            '支持的数据 (*.txt *.csv *.dat *.xlsx *.xls);;所有文件 (*.*)'
        )
        if not filepath:
            return
        try:
            self.compare_truth_df = read_numeric_table(filepath)
            self.compare_truth_filepath = filepath
            self.lbl_cmp_truth.setText(f'真值数据: {os.path.basename(filepath)} ({len(self.compare_truth_df)} 行)')
            self.lbl_cmp_truth.setStyleSheet('color: #334155;')
            self._refresh_compare_column_combos()
            self._invalidate_compare_result()
            self.status_label.setText('已加载真值数据')
            logger.info(f'用户操作: [数据真值复核] 加载真值数据 — {os.path.basename(filepath)}')
        except Exception as exc:
            logger.exception('[数据真值复核] 真值数据加载失败')
            QMessageBox.warning(self, '加载失败', str(exc))

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
            self.compare_test_original_df = self.compare_test_df.copy()
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
            QMessageBox.warning(self, '过滤失败', str(exc))

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

    # ---------- Analysis ----------

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
            logger.exception('[数据真值复核] 分析失败')
            QMessageBox.warning(self, '复核失败', str(exc))

    def _start_compare_worker(self, payload):
        self._set_compare_busy(True)
        self.status_label.setText('正在后台执行数据真值复核，可继续使用其它子模块')
        thread = QThread(self)
        worker = TruthReviewWorker(payload)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.succeeded.connect(self._on_compare_analysis_succeeded)
        worker.failed.connect(self._on_compare_analysis_failed)
        worker.succeeded.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.succeeded.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._on_compare_thread_finished)
        self._compare_thread = thread
        self._compare_worker = worker
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
            logger.exception('[数据真值复核] 结果绘制失败')
            QMessageBox.warning(self, '结果绘制失败', str(exc))
        finally:
            self._set_compare_busy(False)

    def _on_compare_analysis_failed(self, message):
        self._set_compare_busy(False)
        self.status_label.setText('数据真值复核失败')
        QMessageBox.warning(self, '复核失败', message)

    def _on_compare_thread_finished(self):
        self._compare_thread = None
        self._compare_worker = None

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
                QMessageBox.warning(self, '原始数据绘制失败', str(exc))
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
            ax.legend(loc='best', fontsize=8)
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
            axis.legend(loc='best', fontsize=8)
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
            axis.legend(loc='best', fontsize=8)
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
                axis.legend(loc='best', fontsize=8)
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
                ax.legend(loc='best', fontsize=8)
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
            ax.legend(loc='best')
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
        ax.legend(loc='best')
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

    # ---------- Preview and export ----------

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

    def _build_compare_export_tables(self):
        fine = getattr(self, 'compare_last_output', None)
        coarse = getattr(self, 'compare_coarse_output', None)
        if fine is None or coarse is None:
            raise ValueError('粗对齐或精对齐的完整结果不存在，请重新执行两步对齐')

        radar_sample = np.asarray(fine['radar_sample'], dtype=np.int64)
        source_indices = self._current_compare_radar_source_indices()
        time_column = fine['metrics_summary']['gps_time_column']
        gps_time_unit = fine['metrics_summary']['gps_time_unit']
        unit_to_ms = {'s': 1000.0, 'ms': 1.0, 'us': 0.001}
        gps_time_raw = pd.to_numeric(
            self.compare_truth_df[time_column], errors='coerce'
        ).to_numpy(dtype=float)
        finite_gps_time = gps_time_raw[np.isfinite(gps_time_raw)]
        if len(finite_gps_time) < 2:
            raise ValueError('GPS UTC 时间有效值不足，无法生成导出时间列')
        gps_utc_origin = float(finite_gps_time[0])
        interval_ms = float(fine['metrics_summary']['radar_interval_ms'])
        interpolation_sample = np.asarray(fine['gps_interpolated_sample'], dtype=float)

        def aligned_utc(output, apply_pair_mask=False):
            mapping = output['mapping']
            query_sample = (
                float(mapping.get('query_scale', 1.0)) * radar_sample
                + float(mapping.get('query_offset_samples', 0.0))
            )
            utc = (
                gps_utc_origin
                + query_sample * interval_ms / unit_to_ms[gps_time_unit]
            ).astype(float)
            valid = (
                np.isfinite(query_sample)
                & (query_sample >= interpolation_sample[0])
                & (query_sample <= interpolation_sample[-1])
            )
            if apply_pair_mask:
                valid &= fine['result']['paired_sample_kept'].to_numpy(dtype=bool)
            return np.where(valid, utc, np.nan)

        coarse_utc = aligned_utc(coarse)
        fine_utc = aligned_utc(fine, apply_pair_mask=True)
        final_columns = {
            '雷达原始样点索引(radar_source_sample_index)': source_indices,
            '雷达相对样点索引(radar_sample_index)': radar_sample,
            'GPS粗对齐UTC时间(gps_coarse_aligned_utc_time)': coarse_utc,
            'GPS精对齐UTC时间(gps_fine_aligned_utc_time)': fine_utc,
            'GPS UTC时间单位(gps_utc_time_unit)': np.full(
                len(radar_sample), gps_time_unit, dtype=object
            ),
            '配对样点保留(paired_sample_kept)': fine['result'][
                'paired_sample_kept'
            ].to_numpy(dtype=bool),
        }
        radar_columns = {
            '雷达原始样点索引(radar_source_sample_index)': source_indices,
            '雷达相对样点索引(radar_sample_index)': radar_sample,
            'GPS粗对齐UTC时间(gps_coarse_aligned_utc_time)': coarse_utc,
            'GPS精对齐UTC时间(gps_fine_aligned_utc_time)': fine_utc,
            'GPS UTC时间单位(gps_utc_time_unit)': np.full(
                len(radar_sample), gps_time_unit, dtype=object
            ),
        }
        coarse_columns = {
            '雷达原始样点索引(radar_source_sample_index)': source_indices,
            '雷达相对样点索引(radar_sample_index)': radar_sample,
            'GPS粗对齐UTC时间(gps_coarse_aligned_utc_time)': coarse_utc,
            'GPS UTC时间单位(gps_utc_time_unit)': np.full(
                len(radar_sample), gps_time_unit, dtype=object
            ),
        }
        for key, item in fine['metric_results'].items():
            label = item['config']['label']
            radar_columns[f'雷达{label}原始(radar_{key}_raw)'] = item['raw_radar']
            final_columns[f'雷达{label}原始(radar_{key}_raw)'] = item['raw_radar']
            final_columns[f'雷达{label}修正后(radar_{key}_corrected)'] = (
                np.asarray(item['raw_radar'], dtype=float)
                + float(item['config']['radar_bias'])
            )
            final_columns[f'GPS{label}粗对齐(gps_{key}_coarse_aligned)'] = (
                coarse['metric_results'][key]['truth']
            )
            final_columns[f'GPS{label}精对齐(gps_{key}_fine_aligned)'] = item['truth']
            final_columns[f'{label}精对齐误差(error_{key})'] = item['error']
            coarse_columns[f'雷达{label}原始(radar_{key}_raw)'] = (
                coarse['metric_results'][key]['radar']
            )
            coarse_columns[f'GPS{label}粗对齐(gps_{key}_coarse_aligned)'] = (
                coarse['metric_results'][key]['truth']
            )
            coarse_columns[f'{label}粗对齐差值(coarse_error_{key})'] = (
                coarse['metric_results'][key]['error']
            )

        gps_raw_columns = {
            'GPS原始行号(gps_source_row_index)': np.arange(
                len(self.compare_truth_df), dtype=np.int64
            ),
            'GPS原始UTC时间(gps_utc_time_raw)': gps_time_raw,
            'GPS UTC时间单位(gps_utc_time_unit)': np.full(
                len(self.compare_truth_df), gps_time_unit, dtype=object
            ),
        }
        gps_interpolation_columns = {
            'GPS插值样点索引(gps_interpolated_sample_index)': interpolation_sample,
            'GPS插值相对时间毫秒(gps_interpolated_time_ms)': (
                interpolation_sample * interval_ms
            ),
            'GPS插值UTC时间(gps_interpolated_utc_time)': (
                gps_utc_origin
                + interpolation_sample * interval_ms / unit_to_ms[gps_time_unit]
            ),
            'GPS UTC时间单位(gps_utc_time_unit)': np.full(
                len(interpolation_sample), gps_time_unit, dtype=object
            ),
        }
        for key, item in fine['metric_results'].items():
            label = item['config']['label']
            gps_raw_columns[f'GPS{label}原始(gps_{key}_raw)'] = item['raw_truth']
            gps_interpolation_columns[
                f'GPS{label}时间插值原始(gps_{key}_time_interpolated_raw)'
            ] = coarse['metric_results'][key]['gps_interpolated']
            gps_interpolation_columns[
                f'GPS{label}时间插值修正后(gps_{key}_time_interpolated_corrected)'
            ] = item['gps_interpolated']

        metric_names = {
            'count': '有效样点数(count)',
            'mean_error': '平均误差(mean_error)',
            'std_error': '误差标准差(std_error)',
            'mae': '平均绝对误差(mae)',
            'rmse': '均方根误差(rmse)',
            'max_abs': '最大绝对误差(max_abs)',
            'p95_abs': '绝对误差P95(p95_abs)',
            'corr': '相关系数(corr)',
            'r2': '决定系数(r2)',
        }
        metric_rows = []
        for key, metrics in self.compare_last_metrics['metrics'].items():
            row = {
                '维度(metric)': METRIC_BY_KEY[key]['label'],
                '单位(unit)': METRIC_BY_KEY[key]['unit'],
            }
            row.update({metric_names[name]: value for name, value in metrics.items()})
            metric_rows.append(row)

        candidate_rows = []
        for candidate in self.compare_last_metrics.get('alignment_candidates', ()):
            candidate_rows.append({
                '对齐方法(method)': candidate.get('method'),
                '样点比例(query_scale)': candidate.get('query_scale'),
                '样点偏移(query_offset_samples)': candidate.get(
                    'query_offset_samples'
                ),
                '互相关平移样点(lag_samples)': candidate.get('lag_samples'),
                '均方根误差(rmse)': candidate.get('rmse'),
                '平均绝对误差(mae)': candidate.get('mae'),
                '相关系数(corr)': candidate.get('corr'),
                '有效样点数(count)': candidate.get('count'),
            })

        final_table = pd.DataFrame(final_columns)
        return {
            '01_真值复核结果.csv': final_table,
            '02_真值复核有效配对.csv': final_table.loc[
                final_table['配对样点保留(paired_sample_kept)']
            ].reset_index(drop=True),
            '03_雷达测量数据.csv': pd.DataFrame(radar_columns),
            '04_GPS原始真值数据.csv': pd.DataFrame(gps_raw_columns),
            '05_GPS时间插值数据.csv': pd.DataFrame(gps_interpolation_columns),
            '06_粗对齐结果.csv': pd.DataFrame(coarse_columns),
            '07_误差指标.csv': pd.DataFrame(metric_rows),
            '08_对齐算法比较.csv': pd.DataFrame(candidate_rows),
        }

    def _create_compare_export_directory(self, root_directory):
        radar_stem = os.path.splitext(
            os.path.basename(self.compare_test_filepath)
        )[0] or '雷达数据'
        safe_stem = re.sub(r'[<>:"/\\|?*]+', '_', radar_stem).strip(' ._')
        safe_stem = (safe_stem or '雷达数据')[:80]
        prefix = datetime.now().strftime('%Y%m%d_%H%M%S')
        base_name = f'{prefix}_{safe_stem}_真值复核'
        target = os.path.join(root_directory, base_name)
        sequence = 2
        while os.path.exists(target):
            target = os.path.join(root_directory, f'{base_name}_{sequence:02d}')
            sequence += 1
        os.makedirs(target)
        return target

    def export_compare_result(self):
        if (
            self.compare_last_result is None
            or not self.compare_last_metrics
            or getattr(self, 'compare_last_output', None) is None
        ):
            QMessageBox.information(self, '提示', '请先完成粗对齐和精对齐')
            return
        default_root = (
            os.path.dirname(self.compare_test_filepath)
            if self.compare_test_filepath else ''
        )
        root_directory = QFileDialog.getExistingDirectory(
            self, '选择完整复核结果保存目录', default_root
        )
        if not root_directory:
            return
        batch_directory = None
        try:
            tables = self._build_compare_export_tables()
            batch_directory = self._create_compare_export_directory(root_directory)
            for filename, dataframe in tables.items():
                dataframe.to_csv(
                    os.path.join(batch_directory, filename), index=False,
                    encoding='utf-8-sig',
                )

            export_time = datetime.now().isoformat(timespec='seconds')
            configuration = {
                '导出时间(exported_at)': export_time,
                '雷达数据文件(radar_file)': self.compare_test_filepath,
                'GPS真值文件(gps_truth_file)': self.compare_truth_filepath,
                '雷达列名文件(radar_metadata_file)': getattr(
                    self, 'compare_meta_filepath', ''
                ),
                '批次目录(batch_directory)': batch_directory,
                '复核配置(review_configuration)': self.compare_last_metrics,
            }
            with open(
                os.path.join(batch_directory, '09_复核配置.json'),
                'w', encoding='utf-8',
            ) as handle:
                json.dump(configuration, handle, ensure_ascii=False, indent=2)

            for key, filename in (
                ('raw', '图件_01_原始数据.png'),
                ('range', '图件_02_过滤截取前后.png'),
                ('interpolation', '图件_03_GPS时间插值.png'),
                ('coarse_difference', '图件_04_粗对齐差值.png'),
                ('overview', '图件_05_精对齐曲线.png'),
                ('error', '图件_06_精对齐误差.png'),
                ('distribution', '图件_07_误差分布.png'),
                ('trajectory', '图件_08_轨迹对比.png'),
                ('algorithms', '图件_09_算法对比.png'),
            ):
                self.compare_figures[key].savefig(
                    os.path.join(batch_directory, filename), dpi=240,
                    bbox_inches='tight',
                )
            self.status_label.setText(f'完整复核结果已导出: {batch_directory}')
            logger.info(f'用户操作: [数据真值复核] 导出完整批次 — {batch_directory}')
        except Exception as exc:
            logger.exception('[数据真值复核] 导出失败')
            detail = str(exc)
            if batch_directory:
                detail += f'\n已创建目录: {batch_directory}'
            QMessageBox.warning(self, '导出失败', detail)
