"""
阵列设计助手 - Array Design Assistant
基于 PyQt5 + matplotlib，用于阵列方向图快速设计与评估
"""

import math
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
from .logger import get_logger

logger = get_logger('array_designer')

C = 3e8


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

        ctrl_layout.addWidget(QLabel('频率:'))
        self.combo_freq = QComboBox()
        self.combo_freq.addItems(['10 GHz', '2.4 GHz', '5.8 GHz', '1 GHz'])
        self.combo_freq.currentIndexChanged.connect(self._on_freq_change)
        ctrl_layout.addWidget(self.combo_freq)

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
        return [10e9, 2.4e9, 5.8e9, 1e9][idx]

    def _on_freq_change(self):
        self.fc = self._get_freq()
        self._on_param_change()

    def _on_template_change(self):
        idx = self.combo_template.currentIndex()
        # 自定义时显示编辑按钮，隐藏阵元数/间距控件；其他模板相反
        is_custom = (idx == 5)
        self.spin_N.setVisible(not is_custom)
        self.btn_edit_custom.setVisible(is_custom)
        # 间距控件在自定义模式下隐藏，但加权保持在自定义模式下可见
        self.spin_d.setVisible(not is_custom)
        self._generate_template()
        self._update_all()

    def _on_param_change(self):
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
            radius = d_lam * lam * N / (2 * math.pi)
            self.elements = []
            for i in range(N):
                angle = 2 * math.pi * i / N
                self.elements.append({
                    'x': radius * math.cos(angle),
                    'y': radius * math.sin(angle),
                    'amp': 1.0, 'phase': 0.0
                })
        elif idx == 2:  # 矩形面阵
            cols = int(math.sqrt(N))
            rows = (N + cols - 1) // cols
            self.elements = []
            for r in range(rows):
                for c in range(cols):
                    if len(self.elements) >= N:
                        break
                    x = (c - (cols-1)/2) * d_lam * lam
                    y = (r - (rows-1)/2) * d_lam * lam
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
        w_idx = self.combo_weight.currentIndex()
        amps = np.ones(N)
        if w_idx == 0:  # 均匀
            amps = np.ones(N)
        elif w_idx == 1:  # 余弦
            amps = np.cos(np.linspace(-math.pi/2, math.pi/2, N)) + 0.1
        elif w_idx == 2:  # 汉明
            amps = 0.54 - 0.46 * np.cos(2 * math.pi * np.arange(N) / (N-1))
        elif w_idx == 3:  # 切比雪夫-30
            amps = self._chebyshev(N, 30)
        elif w_idx == 4:  # 切比雪夫-40
            amps = self._chebyshev(N, 40)
        return amps / np.max(amps)

    def _chebyshev(self, N, sidelobe_db):
        """切比雪夫加权近似"""
        beta = 0.5
        x0 = np.cosh(1.0 / N * np.arccosh(10 ** (sidelobe_db / 20)))
        amps = []
        for n in range(N):
            val = 0
            for m in range(N):
                angle = math.pi * (2*m + 1) / (2*N)
                val += np.cos((n - (N-1)/2) * angle) * np.cos(beta * math.pi * m / N)
            amps.append(abs(val))
        return np.array(amps)

    def _calc_pattern(self, theta_deg):
        """计算方向图"""
        lam = C / self.fc
        k = 2 * math.pi / lam
        theta = np.deg2rad(theta_deg)
        amps = self._compute_weights()
        cut = self.combo_cut.currentIndex()  # 0=方位面(XY), 1=俯仰面(XZ)

        pattern = np.zeros_like(theta, dtype=complex)
        for ei, elem in enumerate(self.elements):
            if cut == 0:  # 方位面: 沿X轴投影
                u = elem['x']
            else:          # 俯仰面: 沿Y轴投影
                u = elem['y']
            phase = k * u * np.sin(theta)
            pattern += amps[ei] * np.exp(1j * phase) * elem['amp']

        gain = 20 * np.log10(np.abs(pattern) / len(self.elements) + 1e-30)
        return gain - np.max(gain)  # 归一化

    def _extract_metrics(self, angles, gains):
        """提取性能指标"""
        max_gain_db = np.max(gains)
        max_idx = np.argmax(gains)

        # 3dB波束宽度
        threshold = max_gain_db - 3
        above = gains >= threshold
        if np.any(above):
            left_idx = np.where(above[:max_idx])[0]
            right_idx = np.where(above[max_idx:])[0]
            left_angle = angles[left_idx[0]] if len(left_idx) > 0 else angles[0]
            right_angle = angles[max_idx + right_idx[-1]] if len(right_idx) > 0 else angles[-1]
            beamwidth = right_angle - left_angle
        else:
            beamwidth = 0

        # 副瓣电平
        sidelobes = []
        in_main = False
        for i in range(1, len(gains)-1):
            if gains[i] >= threshold:
                in_main = True
            elif gains[i] > gains[i-1] and gains[i] > gains[i+1] and not in_main:
                sidelobes.append(gains[i])
        first_sll = max(sidelobes) - max_gain_db if sidelobes else -99

        # 栅瓣检查
        grating_level = -99
        grating_angle = 0
        for i in range(1, len(gains)-1):
            if gains[i] > gains[i-1] and gains[i] > gains[i+1]:
                val = gains[i] - max_gain_db
                if val > -15 and abs(angles[i] - angles[max_idx]) > beamwidth/2:
                    if val > grating_level:
                        grating_level = val
                        grating_angle = angles[i]

        d_lam = self.spin_d.value()
        unambig = 2 * math.degrees(math.asin(1/(2*d_lam))) if d_lam > 0.5 else 180

        N = len(self.elements)
        aperture = max([e['x'] for e in self.elements]) - min([e['x'] for e in self.elements])
        array_gain = 10 * math.log10(N) + 3  # 近似

        return {
            'gain': array_gain,
            'beamwidth': beamwidth,
            'first_sll': first_sll,
            'grating_level': grating_level,
            'grating_angle': grating_angle,
            'aperture': aperture / (C/self.fc),
            'unambig': unambig,
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

        fig.tight_layout()
        self.pattern_canvas.draw()

    def _update_metrics(self):
        """更新指标显示"""
        theta_deg = np.arange(-90, 91, 0.5)
        gains = self._calc_pattern(theta_deg)
        metrics = self._extract_metrics(theta_deg, gains)

        warning = ''
        if metrics['grating_level'] > -10:
            warning = '🔴 ⚠️ 栅瓣严重！'
        elif metrics['grating_level'] > -20:
            warning = '🟡 注意栅瓣'
        else:
            warning = '🟢 栅瓣正常'

        lines = [
            f'{"指标":<16} {"数值":>10} {"说明":<20}',
            f'{"─"*50}',
            f'{"阵元数":<16} {metrics["N"]:>10d} {"":<20}',
            f'{"阵列增益":<16} {metrics["gain"]:>8.1f} dBi {"":<20}',
            f'{"3dB波束宽度":<16} {metrics["beamwidth"]:>8.2f}° {"":<20}',
            f'{"第一副瓣":<16} {metrics["first_sll"]:>8.1f} dB {"越低越好":<20}',
            f'{"阵列孔径":<16} {metrics["aperture"]:>8.2f} λ {"":<20}',
            f'{"无模糊范围":<16} ±{metrics["unambig"]:>6.1f}° {"":<20}',
            f'',
            f'{"栅瓣电平":<16} {metrics["grating_level"]:>8.1f} dB {warning}',
        ]
        if metrics['grating_level'] > -20:
            lines.append(f'{"栅瓣角度":<16} {metrics["grating_angle"]:>8.1f}° {"间距需≤0.5λ":<20}')

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
        """表格编辑后更新"""
        self.table.blockSignals(True)
        for i in range(self.table.rowCount()):
            try:
                x = float(self.table.item(i, 0).text())
                y = float(self.table.item(i, 1).text())
                amp = float(self.table.item(i, 2).text())
                phase = float(self.table.item(i, 3).text())
                if i < len(self.elements):
                    self.elements[i] = {'x': x, 'y': y, 'amp': amp, 'phase': phase}
            except (ValueError, TypeError, AttributeError):
                pass
        self.table.blockSignals(False)
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
        self.custom_coords_table.setColumnCount(2)
        self.custom_coords_table.setHorizontalHeaderLabels(['X (m)', 'Y (m)'])
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

        # 加载当前自定义坐标
        if self._custom_coords is not None and len(self._custom_coords) > 0:
            self.custom_coords_table.setRowCount(len(self._custom_coords))
            for i, (x, y) in enumerate(self._custom_coords):
                self.custom_coords_table.setItem(i, 0, QTableWidgetItem(f'{x:.6f}'))
                self.custom_coords_table.setItem(i, 1, QTableWidgetItem(f'{y:.6f}'))
        else:
            # 默认加载当前 elements 的坐标
            self.custom_coords_table.setRowCount(len(self.elements))
            for i, e in enumerate(self.elements):
                self.custom_coords_table.setItem(i, 0, QTableWidgetItem(f'{e["x"]:.6f}'))
                self.custom_coords_table.setItem(i, 1, QTableWidgetItem(f'{e["y"]:.6f}'))

        dialog.exec_()

    def _custom_add_row(self):
        """在自定义坐标表格中添加一行"""
        row = self.custom_coords_table.rowCount()
        self.custom_coords_table.insertRow(row)
        self.custom_coords_table.setItem(row, 0, QTableWidgetItem('0.000000'))
        self.custom_coords_table.setItem(row, 1, QTableWidgetItem('0.000000'))

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
                self.custom_coords_table.setRowCount(len(data))
                for i, row in enumerate(data):
                    self.custom_coords_table.setItem(i, 0, QTableWidgetItem(f'{row[0]:.6f}'))
                    self.custom_coords_table.setItem(i, 1, QTableWidgetItem(f'{row[1]:.6f}'))
                QMessageBox.information(self, '导入成功', f'已导入 {len(data)} 个阵元坐标')
            else:
                QMessageBox.warning(self, '格式错误', 'CSV文件至少需要2列数据 (X, Y)')
        except Exception as e:
            QMessageBox.warning(self, '导入失败', str(e))

    def _custom_apply(self, dialog):
        """应用自定义坐标"""
        try:
            coords = []
            for i in range(self.custom_coords_table.rowCount()):
                x = float(self.custom_coords_table.item(i, 0).text())
                y = float(self.custom_coords_table.item(i, 1).text())
                coords.append((x, y))
            self._custom_coords = coords
            # 更新 elements
            self.elements = []
            for x, y in coords:
                self.elements.append({'x': x, 'y': y, 'amp': 1.0, 'phase': 0.0})
            self._update_all()
            dialog.accept()
            QMessageBox.information(self, '编辑完成', f'已应用 {len(coords)} 个阵元的自定义坐标')
        except (ValueError, TypeError, AttributeError) as e:
            QMessageBox.warning(self, '输入错误', f'坐标格式无效：{str(e)}')

    def statusBar(self):
        parent = self.parent()
        while parent is not None:
            if hasattr(parent, 'statusBar'):
                return parent.statusBar()
            parent = parent.parent()
        return None
