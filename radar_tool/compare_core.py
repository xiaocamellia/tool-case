"""Comparison core data mapping, alignment, and truth-review calculations."""
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
logger = get_logger('compare_core')
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


def _compute_truth_review(payload, cancel_event=None, progress_callback=None):
    """Run coarse or fine review without changing the GPS time scale."""
    def ensure_not_cancelled():
        if cancel_event is not None and cancel_event.is_set():
            raise RuntimeError('数据真值复核已取消')

    def report(percent, message):
        if progress_callback is not None:
            progress_callback(percent, message)

    ensure_not_cancelled()
    report(5, '准备复核数据')
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
    report(25, '执行时间插值与对齐')
    ensure_not_cancelled()
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

    report(55, '计算误差指标')
    ensure_not_cancelled()
    result = pd.DataFrame({
        'radar_sample_index': radar_sample.astype(np.int64),
        'paired_sample_kept': pair_mask,
    })
    metric_results = {}
    for index, (key, item) in enumerate(series.items()):
        ensure_not_cancelled()
        report(
            55 + int(35 * (index + 1) / max(1, len(series))),
            f'计算指标 {key}',
        )
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
    report(95, '整理复核结果')
    ensure_not_cancelled()
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
    cancelled = pyqtSignal(str)
    progress = pyqtSignal(int, str)

    def __init__(self, payload):
        super().__init__()
        self.payload = payload
        import threading
        self._cancel_event = threading.Event()

    def cancel(self):
        self._cancel_event.set()

    @pyqtSlot()
    def run(self):
        try:
            self.progress.emit(5, '准备复核数据')
            self.succeeded.emit(_compute_truth_review(
                self.payload,
                cancel_event=self._cancel_event,
                progress_callback=self.progress.emit,
            ))
        except RuntimeError as exc:
            if self._cancel_event.is_set():
                self.cancelled.emit('数据真值复核已取消')
            else:
                logger.exception('[数据真值复核] 后台分析失败')
                self.failed.emit(safe_exception_message(exc))
        except Exception as exc:
            logger.exception('[数据真值复核] 后台分析失败')
            self.failed.emit(safe_exception_message(exc))
