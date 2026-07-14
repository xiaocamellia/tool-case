"""
Compare analysis module: test vs truth data alignment and evaluation.

Extracted from original main_window.py for modularity.
"""

import os

import numpy as np
import pandas as pd
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QGridLayout, QGroupBox,
    QPushButton, QLabel, QFileDialog, QComboBox,
    QDoubleSpinBox, QMessageBox, QTextEdit
)
from PyQt5.QtGui import QFont
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

from .alignment import clean_series, run_alignment
from .data_loader import DataLoader, read_numeric_table
from .ui_theme import set_button_icon, style_primary_button
from .logger import get_logger

logger = get_logger('compare_analysis')


class CompareAnalysisMixin:
    """Mixin providing compare analysis UI and logic for MainWindow."""

    def _create_compare_analysis_page(self):
        """Create and return the 'measure comparison' page widget."""
        page = QWidget()
        layout = QVBoxLayout(page)

        ctrl_group = QGroupBox('输入数据与对齐设置')
        ctrl_layout = QGridLayout(ctrl_group)

        self.btn_cmp_load_test = QPushButton('📂 加载测试数据')
        self.btn_cmp_load_test.clicked.connect(self.load_compare_test_data)
        set_button_icon(self.btn_cmp_load_test, 'open')
        style_primary_button(self.btn_cmp_load_test)
        ctrl_layout.addWidget(self.btn_cmp_load_test, 0, 0)

        self.lbl_cmp_test = QLabel('测试数据: 未加载')
        self.lbl_cmp_test.setStyleSheet('color: gray;')
        ctrl_layout.addWidget(self.lbl_cmp_test, 0, 1, 1, 5)

        self.btn_cmp_load_meta = QPushButton('📄 加载元数据(列名)')
        self.btn_cmp_load_meta.clicked.connect(self.load_compare_metadata)
        set_button_icon(self.btn_cmp_load_meta, 'file')
        ctrl_layout.addWidget(self.btn_cmp_load_meta, 1, 0)

        self.lbl_cmp_meta = QLabel('元数据: 未加载')
        self.lbl_cmp_meta.setStyleSheet('color: gray;')
        ctrl_layout.addWidget(self.lbl_cmp_meta, 1, 1, 1, 5)

        self.btn_cmp_load_truth = QPushButton('📂 加载真实数据')
        self.btn_cmp_load_truth.clicked.connect(self.load_compare_truth_data)
        set_button_icon(self.btn_cmp_load_truth, 'open')
        style_primary_button(self.btn_cmp_load_truth)
        ctrl_layout.addWidget(self.btn_cmp_load_truth, 2, 0)

        self.lbl_cmp_truth = QLabel('真实数据: 未加载')
        self.lbl_cmp_truth.setStyleSheet('color: gray;')
        ctrl_layout.addWidget(self.lbl_cmp_truth, 2, 1, 1, 5)

        ctrl_layout.addWidget(QLabel('测试列:'), 3, 0)
        self.combo_cmp_test_col = QComboBox()
        self.combo_cmp_test_col.setMinimumWidth(220)
        ctrl_layout.addWidget(self.combo_cmp_test_col, 3, 1)

        ctrl_layout.addWidget(QLabel('真实列:'), 3, 2)
        self.combo_cmp_truth_col = QComboBox()
        self.combo_cmp_truth_col.setMinimumWidth(220)
        ctrl_layout.addWidget(self.combo_cmp_truth_col, 3, 3)

        ctrl_layout.addWidget(QLabel('对齐方法:'), 4, 0)
        self.combo_cmp_method = QComboBox()
        self.combo_cmp_method.addItem('基线重采样', 'resample')
        self.combo_cmp_method.addItem('互相关平移对齐', 'xcorr')
        self.combo_cmp_method.addItem('最小二乘(时间缩放+平移)', 'least_squares_time')
        self.combo_cmp_method.addItem('稳健互相关+幅值校正', 'robust_xcorr')
        ctrl_layout.addWidget(self.combo_cmp_method, 4, 1)

        ctrl_layout.addWidget(QLabel('最大平移比例:'), 4, 2)
        self.spin_cmp_max_shift_ratio = QDoubleSpinBox()
        self.spin_cmp_max_shift_ratio.setRange(0.01, 0.80)
        self.spin_cmp_max_shift_ratio.setSingleStep(0.01)
        self.spin_cmp_max_shift_ratio.setDecimals(2)
        self.spin_cmp_max_shift_ratio.setValue(0.25)
        ctrl_layout.addWidget(self.spin_cmp_max_shift_ratio, 4, 3)

        ctrl_layout.addWidget(QLabel('缩放搜索比例:'), 5, 0)
        self.spin_cmp_scale_span = QDoubleSpinBox()
        self.spin_cmp_scale_span.setRange(0.05, 1.00)
        self.spin_cmp_scale_span.setSingleStep(0.05)
        self.spin_cmp_scale_span.setDecimals(2)
        self.spin_cmp_scale_span.setValue(0.30)
        ctrl_layout.addWidget(self.spin_cmp_scale_span, 5, 1)

        self.btn_cmp_run = QPushButton('▶ 运行对比分析')
        self.btn_cmp_run.clicked.connect(self.run_compare_analysis)
        set_button_icon(self.btn_cmp_run, 'play')
        style_primary_button(self.btn_cmp_run)
        ctrl_layout.addWidget(self.btn_cmp_run, 5, 2)

        self.btn_cmp_export = QPushButton('⬇ 导出对比结果')
        self.btn_cmp_export.clicked.connect(self.export_compare_result)
        set_button_icon(self.btn_cmp_export, 'save')
        ctrl_layout.addWidget(self.btn_cmp_export, 5, 3)

        layout.addWidget(ctrl_group)

        self.compare_figure = Figure(figsize=(11, 6.8), dpi=160, facecolor='white')
        self.compare_canvas = FigureCanvas(self.compare_figure)
        self.compare_toolbar = NavigationToolbar(self.compare_canvas, self)
        layout.addWidget(self.compare_toolbar)
        layout.addWidget(self.compare_canvas, 1)

        self.txt_cmp_stats = QTextEdit()
        self.txt_cmp_stats.setMaximumHeight(180)
        self.txt_cmp_stats.setReadOnly(True)
        self.txt_cmp_stats.setFont(QFont('Consolas', 9))
        self.txt_cmp_stats.setText('加载测试数据与真实数据后，选择列并运行对比分析。')
        layout.addWidget(self.txt_cmp_stats)

        logger.debug('对比分析页签UI已创建')
        return page

    # ---------- Compare analysis methods ----------

    def load_compare_test_data(self):
        filepath, _ = QFileDialog.getOpenFileName(
            self, '选择测试数据文件', '', '文本文件 (*.txt *.csv);;所有文件 (*.*)'
        )
        if not filepath:
            logger.info('用户操作: [对比分析] 取消加载测试数据')
            return
        try:
            if self.compare_meta_cols:
                self.compare_test_df = DataLoader.load_data(filepath, self.compare_meta_cols)
            else:
                self.compare_test_df = read_numeric_table(filepath)
            self.compare_test_filepath = filepath
            n = len(self.compare_test_df)
            logger.info(f'用户操作: [对比分析] 加载测试数据 — {os.path.basename(filepath)} ({n} 行)')
            self.lbl_cmp_test.setText(f'测试数据: {os.path.basename(filepath)}  ({n} 行)')
            self.lbl_cmp_test.setStyleSheet('color: #334155;')
            self._refresh_compare_column_combos()
            self.status_label.setText('已加载测试数据')
        except Exception as e:
            logger.error(f'[对比分析] 测试数据加载失败: {e}')
            QMessageBox.warning(self, '加载失败', str(e))

    def load_compare_metadata(self):
        filepath, _ = QFileDialog.getOpenFileName(
            self, '选择元数据列名文件', '', '文本文件 (*.txt);;所有文件 (*.*)'
        )
        if not filepath:
            logger.info('用户操作: [对比分析] 取消加载元数据列名')
            return
        try:
            self.compare_meta_cols = DataLoader.load_column_names(filepath)
            logger.info(f'用户操作: [对比分析] 加载元数据列名 — {os.path.basename(filepath)} ({len(self.compare_meta_cols)} 列)')
            self.lbl_cmp_meta.setText(f'元数据: {os.path.basename(filepath)}')
            self.lbl_cmp_meta.setStyleSheet('color: #334155;')
            if self.compare_test_filepath:
                self.compare_test_df = DataLoader.load_data(self.compare_test_filepath, self.compare_meta_cols)
                n = len(self.compare_test_df)
                self.lbl_cmp_test.setText(
                    f'测试数据: {os.path.basename(self.compare_test_filepath)}  ({n} 行)'
                )
            self._refresh_compare_column_combos()
            self.status_label.setText('已加载元数据列名')
        except Exception as e:
            logger.error(f'[对比分析] 元数据加载失败: {e}')
            QMessageBox.warning(self, '加载失败', str(e))

    def load_compare_truth_data(self):
        filepath, _ = QFileDialog.getOpenFileName(
            self, '选择真实数据文件', '', '文本文件 (*.txt *.csv);;所有文件 (*.*)'
        )
        if not filepath:
            logger.info('用户操作: [对比分析] 取消加载真实数据')
            return
        try:
            self.compare_truth_df = read_numeric_table(filepath)
            self.compare_truth_filepath = filepath
            n = len(self.compare_truth_df)
            logger.info(f'用户操作: [对比分析] 加载真实数据 — {os.path.basename(filepath)} ({n} 行)')
            self.lbl_cmp_truth.setText(f'真实数据: {os.path.basename(filepath)}  ({n} 行)')
            self.lbl_cmp_truth.setStyleSheet('color: #334155;')
            self._refresh_compare_column_combos()
            self.status_label.setText('已加载真实数据')
        except Exception as e:
            logger.error(f'[对比分析] 真实数据加载失败: {e}')
            QMessageBox.warning(self, '加载失败', str(e))

    def _refresh_compare_column_combos(self):
        self.combo_cmp_test_col.blockSignals(True)
        self.combo_cmp_truth_col.blockSignals(True)
        self.combo_cmp_test_col.clear()
        self.combo_cmp_truth_col.clear()
        if self.compare_test_df is not None:
            self.combo_cmp_test_col.addItems([str(c) for c in self.compare_test_df.columns])
        if self.compare_truth_df is not None:
            self.combo_cmp_truth_col.addItems([str(c) for c in self.compare_truth_df.columns])
        self.combo_cmp_test_col.blockSignals(False)
        self.combo_cmp_truth_col.blockSignals(False)

    def run_compare_analysis(self):
        if self.compare_test_df is None:
            logger.warning('[对比分析] 运行失败: 未加载测试数据')
            QMessageBox.information(self, '提示', '请先加载测试数据')
            return
        if self.compare_truth_df is None:
            logger.warning('[对比分析] 运行失败: 未加载真实数据')
            QMessageBox.information(self, '提示', '请先加载真实数据')
            return

        test_col = self.combo_cmp_test_col.currentText()
        truth_col = self.combo_cmp_truth_col.currentText()
        if not test_col or not truth_col:
            logger.warning('[对比分析] 运行失败: 未选择分析列')
            QMessageBox.information(self, '提示', '请先选择测试列与真实列')
            return

        test_raw = clean_series(self.compare_test_df[test_col].to_numpy())
        truth_raw = clean_series(self.compare_truth_df[truth_col].to_numpy())
        if len(test_raw) < 3 or len(truth_raw) < 3:
            logger.warning(f'[对比分析] 数据不足: test={len(test_raw)}, truth={len(truth_raw)}')
            QMessageBox.warning(self, '数据不足', '可用样点不足，无法进行对比分析')
            return

        method = self.combo_cmp_method.currentData()
        max_shift_ratio = float(self.spin_cmp_max_shift_ratio.value())
        scale_span = float(self.spin_cmp_scale_span.value())
        logger.info(f'用户操作: [对比分析] 开始运行 — 方法={method}, 测试列={test_col}, 真实列={truth_col}')

        test = test_raw.astype(float)
        truth = truth_raw.astype(float)
        aligned_truth, extra_info = run_alignment(
            test, truth,
            method=method,
            max_shift_ratio=max_shift_ratio,
            scale_span=scale_span,
        )

        valid = np.isfinite(test) & np.isfinite(aligned_truth)
        if np.count_nonzero(valid) < 2:
            logger.error('[对比分析] 对齐失败: 有效重叠样点过少')
            QMessageBox.warning(self, '对齐失败', '有效重叠样点过少，请调整方法或参数')
            return

        residual = np.full(len(test), np.nan)
        residual[valid] = test[valid] - aligned_truth[valid]

        rmse = float(np.sqrt(np.nanmean((residual[valid]) ** 2)))
        mae = float(np.nanmean(np.abs(residual[valid])))
        corr = float(np.corrcoef(test[valid], aligned_truth[valid])[0, 1]) if np.count_nonzero(valid) > 2 else np.nan

        self.compare_figure.clear()
        ax1 = self.compare_figure.add_subplot(211)
        ax2 = self.compare_figure.add_subplot(212)

        x = np.arange(len(test))
        ax1.plot(x, test, color='#1d4ed8', linewidth=1.8, label=f'测试: {test_col}')
        ax1.plot(x, aligned_truth, color='#ef4444', linewidth=1.4, linestyle='--', label=f'对齐后真实: {truth_col}')
        ax1.set_title('量测数据对比（对齐后）', fontsize=12, fontweight='bold')
        ax1.set_xlabel('样点索引')
        ax1.set_ylabel('数值')
        ax1.grid(True, linestyle='--', alpha=0.25)
        ax1.legend(loc='best', fontsize=9)

        ax2.plot(x, residual, color='#0f766e', linewidth=1.4, label='误差: 测试-真实')
        ax2.axhline(0.0, color='#94a3b8', linewidth=1.0)
        ax2.set_title('误差序列', fontsize=11)
        ax2.set_xlabel('样点索引')
        ax2.set_ylabel('误差')
        ax2.grid(True, linestyle='--', alpha=0.25)
        ax2.legend(loc='best', fontsize=9)

        self.compare_figure.tight_layout(pad=1.2)
        self.compare_canvas.draw()

        metrics_lines = [
            f"方法: {extra_info.get('method', method)}",
            f"测试列: {test_col}",
            f"真实列: {truth_col}",
            f"测试样点: {len(test)} | 真实样点: {len(truth)} | 重叠样点: {np.count_nonzero(valid)}",
            f"RMSE: {rmse:.6f}",
            f"MAE : {mae:.6f}",
            f"Corr: {corr:.6f}",
        ]
        if 'lag' in extra_info:
            metrics_lines.append(f"Lag(样点): {extra_info['lag']:.3f}")
        if 'scale' in extra_info:
            metrics_lines.append(f"Scale(时间缩放): {extra_info['scale']:.6f}")
        if 'shift' in extra_info:
            metrics_lines.append(f"Shift(样点): {extra_info['shift']:.3f}")
        if 'gain' in extra_info:
            metrics_lines.append(f"Gain: {extra_info['gain']:.6f}")
        if 'bias' in extra_info:
            metrics_lines.append(f"Bias: {extra_info['bias']:.6f}")

        self.txt_cmp_stats.setText('\n'.join(metrics_lines))

        self.compare_last_result = pd.DataFrame({
            'sample_index': x,
            'test_value': test,
            'truth_aligned': aligned_truth,
            'residual': residual,
        })
        self.compare_last_metrics = {
            'method': extra_info.get('method', method),
            'rmse': rmse,
            'mae': mae,
            'corr': corr,
            **extra_info,
        }
        logger.info(f'用户操作: [对比分析] 完成 — 方法={method}, RMSE={rmse:.6f}, Corr={corr:.6f}, 重叠样点={np.count_nonzero(valid)}')
        self.status_label.setText(f'量测数据对比完成: RMSE={rmse:.4f}, Corr={corr:.4f}')

    def export_compare_result(self):
        if self.compare_last_result is None or self.compare_last_result.empty:
            logger.warning('[对比分析] 导出失败: 尚未运行对比分析')
            QMessageBox.information(self, '提示', '请先运行一次对比分析')
            return
        filepath, _ = QFileDialog.getSaveFileName(
            self, '导出对比结果', '', 'CSV 文件 (*.csv);;文本文件 (*.txt);;所有文件 (*.*)'
        )
        if not filepath:
            logger.info('用户操作: [对比分析] 取消导出结果')
            return
        ext = os.path.splitext(filepath)[1].lower()
        if not ext:
            filepath += '.csv'
        try:
            self.compare_last_result.to_csv(filepath, index=False, encoding='utf-8-sig')
            logger.info(f'用户操作: [对比分析] 导出结果 — {filepath}')
            self.status_label.setText(f'已导出对比结果: {os.path.basename(filepath)}')
        except Exception as e:
            logger.error(f'[对比分析] 导出结果失败: {e}')
            QMessageBox.warning(self, '导出失败', str(e))