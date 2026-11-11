#!/usr/bin/env python3
"""
数据可视化处理面板 - Data Visualization Panel
独立的 QWidget 类，封装数据加载、切片、过滤、绘图、导出等功能。
从 MainWindow 中提取为独立模块。
"""

import os
import threading

import numpy as np
import pandas as pd
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QPushButton, QFileDialog, QLabel, QSpinBox, QListWidget,
    QListWidgetItem, QGroupBox, QTextEdit,
    QCheckBox, QTabWidget, QComboBox, QLineEdit,
    QMessageBox, QAbstractItemView, QStackedWidget, QTableView,
    QDialog, QDialogButtonBox, QFormLayout,
)
from PyQt5.QtCore import QObject, Qt, QThread, pyqtSignal
from PyQt5.QtGui import QFont, QColor

from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar

from .data_loader import DataLoader
from .models import DatasetRecord, PlotDataItem, PlotViewRecord
from .plotting import (
    MatplotlibCanvas, ASPECT_PRESETS, EXPORT_WIDTH_PRESETS_CM, FIG_SIZE_PRESETS,
    apply_figure_size, compact_series_label, default_export_basename,
    resolve_figure_size, scaled_size_for_width, style_axes_legend,
)
from .ui_theme import (
    set_button_icon, style_primary_button, style_warning_button,
)
from .error_ui import handle_ui_exception
from .errors import ExportError, safe_exception_message
from .logger import get_logger
from .background_tasks import (
    ensure_task_can_start, register_background_task, task_result_is_current,
)

logger = get_logger('visualization_panel')


def _load_dataset_payload(filepath):
    col_file = DataLoader.auto_find_column_file(filepath)
    if col_file and os.path.isfile(col_file):
        col_names = DataLoader.load_column_names(col_file)
    else:
        col_names = None
        col_file = ''
    dataframe = DataLoader.load_data(
        filepath, col_names, validate_limits=False
    )
    return {
        'filepath': filepath,
        'label': os.path.basename(filepath),
        'col_file': col_file,
        'dataframe': dataframe,
    }


from PyQt5.QtCore import QAbstractTableModel, QModelIndex


class SeriesTableModel(QAbstractTableModel):
    """只读表格模型：按列持有 numpy 数组，百万行也只在可见单元格取数。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._columns = []  # list[tuple[str, np.ndarray]]
        self._row_count = 0

    def set_series(self, columns):
        """columns: [(表头, 一维数组), ...]"""
        self.beginResetModel()
        self._columns = list(columns)
        self._row_count = max((len(values) for _h, values in self._columns), default=0)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else self._row_count

    def columnCount(self, parent=QModelIndex()):
        if parent.isValid() or not self._columns:
            return 0
        return len(self._columns) + 1

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or role not in (Qt.DisplayRole, Qt.ToolTipRole):
            return None
        if index.column() == 0:
            return index.row() + 1
        values = self._columns[index.column() - 1][1]
        row = index.row()
        if row >= len(values):
            return None
        value = values[row]
        if value is None:
            return None
        try:
            if pd.isna(value):
                return None
        except (TypeError, ValueError):
            pass
        return f'{value:.6g}' if isinstance(value, float) else str(value)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return '序号' if section == 0 else self._columns[section - 1][0]
        return str(section + 1)


class DatasetLoadWorker(QObject):
    """Parse selected data files outside the Qt UI thread."""

    succeeded = pyqtSignal(dict)
    failed = pyqtSignal(object)
    cancelled = pyqtSignal(str)
    progress = pyqtSignal(int, str)

    def __init__(self, filepaths):
        super().__init__()
        self.filepaths = list(filepaths)
        self._cancel_event = threading.Event()

    def cancel(self):
        self._cancel_event.set()

    def run(self):
        results = []
        try:
            total = max(1, len(self.filepaths))
            for index, filepath in enumerate(self.filepaths):
                if self._cancel_event.is_set():
                    raise RuntimeError('数据文件加载已取消')
                self.progress.emit(
                    int(index * 100 / total),
                    f'正在加载 {os.path.basename(filepath)}',
                )
                results.append(_load_dataset_payload(filepath))
            self.progress.emit(100, '数据文件加载完成')
            self.succeeded.emit({'results': results})
        except Exception as exc:
            if self._cancel_event.is_set():
                self.cancelled.emit('数据文件加载已取消')
            else:
                self.failed.emit(exc)


class FigureExportWorker(QObject):
    """Encode a prepared Matplotlib figure outside the Qt UI thread."""

    succeeded = pyqtSignal(str)
    failed = pyqtSignal(str)
    cancelled = pyqtSignal(str)
    progress = pyqtSignal(int, str)

    def __init__(self, figure, filepath):
        super().__init__()
        self.figure = figure
        self.filepath = filepath
        self._cancel_event = threading.Event()

    def cancel(self):
        self._cancel_event.set()

    def run(self):
        try:
            if self._cancel_event.is_set():
                raise RuntimeError('高清图导出已取消')
            self.progress.emit(10, '正在编码高清图')
            self.figure.savefig(
                self.filepath,
                dpi=600,
                bbox_inches='tight',
                facecolor='white',
                edgecolor='none',
            )
            if self._cancel_event.is_set():
                raise RuntimeError('高清图导出已取消')
            self.progress.emit(100, '高清图导出完成')
            self.succeeded.emit(self.filepath)
        except Exception as exc:
            if self._cancel_event.is_set():
                self.cancelled.emit('高清图导出已取消')
            else:
                self.failed.emit(safe_exception_message(exc))


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
        self._dataset_load_thread = None
        self._dataset_load_worker = None
        self._export_thread = None
        self._export_worker = None
        self._load_task_name = ''
        self._load_task_version = 0
        self._export_task_name = ''
        self._export_task_version = 0

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

        # 左侧数据管理面板保证底限宽度，不被右侧绘图区挤占
        left_widget.setMinimumWidth(420)
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, False)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        splitter.setSizes([620, 1500])
        layout.addWidget(splitter, 1)

        self._relax_minimum_widths()

    def _relax_minimum_widths(self):
        """把控件最小尺寸压到上限以下，窗口缩小时布局可压缩而不是整窗被撑大。

        只下调（不抬高）显式最小尺寸；控件的首选尺寸不变，正常窗口下外观不受影响。
        """
        from PyQt5.QtWidgets import (
            QAbstractButton, QAbstractSpinBox, QComboBox, QLineEdit,
            QAbstractItemView, QTextEdit,
        )
        width_caps = (
            (QAbstractButton, 84),
            (QComboBox, 96),
            (QAbstractSpinBox, 72),
            (QLineEdit, 80),
        )
        for widget_class, cap in width_caps:
            for widget in self.findChildren(widget_class):
                if widget.minimumSizeHint().width() > cap:
                    widget.setMinimumWidth(cap)
        for widget_class in (QAbstractItemView, QTextEdit):
            for widget in self.findChildren(widget_class):
                if widget.minimumSizeHint().height() > 80:
                    widget.setMinimumHeight(80)



    def _create_top_controls(self):
        group = QGroupBox('数据控制')
        outer = QVBoxLayout(group)
        row1 = QHBoxLayout()
        row2 = QHBoxLayout()

        self.btn_load = QPushButton('📂 加载数据文件(可多选)')
        self.btn_load.clicked.connect(self.load_data_file)
        set_button_icon(self.btn_load, 'open')
        style_primary_button(self.btn_load)
        row1.addWidget(self.btn_load)

        self.btn_load_col = QPushButton('📄 加载列名文件')
        self.btn_load_col.clicked.connect(self.load_column_file)
        set_button_icon(self.btn_load_col, 'file')
        row1.addWidget(self.btn_load_col)

        self.btn_remove_dataset = QPushButton('🗑️ 移除当前数据集')
        self.btn_remove_dataset.clicked.connect(self.remove_active_dataset)
        set_button_icon(self.btn_remove_dataset, 'delete')
        style_warning_button(self.btn_remove_dataset)
        row1.addWidget(self.btn_remove_dataset)

        self.btn_clear_datasets = QPushButton('🧹 清空全部数据集')
        self.btn_clear_datasets.clicked.connect(self.clear_all_datasets)
        set_button_icon(self.btn_clear_datasets, 'delete')
        style_warning_button(self.btn_clear_datasets)
        row1.addWidget(self.btn_clear_datasets)

        row1.addWidget(QLabel('  数据文件:'))
        self.lbl_data_file = QLabel('未加载')
        self.lbl_data_file.setStyleSheet('color: gray;')
        row1.addWidget(self.lbl_data_file, 1)

        row2.addStretch()

        self.btn_clear_overlay = QPushButton('🗑️ 清除叠加')
        self.btn_clear_overlay.clicked.connect(self.clear_overlay)
        set_button_icon(self.btn_clear_overlay, 'clear')
        row2.addWidget(self.btn_clear_overlay)

        self.btn_export = QPushButton('⬇ 导出高清图')
        self.btn_export.clicked.connect(self.export_current_plot)
        set_button_icon(self.btn_export, 'save')
        style_primary_button(self.btn_export)
        row2.addWidget(self.btn_export)

        self.btn_reset = QPushButton('🔄 重置')
        self.btn_reset.clicked.connect(self.reset_view)
        set_button_icon(self.btn_reset, 'reload')
        row2.addWidget(self.btn_reset)

        outer.addLayout(row1)
        outer.addLayout(row2)
        return group


    def _create_left_panel(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

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
        dataset_btn_layout.addStretch()
        dataset_layout.addLayout(dataset_btn_layout)

        layout.addWidget(dataset_group, 1)

        # ===== 范围选择 =====
        range_group = QGroupBox('数据范围 (采样点索引)')
        range_outer = QVBoxLayout(range_group)
        range_row1 = QHBoxLayout()
        range_row2 = QHBoxLayout()

        range_row1.addWidget(QLabel('起始:'))
        self.spin_start = QSpinBox()
        self.spin_start.setRange(0, 999999)
        self.spin_start.setValue(0)
        self.spin_start.valueChanged.connect(self.on_range_changed)
        range_row1.addWidget(self.spin_start)

        range_row1.addWidget(QLabel('结束:'))
        self.spin_end = QSpinBox()
        self.spin_end.setRange(0, 999999)
        self.spin_end.setValue(0)
        self.spin_end.setSpecialValueText('末尾')
        self.spin_end.valueChanged.connect(self.on_range_changed)
        range_row1.addWidget(self.spin_end)

        range_row1.addWidget(QLabel('  总行数:'))
        self.lbl_total_rows = QLabel('0')
        range_row1.addWidget(self.lbl_total_rows)
        range_row1.addStretch()

        self.btn_save_range = QPushButton('保存范围预设')
        self.btn_save_range.clicked.connect(self.save_range_preset)
        set_button_icon(self.btn_save_range, 'save')
        range_row2.addWidget(self.btn_save_range)

        self.btn_refresh_plot = QPushButton('按当前范围重绘对比图')
        self.btn_refresh_plot.clicked.connect(self.redraw_current_range_plot)
        set_button_icon(self.btn_refresh_plot, 'refresh')
        style_primary_button(self.btn_refresh_plot)
        range_row2.addWidget(self.btn_refresh_plot)
        range_row2.addStretch()

        range_outer.addLayout(range_row1)
        range_outer.addLayout(range_row2)

        layout.addWidget(range_group)

        # ===== 数据过滤 =====
        filter_group = QGroupBox('数据过滤 (按值筛选行)')
        filter_outer = QVBoxLayout(filter_group)
        filter_row1 = QHBoxLayout()
        filter_row2 = QHBoxLayout()

        filter_row1.addWidget(QLabel('列:'))
        self.combo_filter_col = QComboBox()
        self.combo_filter_col.setMinimumWidth(120)
        self.combo_filter_col.currentIndexChanged.connect(self.on_filter_col_changed)
        filter_row1.addWidget(self.combo_filter_col)

        filter_row1.addWidget(QLabel('最小值:'))
        self.edit_filter_min = QLineEdit()
        self.edit_filter_min.setPlaceholderText('不限制')
        self.edit_filter_min.setMaximumWidth(110)
        filter_row1.addWidget(self.edit_filter_min)

        filter_row1.addWidget(QLabel('最大值:'))
        self.edit_filter_max = QLineEdit()
        self.edit_filter_max.setPlaceholderText('不限制')
        self.edit_filter_max.setMaximumWidth(110)
        filter_row1.addWidget(self.edit_filter_max)
        filter_row1.addStretch()

        self.btn_apply_filter = QPushButton('应用过滤')
        self.btn_apply_filter.clicked.connect(self.apply_filter)
        set_button_icon(self.btn_apply_filter, 'apply')
        filter_row2.addWidget(self.btn_apply_filter)

        self.btn_clear_filter = QPushButton('清除过滤')
        self.btn_clear_filter.clicked.connect(self.clear_filter)
        set_button_icon(self.btn_clear_filter, 'clear')
        filter_row2.addWidget(self.btn_clear_filter)
        filter_row2.addStretch()

        filter_outer.addLayout(filter_row1)
        filter_outer.addLayout(filter_row2)

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
        select_btn_layout.addStretch()

        # 绑定目标提示（曲线始终绑定到当前页签图，轻量标签不占整行）
        self.lbl_plot_target = QLabel('绘制到: 图1')
        self.lbl_plot_target.setStyleSheet('color: #64748b;')
        self.lbl_plot_target.setToolTip('添加的曲线始终绑定到当前页签图')
        select_btn_layout.addWidget(self.lbl_plot_target)
        select_layout.addLayout(select_btn_layout)

        self.list_columns = QListWidget()
        self.list_columns.setSelectionMode(QAbstractItemView.MultiSelection)
        select_layout.addWidget(self.list_columns)

        layout.addWidget(select_group, 2)

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
        btn_remove_layout.addStretch()

        plotlist_layout.addLayout(btn_remove_layout)

        layout.addWidget(plotlist_group, 1)

        return widget


    def _create_right_panel(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # 多图页签
        self.plot_tabs = QTabWidget()
        self.plot_tabs.setMovable(True)
        self.plot_tabs.currentChanged.connect(self.on_plot_tab_changed)
        layout.addWidget(self.plot_tabs, 1)

        # 绘图控制（两行布局，避免控件最小宽度把窗口横向撑大）
        ctrl_group = QGroupBox('绘图控制')
        ctrl_outer = QVBoxLayout(ctrl_group)
        ctrl_row1 = QHBoxLayout()
        ctrl_row2 = QHBoxLayout()

        self.btn_new_plot = QPushButton('🆕 新建图')
        self.btn_new_plot.clicked.connect(self.create_new_plot_view)
        set_button_icon(self.btn_new_plot, 'file')
        ctrl_row1.addWidget(self.btn_new_plot)

        self.btn_remove_plot = QPushButton('🗑 删除当前图')
        self.btn_remove_plot.clicked.connect(self.remove_current_plot_view)
        set_button_icon(self.btn_remove_plot, 'delete')
        style_warning_button(self.btn_remove_plot)
        ctrl_row1.addWidget(self.btn_remove_plot)

        self.btn_plot = QPushButton('📊 绘制')
        self.btn_plot.clicked.connect(self.plot_data)
        self.btn_plot.setStyleSheet('background-color: #2196F3; color: white; font-weight: bold; padding: 8px;')
        set_button_icon(self.btn_plot, 'play')
        style_primary_button(self.btn_plot)
        ctrl_row1.addWidget(self.btn_plot)

        self.btn_overlay = QPushButton('➕ 叠加绘制 (保持上一幅)')
        self.btn_overlay.clicked.connect(self.plot_data_overlay)
        self.btn_overlay.setStyleSheet('background-color: #FF9800; color: white; font-weight: bold;')
        set_button_icon(self.btn_overlay, 'refresh')
        style_warning_button(self.btn_overlay)
        ctrl_row1.addWidget(self.btn_overlay)

        self.chk_show_stats = QCheckBox('显示统计信息')
        self.chk_show_stats.setChecked(True)
        ctrl_row2.addWidget(self.chk_show_stats)

        self.chk_grid = QCheckBox('网格')
        self.chk_grid.setChecked(True)
        ctrl_row2.addWidget(self.chk_grid)

        ctrl_row2.addWidget(QLabel('显示:'))
        self.combo_display_mode = QComboBox()
        self.combo_display_mode.addItems(['绘图', '表格'])
        self.combo_display_mode.setToolTip('同一数据可在曲线图与数据表格之间切换')
        self.combo_display_mode.currentIndexChanged.connect(self.on_display_mode_changed)
        ctrl_row2.addWidget(self.combo_display_mode)

        ctrl_row2.addWidget(QLabel('图片尺寸:'))
        self.combo_fig_size = QComboBox()
        self.combo_fig_size.addItems(list(FIG_SIZE_PRESETS))
        self.combo_fig_size.setToolTip('绘图区尺寸预设')
        self.combo_fig_size.currentIndexChanged.connect(self.on_figure_format_changed)
        ctrl_row2.addWidget(self.combo_fig_size)

        ctrl_row2.addWidget(QLabel('比例:'))
        self.combo_aspect = QComboBox()
        self.combo_aspect.addItems(list(ASPECT_PRESETS))
        self.combo_aspect.setToolTip('绘图区纵横比')
        self.combo_aspect.currentIndexChanged.connect(self.on_figure_format_changed)
        ctrl_row2.addWidget(self.combo_aspect)

        ctrl_row2.addStretch()

        ctrl_outer.addLayout(ctrl_row1)
        ctrl_outer.addLayout(ctrl_row2)
        layout.addWidget(ctrl_group)

        # 默认创建第1张图
        self._create_plot_view(name='图1', set_active=True)
        self._refresh_plot_target_indicator()

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

        # 绘图 / 表格 双视图（表格使用轻量模型，大数据量不卡顿）
        display_stack = QStackedWidget()
        display_stack.addWidget(canvas)
        table_model = SeriesTableModel(self)
        table_view = QTableView()
        table_view.setModel(table_model)
        table_view.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table_view.verticalHeader().setDefaultSectionSize(22)
        display_stack.addWidget(table_view)

        tab_layout.addWidget(toolbar)
        tab_layout.addWidget(display_stack, 1)
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
            display_stack=display_stack,
            table_view=table_view,
            table_model=table_model,
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


    def _refresh_plot_target_indicator(self):
        if not hasattr(self, 'lbl_plot_target'):
            return
        current_view_id = self._get_current_plot_view_id()
        view = self.plot_views.get(current_view_id) if current_view_id is not None else None
        name = view.name if view is not None else '—'
        self.lbl_plot_target.setText(f'绘制到: {name}')


    def on_plot_tab_changed(self, idx):
        view_id = self._get_current_plot_view_id()
        view = self.plot_views.get(view_id)
        view_name = view.name if view else '未知'
        logger.debug(f'切换绘图页签: {view_name} (index={idx})')
        self._refresh_plot_target_indicator()
        self._update_plot_list()
        if view is not None and view.display_stack is not None:
            mode_idx = self.combo_display_mode.currentIndex() if hasattr(self, 'combo_display_mode') else 0
            view.display_stack.setCurrentIndex(mode_idx)

    def on_display_mode_changed(self, idx):
        view = self._get_current_plot_view()
        if view is None or view.display_stack is None:
            return
        view.display_stack.setCurrentIndex(idx)
        if idx == 1:
            self._update_table_view(view)
        self.main_window.status_label.setText(
            '已切换为表格显示' if idx == 1 else '已切换为绘图显示')

    def on_figure_format_changed(self, _idx=None):
        view = self._get_current_plot_view()
        if view is None:
            return
        preset = self.combo_fig_size.currentText()
        aspect = self.combo_aspect.currentText()
        apply_figure_size(view.canvas.figure, preset, aspect)
        view.canvas.figure.tight_layout(pad=1.2)
        view.canvas.draw()
        self.main_window.status_label.setText(f'图片尺寸: {preset} / 比例: {aspect}')

    def _update_table_view(self, view):
        """把当前图的绘图项数据刷新到表格模型（仅引用数组，不复制）。"""
        if view is None or view.table_model is None:
            return
        columns = []
        for pi in self.plot_items:
            if pi.chart_id != view.view_id:
                continue
            data = pi.get_data(self.datasets)
            if data is None:
                continue
            columns.append((pi.label, data))
        view.table_model.set_series(columns)


    def create_new_plot_view(self):
        view_id = self._create_plot_view(set_active=True)
        self._refresh_plot_target_indicator()
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

        self._refresh_plot_target_indicator()
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
        if self._dataset_load_thread is not None:
            self.main_window.status_label.setText('已有数据加载任务正在后台运行')
            return
        logger.info(f'用户操作: 开始加载数据文件，共 {len(filepaths)} 个')
        task_name = f'数据文件加载（{len(filepaths)} 个）'
        ensure_task_can_start(self, task_name)
        self._load_task_name = task_name
        self.btn_load.setEnabled(False)
        thread = QThread(self)
        worker = DatasetLoadWorker(filepaths)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.succeeded.connect(self._on_dataset_load_succeeded)
        worker.failed.connect(self._on_dataset_load_failed)
        worker.cancelled.connect(self._on_dataset_load_cancelled)
        worker.succeeded.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.cancelled.connect(thread.quit)
        worker.succeeded.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        worker.cancelled.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._on_dataset_load_thread_finished)
        self._dataset_load_thread = thread
        self._dataset_load_worker = worker
        self._load_task_version = register_background_task(
            self,
            task_name,
            thread,
            worker,
            worker.cancel,
        )
        thread.start()

    def _on_dataset_load_succeeded(self, payload):
        if not task_result_is_current(
            self, self._load_task_name, self._load_task_version
        ):
            return
        loaded_ids = [
            self._register_loaded_dataset(item, refresh=False)
            for item in payload['results']
        ]
        if self.active_dataset_id is None and loaded_ids:
            self.set_active_dataset(loaded_ids[0])
        elif loaded_ids:
            self._refresh_dataset_list()
        if loaded_ids:
            msg = f'已加载 {len(loaded_ids)} 个数据集'
            logger.info(f'加载完成: {msg}')
            self.main_window.status_label.setText(msg)

    def _on_dataset_load_failed(self, exc):
        if not task_result_is_current(
            self, self._load_task_name, self._load_task_version
        ):
            return
        handle_ui_exception(self, logger, '加载数据文件', exc)

    def _on_dataset_load_cancelled(self, message):
        if not task_result_is_current(
            self, self._load_task_name, self._load_task_version
        ):
            return
        logger.info(message)
        self.main_window.status_label.setText(message)

    def _on_dataset_load_thread_finished(self):
        self._dataset_load_worker = None
        self._dataset_load_thread = None
        self.btn_load.setEnabled(True)


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
            logger.error(f'列名文件加载失败: {filepath} — {safe_exception_message(e)}')
            handle_ui_exception(self, logger, '加载列名文件', e)
            return

        active = self._get_active_dataset()
        if active is None:
            logger.warning('加载列名文件失败: 当前无数据集')
            QMessageBox.information(self, '提示', '请先加载一个数据文件，再单独加载列名文件。')
            return

        try:
            renamed = active.original_df.copy(deep=False)
            renamed.columns = DataLoader.normalize_column_names(
                col_names, renamed.shape[1]
            )
            active.col_filepath = filepath
            old_start, old_end = active.get_slice_bounds()
            active.df = renamed
            active.original_df = renamed
            active.set_range(old_start, old_end)
            self.set_active_dataset(active.dataset_id)
            logger.info(f'列名已应用到数据集: {active.label} → shape={active.df.shape}')
            self.main_window.status_label.setText(f'已为当前数据集加载列名文件: {os.path.basename(filepath)}')
        except Exception as e:
            logger.error(f'应用列名失败: {safe_exception_message(e)}')
            handle_ui_exception(self, logger, '应用列名文件', e)


    def _load_single_dataset(self, filepath):
        return self._register_loaded_dataset(_load_dataset_payload(filepath))

    def _register_loaded_dataset(self, payload, refresh=True):
        df = payload['dataframe']
        dataset_id = self._dataset_counter
        self._dataset_counter += 1

        record = DatasetRecord(
            dataset_id=dataset_id,
            label=payload['label'],
            data_filepath=payload['filepath'],
            col_filepath=payload['col_file'],
            df=df,
            original_df=df,
            start=0,
            end=len(df),
        )
        self.datasets[dataset_id] = record
        if refresh:
            self._refresh_dataset_list()
        logger.debug(
            f'数据集已注册: id={dataset_id}, '
            f'file={payload["label"]}, shape={df.shape}'
        )
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
            dataset.df = DataLoader.load_data(
                dataset.data_filepath, col_names, validate_limits=False
            )
            dataset.original_df = dataset.df
            dataset.set_range(old_start, old_end)
            self.set_active_dataset(dataset.dataset_id)
            logger.info(f'重载成功: {dataset.label}, shape={dataset.df.shape}')
            self.main_window.status_label.setText(f'已重载: {dataset.label}')
        except Exception as e:
            logger.error(f'重载失败: {safe_exception_message(e)}')
            handle_ui_exception(self, logger, '重载数据', e)


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
            logger.error(f'过滤失败: {safe_exception_message(e)}')
            handle_ui_exception(self, logger, '过滤数据', e)


    def clear_filter(self):
        dataset = self._get_active_dataset()
        if dataset is None:
            return
        self.edit_filter_min.clear()
        self.edit_filter_max.clear()
        try:
            old_start, old_end = dataset.get_slice_bounds()
            dataset.df = dataset.original_df
            dataset.set_range(old_start, old_end)
            self.set_active_dataset(dataset.dataset_id)
            logger.info(f'用户操作: 清除过滤 — {dataset.label}')
            self.main_window.status_label.setText(f'已清除过滤: {dataset.label}')
        except Exception as e:
            logger.error(f'清除过滤失败: {safe_exception_message(e)}')
            handle_ui_exception(self, logger, '清除过滤', e)


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
            item = self.list_columns.item(i)
            item.setCheckState(Qt.Checked)
            item.setSelected(True)
        logger.debug(f'用户操作: 全选列 ({self.list_columns.count()} 个)')


    def deselect_all_columns(self):
        for i in range(self.list_columns.count()):
            self.list_columns.item(i).setCheckState(Qt.Unchecked)
        self.list_columns.clearSelection()
        logger.debug('用户操作: 取消全选列')


    def add_selected_to_plot(self):
        dataset = self._get_active_dataset()
        if dataset is None:
            QMessageBox.information(self, '提示', '请先加载并选择一个数据集')
            return

        checked_items = [
            self.list_columns.item(i)
            for i in range(self.list_columns.count())
            if self.list_columns.item(i).checkState() == Qt.Checked
        ]
        selected_items = self.list_columns.selectedItems()
        candidate_items = list(checked_items)
        candidate_items.extend(
            item for item in selected_items if item not in checked_items
        )
        if not candidate_items:
            QMessageBox.information(self, '提示', '请先选择要绘制的参数列')
            return

        target_chart_id = self._get_current_plot_view_id()
        if target_chart_id is None:
            QMessageBox.information(self, '提示', '当前没有可用绘图页，请先新建图。')
            return

        start, end = dataset.get_slice_bounds()
        added = 0
        col_names_added = []

        for item in candidate_items:
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
                label=compact_series_label(dataset.label, col_name),
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
        self._update_table_view(current_view)
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
            style_axes_legend(ax)
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

        # 默认文件名：数据文件名 + 字段名
        first_dataset = self.datasets.get(plot_items[0].dataset_id)
        file_label = first_dataset.label if first_dataset is not None else 'plot'
        default_name = default_export_basename(file_label, [pi.col_name for pi in plot_items])

        filepath, selected_filter = QFileDialog.getSaveFileName(
            self, '导出高清图', f'{default_name}.png',
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

        # 导出尺寸选项（相对当前绘图尺寸等比缩放，保持纵横比）
        target_width_cm = None
        size_dialog = QDialog(self)
        size_dialog.setWindowTitle('导出尺寸')
        size_form = QFormLayout(size_dialog)
        combo_export_size = QComboBox()
        combo_export_size.addItems(list(EXPORT_WIDTH_PRESETS_CM))
        combo_export_size.setToolTip('按目标宽度导出，高度自动等比缩放')
        size_form.addRow('图片宽度:', combo_export_size)
        size_buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        size_buttons.accepted.connect(size_dialog.accept)
        size_buttons.rejected.connect(size_dialog.reject)
        size_form.addRow(size_buttons)
        if size_dialog.exec_() != QDialog.Accepted:
            logger.info('用户操作: 取消导出图片（尺寸选择）')
            return
        target_width_cm = EXPORT_WIDTH_PRESETS_CM.get(combo_export_size.currentText())

        if self._export_thread is not None:
            self.main_window.status_label.setText('已有图片导出任务正在后台运行')
            return
        export_task_name = f'高清图导出：{os.path.basename(filepath)}'
        ensure_task_can_start(self, export_task_name)
        self._export_task_name = export_task_name
        try:
            self._do_plot(current_view.canvas.axes, current_view)
        except (OSError, ValueError, TypeError) as exc:
            handle_ui_exception(
                self,
                logger,
                '导出图片',
                ExportError('图片导出失败，请检查目录权限和磁盘空间'),
            )
            return
        except Exception as exc:
            handle_ui_exception(self, logger, '导出图片', exc)
            return

        # 按导出尺寸临时缩放（保持纵横比），导出结束后恢复绘图区尺寸
        self._export_restore_figsize = current_view.canvas.figure.get_size_inches()
        if target_width_cm:
            new_size = scaled_size_for_width(current_view.canvas.figure, target_width_cm)
            current_view.canvas.figure.set_size_inches(new_size, forward=True)
            current_view.canvas.figure.tight_layout(pad=1.2)
            current_view.canvas.draw()

        thread = QThread(self)
        worker = FigureExportWorker(current_view.canvas.figure, filepath)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.succeeded.connect(self._on_plot_export_succeeded)
        worker.failed.connect(self._on_plot_export_failed)
        worker.cancelled.connect(self._on_plot_export_cancelled)
        worker.succeeded.connect(thread.quit)
        worker.failed.connect(thread.quit)
        worker.cancelled.connect(thread.quit)
        worker.succeeded.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        worker.cancelled.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._on_plot_export_thread_finished)
        self._export_thread = thread
        self._export_worker = worker
        self.btn_export.setEnabled(False)
        self._export_task_version = register_background_task(
            self,
            export_task_name,
            thread,
            worker,
            worker.cancel,
        )
        thread.start()

    def _on_plot_export_succeeded(self, filepath):
        if not task_result_is_current(
            self, self._export_task_name, self._export_task_version
        ):
            return
        logger.info(
            '用户操作: 导出图片 — %s (格式: %s)',
            os.path.basename(filepath),
            os.path.splitext(filepath)[1],
        )
        self.main_window.status_label.setText(
            f'已导出高清图: {os.path.basename(filepath)}'
        )

    def _on_plot_export_failed(self, message):
        if not task_result_is_current(
            self, self._export_task_name, self._export_task_version
        ):
            return
        handle_ui_exception(
            self, logger, '导出图片', ExportError(message)
        )

    def _on_plot_export_cancelled(self, message):
        if not task_result_is_current(
            self, self._export_task_name, self._export_task_version
        ):
            return
        logger.info(message)
        self.main_window.status_label.setText(message)

    def _on_plot_export_thread_finished(self):
        restore_size = getattr(self, '_export_restore_figsize', None)
        if restore_size is not None:
            current_view = self._get_current_plot_view()
            if current_view is not None:
                current_view.canvas.figure.set_size_inches(restore_size, forward=True)
                current_view.canvas.figure.tight_layout(pad=1.2)
                current_view.canvas.draw()
            self._export_restore_figsize = None
        self._export_worker = None
        self._export_thread = None
        self.btn_export.setEnabled(True)


    def reset_view(self):
        current_view = self._get_current_plot_view()
        if current_view is None:
            return
        current_view.canvas.axes.relim()
        current_view.canvas.axes.autoscale_view()
        current_view.canvas.draw()
        logger.info(f'用户操作: 重置视图 — {current_view.name}')
        self.main_window.status_label.setText('视图已重置')
