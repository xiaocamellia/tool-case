"""Direction-finding calibration panel with reusable batch parameter profiles."""

from __future__ import annotations

import copy
import datetime as dt
import json
import os

import numpy as np
import pandas as pd
from PyQt5.QtCore import QObject, QThread, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from matplotlib.backends.backend_qt5agg import (
    FigureCanvasQTAgg as FigureCanvas,
    NavigationToolbar2QT as NavigationToolbar,
)
from matplotlib.figure import Figure

from .calibration_batch_store import (
    DEFAULT_FIXED_PARAMS,
    DEFAULT_INIT_PARAMS,
    CalibrationBatchStore,
)
from .calibration_data_loader import load_calibration_data
from .calibration_optimizer import run_calibration
from .logger import get_logger
from .ui_theme import style_primary_button, style_warning_button

logger = get_logger('calibration_panel')


class CalibrationWorker(QObject):
    """Run numerical calibration outside the Qt UI thread."""

    finished = pyqtSignal(dict)
    failed = pyqtSignal(str)

    def __init__(self, data, fixed_params, init_params, max_iterations):
        super().__init__()
        self.data = data
        self.fixed_params = fixed_params
        self.init_params = init_params
        self.max_iterations = max_iterations

    def run(self):
        try:
            result = run_calibration(
                self.data,
                self.fixed_params,
                self.init_params,
                max_iterations=self.max_iterations,
            )
            self.finished.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))


class CalibrationPanel(QWidget):
    """Automate direction-finding calibration for one measurement batch."""

    METRICS = (
        ('mean', '均值'),
        ('std', '标准差'),
        ('rmse', 'RMSE'),
        ('max_abs', '最大绝对误差'),
    )

    def __init__(self, parent=None, batch_store=None):
        super().__init__(parent)
        self.batch_store = batch_store or CalibrationBatchStore()
        self.current_profile_id = None
        self.calibration_data = None
        self.result = None
        self._loaded_data_path = ''
        self._profile_dirty = False
        self._loading_profile = False
        self._last_profile_index = 0
        self._calibration_thread = None
        self._calibration_worker = None
        self._run_context = None

        self._init_ui()
        self._connect_dirty_signals()
        self._refresh_profile_combo()
        profiles = self.batch_store.list_profiles()
        if profiles:
            self._select_profile_by_id(profiles[0]['id'])
        else:
            self._new_profile(confirm=False)
        logger.info('测向校正自动化面板已创建')

    @staticmethod
    def _make_double_spin(value, minimum=-1e9, maximum=1e9, decimals=6):
        control = QDoubleSpinBox()
        control.setRange(minimum, maximum)
        control.setDecimals(decimals)
        control.setValue(value)
        control.setKeyboardTracking(False)
        control.setSingleStep(0.1)
        return control

    def _init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)

        toolbar = QHBoxLayout()
        title = QLabel('测向校正自动化')
        title.setStyleSheet('font-size: 18px; font-weight: bold; color: #172033;')
        toolbar.addWidget(title)
        toolbar.addStretch()

        self.btn_run = QPushButton('开始校正')
        self.btn_run.clicked.connect(self._start_calibration)
        style_primary_button(self.btn_run)
        toolbar.addWidget(self.btn_run)

        self.btn_copy = QPushButton('复制参数')
        self.btn_copy.clicked.connect(self._copy_result_parameters)
        self.btn_copy.setEnabled(False)
        toolbar.addWidget(self.btn_copy)

        self.btn_apply_result = QPushButton('应用为初值')
        self.btn_apply_result.clicked.connect(self._apply_result_as_initial)
        self.btn_apply_result.setEnabled(False)
        toolbar.addWidget(self.btn_apply_result)

        self.btn_export = QPushButton('导出结果')
        self.btn_export.clicked.connect(self._export_result)
        self.btn_export.setEnabled(False)
        toolbar.addWidget(self.btn_export)
        root.addLayout(toolbar)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._create_parameter_area())
        splitter.addWidget(self._create_result_area())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([430, 950])
        root.addWidget(splitter, 1)

    def _create_parameter_area(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setMinimumWidth(390)
        scroll.setMaximumWidth(540)
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(4, 4, 8, 4)

        profile_group = QGroupBox('批次参数库')
        profile_layout = QGridLayout(profile_group)
        profile_layout.addWidget(QLabel('已保存配置:'), 0, 0)
        self.profile_combo = QComboBox()
        self.profile_combo.currentIndexChanged.connect(self._on_profile_changed)
        profile_layout.addWidget(self.profile_combo, 0, 1, 1, 3)

        self.btn_new_profile = QPushButton('新建')
        self.btn_new_profile.clicked.connect(self._new_profile)
        profile_layout.addWidget(self.btn_new_profile, 1, 0)
        self.btn_save_profile = QPushButton('保存修改')
        self.btn_save_profile.clicked.connect(self._save_profile)
        style_primary_button(self.btn_save_profile)
        profile_layout.addWidget(self.btn_save_profile, 1, 1)
        self.btn_save_as = QPushButton('另存为')
        self.btn_save_as.clicked.connect(self._save_profile_as)
        profile_layout.addWidget(self.btn_save_as, 1, 2)
        self.btn_delete_profile = QPushButton('删除')
        self.btn_delete_profile.clicked.connect(self._delete_profile)
        style_warning_button(self.btn_delete_profile)
        profile_layout.addWidget(self.btn_delete_profile, 1, 3)

        profile_layout.addWidget(QLabel('批次名称:'), 2, 0)
        self.edit_profile_name = QLineEdit()
        self.edit_profile_name.setPlaceholderText('例如：2026-08 暗室 A01')
        profile_layout.addWidget(self.edit_profile_name, 2, 1, 1, 3)
        self.lbl_profile_status = QLabel('')
        self.lbl_profile_status.setWordWrap(True)
        profile_layout.addWidget(self.lbl_profile_status, 3, 0, 1, 4)
        layout.addWidget(profile_group)

        data_group = QGroupBox('标定数据')
        data_layout = QGridLayout(data_group)
        self.edit_data_path = QLineEdit()
        self.edit_data_path.setPlaceholderText('Excel / CSV 文件路径')
        data_layout.addWidget(self.edit_data_path, 0, 0)
        self.btn_browse = QPushButton('浏览')
        self.btn_browse.clicked.connect(self._browse_data_file)
        data_layout.addWidget(self.btn_browse, 0, 1)
        self.lbl_data_status = QLabel('未加载数据')
        self.lbl_data_status.setWordWrap(True)
        self.lbl_data_status.setStyleSheet('color: #64748b;')
        data_layout.addWidget(self.lbl_data_status, 1, 0, 1, 2)
        layout.addWidget(data_group)

        fixed_group = QGroupBox('固定参数（当前批次）')
        fixed_layout = QGridLayout(fixed_group)
        self.spin_rho = self._make_double_spin(DEFAULT_FIXED_PARAMS['rho_obj'], 0.001)
        self.spin_xx = self._make_double_spin(DEFAULT_FIXED_PARAMS['xx_r4'])
        self.spin_bs14 = self._make_double_spin(DEFAULT_FIXED_PARAMS['BS14'])
        self.spin_bs24 = self._make_double_spin(DEFAULT_FIXED_PARAMS['BS24'])
        self.spin_bs34 = self._make_double_spin(DEFAULT_FIXED_PARAMS['BS34'])
        fixed_layout.addWidget(QLabel('rho_obj (mm):'), 0, 0)
        fixed_layout.addWidget(self.spin_rho, 0, 1)
        fixed_layout.addWidget(QLabel('xx_r4 (mm):'), 1, 0)
        fixed_layout.addWidget(self.spin_xx, 1, 1)
        fixed_layout.addWidget(QLabel('BS14 (mm):'), 2, 0)
        fixed_layout.addWidget(self.spin_bs14, 2, 1)
        fixed_layout.addWidget(QLabel('BS24 (mm):'), 3, 0)
        fixed_layout.addWidget(self.spin_bs24, 3, 1)
        fixed_layout.addWidget(QLabel('BS34 (mm):'), 4, 0)
        fixed_layout.addWidget(self.spin_bs34, 4, 1)
        fixed_layout.addWidget(QLabel('matrixZT2ANT:'), 5, 0, 1, 2)

        self.matrix_table = QTableWidget(3, 3)
        self.matrix_table.setHorizontalHeaderLabels(['X', 'Y', 'Z'])
        self.matrix_table.setVerticalHeaderLabels(['X', 'Y', 'Z'])
        self.matrix_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.matrix_table.verticalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.matrix_table.setFixedHeight(128)
        fixed_layout.addWidget(self.matrix_table, 6, 0, 1, 2)
        layout.addWidget(fixed_group)

        init_group = QGroupBox('优化设置')
        init_layout = QGridLayout(init_group)
        self.spin_yy = self._make_double_spin(DEFAULT_INIT_PARAMS['yy_r4_ZT'])
        self.spin_zz = self._make_double_spin(DEFAULT_INIT_PARAMS['zz_r4_ZT'])
        self.spin_max_iterations = QSpinBox()
        self.spin_max_iterations.setRange(50, 100000)
        self.spin_max_iterations.setValue(1000)
        init_layout.addWidget(QLabel('yy_r4_ZT 初值:'), 0, 0)
        init_layout.addWidget(self.spin_yy, 0, 1)
        init_layout.addWidget(QLabel('zz_r4_ZT 初值:'), 1, 0)
        init_layout.addWidget(self.spin_zz, 1, 1)
        init_layout.addWidget(QLabel('最大迭代次数:'), 2, 0)
        init_layout.addWidget(self.spin_max_iterations, 2, 1)
        layout.addWidget(init_group)

        notes_group = QGroupBox('批次备注')
        notes_layout = QVBoxLayout(notes_group)
        self.edit_notes = QTextEdit()
        self.edit_notes.setPlaceholderText('试验位置、设备状态、装调变更等')
        self.edit_notes.setMaximumHeight(82)
        notes_layout.addWidget(self.edit_notes)
        layout.addWidget(notes_group)
        layout.addStretch()

        scroll.setWidget(container)
        return scroll

    def _create_result_area(self):
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(8, 4, 4, 4)

        summary_layout = QHBoxLayout()
        self.lbl_yy_result = self._create_summary_box(summary_layout, 'yy_r4_ZT', '--', '#2563eb')
        self.lbl_zz_result = self._create_summary_box(summary_layout, 'zz_r4_ZT', '--', '#0f766e')
        self.lbl_cost_result = self._create_summary_box(summary_layout, '成本下降', '--', '#b45309')
        layout.addLayout(summary_layout)

        self.result_tabs = QTabWidget()
        plot_page = QWidget()
        plot_layout = QVBoxLayout(plot_page)
        plot_layout.setContentsMargins(2, 2, 2, 2)
        self.figure = Figure(figsize=(9, 6), dpi=100)
        self.canvas = FigureCanvas(self.figure)
        self.nav_toolbar = NavigationToolbar(self.canvas, plot_page)
        plot_layout.addWidget(self.nav_toolbar)
        plot_layout.addWidget(self.canvas, 1)
        self.result_tabs.addTab(plot_page, '误差曲线')

        metric_page = QWidget()
        metric_layout = QVBoxLayout(metric_page)
        self.metrics_table = QTableWidget(8, 5)
        self.metrics_table.setHorizontalHeaderLabels(
            ['角度', '指标', '优化前 (deg)', '优化后 (deg)', '变化'])
        self.metrics_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.metrics_table.verticalHeader().setVisible(False)
        self.metrics_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.metrics_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        metric_layout.addWidget(self.metrics_table)
        self.result_tabs.addTab(metric_page, '统计指标')

        preview_page = QWidget()
        preview_layout = QVBoxLayout(preview_page)
        self.preview_table = QTableWidget(0, 4)
        self.preview_table.setHorizontalHeaderLabels(
            ['方位真值', '俯仰真值', '方位实测', '俯仰实测'])
        self.preview_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.preview_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.preview_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        preview_layout.addWidget(self.preview_table)
        self.result_tabs.addTab(preview_page, '数据预览')
        layout.addWidget(self.result_tabs, 1)

        self.txt_result = QTextEdit()
        self.txt_result.setReadOnly(True)
        self.txt_result.setMaximumHeight(126)
        self.txt_result.setPlaceholderText('校正结果与运行状态')
        layout.addWidget(self.txt_result)

        self._draw_empty_plot()
        return container

    @staticmethod
    def _create_summary_box(parent_layout, title, value, accent):
        frame = QFrame()
        frame.setStyleSheet(
            f'QFrame {{ background: #ffffff; border: 1px solid #d7dee9; '
            f'border-left: 4px solid {accent}; border-radius: 6px; }}')
        box = QVBoxLayout(frame)
        box.setContentsMargins(12, 8, 12, 8)
        title_label = QLabel(title)
        title_label.setStyleSheet('color: #64748b; font-size: 9pt; border: none;')
        value_label = QLabel(value)
        value_label.setStyleSheet(
            f'color: {accent}; font-size: 16pt; font-weight: 700; border: none;')
        box.addWidget(title_label)
        box.addWidget(value_label)
        parent_layout.addWidget(frame, 1)
        return value_label

    def _connect_dirty_signals(self):
        self.edit_profile_name.textChanged.connect(self._mark_profile_dirty)
        self.edit_data_path.textChanged.connect(self._mark_profile_dirty)
        self.edit_data_path.textChanged.connect(self._on_data_path_changed)
        self.edit_notes.textChanged.connect(self._mark_profile_dirty)
        for control in (
            self.spin_rho, self.spin_xx, self.spin_bs14, self.spin_bs24,
            self.spin_bs34, self.spin_yy, self.spin_zz,
        ):
            control.valueChanged.connect(self._mark_profile_dirty)
        self.matrix_table.cellChanged.connect(self._mark_profile_dirty)

    def _refresh_profile_combo(self, selected_id=None):
        self._loading_profile = True
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        self.profile_combo.addItem('新建 / 未保存', None)
        selected_index = 0
        for profile in self.batch_store.list_profiles():
            self.profile_combo.addItem(profile['name'], profile['id'])
            if profile['id'] == selected_id:
                selected_index = self.profile_combo.count() - 1
        self.profile_combo.setCurrentIndex(selected_index)
        self._last_profile_index = selected_index
        self.profile_combo.blockSignals(False)
        self._loading_profile = False

    def _select_profile_by_id(self, profile_id):
        index = self.profile_combo.findData(profile_id)
        if index >= 0:
            self.profile_combo.setCurrentIndex(index)

    def _on_profile_changed(self, index):
        if self._loading_profile:
            return
        requested_id = self.profile_combo.itemData(index)
        if self._profile_dirty and requested_id != self.current_profile_id:
            answer = QMessageBox.question(
                self,
                '放弃未保存修改',
                '当前批次参数尚未保存，确定切换并放弃修改吗？',
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                self.profile_combo.blockSignals(True)
                self.profile_combo.setCurrentIndex(self._last_profile_index)
                self.profile_combo.blockSignals(False)
                return
        self._last_profile_index = index
        if requested_id is None:
            self._new_profile(confirm=False)
            return
        profile = self.batch_store.get_profile(requested_id)
        if profile:
            self._apply_profile(profile)

    def _apply_profile(self, profile):
        self._loading_profile = True
        self.current_profile_id = profile['id']
        self.edit_profile_name.setText(profile['name'])
        self.edit_data_path.setText(profile.get('data_path', ''))
        fixed = profile['fixed_params']
        self.spin_rho.setValue(float(fixed['rho_obj']))
        self.spin_xx.setValue(float(fixed['xx_r4']))
        self.spin_bs14.setValue(float(fixed.get('BS14', DEFAULT_FIXED_PARAMS['BS14'])))
        self.spin_bs24.setValue(float(fixed.get('BS24', DEFAULT_FIXED_PARAMS['BS24'])))
        self.spin_bs34.setValue(float(fixed.get('BS34', DEFAULT_FIXED_PARAMS['BS34'])))
        self._set_matrix(fixed['matrixZT2ANT'])
        init = profile['init_params']
        self.spin_yy.setValue(float(init['yy_r4_ZT']))
        self.spin_zz.setValue(float(init['zz_r4_ZT']))
        self.edit_notes.setPlainText(profile.get('notes', ''))
        self._loading_profile = False
        self._profile_dirty = False
        self.lbl_profile_status.setText(f'已加载：{profile["name"]}')
        self.lbl_profile_status.setStyleSheet('color: #0f766e;')
        self.btn_delete_profile.setEnabled(True)

    def _on_data_path_changed(self, filepath):
        normalized = os.path.normcase(os.path.abspath(filepath)) if filepath.strip() else ''
        loaded = os.path.normcase(self._loaded_data_path) if self._loaded_data_path else ''
        if normalized == loaded:
            return
        self.calibration_data = None
        self.preview_table.setRowCount(0)
        if filepath.strip():
            self.lbl_data_status.setText('配置路径尚未加载')
        else:
            self.lbl_data_status.setText('未加载数据')
        self.lbl_data_status.setStyleSheet('color: #64748b;')

    def _set_matrix(self, matrix):
        self.matrix_table.blockSignals(True)
        for row in range(3):
            for column in range(3):
                item = QTableWidgetItem(f'{float(matrix[row][column]):.9f}')
                item.setTextAlignment(Qt.AlignCenter)
                self.matrix_table.setItem(row, column, item)
        self.matrix_table.blockSignals(False)

    def _mark_profile_dirty(self, *args):
        if self._loading_profile:
            return
        self._profile_dirty = True
        self.lbl_profile_status.setText('参数已修改，尚未保存')
        self.lbl_profile_status.setStyleSheet('color: #b45309;')

    def _confirm_discard(self):
        if not self._profile_dirty:
            return True
        return QMessageBox.question(
            self,
            '放弃未保存修改',
            '当前批次参数尚未保存，确定放弃修改吗？',
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        ) == QMessageBox.Yes

    def _new_profile(self, checked=False, confirm=True):
        if confirm and not self._confirm_discard():
            return
        self._loading_profile = True
        self.current_profile_id = None
        self.profile_combo.blockSignals(True)
        self.profile_combo.setCurrentIndex(0)
        self.profile_combo.blockSignals(False)
        self._last_profile_index = 0
        self.edit_profile_name.setText('新批次参数')
        self.edit_data_path.clear()
        self.spin_rho.setValue(DEFAULT_FIXED_PARAMS['rho_obj'])
        self.spin_xx.setValue(DEFAULT_FIXED_PARAMS['xx_r4'])
        self.spin_bs14.setValue(DEFAULT_FIXED_PARAMS['BS14'])
        self.spin_bs24.setValue(DEFAULT_FIXED_PARAMS['BS24'])
        self.spin_bs34.setValue(DEFAULT_FIXED_PARAMS['BS34'])
        self._set_matrix(DEFAULT_FIXED_PARAMS['matrixZT2ANT'])
        self.spin_yy.setValue(DEFAULT_INIT_PARAMS['yy_r4_ZT'])
        self.spin_zz.setValue(DEFAULT_INIT_PARAMS['zz_r4_ZT'])
        self.edit_notes.clear()
        self._loading_profile = False
        self._profile_dirty = True
        self.lbl_profile_status.setText('新参数，保存后可在其他试验中复用')
        self.lbl_profile_status.setStyleSheet('color: #2563eb;')
        self.btn_delete_profile.setEnabled(False)

    def _collect_profile(self):
        name = self.edit_profile_name.text().strip()
        if not name:
            raise ValueError('请输入批次参数名称')
        matrix = []
        for row in range(3):
            matrix_row = []
            for column in range(3):
                item = self.matrix_table.item(row, column)
                if item is None or not item.text().strip():
                    raise ValueError(f'变换矩阵第 {row + 1} 行第 {column + 1} 列为空')
                try:
                    value = float(item.text())
                except ValueError as exc:
                    raise ValueError(
                        f'变换矩阵第 {row + 1} 行第 {column + 1} 列不是数值') from exc
                if not np.isfinite(value):
                    raise ValueError('变换矩阵不能包含 NaN 或无穷值')
                matrix_row.append(value)
            matrix.append(matrix_row)
        return {
            'name': name,
            'data_path': self.edit_data_path.text().strip(),
            'fixed_params': {
                'rho_obj': self.spin_rho.value(),
                'xx_r4': self.spin_xx.value(),
                'BS14': self.spin_bs14.value(),
                'BS24': self.spin_bs24.value(),
                'BS34': self.spin_bs34.value(),
                'matrixZT2ANT': matrix,
            },
            'init_params': {
                'yy_r4_ZT': self.spin_yy.value(),
                'zz_r4_ZT': self.spin_zz.value(),
            },
            'notes': self.edit_notes.toPlainText().strip(),
        }

    def _save_profile(self):
        try:
            saved = self.batch_store.save_profile(
                self._collect_profile(), self.current_profile_id)
        except Exception as exc:
            QMessageBox.warning(self, '保存失败', str(exc))
            return
        self.current_profile_id = saved['id']
        self._profile_dirty = False
        self._refresh_profile_combo(saved['id'])
        self.lbl_profile_status.setText(f'已保存：{saved["name"]}')
        self.lbl_profile_status.setStyleSheet('color: #0f766e;')
        self.btn_delete_profile.setEnabled(True)
        self._show_status(f'批次参数“{saved["name"]}”已保存')
        logger.info(f'批次参数已保存: {saved["name"]}')

    def _save_profile_as(self):
        try:
            profile = self._collect_profile()
        except ValueError as exc:
            QMessageBox.warning(self, '参数无效', str(exc))
            return
        default_name = profile['name'] + ' 副本'
        name, accepted = QInputDialog.getText(
            self, '另存批次参数', '新配置名称:', text=default_name)
        if not accepted:
            return
        profile['name'] = name.strip()
        try:
            saved = self.batch_store.save_profile(profile)
        except Exception as exc:
            QMessageBox.warning(self, '另存失败', str(exc))
            return
        self._refresh_profile_combo(saved['id'])
        self._apply_profile(saved)
        self._show_status(f'已另存为“{saved["name"]}”')
        logger.info(f'批次参数已另存: {saved["name"]}')

    def _delete_profile(self):
        if not self.current_profile_id:
            return
        name = self.edit_profile_name.text().strip()
        answer = QMessageBox.warning(
            self,
            '删除批次参数',
            f'确定永久删除“{name}”吗？\n此操作不会删除原始试验数据。',
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        profile_id = self.current_profile_id
        if self.batch_store.delete_profile(profile_id):
            profiles = self.batch_store.list_profiles()
            self._refresh_profile_combo()
            if profiles:
                self._select_profile_by_id(profiles[0]['id'])
            else:
                self._new_profile(confirm=False)
            self._show_status(f'批次参数“{name}”已删除')
            logger.info(f'批次参数已删除: {name}')

    def _browse_data_file(self):
        filepath, _ = QFileDialog.getOpenFileName(
            self,
            '选择标定数据',
            self.edit_data_path.text().strip(),
            '标定数据 (*.xlsx *.xls *.xlsm *.csv *.txt);;Excel (*.xlsx *.xls *.xlsm);;CSV/Text (*.csv *.txt)',
        )
        if filepath:
            self.edit_data_path.setText(filepath)
            self._load_data(filepath, show_dialog=True)

    def _load_data(self, filepath, show_dialog=False):
        try:
            data = load_calibration_data(filepath)
        except Exception as exc:
            self.calibration_data = None
            self._loaded_data_path = ''
            self.lbl_data_status.setText(f'加载失败：{exc}')
            self.lbl_data_status.setStyleSheet('color: #b91c1c;')
            if show_dialog:
                QMessageBox.warning(self, '数据加载失败', str(exc))
            return False
        self.calibration_data = data
        self._loaded_data_path = os.path.abspath(filepath)
        warning = '；样本少于 30，结果可能不稳定' if data['small_sample_warning'] else ''
        self.lbl_data_status.setText(f'已加载 {data["sample_count"]} 条样本{warning}')
        self.lbl_data_status.setStyleSheet(
            'color: #b45309;' if data['small_sample_warning'] else 'color: #0f766e;')
        self._update_preview(data)
        self.result_tabs.setCurrentIndex(2)
        self._show_status(f'已加载 {data["sample_count"]} 条标定数据')
        logger.info(f'标定数据已加载: {filepath} ({data["sample_count"]} 条)')
        return True

    def _update_preview(self, data):
        count = min(int(data['sample_count']), 200)
        self.preview_table.setRowCount(count)
        fields = ('az_true', 'el_true', 'az_meas', 'el_meas')
        for row in range(count):
            for column, field in enumerate(fields):
                item = QTableWidgetItem(f'{float(data[field][row]):.6f}')
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.preview_table.setItem(row, column, item)

    def _start_calibration(self):
        if self._calibration_thread is not None:
            return
        data_path = self.edit_data_path.text().strip()
        normalized_path = os.path.normcase(os.path.abspath(data_path)) if data_path else ''
        loaded_path = os.path.normcase(self._loaded_data_path) if self._loaded_data_path else ''
        if self.calibration_data is None or normalized_path != loaded_path:
            if not self._load_data(data_path, show_dialog=True):
                return
        try:
            profile = self._collect_profile()
        except ValueError as exc:
            QMessageBox.warning(self, '参数无效', str(exc))
            return

        self._run_context = {
            'profile': copy.deepcopy(profile),
            'source_path': self._loaded_data_path,
            'started_at': dt.datetime.now().isoformat(timespec='seconds'),
        }
        worker_data = {
            key: np.array(self.calibration_data[key], copy=True)
            for key in ('az_true', 'el_true', 'az_meas', 'el_meas')
        }
        self._calibration_thread = QThread(self)
        self._calibration_worker = CalibrationWorker(
            worker_data,
            copy.deepcopy(profile['fixed_params']),
            copy.deepcopy(profile['init_params']),
            self.spin_max_iterations.value(),
        )
        self._calibration_worker.moveToThread(self._calibration_thread)
        self._calibration_thread.started.connect(self._calibration_worker.run)
        self._calibration_worker.finished.connect(self._on_calibration_finished)
        self._calibration_worker.failed.connect(self._on_calibration_failed)
        self._calibration_worker.finished.connect(self._calibration_thread.quit)
        self._calibration_worker.failed.connect(self._calibration_thread.quit)
        self._calibration_thread.finished.connect(self._cleanup_calibration_thread)
        self.btn_run.setEnabled(False)
        self.btn_run.setText('校正计算中...')
        self.txt_result.setPlainText(
            f'正在校正\n批次：{profile["name"]}\n样本数：{self.calibration_data["sample_count"]}')
        self._show_status('测向校正正在后台运行...')
        self._calibration_thread.start()

    def _on_calibration_finished(self, result):
        result['context'] = copy.deepcopy(self._run_context)
        result['completed_at'] = dt.datetime.now().isoformat(timespec='seconds')
        self.result = result
        params = result['optimized_params']
        self.lbl_yy_result.setText(f'{params["yy_r4_ZT"]:.6f}')
        self.lbl_zz_result.setText(f'{params["zz_r4_ZT"]:.6f}')
        if result['initial_cost'] > 0:
            reduction = (result['initial_cost'] - result['final_cost']) / result['initial_cost'] * 100
        else:
            reduction = 0.0
        self.lbl_cost_result.setText(f'{reduction:.2f}%')
        self._update_metrics(result['metrics'])
        self._plot_result(result)
        status = '收敛' if result['success'] else '已结束（优化器未报告收敛）'
        self.txt_result.setPlainText(
            f'优化状态：{status}\n'
            f'迭代次数：{result["iterations"]}\n'
            f'初始成本：{result["initial_cost"]:.8g}  →  最终成本：{result["final_cost"]:.8g}\n'
            f'建议参数：yy_r4_ZT = {params["yy_r4_ZT"]:.6f}，zz_r4_ZT = {params["zz_r4_ZT"]:.6f}')
        self.btn_copy.setEnabled(True)
        self.btn_apply_result.setEnabled(True)
        self.btn_export.setEnabled(True)
        self.result_tabs.setCurrentIndex(0)
        self._show_status(f'测向校正完成，成本下降 {reduction:.2f}%')
        logger.info(
            f'测向校正完成: yy={params["yy_r4_ZT"]:.6f}, '
            f'zz={params["zz_r4_ZT"]:.6f}, cost={result["final_cost"]:.8g}')

    def _on_calibration_failed(self, message):
        self.txt_result.setPlainText(f'校正失败：{message}')
        self._show_status('测向校正失败')
        logger.error(f'测向校正失败: {message}')
        QMessageBox.critical(self, '校正失败', message)

    def _cleanup_calibration_thread(self):
        if self._calibration_worker is not None:
            self._calibration_worker.deleteLater()
        if self._calibration_thread is not None:
            self._calibration_thread.deleteLater()
        self._calibration_worker = None
        self._calibration_thread = None
        self.btn_run.setEnabled(True)
        self.btn_run.setText('开始校正')

    def _update_metrics(self, metrics):
        row = 0
        for angle_key, angle_label in (('azimuth', '方位'), ('elevation', '俯仰')):
            for metric_key, metric_label in self.METRICS:
                before = metrics[angle_key]['before'][metric_key]
                after = metrics[angle_key]['after'][metric_key]
                change = after - before
                values = (angle_label, metric_label, f'{before:.6f}', f'{after:.6f}', f'{change:+.6f}')
                for column, value in enumerate(values):
                    item = QTableWidgetItem(value)
                    if column >= 2:
                        item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    self.metrics_table.setItem(row, column, item)
                row += 1

    def _draw_empty_plot(self):
        self.figure.clear()
        axis = self.figure.add_subplot(111)
        axis.text(0.5, 0.5, '等待校正结果', ha='center', va='center', color='#64748b')
        axis.set_axis_off()
        self.figure.tight_layout()
        self.canvas.draw_idle()

    def _plot_result(self, result):
        series = result['series']
        sample_index = np.arange(1, result['sample_count'] + 1)
        self.figure.clear()
        axes = self.figure.subplots(2, 1, sharex=True)
        configs = (
            (axes[0], series['err_az_orig'], series['err_az_opt'], '方位角误差'),
            (axes[1], series['err_el_orig'], series['err_el_opt'], '俯仰角误差'),
        )
        for axis, before, after, title in configs:
            axis.plot(sample_index, before, color='#dc2626', linewidth=1.2, label='优化前')
            axis.plot(sample_index, after, color='#059669', linewidth=1.3, label='优化后')
            axis.axhline(0, color='#475569', linestyle='--', linewidth=0.8)
            axis.set_title(title)
            axis.set_ylabel('误差 (deg)')
            axis.grid(True, alpha=0.25)
            axis.legend(loc='best')
        axes[1].set_xlabel('样本序号')
        self.figure.tight_layout()
        self.canvas.draw_idle()

    def _copy_result_parameters(self):
        if not self.result:
            return
        params = self.result['optimized_params']
        text = (
            f'yy_r4_ZT = {params["yy_r4_ZT"]:.6f}\n'
            f'zz_r4_ZT = {params["zz_r4_ZT"]:.6f}')
        QApplication.clipboard().setText(text)
        self._show_status('优化参数已复制到剪贴板')

    def _apply_result_as_initial(self):
        if not self.result:
            return
        params = self.result['optimized_params']
        self.spin_yy.setValue(params['yy_r4_ZT'])
        self.spin_zz.setValue(params['zz_r4_ZT'])
        self._show_status('优化结果已应用为当前初值，保存批次参数后可复用')

    def _export_result(self):
        if not self.result:
            return
        profile_name = self.result['context']['profile']['name']
        safe_name = ''.join(char if char not in '\\/:*?"<>|' else '_' for char in profile_name)
        default_name = f'校正结果_{safe_name}_{dt.datetime.now():%Y%m%d_%H%M%S}.json'
        filepath, _ = QFileDialog.getSaveFileName(
            self, '导出校正结果', default_name, 'JSON 结果 (*.json)')
        if not filepath:
            return
        if not filepath.lower().endswith('.json'):
            filepath += '.json'
        stem = os.path.splitext(filepath)[0]
        csv_path = stem + '_样本明细.csv'
        image_path = stem + '_误差曲线.png'
        try:
            serializable = {
                key: value for key, value in self.result.items()
                if key != 'series'
            }
            with open(filepath, 'w', encoding='utf-8') as file:
                json.dump(serializable, file, ensure_ascii=False, indent=2)
            pd.DataFrame(self.result['series']).to_csv(
                csv_path, index=False, encoding='utf-8-sig')
            self.figure.savefig(image_path, dpi=300, bbox_inches='tight')
        except Exception as exc:
            logger.error(f'校正结果导出失败: {exc}')
            QMessageBox.critical(self, '导出失败', str(exc))
            return
        logger.info(f'校正结果已导出: {filepath}')
        QMessageBox.information(
            self,
            '导出完成',
            f'参数与指标：{filepath}\n样本明细：{csv_path}\n误差曲线：{image_path}',
        )
        self._show_status('测向校正结果已导出')

    def _show_status(self, message):
        status_bar = self.statusBar()
        if status_bar is not None:
            status_bar.showMessage(message, 5000)

    def statusBar(self):
        parent = self.parent()
        while parent is not None:
            if hasattr(parent, 'statusBar'):
                return parent.statusBar()
            parent = parent.parent()
        return None
