#!/usr/bin/env python3
"""
数据可视化处理面板 - Data Visualization Panel
独立的 QWidget 类，封装数据加载、切片、过滤、绘图、导出等功能。
从 MainWindow 中提取为独立模块。
"""

import os

import numpy as np
import pandas as pd
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QPushButton, QFileDialog, QLabel, QSpinBox, QListWidget,
    QListWidgetItem, QGroupBox, QTextEdit,
    QCheckBox, QTabWidget, QComboBox, QLineEdit,
    QMessageBox, QAbstractItemView,
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont, QColor

from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar

from .data_loader import DataLoader
from .models import DatasetRecord, PlotDataItem, PlotViewRecord
from .plotting import MatplotlibCanvas
from .ui_theme import (
    set_button_icon, style_primary_button, style_warning_button,
)
from .logger import get_logger

logger = get_logger('visualization_panel')


class VisualizationPanel(QWidget):
    """数据可视化处理面板 — 独立的 QWidget 类"""

    def __init__(self, main_window):
        super().__init__(main_window)
        self.main_window = main_window

        # ---- 数据集管理 ----
        self.datasets = {}
        self.active_dataset_id = None
        self._dataset_counter = 0
        self.current_df = None
        self.col_names = []
        self.data_filepath = ''
        self.col_filepath = ''

        # ---- 绘图项管理 ----
        self.plot_items = []
        self._color_counter = 0
        self._current_plot_item_indices = []

        # ---- 多图页签 ----
        self.plot_views = {}
        self._plot_view_counter = 0
        self._plot_tab_order = []

        self._init_ui()
        logger.info('可视化处理面板已创建')

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        top_widget = self._create_top_controls()
        layout.addWidget(top_widget)

        splitter = QSplitter(Qt.Horizontal)
        left_widget = self._create_left_panel()
        splitter.addWidget(left_widget)
        right_widget = self._create_right_panel()
        splitter.addWidget(right_widget)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        layout.addWidget(splitter, 1)



    def _create_top_controls(self):
        group = QGroupBox('数据控制')
        layout = QHBoxLayout(group)

        self.btn_load = QPushButton('📂 加载数据文件(可多选)')
        self.btn_load.clicked.connect(self.load_data_file)
        set_button_icon(self.btn_load, 'open')
        style_primary_button(self.btn_load)
        layout.addWidget(self.btn_load)

        self.btn_load_col = QPushButton('📄 加载列名文件')
        self.btn_load_col.clicked.connect(self.load_column_file)
        set_button_icon(self.btn_load_col, 'file')
        layout.addWidget(self.btn_load_col)

        self.btn_remove_dataset = QPushButton('🗑️ 移除当前数据集')
        self.btn_remove_dataset.clicked.connect(self.remove_active_dataset)
        set_button_icon(self.btn_remove_dataset, 'delete')
        style_warning_button(self.btn_remove_dataset)
        layout.addWidget(self.btn_remove_dataset)

        self.btn_clear_datasets = QPushButton('🧹 清空全部数据集')
        self.btn_clear_datasets.clicked.connect(self.clear_all_datasets)
        set_button_icon(self.btn_clear_datasets, 'delete')
        style_warning_button(self.btn_clear_datasets)
        layout.addWidget(self.btn_clear_datasets)

        layout.addWidget(QLabel('  数据文件:'))
        self.lbl_data_file = QLabel('未加载')
        self.lbl_data_file.setStyleSheet('color: gray;')
        layout.addWidget(self.lbl_data_file, 1)

        layout.addStretch()

        self.btn_clear_overlay = QPushButton('🗑️ 清除叠加')
        self.btn_clear_overlay.clicked.connect(self.clear_overlay)
        set_button_icon(self.btn_clear_overlay, 'clear')
        layout.addWidget(self.btn_clear_overlay)

        self.btn_export = QPushButton('⬇ 导出高清图')
        self.btn_export.clicked.connect(self.export_current_plot)
        set_button_icon(self.btn_export, 'save')
        style_primary_button(self.btn_export)
        layout.addWidget(self.btn_export)

        self.btn_reset = QPushButton('🔄 重置')
        self.btn_reset.clicked.connect(self.reset_view)
        set_button_icon(self.btn_reset, 'reload')
        layout.addWidget(self.btn_reset)

        return group


    def _create_left_panel(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # ===== 数据集列表 =====
        dataset_group = QGroupBox('已加载数据集')
        dataset_layout = QVBoxLayout(dataset_group)

        self.list_datasets = QListWidget()
        self.list_datasets.setMinimumHeight(110)
        self.list_datasets.currentRowChanged.connect(self.on_dataset_selected)
        dataset_layout.addWidget(self.list_datasets)

        dataset_btn_layout = QHBoxLayout()
        self.btn_set_active = QPushButton('设为当前')
        self.btn_set_active.clicked.connect(self.set_selected_dataset_active)
        set_button_icon(self.btn_set_active, 'apply')
        dataset_btn_layout.addWidget(self.btn_set_active)
        self.btn_reload_active = QPushButton('重载当前')
        self.btn_reload_active.clicked.connect(self.reload_active_dataset)
        set_button_icon(self.btn_reload_active, 'reload')
        dataset_btn_layout.addWidget(self.btn_reload_active)
        dataset_layout.addLayout(dataset_btn_layout)

        layout.addWidget(dataset_group)

        # ===== 范围选择 =====
        range_group = QGroupBox('数据范围 (采样点索引)')
        range_layout = QHBoxLayout(range_group)

        range_layout.addWidget(QLabel('起始:'))
        self.spin_start = QSpinBox()
        self.spin_start.setRange(0, 999999)
        self.spin_start.setValue(0)
        self.spin_start.valueChanged.connect(self.on_range_changed)
        range_layout.addWidget(self.spin_start)

        range_layout.addWidget(QLabel('结束:'))
        self.spin_end = QSpinBox()
        self.spin_end.setRange(0, 999999)
        self.spin_end.setValue(0)
        self.spin_end.setSpecialValueText('末尾')
        self.spin_end.valueChanged.connect(self.on_range_changed)
        range_layout.addWidget(self.spin_end)

        range_layout.addWidget(QLabel('  总行数:'))
        self.lbl_total_rows = QLabel('0')
        range_layout.addWidget(self.lbl_total_rows)

        self.btn_save_range = QPushButton('保存范围预设')
        self.btn_save_range.clicked.connect(self.save_range_preset)
        set_button_icon(self.btn_save_range, 'save')
        range_layout.addWidget(self.btn_save_range)

        self.btn_refresh_plot = QPushButton('按当前范围重绘对比图')
        self.btn_refresh_plot.clicked.connect(self.redraw_current_range_plot)
        set_button_icon(self.btn_refresh_plot, 'refresh')
        style_primary_button(self.btn_refresh_plot)
        range_layout.addWidget(self.btn_refresh_plot)

        layout.addWidget(range_group)

        # ===== 数据过滤 =====
        filter_group = QGroupBox('数据过滤 (按值筛选行)')
        filter_layout = QHBoxLayout(filter_group)

        filter_layout.addWidget(QLabel('列:'))
        self.combo_filter_col = QComboBox()
        self.combo_filter_col.setMinimumWidth(120)
        self.combo_filter_col.currentIndexChanged.connect(self.on_filter_col_changed)
        filter_layout.addWidget(self.combo_filter_col)

        filter_layout.addWidget(QLabel('最小值:'))
        self.edit_filter_min = QLineEdit()
        self.edit_filter_min.setPlaceholderText('不限制')
        self.edit_filter_min.setMaximumWidth(80)
        filter_layout.addWidget(self.edit_filter_min)

        filter_layout.addWidget(QLabel('最大值:'))
        self.edit_filter_max = QLineEdit()
        self.edit_filter_max.setPlaceholderText('不限制')
        self.edit_filter_max.setMaximumWidth(80)
        filter_layout.addWidget(self.edit_filter_max)

        self.btn_apply_filter = QPushButton('应用过滤')
        self.btn_apply_filter.clicked.connect(self.apply_filter)
        set_button_icon(self.btn_apply_filter, 'apply')
        filter_layout.addWidget(self.btn_apply_filter)

        self.btn_clear_filter = QPushButton('清除过滤')
        self.btn_clear_filter.clicked.connect(self.clear_filter)
        set_button_icon(self.btn_clear_filter, 'clear')
        filter_layout.addWidget(self.btn_clear_filter)

        layout.addWidget(filter_group)

        # ===== 列选择 =====
        select_group = QGroupBox('选择要绘制的参数 (可多选)')
        select_layout = QVBoxLayout(select_group)

        select_btn_layout = QHBoxLayout()
        self.btn_select_all = QPushButton('全选')
        self.btn_select_all.clicked.connect(self.select_all_columns)
        set_button_icon(self.btn_select_all, 'apply')
        select_btn_layout.addWidget(self.btn_select_all)

        self.btn_deselect_all = QPushButton('全不选')
        self.btn_deselect_all.clicked.connect(self.deselect_all_columns)
        set_button_icon(self.btn_deselect_all, 'clear')
        select_btn_layout.addWidget(self.btn_deselect_all)

        self.btn_add_to_plot = QPushButton('▶ 添加到绘图')
        self.btn_add_to_plot.clicked.connect(self.add_selected_to_plot)
        self.btn_add_to_plot.setStyleSheet('background-color: #4CAF50; color: white; font-weight: bold;')
        set_button_icon(self.btn_add_to_plot, 'play')
        select_btn_layout.addWidget(self.btn_add_to_plot)
        select_layout.addLayout(select_btn_layout)

        target_layout = QHBoxLayout()
        target_layout.addWidget(QLabel('绘制到:'))
        self.combo_plot_target = QComboBox()
        self.combo_plot_target.setMinimumWidth(200)
        self.combo_plot_target.setEnabled(False)
        self.combo_plot_target.setToolTip('始终绑定到当前页签图')
        target_layout.addWidget(self.combo_plot_target, 1)
        select_layout.addLayout(target_layout)

        self.list_columns = QListWidget()
        self.list_columns.setSelectionMode(QAbstractItemView.MultiSelection)
        select_layout.addWidget(self.list_columns)

        layout.addWidget(select_group, 1)

        # ===== 当前绘图项列表 =====
        plotlist_group = QGroupBox('当前绘图项')
        plotlist_layout = QVBoxLayout(plotlist_group)

        self.list_plot_items = QListWidget()
        self.list_plot_items.setMinimumHeight(110)
        plotlist_layout.addWidget(self.list_plot_items)

        btn_remove_layout = QHBoxLayout()
        self.btn_remove_selected = QPushButton('移除选中')
        self.btn_remove_selected.clicked.connect(self.remove_selected_plot_item)
        set_button_icon(self.btn_remove_selected, 'delete')
        btn_remove_layout.addWidget(self.btn_remove_selected)

        self.btn_clear_all_plots = QPushButton('清空所有')
        self.btn_clear_all_plots.clicked.connect(self.clear_all_plot_items)
        set_button_icon(self.btn_clear_all_plots, 'clear')
        btn_remove_layout.addWidget(self.btn_clear_all_plots)

        plotlist_layout.addLayout(btn_remove_layout)

        layout.addWidget(plotlist_group)

        return widget


    def _create_right_panel(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # 多图页签
        self.plot_tabs = QTabWidget()
        self.plot_tabs.setMovable(True)
        self.plot_tabs.currentChanged.connect(self.on_plot_tab_changed)
        layout.addWidget(self.plot_tabs, 1)

        # 绘图控制
        ctrl_group = QGroupBox('绘图控制')
        ctrl_layout = QHBoxLayout(ctrl_group)

        self.btn_new_plot = QPushButton('🆕 新建图')
        self.btn_new_plot.clicked.connect(self.create_new_plot_view)
        set_button_icon(self.btn_new_plot, 'file')
        ctrl_layout.addWidget(self.btn_new_plot)

        self.btn_remove_plot = QPushButton('🗑 删除当前图')
        self.btn_remove_plot.clicked.connect(self.remove_current_plot_view)
        set_button_icon(self.btn_remove_plot, 'delete')
        style_warning_button(self.btn_remove_plot)
        ctrl_layout.addWidget(self.btn_remove_plot)

        self.btn_plot = QPushButton('📊 绘制')
        self.btn_plot.clicked.connect(self.plot_data)
        self.btn_plot.setStyleSheet('background-color: #2196F3; color: white; font-weight: bold; padding: 8px;')
        set_button_icon(self.btn_plot, 'play')
        style_primary_button(self.btn_plot)
        ctrl_layout.addWidget(self.btn_plot)

        self.btn_overlay = QPushButton('➕ 叠加绘制 (保持上一幅)')
        self.btn_overlay.clicked.connect(self.plot_data_overlay)
        self.btn_overlay.setStyleSheet('background-color: #FF9800; color: white; font-weight: bold;')
        set_button_icon(self.btn_overlay, 'refresh')
        style_warning_button(self.btn_overlay)
        ctrl_layout.addWidget(self.btn_overlay)

        self.chk_show_stats = QCheckBox('显示统计信息')
        self.chk_show_stats.setChecked(True)
        ctrl_layout.addWidget(self.chk_show_stats)

        self.chk_grid = QCheckBox('网格')
        self.chk_grid.setChecked(True)
        ctrl_layout.addWidget(self.chk_grid)

        ctrl_layout.addStretch()

        layout.addWidget(ctrl_group)

        # 默认创建第1张图
        self._create_plot_view(name='图1', set_active=True)
        self._refresh_plot_target_combo()

        return widget

    # ==================== 绘图页签管理 ====================


    def _create_plot_view(self, name=None, set_active=True):
        if name is None:
            name = f'图{self._plot_view_counter + 1}'

        view_id = self._plot_view_counter
        self._plot_view_counter += 1

        tab = QWidget()
        tab_layout = QVBoxLayout(tab)
        canvas = MatplotlibCanvas(self)
        toolbar = NavigationToolbar(canvas, self)
        txt_stats = QTextEdit()
        txt_stats.setMaximumHeight(150)
        txt_stats.setReadOnly(True)
        txt_stats.setFont(QFont('Consolas', 9))
        txt_stats.setText('(无数据)')

        tab_layout.addWidget(toolbar)
        tab_layout.addWidget(canvas, 1)
        tab_layout.addWidget(txt_stats)

        tab_index = self.plot_tabs.addTab(tab, name)
        self._plot_tab_order.append(view_id)
        self.plot_views[view_id] = PlotViewRecord(
            view_id=view_id,
            name=name,
            tab_widget=tab,
            canvas=canvas,
            toolbar=toolbar,
            txt_stats=txt_stats,
        )

        if set_active:
            self.plot_tabs.setCurrentIndex(tab_index)

        logger.debug(f'创建绘图页: {name} (id={view_id})')
        return view_id


    def _get_current_plot_view_id(self):
        idx = self.plot_tabs.currentIndex()
        if idx < 0 or idx >= len(self._plot_tab_order):
            return None
        return self._plot_tab_order[idx]


    def _get_current_plot_view(self):
        view_id = self._get_current_plot_view_id()
        if view_id is None:
            return None
        return self.plot_views.get(view_id)


    def _refresh_plot_target_combo(self):
        if not hasattr(self, 'combo_plot_target'):
            return
        current_view_id = self._get_current_plot_view_id()
        self.combo_plot_target.blockSignals(True)
        self.combo_plot_target.clear()
        for view_id in self._plot_tab_order:
            view = self.plot_views.get(view_id)
            if view is not None:
                self.combo_plot_target.addItem(view.name, view_id)

        set_index = 0
        for i in range(self.combo_plot_target.count()):
            if self.combo_plot_target.itemData(i) == current_view_id:
                set_index = i
                break
        if self.combo_plot_target.count() > 0:
            self.combo_plot_target.setCurrentIndex(set_index)
        self.combo_plot_target.blockSignals(False)


    def on_plot_tab_changed(self, idx):
        view_id = self._get_current_plot_view_id()
        view = self.plot_views.get(view_id)
        view_name = view.name if view else '未知'
        logger.debug(f'切换绘图页签: {view_name} (index={idx})')
        self._refresh_plot_target_combo()
        self._update_plot_list()


    def create_new_plot_view(self):
        view_id = self._create_plot_view(set_active=True)
        self._refresh_plot_target_combo()
        view = self.plot_views.get(view_id)
        if view is not None:
            logger.info(f'用户操作: 新建绘图页 — {view.name}')
            self.main_window.status_label.setText(f'已新建绘图页: {view.name}')


    def remove_current_plot_view(self):
        if self.plot_tabs.count() == 0:
            return
        idx = self.plot_tabs.currentIndex()
        if idx < 0 or idx >= len(self._plot_tab_order):
            return
        view_id = self._plot_tab_order[idx]
        view = self.plot_views.get(view_id)
        view_name = view.name if view is not None else f'图{view_id}'

        self.plot_items = [pi for pi in self.plot_items if pi.chart_id != view_id]

        self.plot_tabs.blockSignals(True)
        self.plot_tabs.removeTab(idx)
        self.plot_tabs.blockSignals(False)
        self._plot_tab_order.pop(idx)
        self.plot_views.pop(view_id, None)

        if self.plot_tabs.count() == 0:
            self._create_plot_view(name='图1', set_active=True)
        else:
            self.plot_tabs.setCurrentIndex(min(idx, self.plot_tabs.count() - 1))

        self._refresh_plot_target_combo()
        self._update_plot_list()
        logger.info(f'用户操作: 删除绘图页 — {view_name}')
        self.main_window.status_label.setText(f'已删除绘图页: {view_name}')

    # ==================== 文件加载 ====================


    def load_data_file(self):
        filepaths, _ = QFileDialog.getOpenFileNames(
            self, '选择数据文件', '', '文本文件 (*.txt);;所有文件 (*.*)'
        )
        if not filepaths:
            logger.info('用户操作: 取消加载数据文件')
            return
        logger.info(f'用户操作: 开始加载数据文件，共 {len(filepaths)} 个')
        loaded_ids = []
        for filepath in filepaths:
            try:
                dataset_id = self._load_single_dataset(filepath)
                loaded_ids.append(dataset_id)
                logger.info(f'  数据加载成功: {os.path.basename(filepath)} (id={dataset_id})')
            except Exception as e:
                logger.error(f'  数据加载失败: {os.path.basename(filepath)} — {e}')
                QMessageBox.warning(self, '加载失败', f'{os.path.basename(filepath)}\n{e}')

        if loaded_ids and self.active_dataset_id is None:
            self.set_active_dataset(loaded_ids[0])
        elif loaded_ids:
            self._refresh_dataset_list()

        if loaded_ids:
            msg = f'已加载 {len(loaded_ids)} 个数据集'
            logger.info(f'加载完成: {msg}')
            self.main_window.status_label.setText(msg)


    def load_column_file(self):
        filepath, _ = QFileDialog.getOpenFileName(
            self, '选择列名文件', '', '文本文件 (*.txt);;所有文件 (*.*)'
        )
        if not filepath:
            logger.info('用户操作: 取消加载列名文件')
            return
        try:
            col_names = DataLoader.load_column_names(filepath)
            logger.info(f'用户操作: 加载列名文件 — {os.path.basename(filepath)} ({len(col_names)} 列)')
        except Exception as e:
            logger.error(f'列名文件加载失败: {filepath} — {e}')
            QMessageBox.warning(self, '错误', str(e))
            return

        active = self._get_active_dataset()
        if active is None:
            logger.warning('加载列名文件失败: 当前无数据集')
            QMessageBox.information(self, '提示', '请先加载一个数据文件，再单独加载列名文件。')
            return

        try:
            active.col_filepath = filepath
            old_start, old_end = active.get_slice_bounds()
            active.df = DataLoader.load_data(active.data_filepath, col_names)
            active.original_df = active.df.copy()
            active.set_range(old_start, old_end)
            self.set_active_dataset(active.dataset_id)
            logger.info(f'列名已应用到数据集: {active.label} → shape={active.df.shape}')
            self.main_window.status_label.setText(f'已为当前数据集加载列名文件: {os.path.basename(filepath)}')
        except Exception as e:
            logger.error(f'应用列名失败: {e}')
            QMessageBox.warning(self, '错误', str(e))


    def _load_single_dataset(self, filepath):
        col_file = DataLoader.auto_find_column_file(filepath)
        if col_file and os.path.isfile(col_file):
            col_names = DataLoader.load_column_names(col_file)
        else:
            col_names = None
            col_file = ''

        df = DataLoader.load_data(filepath, col_names)
        dataset_id = self._dataset_counter
        self._dataset_counter += 1

        record = DatasetRecord(
            dataset_id=dataset_id,
            label=os.path.basename(filepath),
            data_filepath=filepath,
            col_filepath=col_file,
            df=df.copy(),
            original_df=df.copy(),
            start=0,
            end=len(df),
        )
        self.datasets[dataset_id] = record
        self._refresh_dataset_list()
        logger.debug(f'数据集已注册: id={dataset_id}, file={os.path.basename(filepath)}, shape={df.shape}')
        return dataset_id


    def _get_active_dataset(self):
        if self.active_dataset_id is None:
            return None
        return self.datasets.get(self.active_dataset_id)


    def _refresh_dataset_list(self):
        self.list_datasets.blockSignals(True)
        self.list_datasets.clear()
        active_row = -1
        for row, dataset_id in enumerate(sorted(self.datasets.keys())):
            dataset = self.datasets[dataset_id]
            start, end = dataset.get_slice_bounds()
            col_text = f" | {os.path.basename(dataset.col_filepath)}" if dataset.col_filepath else ''
            item = QListWidgetItem(f"{dataset.label}  [{start}:{end if end > 0 else 'end'}]{col_text}")
            self.list_datasets.addItem(item)
            if dataset_id == self.active_dataset_id:
                active_row = row
        if active_row >= 0:
            self.list_datasets.setCurrentRow(active_row)
        self.list_datasets.blockSignals(False)


    def set_active_dataset(self, dataset_id):
        dataset = self.datasets.get(dataset_id)
        if dataset is None:
            return

        prev_id = self.active_dataset_id
        self.active_dataset_id = dataset_id
        self.current_df = dataset.df
        self.col_names = list(dataset.df.columns)
        self.data_filepath = dataset.data_filepath
        self.col_filepath = dataset.col_filepath

        n_rows, n_cols = dataset.df.shape
        self.lbl_data_file.setText(dataset.label)
        self.lbl_total_rows.setText(str(n_rows))

        self.spin_start.blockSignals(True)
        self.spin_end.blockSignals(True)
        self.spin_start.setRange(0, max(0, n_rows - 1))
        self.spin_end.setRange(0, n_rows)
        self.spin_start.setValue(max(0, min(dataset.start, max(0, n_rows - 1))))
        self.spin_end.setValue(0 if dataset.end <= 0 else min(dataset.end, n_rows))
        self.spin_start.blockSignals(False)
        self.spin_end.blockSignals(False)

        self.list_columns.clear()
        for col in dataset.df.columns:
            item = QListWidgetItem(str(col))
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Unchecked)
            self.list_columns.addItem(item)

        self.combo_filter_col.blockSignals(True)
        self.combo_filter_col.clear()
        self.combo_filter_col.addItems([str(c) for c in dataset.df.columns])
        self.combo_filter_col.setCurrentIndex(0 if n_cols else -1)
        self.combo_filter_col.blockSignals(False)

        stats_text = f"📋 数据概览: {n_rows} 行 × {n_cols} 列\n"
        stats_text += f"数据文件: {os.path.basename(dataset.data_filepath)}\n"
        if dataset.col_filepath:
            stats_text += f"列名文件: {os.path.basename(dataset.col_filepath)}\n"
        stats_text += "列名列表:\n"
        for i, col in enumerate(dataset.df.columns):
            stats_text += f"  {i+1}. {col}\n"
        current_view = self._get_current_plot_view()
        if current_view is not None:
            current_view.txt_stats.setText(stats_text)

        self._refresh_dataset_list()
        logger.info(f'激活数据集: id={dataset_id}, "{dataset.label}", {n_rows}行×{n_cols}列')
        self.main_window.status_label.setText(f'✅ 当前数据集: {dataset.label} ({n_rows} 行 × {n_cols} 列)')


    def on_dataset_selected(self, row):
        dataset_ids = sorted(self.datasets.keys())
        if row < 0 or row >= len(dataset_ids):
            return
        self.set_active_dataset(dataset_ids[row])


    def set_selected_dataset_active(self):
        row = self.list_datasets.currentRow()
        if row >= 0:
            self.on_dataset_selected(row)


    def reload_active_dataset(self):
        dataset = self._get_active_dataset()
        if dataset is None:
            return
        logger.info(f'用户操作: 重载数据集 — {dataset.label}')
        try:
            old_start, old_end = dataset.get_slice_bounds()
            if dataset.col_filepath and os.path.isfile(dataset.col_filepath):
                col_names = DataLoader.load_column_names(dataset.col_filepath)
            else:
                col_names = None
            dataset.df = DataLoader.load_data(dataset.data_filepath, col_names)
            dataset.original_df = dataset.df.copy()
            dataset.set_range(old_start, old_end)
            self.set_active_dataset(dataset.dataset_id)
            logger.info(f'重载成功: {dataset.label}, shape={dataset.df.shape}')
            self.main_window.status_label.setText(f'已重载: {dataset.label}')
        except Exception as e:
            logger.error(f'重载失败: {e}')
            QMessageBox.warning(self, '重载失败', str(e))


    def remove_active_dataset(self):
        dataset = self._get_active_dataset()
        if dataset is None:
            return

        dataset_id = dataset.dataset_id
        label = dataset.label
        self.plot_items = [item for item in self.plot_items if item.dataset_id != dataset_id]
        self.datasets.pop(dataset_id, None)
        logger.info(f'用户操作: 移除数据集 — "{label}" (id={dataset_id})')

        if self.datasets:
            next_id = sorted(self.datasets.keys())[0]
            self.set_active_dataset(next_id)
        else:
            self.active_dataset_id = None
            self.current_df = None
            self.col_names = []
            self.data_filepath = ''
            self.col_filepath = ''
            self.list_datasets.clear()
            self.list_columns.clear()
            self.combo_filter_col.clear()
            self.lbl_data_file.setText('未加载')
            self.lbl_total_rows.setText('0')
            for view in self.plot_views.values():
                view.txt_stats.clear()
                view.canvas.axes.clear()
                view.canvas.draw()
            logger.info('数据集已全部清空 (移除最后一个数据集后)')

        self._update_plot_list()


    def clear_all_datasets(self):
        n = len(self.datasets)
        self.datasets.clear()
        self.active_dataset_id = None
        self.current_df = None
        self.col_names = []
        self.data_filepath = ''
        self.col_filepath = ''
        self.plot_items.clear()
        self._update_plot_list()
        self.list_datasets.clear()
        self.list_columns.clear()
        self.combo_filter_col.clear()
        self.lbl_data_file.setText('未加载')
        self.lbl_total_rows.setText('0')
        for view in self.plot_views.values():
            view.txt_stats.clear()
            view.canvas.axes.clear()
            view.canvas.draw()
        logger.info(f'用户操作: 清空全部数据集 (共移除 {n} 个)')
        self.main_window.status_label.setText('已清空全部数据集')

    # ==================== 范围与过滤 ====================


    def on_range_changed(self):
        dataset = self._get_active_dataset()
        if dataset is None:
            return
        dataset.set_range(self.spin_start.value(), self.spin_end.value())
        self._refresh_dataset_list()
        logger.debug(f'范围变更: {dataset.label} [{dataset.start}:{dataset.end}]')
        self.main_window.status_label.setText(f'已更新范围: {dataset.label} [{dataset.start}:{dataset.end if dataset.end > 0 else "end"}]')
        if self.plot_items:
            self.plot_data()


    def on_filter_col_changed(self, idx):
        _ = idx


    def apply_filter(self):
        dataset = self._get_active_dataset()
        if dataset is None or dataset.df is None:
            return

        col_name = self.combo_filter_col.currentText()
        if not col_name:
            return

        min_str = self.edit_filter_min.text().strip()
        max_str = self.edit_filter_max.text().strip()

        df = dataset.df
        try:
            if col_name in df.columns:
                mask = pd.Series([True] * len(df))
                if min_str:
                    mask &= (df[col_name] >= float(min_str))
                if max_str:
                    mask &= (df[col_name] <= float(max_str))

                filtered_df = df[mask].copy()
                n_removed = len(df) - len(filtered_df)

                dataset.df = filtered_df
                dataset.set_range(0, len(filtered_df))
                self.set_active_dataset(dataset.dataset_id)

                logger.info(f'用户操作: 数据过滤 — {dataset.label}, 列"{col_name}" 范围[{min_str or "不限"}, {max_str or "不限"}] 移除{n_removed}行, 保留{len(filtered_df)}行')
                self.main_window.status_label.setText(f'过滤完成: {dataset.label} 移除 {n_removed} 行, 保留 {len(filtered_df)} 行')
        except Exception as e:
            logger.error(f'过滤失败: {e}')
            QMessageBox.warning(self, '过滤错误', str(e))


    def clear_filter(self):
        dataset = self._get_active_dataset()
        if dataset is None:
            return
        self.edit_filter_min.clear()
        self.edit_filter_max.clear()
        try:
            old_start, old_end = dataset.get_slice_bounds()
            if dataset.col_filepath and os.path.isfile(dataset.col_filepath):
                col_names = DataLoader.load_column_names(dataset.col_filepath)
            else:
                col_names = None
            dataset.df = DataLoader.load_data(dataset.data_filepath, col_names)
            dataset.original_df = dataset.df.copy()
            dataset.set_range(old_start, old_end)
            self.set_active_dataset(dataset.dataset_id)
            logger.info(f'用户操作: 清除过滤 — {dataset.label}')
            self.main_window.status_label.setText(f'已清除过滤: {dataset.label}')
        except Exception as e:
            logger.error(f'清除过滤失败: {e}')
            QMessageBox.critical(self, '错误', str(e))


    def save_range_preset(self):
        dataset = self._get_active_dataset()
        if dataset is None:
            QMessageBox.information(self, '提示', '请先选择一个数据集')
            return
        dataset.set_range(self.spin_start.value(), self.spin_end.value())
        self._refresh_dataset_list()
        logger.info(f'用户操作: 保存范围预设 — {dataset.label} [{dataset.start}:{dataset.end}]')
        self.main_window.status_label.setText(
            f'已保存范围预设: {dataset.label} [{dataset.start}:{dataset.end if dataset.end > 0 else "end"}]'
        )


    def redraw_current_range_plot(self):
        dataset = self._get_active_dataset()
        if dataset is None:
            QMessageBox.information(self, '提示', '请先选择一个数据集')
            return
        dataset.set_range(self.spin_start.value(), self.spin_end.value())
        self._refresh_dataset_list()
        self.plot_data()
        logger.info(f'用户操作: 按当前范围重绘 — {dataset.label}')
        self.main_window.status_label.setText(f'已按当前范围重绘对比图: {dataset.label}')

    # ==================== 列选择管理 ====================


    def select_all_columns(self):
        for i in range(self.list_columns.count()):
            self.list_columns.item(i).setSelected(True)
        logger.debug(f'用户操作: 全选列 ({self.list_columns.count()} 个)')


    def deselect_all_columns(self):
        self.list_columns.clearSelection()
        logger.debug('用户操作: 取消全选列')


    def add_selected_to_plot(self):
        dataset = self._get_active_dataset()
        if dataset is None:
            QMessageBox.information(self, '提示', '请先加载并选择一个数据集')
            return

        selected_items = self.list_columns.selectedItems()
        if not selected_items:
            QMessageBox.information(self, '提示', '请先选择要绘制的参数列')
            return

        target_chart_id = self._get_current_plot_view_id()
        if target_chart_id is None:
            QMessageBox.information(self, '提示', '当前没有可用绘图页，请先新建图。')
            return

        start, end = dataset.get_slice_bounds()
        added = 0
        col_names_added = []

        for item in selected_items:
            col_name = item.text()
            exists = any(
                pi.col_name == col_name and
                pi.dataset_id == dataset.dataset_id and
                pi.chart_id == target_chart_id
                for pi in self.plot_items
            )
            if exists:
                continue

            pi = PlotDataItem(
                dataset_id=dataset.dataset_id,
                col_name=col_name,
                start=start,
                end=end,
                color_idx=self._color_counter,
                label=f"{dataset.label} | {col_name} [{start}:{end if end > 0 else 'end'}]",
                chart_id=target_chart_id,
            )
            self.plot_items.append(pi)
            self._color_counter += 1
            added += 1
            col_names_added.append(col_name)

        target_view = self.plot_views.get(target_chart_id)
        target_name = target_view.name if target_view is not None else f'图{target_chart_id}'
        self._update_plot_list()
        logger.info(f'用户操作: 添加绘图项 — {added} 个参数 → {target_name} | {", ".join(col_names_added)}')
        self.main_window.status_label.setText(f'已添加 {added} 个参数到 {target_name}')


    def _update_plot_list(self):
        self.list_plot_items.clear()
        self._current_plot_item_indices = []
        for i, pi in enumerate(self.plot_items):
            view = self.plot_views.get(pi.chart_id)
            view_name = view.name if view is not None else f'图{pi.chart_id}'
            text = f"[{view_name}] [{pi.color}] {pi.label}"
            item = QListWidgetItem(text)
            item.setForeground(QColor(pi.color))
            self.list_plot_items.addItem(item)
            self._current_plot_item_indices.append(i)


    def remove_selected_plot_item(self):
        selected = self.list_plot_items.currentRow()
        if selected >= 0 and selected < len(self._current_plot_item_indices):
            real_idx = self._current_plot_item_indices[selected]
            removed = self.plot_items.pop(real_idx)
            self._update_plot_list()
            logger.info(f'用户操作: 移除绘图项 — "{removed.label}"')


    def clear_all_plot_items(self):
        current_view_id = self._get_current_plot_view_id()
        if current_view_id is None:
            return
        n = len([pi for pi in self.plot_items if pi.chart_id == current_view_id])
        self.plot_items = [pi for pi in self.plot_items if pi.chart_id != current_view_id]
        self._update_plot_list()
        view = self._get_current_plot_view()
        if view is not None:
            view.canvas.axes.clear()
            view.canvas.draw()
            view.txt_stats.setText('(无数据)')
        logger.info(f'用户操作: 清空当前图绘图项 ({n} 条)')

    # ==================== 绘图功能 ====================


    def plot_data(self):
        current_view = self._get_current_plot_view()
        if current_view is None:
            return
        ax = current_view.canvas.axes
        ax.clear()
        n_items = len([pi for pi in self.plot_items if pi.chart_id == current_view.view_id])
        self._do_plot(ax, current_view)
        current_view.canvas.draw()
        logger.info(f'用户操作: 绘制图表 — {current_view.name} ({n_items} 条曲线)')
        self.main_window.status_label.setText(f'✅ 绘图完成: {current_view.name}')


    def plot_data_overlay(self):
        self.plot_data()
        current_view = self._get_current_plot_view()
        view_name = current_view.name if current_view is not None else '当前图'
        self.main_window.status_label.setText(f'✅ 已按当前对比列表重新叠加绘制: {view_name}')


    def _do_plot(self, ax, plot_view, overlay=False):
        if not overlay:
            ax.clear()

        ax.set_facecolor('white')

        stats_lines = []
        plot_items = [pi for pi in self.plot_items if pi.chart_id == plot_view.view_id]

        for pi in plot_items:
            data = pi.get_data(self.datasets)
            if data is None or len(data) == 0:
                continue

            x = np.arange(len(data))
            ax.plot(x, data, color=pi.color, linestyle=pi.linestyle,
                    linewidth=2.0, label=pi.label, antialiased=True)

            if self.chk_show_stats.isChecked():
                dataset = self.datasets.get(pi.dataset_id)
                if dataset is not None:
                    stats = pd.to_numeric(dataset.df[pi.col_name], errors='coerce').to_numpy()
                    s, e = dataset.get_slice_bounds()
                    stats = stats[s:e]
                else:
                    stats = np.array([])

                stats = stats[~np.isnan(stats)] if len(stats) > 0 else stats
                if len(stats) > 0:
                    mean_value = float(np.nanmean(stats))
                    std_value = float(np.nanstd(stats))
                    min_value = float(np.nanmin(stats))
                    max_value = float(np.nanmax(stats))
                    label = dataset.label if dataset is not None else pi.label
                    s = (f"{pi.col_name}: μ={mean_value:.4f}, σ={std_value:.4f}, "
                         f"min={min_value:.4f}, max={max_value:.4f}, N={len(stats)}")
                    stats_lines.append(f"{label} | " + s)

        if self.chk_grid.isChecked():
            ax.grid(True, linestyle='--', linewidth=0.7, alpha=0.28)

        for spine in ax.spines.values():
            spine.set_linewidth(1.0)
            spine.set_color('#334155')

        ax.tick_params(axis='both', which='major', labelsize=10, width=1.0, length=4, colors='#111827')
        ax.margins(x=0.01)

        if plot_items:
            legend = ax.legend(loc='best', fontsize=9, frameon=True, framealpha=0.95)
            legend.get_frame().set_edgecolor('#cbd5e1')
            legend.get_frame().set_linewidth(0.9)
        ax.set_xlabel('采样点 (128ms/点)', fontsize=11)
        ax.set_ylabel('数值', fontsize=11)
        ax.set_title('雷达数据曲线', fontsize=13, fontweight='bold')

        if stats_lines:
            plot_view.txt_stats.setText('\n'.join(stats_lines))
        else:
            plot_view.txt_stats.setText('(无数据)')

    # ==================== 工具操作 ====================


    def clear_overlay(self):
        current_view = self._get_current_plot_view()
        if current_view is None:
            return
        has_items = any(pi.chart_id == current_view.view_id for pi in self.plot_items)
        if has_items:
            self.plot_data()
        else:
            current_view.canvas.axes.clear()
            current_view.canvas.draw()
            current_view.txt_stats.setText('(无数据)')
        logger.info(f'用户操作: 清除叠加 — {current_view.name}')
        self.main_window.status_label.setText('已重新绘制当前对比曲线')


    def export_current_plot(self):
        current_view = self._get_current_plot_view()
        if current_view is None:
            return

        plot_items = [pi for pi in self.plot_items if pi.chart_id == current_view.view_id]
        if not plot_items:
            msg = '当前没有可导出的对比曲线，请先添加绘图项。'
            logger.warning(f'导出失败: {msg}')
            QMessageBox.information(self, '提示', msg)
            return

        filepath, selected_filter = QFileDialog.getSaveFileName(
            self, '导出高清图', '',
            'PNG 图片 (*.png);;PDF 矢量图 (*.pdf);;SVG 矢量图 (*.svg);;TIFF 图片 (*.tiff);;所有文件 (*.*)'
        )
        if not filepath:
            logger.info('用户操作: 取消导出图片')
            return

        ext = os.path.splitext(filepath)[1].lower()
        if not ext:
            if 'PDF' in selected_filter:
                filepath += '.pdf'
            elif 'SVG' in selected_filter:
                filepath += '.svg'
            elif 'TIFF' in selected_filter:
                filepath += '.tiff'
            else:
                filepath += '.png'

        self._do_plot(current_view.canvas.axes, current_view)
        current_view.canvas.figure.savefig(
            filepath, dpi=600, bbox_inches='tight',
            facecolor='white', edgecolor='none'
        )
        logger.info(f'用户操作: 导出图片 — {filepath} (格式: {os.path.splitext(filepath)[1]})')
        self.main_window.status_label.setText(f'已导出高清图: {os.path.basename(filepath)}')


    def reset_view(self):
        current_view = self._get_current_plot_view()
        if current_view is None:
            return
        current_view.canvas.axes.relim()
        current_view.canvas.axes.autoscale_view()
        current_view.canvas.draw()
        logger.info(f'用户操作: 重置视图 — {current_view.name}')
        self.main_window.status_label.setText('视图已重置')