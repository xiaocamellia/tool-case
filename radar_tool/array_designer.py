"""
阵列设计助手 - Array Design Assistant
基于 PyQt5 + matplotlib，用于阵列方向图快速设计与评估
"""

import math
import re
import warnings

import numpy as np
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox,
    QPushButton, QLabel, QFileDialog, QComboBox, QDoubleSpinBox,
    QSpinBox, QMessageBox, QTextEdit, QTabWidget, QSplitter,
    QFrame, QListWidget, QListWidgetItem, QAbstractItemView,
    QLineEdit, QScrollArea, QStackedWidget, QTableWidget,
    QTableWidgetItem, QHeaderView, QCheckBox
)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont, QColor

from matplotlib.backends.backend_qt5agg import (
    NavigationToolbar2QT as NavigationToolbar,
    FigureCanvasQTAgg as FigureCanvas,
)
from matplotlib.figure import Figure
import matplotlib.pyplot as plt

from .ui_theme import set_button_icon, style_primary_button, style_warning_button
from .error_ui import handle_ui_exception
from .errors import safe_exception_message
from .logger import get_logger

logger = get_logger('array_designer')

C = 3e8


def _validate_elements(elements):
    """Validate array element coordinates, amplitudes, and phases."""

    if len(elements) < 2:
        raise ValueError('自定义阵列至少需要 2 个有效阵元')
    for index, element in enumerate(elements, 1):
        for field in ('x', 'y', 'amp', 'phase'):
            try:
                value = float(element.get(field))
            except (AttributeError, TypeError, ValueError) as exc:
                raise ValueError(f'阵元 {index} 的{field}必须是有限数值') from exc
            if not math.isfinite(value):
                raise ValueError(f'阵元 {index} 的{field}必须是有限数值')
        if abs(float(element.get('amp'))) == 0:
            raise ValueError(f'阵元 {index} 的幅度不能为零')
    return elements


class ArrayDesignerPanel(QWidget):
    """阵列设计助手主面板"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.elements = []      # [(x, y, amp, phase), ...]
        self.fc = 10e9
        self.weight_type = 'uniform'
        self._custom_coords = None  # 自定义坐标: [(x, y), ...]
        self._init_default_array()
        self._init_ui()
        logger.info('阵列设计助手已创建')

    def _init_default_array(self):
        """8元均匀线阵，半波长间距"""
        N = 8
        d_lam = 0.5
        lam = C / self.fc
        self.elements = []
        for i in range(N):
            x = (i - (N-1)/2) * d_lam * lam
            self.elements.append({'x': x, 'y': 0.0, 'amp': 1.0, 'phase': 0.0})

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)

        # 标题
        title = QLabel('📡 阵列设计助手')
        title.setStyleSheet('font-size: 18px; font-weight: bold; color: #1e293b;')
        layout.addWidget(title)

        # 控制栏
        ctrl_layout = QHBoxLayout()
        self.combo_template = QComboBox()
        self.combo_template.addItems(['均匀线阵 (ULA)', '均匀圆阵 (UCA)', '矩形面阵', 'L型阵列', '十字阵', '自定义'])
        self.combo_template.currentIndexChanged.connect(self._on_template_change)
        ctrl_layout.addWidget(QLabel('阵列类型:'))
        ctrl_layout.addWidget(self.combo_template, 1)

        ctrl_layout.addWidget(QLabel('阵元数:'))
        self.spin_N = QSpinBox()
        self.spin_N.setRange(2, 128)
        self.spin_N.setValue(8)
        self.spin_N.valueChanged.connect(self._on_param_change)
        ctrl_layout.addWidget(self.spin_N)

        ctrl_layout.addWidget(QLabel('间距(λ):'))
        self.spin_d = QDoubleSpinBox()
        self.spin_d.setRange(0.1, 5.0)
        self.spin_d.setValue(0.5)
        self.spin_d.setSingleStep(0.1)
        self.spin_d.valueChanged.connect(self._on_param_change)
        ctrl_layout.addWidget(self.spin_d)

        self.uca_radius_label = QLabel('UCA半径(λ):')
        self.spin_radius = QDoubleSpinBox()
        self.spin_radius.setRange(0.1, 100.0)
        self.spin_radius.setValue(2.0)
        self.spin_radius.setSingleStep(0.1)
        self.spin_radius.valueChanged.connect(self._on_param_change)
        ctrl_layout.addWidget(self.uca_radius_label)
        ctrl_layout.addWidget(self.spin_radius)

        self.rect_rows_label = QLabel('行数:')
        self.spin_rows = QSpinBox()
        self.spin_rows.setRange(1, 128)
        self.spin_rows.setValue(2)
        self.spin_rows.valueChanged.connect(self._on_param_change)
        ctrl_layout.addWidget(self.rect_rows_label)
        ctrl_layout.addWidget(self.spin_rows)

        self.rect_cols_label = QLabel('列数:')
        self.spin_cols = QSpinBox()
        self.spin_cols.setRange(1, 128)
        self.spin_cols.setValue(4)
        self.spin_cols.valueChanged.connect(self._on_param_change)
        ctrl_layout.addWidget(self.rect_cols_label)
        ctrl_layout.addWidget(self.spin_cols)

        self.rect_dx_label = QLabel('X间距(λ):')
        self.spin_dx = QDoubleSpinBox()
        self.spin_dx.setRange(0.1, 5.0)
        self.spin_dx.setValue(0.5)
        self.spin_dx.setSingleStep(0.1)
        self.spin_dx.valueChanged.connect(self._on_param_change)
        ctrl_layout.addWidget(self.rect_dx_label)
        ctrl_layout.addWidget(self.spin_dx)

        self.rect_dy_label = QLabel('Y间距(λ):')
        self.spin_dy = QDoubleSpinBox()
        self.spin_dy.setRange(0.1, 5.0)
        self.spin_dy.setValue(0.5)
        self.spin_dy.setSingleStep(0.1)
        self.spin_dy.valueChanged.connect(self._on_param_change)
        ctrl_layout.addWidget(self.rect_dy_label)
        ctrl_layout.addWidget(self.spin_dy)

        for widget in (
            self.uca_radius_label, self.spin_radius,
            self.rect_rows_label, self.spin_rows,
            self.rect_cols_label, self.spin_cols,
            self.rect_dx_label, self.spin_dx,
            self.rect_dy_label, self.spin_dy,
        ):
            widget.hide()

        ctrl_layout.addWidget(QLabel('频率:'))
        self.combo_freq = QComboBox()
        self.combo_freq.addItems(['10 GHz', '2.4 GHz', '5.8 GHz', '1 GHz', '自定义'])
        self.combo_freq.currentIndexChanged.connect(self._on_freq_change)
        ctrl_layout.addWidget(self.combo_freq)

        self.edit_freq_custom = QLineEdit('10000000000')
        self.edit_freq_custom.setPlaceholderText('数值或带单位, 如 3.5e9 / 3.5 GHz')
        self.edit_freq_custom.setToolTip('支持 Hz / kHz / MHz / GHz，也可直接输入纯数值（Hz）')
        self.edit_freq_custom.setMaximumWidth(170)
        self.edit_freq_custom.editingFinished.connect(self._on_freq_change)
        self.edit_freq_custom.hide()
        ctrl_layout.addWidget(self.edit_freq_custom)

        self.combo_weight = QComboBox()
        self.combo_weight.addItems(['均匀加权', '余弦加权', '汉明加权', '切比雪夫(-30dB)', '切比雪夫(-40dB)'])
        self.combo_weight.currentIndexChanged.connect(self._on_param_change)
        ctrl_layout.addWidget(QLabel('加权:'))
        ctrl_layout.addWidget(self.combo_weight, 1)

        self.btn_edit_custom = QPushButton('✏️ 编辑自定义')
        self.btn_edit_custom.setStyleSheet("""
            QPushButton {
                background-color: #f59e0b; color: white; border: none;
                border-radius: 4px; padding: 4px 10px; font-size: 12px;
            }
            QPushButton:hover { background-color: #d97706; }
        """)
        self.btn_edit_custom.clicked.connect(self._edit_custom_coords)
        self.btn_edit_custom.hide()
        ctrl_layout.addWidget(self.btn_edit_custom)

        layout.addLayout(ctrl_layout)

        # 主区域
        splitter = QSplitter(Qt.Horizontal)

        # 左侧：阵列布局 + 坐标表格
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)

        # 阵列俯视图
        self.array_figure = Figure(figsize=(3, 3), dpi=100, facecolor='white')
        self.array_canvas = FigureCanvas(self.array_figure)
        left_layout.addWidget(QLabel('阵列俯视图'))
        left_layout.addWidget(self.array_canvas)

        # 坐标表格
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(['X (m)', 'Y (m)', '幅度', '相位(°)'])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.itemChanged.connect(self._on_table_edit)
        left_layout.addWidget(QLabel('阵元坐标'))
        left_layout.addWidget(self.table, 1)

        splitter.addWidget(left_widget)

        # 右侧：方向图 + 指标
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)

        # 方向图
        self.pattern_figure = Figure(figsize=(5, 3.5), dpi=120, facecolor='white')
        self.pattern_canvas = FigureCanvas(self.pattern_figure)
        self.pattern_toolbar = NavigationToolbar(self.pattern_canvas, self)
        right_layout.addWidget(self.pattern_toolbar)
        right_layout.addWidget(self.pattern_canvas, 1)

        # 显示控制
        view_layout = QHBoxLayout()
        self.chk_polar = QCheckBox('极坐标')
        view_layout.addWidget(self.chk_polar)
        self.combo_cut = QComboBox()
        self.combo_cut.addItems(['方位面 (XY)', '俯仰面 (XZ)'])
        view_layout.addWidget(self.combo_cut)
        self.combo_cut.currentIndexChanged.connect(self._replot)
        self.chk_polar.stateChanged.connect(self._replot)
        view_layout.addStretch()
        right_layout.addLayout(view_layout)

        # 指标
        self.metrics_text = QTextEdit()
        self.metrics_text.setMaximumHeight(130)
        self.metrics_text.setReadOnly(True)
        self.metrics_text.setFont(QFont('Consolas', 9))
        right_layout.addWidget(self.metrics_text)

        splitter.addWidget(right_widget)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        layout.addWidget(splitter, 1)

        self._update_all()

    def _get_freq(self):
        idx = self.combo_freq.currentIndex()
        if idx < 4:
            return [10e9, 2.4e9, 5.8e9, 1e9][idx]
        return self._parse_custom_freq(self.edit_freq_custom.text())

    @staticmethod
    def _parse_custom_freq(text):
        """解析自定义频率，支持纯数值（Hz）或带 Hz/kHz/MHz/GHz 后缀。"""
        s = str(text).strip().replace(',', '').replace(' ', '')
        if not s:
            raise ValueError('频率不能为空')
        match = re.fullmatch(
            r'(?i)([+-]?(?:\d+\.?\d*|\.\d+)(?:e[+-]?\d+)?)(ghz|mhz|khz|hz|g|m|k)?',
            s,
        )
        if not match:
            raise ValueError('频率必须是数值，可选单位 Hz/kHz/MHz/GHz')
        value = float(match.group(1))
        unit = (match.group(2) or 'hz').lower()
        factor = {'hz': 1.0, 'khz': 1e3, 'k': 1e3,
                  'mhz': 1e6, 'm': 1e6, 'ghz': 1e9, 'g': 1e9}[unit]
        freq = value * factor
        if not math.isfinite(freq) or freq <= 0:
            raise ValueError('频率必须是大于 0 的有限数值')
        return freq

    def _on_freq_change(self, *args):
        is_custom = self.combo_freq.currentIndex() == self.combo_freq.count() - 1
        self.edit_freq_custom.setVisible(is_custom)
        try:
            self.fc = self._get_freq()
        except ValueError as exc:
            self.edit_freq_custom.setStyleSheet('border: 1px solid #ef4444;')
            self.edit_freq_custom.setToolTip(str(exc))
            logger.warning('频率设置无效: %s', exc)
            return
        self.edit_freq_custom.setStyleSheet('')
        self.edit_freq_custom.setToolTip('支持 Hz / kHz / MHz / GHz，也可直接输入纯数值（Hz）')
        self._on_param_change()

    def _on_template_change(self):
        idx = self.combo_template.currentIndex()
        is_custom = (idx == 5)
        is_uca = (idx == 1)
        is_rect = (idx == 2)
        self.spin_N.setVisible(not is_custom)
        self.btn_edit_custom.setVisible(is_custom)
        self.spin_d.setVisible(not is_custom and not is_rect)

        self.uca_radius_label.setVisible(is_uca)
        self.spin_radius.setVisible(is_uca)
        for widget in (
            self.rect_rows_label, self.spin_rows,
            self.rect_cols_label, self.spin_cols,
            self.rect_dx_label, self.spin_dx,
            self.rect_dy_label, self.spin_dy,
        ):
            widget.setVisible(is_rect)

        if is_rect:
            self._sync_rect_count()
        self._generate_template()
        self._update_all()

    def _sync_rect_count(self):
        count = self.spin_rows.value() * self.spin_cols.value()
        if self.spin_N.value() != count:
            self.spin_N.blockSignals(True)
            self.spin_N.setValue(count)
            self.spin_N.blockSignals(False)

    def _on_param_change(self):
        if self.combo_template.currentIndex() == 2:
            self._sync_rect_count()
        self._generate_template()
        self._update_all()

    def _generate_template(self):
        """根据模板生成阵元坐标"""
        idx = self.combo_template.currentIndex()
        N = self.spin_N.value()
        d_lam = self.spin_d.value()
        lam = C / self.fc

        if idx == 0:  # ULA
            self.elements = []
            for i in range(N):
                x = (i - (N-1)/2) * d_lam * lam
                self.elements.append({'x': x, 'y': 0.0, 'amp': 1.0, 'phase': 0.0})
        elif idx == 1:  # UCA
            radius = self.spin_radius.value() * lam
            self.elements = []
            for i in range(N):
                angle = 2 * math.pi * i / N
                self.elements.append({
                    'x': radius * math.cos(angle),
                    'y': radius * math.sin(angle),
                    'amp': 1.0, 'phase': 0.0
                })
        elif idx == 2:  # 矩形面阵
            rows = self.spin_rows.value()
            cols = self.spin_cols.value()
            dx_lam = self.spin_dx.value()
            dy_lam = self.spin_dy.value()
            self.elements = []
            for r in range(rows):
                for c in range(cols):
                    x = (c - (cols - 1) / 2) * dx_lam * lam
                    y = (r - (rows - 1) / 2) * dy_lam * lam
                    self.elements.append({'x': x, 'y': y, 'amp': 1.0, 'phase': 0.0})
        elif idx == 3:  # L阵
            Nx = max(N // 2, 2)
            Ny = N - Nx + 1
            self.elements = []
            for i in range(Nx):
                x = i * d_lam * lam
                self.elements.append({'x': x, 'y': 0.0, 'amp': 1.0, 'phase': 0.0})
            for i in range(1, Ny):
                y = i * d_lam * lam
                self.elements.append({'x': 0.0, 'y': y, 'amp': 1.0, 'phase': 0.0})
        elif idx == 4:  # 十字阵
            Nh = N // 2
            Nv = N - Nh
            self.elements = []
            for i in range(Nh):
                x = (i - (Nh-1)/2) * d_lam * lam
                self.elements.append({'x': x, 'y': 0.0, 'amp': 1.0, 'phase': 0.0})
            for i in range(1, Nv):
                y = i * d_lam * lam
                self.elements.append({'x': 0.0, 'y': y, 'amp': 1.0, 'phase': 0.0})
        else:  # 自定义
            pass

    def _compute_weights(self):
        """计算加权系数"""
        N = len(self.elements)
        if N == 0:
            return np.array([], dtype=float)
        w_idx = self.combo_weight.currentIndex()
        if w_idx == 0:
            amps = np.ones(N)
        elif w_idx == 1:
            amps = np.cos(np.linspace(-math.pi / 2, math.pi / 2, N)) + 0.1
        elif w_idx == 2:
            amps = 0.54 - 0.46 * np.cos(
                2 * math.pi * np.arange(N) / max(N - 1, 1))
        elif w_idx == 3:
            amps = self._chebyshev(N, 30)
        elif w_idx == 4:
            amps = self._chebyshev(N, 40)
        else:
            amps = np.ones(N)
        scale = float(np.max(np.abs(amps)))
        return amps / scale if scale > 0 else np.zeros(N)

    def _chebyshev(self, N, sidelobe_db):
        """切比雪夫加权近似"""
        if N < 2:
            return np.ones(max(N, 0))
        beta = 0.5
        x0 = np.cosh(1.0 / N * np.arccosh(10 ** (sidelobe_db / 20)))
        amps = []
        for n in range(N):
            val = 0
            for m in range(N):
                angle = math.pi * (2 * m + 1) / (2 * N)
                val += np.cos((n - (N - 1) / 2) * angle) * np.cos(
                    beta * math.pi * m / N)
            amps.append(abs(val))
        return np.array(amps)

    def _calc_pattern(self, theta_deg):
        """计算方向图，包含阵元幅度和相位。"""
        _validate_elements(self.elements)
        lam = C / self.fc
        k = 2 * math.pi / lam
        theta = np.deg2rad(theta_deg)
        amps = self._compute_weights()
        cut = self.combo_cut.currentIndex()

        pattern = np.zeros_like(theta, dtype=complex)
        for ei, elem in enumerate(self.elements):
            u = elem['x'] if cut == 0 else elem['y']
            geometric_phase = k * u * np.sin(theta)
            element_phase = math.radians(float(elem['phase']))
            pattern += (
                amps[ei] * np.exp(1j * geometric_phase)
                * float(elem['amp']) * np.exp(1j * element_phase)
            )

        gain = 20 * np.log10(np.abs(pattern) + 1e-30)
        return gain - np.max(gain)

    @staticmethod
    def _local_peak_indices(gains, start, end):
        peaks = []
        for index in range(max(1, start), min(len(gains) - 1, end + 1)):
            if gains[index] >= gains[index - 1] and gains[index] > gains[index + 1]:
                peaks.append(index)
            elif gains[index] > gains[index - 1] and gains[index] >= gains[index + 1]:
                peaks.append(index)
        return peaks

    def _extract_metrics(self, angles, gains):
        """提取主瓣边界、左右副瓣和构型相关指标。"""
        angles = np.asarray(angles, dtype=float)
        gains = np.asarray(gains, dtype=float)
        if len(angles) != len(gains) or len(gains) < 3:
            raise ValueError('方向图采样点不足')

        max_gain_db = float(np.max(gains))
        max_idx = int(np.argmax(gains))
        threshold = max_gain_db - 3

        left_boundary = max_idx
        while left_boundary > 0 and gains[left_boundary - 1] >= threshold:
            left_boundary -= 1
        right_boundary = max_idx
        while right_boundary < len(gains) - 1 and gains[right_boundary + 1] >= threshold:
            right_boundary += 1
        beamwidth = float(angles[right_boundary] - angles[left_boundary])

        left_peaks = self._local_peak_indices(gains, 1, left_boundary - 1)
        right_peaks = self._local_peak_indices(
            gains, right_boundary + 1, len(gains) - 2)
        sidelobe_indices = left_peaks + right_peaks
        left_sll = (
            float(gains[left_peaks[np.argmax(gains[left_peaks])]] - max_gain_db)
            if left_peaks else -99.0
        )
        right_sll = (
            float(gains[right_peaks[np.argmax(gains[right_peaks])]] - max_gain_db)
            if right_peaks else -99.0
        )
        first_sll = max(left_sll, right_sll)

        grating_candidates = [
            index for index in sidelobe_indices
            if gains[index] - max_gain_db > -15
        ]
        if grating_candidates:
            grating_index = max(grating_candidates, key=lambda index: gains[index])
            grating_level = float(gains[grating_index] - max_gain_db)
            grating_angle = float(angles[grating_index])
        else:
            grating_level = -99.0
            grating_angle = 0.0

        template_idx = self.combo_template.currentIndex()
        lam = C / self.fc
        N = len(self.elements)
        d_lam = self.spin_d.value()
        array_type = (
            'ULA' if template_idx == 0 else
            'UCA' if template_idx == 1 else
            'RECT' if template_idx == 2 else
            'CUSTOM'
        )

        if template_idx == 0:
            aperture_x = (N - 1) * d_lam
            aperture_y = 0.0
            aperture = aperture_x
            beamwidth_formula = f'50.8/(N*d) = {50.8 / max(N * d_lam, 1e-12):.2f}°'
            theoretical_beamwidth = 50.8 / max(N * d_lam, 1e-12)
            if d_lam > 1:
                grating_formula = f'asin(1/d) = {math.degrees(math.asin(min(1 / d_lam, 1))):.1f}°'
                unambig = math.degrees(math.asin(min(1 / (2 * d_lam), 1)))
            else:
                grating_formula = 'd≤1λ，无栅瓣'
                unambig = 90.0 if d_lam > 0.5 else 180.0
        elif template_idx == 1:
            radius_lam = self.spin_radius.value()
            aperture_x = aperture_y = 2 * radius_lam
            aperture = aperture_x
            theoretical_beamwidth = 50.8 / max(2 * radius_lam, 1e-12)
            beamwidth_formula = (
                f'50.8/(2R) = {theoretical_beamwidth:.2f}°'
            )
            grating_formula = '圆阵无一维线阵栅瓣公式'
            unambig = 180.0
        elif template_idx == 2:
            rows = self.spin_rows.value()
            cols = self.spin_cols.value()
            dx_lam = self.spin_dx.value()
            dy_lam = self.spin_dy.value()
            aperture_x = (cols - 1) * dx_lam
            aperture_y = (rows - 1) * dy_lam
            aperture = math.hypot(aperture_x, aperture_y)
            theoretical_beamwidth = min(
                50.8 / max(cols * dx_lam, 1e-12),
                50.8 / max(rows * dy_lam, 1e-12),
            )
            beamwidth_formula = (
                f'方位 {50.8 / max(cols * dx_lam, 1e-12):.2f}° / '
                f'俯仰 {50.8 / max(rows * dy_lam, 1e-12):.2f}°'
            )
            if dx_lam > 1 or dy_lam > 1:
                spacing = max(dx_lam, dy_lam)
                grating_formula = (
                    f'asin(1/dmax) = '
                    f'{math.degrees(math.asin(min(1 / spacing, 1))):.1f}°'
                )
            else:
                grating_formula = 'dx,dy≤1λ，无一维栅瓣'
            unambig = min(
                90.0 if dx_lam > 0.5 else 180.0,
                90.0 if dy_lam > 0.5 else 180.0,
            )
        else:
            xs = [float(element['x']) / lam for element in self.elements]
            ys = [float(element['y']) / lam for element in self.elements]
            aperture_x = max(xs) - min(xs)
            aperture_y = max(ys) - min(ys)
            aperture = math.hypot(aperture_x, aperture_y)
            theoretical_beamwidth = beamwidth
            beamwidth_formula = '由数值方向图测量'
            grating_formula = '自定义阵列按数值峰值判断'
            unambig = 180.0

        array_gain = 10 * math.log10(max(N, 1)) + 3
        return {
            'gain': array_gain,
            'beamwidth': beamwidth,
            'theoretical_beamwidth': theoretical_beamwidth,
            'beamwidth_formula': beamwidth_formula,
            'first_sll': first_sll,
            'left_sll': left_sll,
            'right_sll': right_sll,
            'main_left': float(angles[left_boundary]),
            'main_right': float(angles[right_boundary]),
            'grating_level': grating_level,
            'grating_angle': grating_angle,
            'grating_formula': grating_formula,
            'aperture': aperture,
            'aperture_x': aperture_x,
            'aperture_y': aperture_y,
            'unambig': unambig,
            'array_type': array_type,
            'N': N,
            'd_lam': d_lam,
        }

    def _plot_array(self):
        """绘制阵列俯视图"""
        self.array_figure.clear()
        ax = self.array_figure.add_subplot(111)

        xs = [e['x'] for e in self.elements]
        ys = [e['y'] for e in self.elements]
        amps = self._compute_weights()

        for i, (x, y) in enumerate(zip(xs, ys)):
            size = max(20, amps[i] * 80)
            ax.scatter(x, y, s=size, c='#1d4ed8', marker='o', alpha=0.7, zorder=5)
            ax.annotate(str(i+1), (x, y), xytext=(4, 4),
                       textcoords='offset points', fontsize=6)

        # 坐标轴
        margin = max(np.ptp(xs) * 0.3 if len(xs) > 1 else 0.05, 0.02)
        ax.set_xlim(min(xs) - margin, max(xs) + margin)
        ax.set_ylim(min(ys) - margin, max(ys) + margin)
        ax.set_xlabel('X (m)', fontsize=8)
        ax.set_ylabel('Y (m)', fontsize=8)
        ax.set_aspect('equal')
        ax.grid(True, linestyle='--', alpha=0.3)
        self.array_canvas.draw()

    def _replot(self):
        self._plot_pattern()

    def _plot_pattern(self):
        """绘制方向图"""
        fig = self.pattern_figure
        fig.clear()

        if self.chk_polar.isChecked():
            ax = fig.add_subplot(111, projection='polar')
            theta_deg = np.arange(-180, 181, 1)
            gains = self._calc_pattern(theta_deg)
            theta_rad = np.deg2rad(theta_deg)
            ax.plot(theta_rad, gains, color='#1d4ed8', linewidth=1.8)
            ax.set_theta_offset(np.pi/2)
            ax.set_theta_direction(-1)
            ax.set_thetamin(-90)
            ax.set_thetamax(90)
            ax.set_title('方向图 (极坐标)', fontsize=11, fontweight='bold')
        else:
            cut = self.combo_cut.currentIndex()
            if cut == 0:
                theta_deg = np.arange(-90, 91, 0.5)
                label = '方位角 (°)'
            else:
                theta_deg = np.arange(-90, 91, 0.5)
                label = '俯仰角 (°)'

            gains = self._calc_pattern(theta_deg)

            ax = fig.add_subplot(111)
            ax.plot(theta_deg, gains, color='#1d4ed8', linewidth=2.0, label='方向图')

            # 3dB线
            max_g = np.max(gains)
            ax.axhline(max_g - 3, color='#10b981', linestyle='--', linewidth=1, alpha=0.7, label='-3dB')

            ax.set_xlabel(label, fontsize=10)
            ax.set_ylabel('归一化增益 (dB)', fontsize=10)
            ax.set_title('阵列方向图', fontsize=12, fontweight='bold')
            ax.grid(True, linestyle='--', alpha=0.3)
            ax.set_xlim(-90, 90)
            ax.set_ylim(max(-50, np.min(gains) - 2), 3)
            ax.legend(fontsize=8)

        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            fig.tight_layout()
            self.pattern_canvas.draw()

    def _update_metrics(self):
        """更新指标显示"""
        theta_deg = np.arange(-90, 91, 0.5)
        gains = self._calc_pattern(theta_deg)
        metrics = self._extract_metrics(theta_deg, gains)

        if metrics['grating_level'] > -10:
            warning = '🔴 ⚠️ 栅瓣严重！'
        elif metrics['grating_level'] > -20:
            warning = '🟡 注意栅瓣'
        else:
            warning = '🟢 栅瓣正常'

        type_labels = {
            'ULA': '均匀线阵',
            'UCA': '均匀圆阵',
            'RECT': '矩形面阵',
            'CUSTOM': '自定义/复合阵',
        }
        aperture_label = (
            f'{metrics["aperture"]:.2f} λ'
            if metrics['array_type'] != 'RECT'
            else (
                f'X={metrics["aperture_x"]:.2f}λ, '
                f'Y={metrics["aperture_y"]:.2f}λ'
            )
        )
        unambig_text = (
            f'±{metrics["unambig"]:.1f}°'
            if metrics['array_type'] not in ('UCA', 'CUSTOM')
            else '圆阵/自定义按数值方向图判断'
        )
        sidelobe_note = (
            f'左 {metrics["left_sll"]:.1f} / '
            f'右 {metrics["right_sll"]:.1f} dB'
        )
        lines = [
            f'{"指标":<16} {"数值":>10} {"说明":<28}',
            f'{"─"*62}',
            f'{"阵列类型":<16} {type_labels.get(metrics["array_type"], metrics["array_type"]):>10} {"":<28}',
            f'{"阵元数":<16} {metrics["N"]:>10d} {"":<28}',
            f'{"阵列增益":<16} {metrics["gain"]:>8.1f} dBi {"近似 10log10(N)+3":<28}',
            f'{"3dB波束宽度":<16} {metrics["beamwidth"]:>8.2f}° {metrics["beamwidth_formula"]:<28}',
            f'{"第一副瓣":<16} {metrics["first_sll"]:>8.1f} dB {sidelobe_note:<28}',
            f'{"主瓣边界":<16} {metrics["main_left"]:>6.1f}°~{metrics["main_right"]:<6.1f}° {"-3dB连续区域":<28}',
            f'{"阵列孔径":<16} {aperture_label:>10} {"构型相关":<28}',
            f'{"无模糊范围":<16} {unambig_text:>10} {"":<28}',
            f'',
            f'{"栅瓣电平":<16} {metrics["grating_level"]:>8.1f} dB {warning}',
            f'{"栅瓣公式":<16} {"":>10} {metrics["grating_formula"]}',
        ]
        if metrics['grating_level'] > -20 and metrics['array_type'] != 'UCA':
            lines.append(
                f'{"栅瓣角度":<16} {metrics["grating_angle"]:>8.1f}° '
                f'{"间距需≤1λ":<20}'
            )
        self.metrics_text.setPlainText('\n'.join(lines))

    def _update_all(self):
        """全部更新"""
        self._update_table()
        self._plot_array()
        self._plot_pattern()
        self._update_metrics()

    def _update_table(self):
        """更新坐标表格"""
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.elements))
        for i, e in enumerate(self.elements):
            self.table.setItem(i, 0, QTableWidgetItem(f'{e["x"]:.6f}'))
            self.table.setItem(i, 1, QTableWidgetItem(f'{e["y"]:.6f}'))
            self.table.setItem(i, 2, QTableWidgetItem(f'{e["amp"]:.4f}'))
            self.table.setItem(i, 3, QTableWidgetItem(f'{e["phase"]:.1f}'))
        self.table.blockSignals(False)

    def _on_table_edit(self):
        """表格编辑后立即校验并更新方向图和指标。"""
        parsed = []
        try:
            for i in range(self.table.rowCount()):
                x = float(self.table.item(i, 0).text())
                y = float(self.table.item(i, 1).text())
                amp = float(self.table.item(i, 2).text())
                phase = float(self.table.item(i, 3).text())
                parsed.append({'x': x, 'y': y, 'amp': amp, 'phase': phase})
            _validate_elements(parsed)
        except (ValueError, TypeError, AttributeError) as exc:
            self.metrics_text.setPlainText(f'❌ {safe_exception_message(exc)}')
            logger.warning('阵元表格输入无效: %s', exc)
            self._update_table()
            return

        self.elements = parsed
        self._plot_array()
        self._plot_pattern()
        self._update_metrics()

    def _edit_custom_coords(self):
        """打开自定义阵元坐标编辑对话框（参考干涉仪模块设计）"""
        from PyQt5.QtWidgets import QDialog

        dialog = QDialog(self)
        dialog.setWindowTitle('自定义阵元坐标编辑')
        dialog.setMinimumSize(500, 400)
        dlg_layout = QVBoxLayout(dialog)

        # 提示信息
        info_label = QLabel(
            '坐标系说明：XY 平面，阵元位于 Z=0 平面。\n'
            '输入 X (m) 和 Y (m) 坐标即可。每次编辑完成后点击确定生效。'
        )
        info_label.setStyleSheet('color: #334155; font-size: 10px;')
        dlg_layout.addWidget(info_label)

        # 表格
        self.custom_coords_table = QTableWidget()
        self.custom_coords_table.setColumnCount(4)
        self.custom_coords_table.setHorizontalHeaderLabels(
            ['X (m)', 'Y (m)', '幅度', '相位(°)'])
        self.custom_coords_table.horizontalHeader().setStretchLastSection(True)
        self.custom_coords_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        dlg_layout.addWidget(self.custom_coords_table, 1)

        # 按钮行
        btn_layout = QHBoxLayout()
        btn_add = QPushButton('➕ 添加行')
        btn_add.clicked.connect(self._custom_add_row)
        btn_layout.addWidget(btn_add)

        btn_remove = QPushButton('➖ 删除选中')
        btn_remove.clicked.connect(self._custom_remove_row)
        btn_layout.addWidget(btn_remove)

        btn_layout.addStretch()

        btn_import = QPushButton('📂 从CSV导入')
        btn_import.clicked.connect(self._custom_import_csv)
        btn_layout.addWidget(btn_import)
        dlg_layout.addLayout(btn_layout)

        # 确定/取消
        okcancel = QHBoxLayout()
        okcancel.addStretch()
        btn_ok = QPushButton('确定')
        btn_ok.clicked.connect(lambda: self._custom_apply(dialog))
        style_primary_button(btn_ok)
        okcancel.addWidget(btn_ok)

        btn_cancel = QPushButton('取消')
        btn_cancel.clicked.connect(dialog.reject)
        okcancel.addWidget(btn_cancel)
        dlg_layout.addLayout(okcancel)

        # 始终加载当前阵元，保留已编辑的幅度和相位。
        self.custom_coords_table.setRowCount(len(self.elements))
        for i, element in enumerate(self.elements):
            self.custom_coords_table.setItem(
                i, 0, QTableWidgetItem(f'{float(element["x"]):.6f}'))
            self.custom_coords_table.setItem(
                i, 1, QTableWidgetItem(f'{float(element["y"]):.6f}'))
            self.custom_coords_table.setItem(
                i, 2, QTableWidgetItem(f'{float(element["amp"]):.4f}'))
            self.custom_coords_table.setItem(
                i, 3, QTableWidgetItem(f'{float(element["phase"]):.1f}'))

        dialog.exec_()

    def _custom_add_row(self):
        """在自定义坐标表格中添加一行"""
        row = self.custom_coords_table.rowCount()
        self.custom_coords_table.insertRow(row)
        self.custom_coords_table.setItem(row, 0, QTableWidgetItem('0.000000'))
        self.custom_coords_table.setItem(row, 1, QTableWidgetItem('0.000000'))
        self.custom_coords_table.setItem(row, 2, QTableWidgetItem('1.0000'))
        self.custom_coords_table.setItem(row, 3, QTableWidgetItem('0.0'))

    def _custom_remove_row(self):
        """删除选中的行"""
        rows = set()
        for item in self.custom_coords_table.selectedItems():
            rows.add(item.row())
        for row in sorted(rows, reverse=True):
            self.custom_coords_table.removeRow(row)

    def _custom_import_csv(self):
        """从CSV文件导入坐标"""
        filepath, _ = QFileDialog.getOpenFileName(
            self, '导入阵元坐标 (CSV)', '', 'CSV文件 (*.csv);;文本文件 (*.txt);;所有文件 (*.*)'
        )
        if not filepath:
            return
        try:
            data = np.loadtxt(filepath, delimiter=',')
            if data.ndim == 1:
                data = data.reshape(-1, 1)
            if data.shape[1] >= 2:
                if len(data) < 2:
                    raise ValueError('自定义阵列至少需要 2 个有效阵元')
                self.custom_coords_table.setRowCount(len(data))
                for i, row in enumerate(data):
                    self.custom_coords_table.setItem(i, 0, QTableWidgetItem(f'{row[0]:.6f}'))
                    self.custom_coords_table.setItem(i, 1, QTableWidgetItem(f'{row[1]:.6f}'))
                    amp = float(row[2]) if data.shape[1] >= 3 else 1.0
                    phase = float(row[3]) if data.shape[1] >= 4 else 0.0
                    self.custom_coords_table.setItem(i, 2, QTableWidgetItem(f'{amp:.4f}'))
                    self.custom_coords_table.setItem(i, 3, QTableWidgetItem(f'{phase:.1f}'))
                QMessageBox.information(self, '导入成功', f'已导入 {len(data)} 个阵元')
            else:
                QMessageBox.warning(self, '格式错误', 'CSV文件至少需要2列数据 (X, Y)')
        except Exception as e:
            handle_ui_exception(self, logger, '导入阵列坐标', e)

    def _custom_apply(self, dialog):
        """应用自定义坐标"""
        try:
            coords = []
            elements = []
            for i in range(self.custom_coords_table.rowCount()):
                x = float(self.custom_coords_table.item(i, 0).text())
                y = float(self.custom_coords_table.item(i, 1).text())
                amp = float(self.custom_coords_table.item(i, 2).text())
                phase = float(self.custom_coords_table.item(i, 3).text())
                coords.append((x, y))
                elements.append({'x': x, 'y': y, 'amp': amp, 'phase': phase})
            _validate_elements(elements)
            self._custom_coords = coords
            self.elements = elements
            self._update_all()
            dialog.accept()
            QMessageBox.information(self, '编辑完成', f'已应用 {len(coords)} 个阵元的自定义坐标')
            return True
        except (ValueError, TypeError, AttributeError) as e:
            handle_ui_exception(self, logger, '应用阵列坐标', e)
            return False

    def statusBar(self):
        parent = self.parent()
        while parent is not None:
            if hasattr(parent, 'statusBar'):
                return parent.statusBar()
            parent = parent.parent()
        return None
