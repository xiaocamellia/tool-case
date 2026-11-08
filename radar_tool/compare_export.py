"""Comparison result export tables and batch output."""
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
from .export_safety import (
    BatchExportError,
    atomic_export_batch,
    build_export_metadata,
    write_dataframe_csv,
)
from .schemas import TruthReviewConfig
from .logger import get_logger
from .ui_theme import set_button_icon, style_primary_button
from .compare_core import (
    MAX_PLOT_POINTS, METRIC_BY_KEY, METRIC_COLUMN_ALIASES, METRIC_DEFINITIONS, TruthReviewWorker, _compute_truth_review, _decimate_plot_arrays, _estimate_fixed_scale_alignment, _normalize_column_name, _paired_outlier_mask, _sample_mapping, find_metric_column, resample_gps_to_radar_cadence
)
logger = get_logger("compare_analysis")

class CompareExportMixin:
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
        try:
            tables = self._build_compare_export_tables()
            batch_directory = self._create_compare_export_directory(root_directory)
            export_metadata = build_export_metadata(
                input_summary={
                    'radar_file': os.path.basename(
                        self.compare_test_filepath or ''
                    ),
                    'gps_truth_file': os.path.basename(
                        self.compare_truth_filepath or ''
                    ),
                    'radar_metadata_file': os.path.basename(
                        getattr(self, 'compare_meta_filepath', '') or ''
                    ),
                    'radar_rows': len(self.compare_test_df),
                    'gps_truth_rows': len(self.compare_truth_df),
                    'export_tables': list(tables),
                },
                parameters={
                    'alignment_mapping': self.compare_last_result.get(
                        'mapping', {}
                    ),
                    'field_configuration': self.compare_last_metrics.get(
                        'fields', {}
                    ),
                    'interpolation': self.compare_last_metrics.get(
                        'interpolation', {}
                    ),
                    'outlier_removal': self.compare_last_metrics.get(
                        'outlier_removal', {}
                    ),
                },
            )

            def write_batch(temporary_directory):
                for filename, dataframe in tables.items():
                    write_dataframe_csv(
                        dataframe,
                        os.path.join(temporary_directory, filename),
                        index=False,
                        encoding='utf-8-sig',
                    )

                configuration = TruthReviewConfig.create(
                    exported_at=export_metadata['generated_at'],
                    radar_file=os.path.basename(
                        self.compare_test_filepath or ''
                    ),
                    gps_truth_file=os.path.basename(
                        self.compare_truth_filepath or ''
                    ),
                    radar_metadata_file=os.path.basename(
                        getattr(self, 'compare_meta_filepath', '') or ''
                    ),
                    batch_directory=os.path.basename(batch_directory),
                    review_configuration=self.compare_last_metrics,
                ).to_payload()
                configuration['export_metadata'] = export_metadata
                with open(
                    os.path.join(temporary_directory, '09_复核配置.json'),
                    'w', encoding='utf-8',
                ) as handle:
                    json.dump(
                        configuration, handle, ensure_ascii=False, indent=2
                    )
                with open(
                    os.path.join(temporary_directory, '00_导出元数据.json'),
                    'w', encoding='utf-8',
                ) as handle:
                    json.dump(
                        export_metadata, handle, ensure_ascii=False, indent=2
                    )

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
                        os.path.join(temporary_directory, filename),
                        dpi=240,
                        bbox_inches='tight',
                    )

            atomic_export_batch(batch_directory, write_batch)
            export_name = os.path.basename(batch_directory)
            self.status_label.setText(
                f'完整复核结果已导出: {export_name}'
            )
            logger.info(
                '用户操作: [数据真值复核] 导出完整批次 — %s',
                export_name,
            )
        except BatchExportError as exc:
            handle_ui_exception(
                self, logger, '导出复核结果', exc
            )
        except (OSError, ValueError, TypeError, OverflowError) as exc:
            export_error = ExportError(
                '复核结果导出失败，请检查目标目录空间和文件权限'
            )
            handle_ui_exception(
                self, logger, '导出复核结果', export_error
            )
        except Exception as exc:
            handle_ui_exception(
                self, logger, '导出复核结果', exc
            )
