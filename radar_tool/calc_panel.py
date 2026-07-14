"""
指标计算器合集 - Engineering Calculator Collection
基于 PyQt5，提供天线、雷达、链路、测向等常用工程计算
"""

import math
import numpy as np
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox,
    QPushButton, QLabel, QFileDialog, QComboBox, QDoubleSpinBox,
    QSpinBox, QMessageBox, QTextEdit, QTabWidget, QSplitter,
    QFrame, QListWidget, QListWidgetItem, QAbstractItemView,
    QLineEdit, QScrollArea, QStackedWidget
)
from PyQt5.QtCore import Qt, QTimer, QCoreApplication
from PyQt5.QtGui import QFont, QColor

from .ui_theme import set_button_icon, style_primary_button, style_warning_button, style_calc_button
from .logger import get_logger

logger = get_logger('calc_panel')

C = 3e8  # 光速
K_BOLTZ = 1.38e-23  # 玻尔兹曼常数


class CalcPanel(QWidget):
    """指标计算器合集主面板"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()
        logger.info('计算器合集已创建')

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)

        # 标题
        title = QLabel('🧮 指标计算器合集')
        title.setStyleSheet('font-size: 18px; font-weight: bold; color: #1e293b;')
        layout.addWidget(title)

        # 主区域
        splitter = QSplitter(Qt.Horizontal)

        # 左侧导航
        nav_widget = QWidget()
        nav_layout = QVBoxLayout(nav_widget)
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.addWidget(QLabel('📂 计算器分类'))

        self.nav_list = QListWidget()
        self.nav_list.setMinimumWidth(160)
        self.nav_list.setMaximumWidth(200)

        calculators = [
            ('🔧 单位转换器', 0),
            ('📡 天线增益估算', 1),
            ('🎯 作用距离估算', 2),
            ('📶 链路预算', 3),
            ('🧭 测向精度估算', 4),
            ('📊 阵列参数计算', 5),
            ('🔊 信噪比计算', 6),
        ]
        for name, idx in calculators:
            item = QListWidgetItem(name)
            item.setData(Qt.UserRole, idx)
            self.nav_list.addItem(item)

        self.nav_list.setCurrentRow(0)
        self.nav_list.currentRowChanged.connect(self._switch_calc)
        nav_layout.addWidget(self.nav_list, 1)
        splitter.addWidget(nav_widget)

        # 右侧计算区
        self.stack = QStackedWidget()
        self.calc_widgets = {}
        self._create_all_calculators()
        for key in range(7):
            if key in self.calc_widgets:
                self.stack.addWidget(self.calc_widgets[key])
        splitter.addWidget(self.stack)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        layout.addWidget(splitter, 1)

    def _switch_calc(self, idx):
        if idx >= 0 and idx < self.stack.count():
            self.stack.setCurrentIndex(idx)

    def _create_all_calculators(self):
        self.calc_widgets[0] = _UnitConverter()
        self.calc_widgets[1] = _AntennaGainCalc()
        self.calc_widgets[2] = _RadarRangeCalc()
        self.calc_widgets[3] = _LinkBudgetCalc()
        self.calc_widgets[4] = _DFAccuracyCalc()
        self.calc_widgets[5] = _ArrayParamCalc()
        self.calc_widgets[6] = _SNRCalc()


# ==================== 计算器基类 ====================

class _BaseCalc(QWidget):
    """计算器基类 - 提供输入/结果布局"""

    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.title = title
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        # 标题
        lbl = QLabel(self.title)
        lbl.setStyleSheet('font-size: 15px; font-weight: bold; color: #1e293b;')
        layout.addWidget(lbl)

        # 可滚动的中间区
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        container = QWidget()
        self.main_layout = QVBoxLayout(container)
        self._build_inputs()
        scroll.setWidget(container)
        layout.addWidget(scroll, 1)

        # 公式显示区
        self.formula_label = QLabel()
        self.formula_label.setWordWrap(True)
        self.formula_label.setStyleSheet("""
            QLabel {
                background-color: #f8fafc;
                border: 2px solid #cbd5e1;
                border-radius: 8px;
                padding: 12px 16px;
                font-size: 28px;
                color: #1e293b;
                font-family: 'Microsoft YaHei', 'SimHei', 'Cambria', serif;
                min-height: 48px;
            }
        """)
        layout.addWidget(self.formula_label)

        # 结果区
        result_group = QGroupBox('计算结果')
        result_layout = QVBoxLayout(result_group)
        self.result_text = QTextEdit()
        self.result_text.setReadOnly(True)
        self.result_text.setMaximumHeight(200)
        self.result_text.setFont(QFont('Consolas', 10))
        result_layout.addWidget(self.result_text)
        layout.addWidget(result_group)

    def _build_inputs(self):
        """子类重写此方法构建输入控件，使用 self.main_layout 添加内容"""
        pass

    def set_formula(self, text):
        """设置当前显示的公式"""
        if text:
            self.formula_label.setText(f'📐 公式：{text}')
        else:
            self.formula_label.setText('')

    def _show_result(self, lines):
        """显示结果"""
        html = ''
        for line in lines:
            if line.startswith('##'):
                html += f'<h3 style="color:#1d4ed8;margin:4px 0;">{line[2:].strip()}</h3>'
            elif line.startswith('**') and line.endswith('**'):
                html += f'<p style="font-weight:bold;font-size:13px;color:#111827;">{line.strip("*")}</p>'
            elif '🔴' in line or '❌' in line:
                html += f'<p style="color:#ef4444;">{line}</p>'
            elif '🟢' in line or '✅' in line:
                html += f'<p style="color:#22c55e;">{line}</p>'
            elif '🟡' in line:
                html += f'<p style="color:#eab308;">{line}</p>'
            elif ':' in line:
                parts = line.split(':', 1)
                html += f'<p><span style="color:#475569;">{parts[0]}:</span> <span style="font-weight:bold;color:#111827;">{parts[1]}</span></p>'
            else:
                html += f'<p style="color:#334155;">{line}</p>'
        self.result_text.setHtml(html)


# ==================== 1. 单位转换器 ====================

class _UnitConverter(_BaseCalc):
    def __init__(self, parent=None):
        super().__init__('🔧 单位转换器', parent)
        self._update_formula(0)

    def _update_formula(self, idx):
        formulas = [
            '频率 -> 波长: lam = c/f    |    波长 -> 频率: f = c/lam',
            'dBm = 10*log10(P/1mW)    |    P(mW) = 10^(dBm/10)    |    P(W) = 10^((dBm-30)/10)',
            'rad = deg * pi/180    |    deg = rad * 180/pi    |    mrad = rad * 1000',
            '倍数 = 10^(dB/10)    |    dB = 10*log10(倍数)',
            'F = C*9/5+32    |    K = C+273.15    |    C = (F-32)*5/9',
            'V2 = V1 * (factor2/factor1)',
        ]
        self.set_formula(formulas[idx] if 0 <= idx < len(formulas) else '')

    def _build_inputs(self):
        layout = QVBoxLayout()

        row0 = QHBoxLayout()
        row0.addWidget(QLabel('转换类型:'))
        self.combo_type = QComboBox()
        self.combo_type.addItems([
            '频率 ↔ 波长', '功率 ↔ dBm', '角度 ↔ 弧度',
            '增益 ↔ 倍数', '温度转换', '长度转换'
        ])
        self.combo_type.currentIndexChanged.connect(self._on_type_changed)
        row0.addWidget(self.combo_type, 1)
        layout.addLayout(row0)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel('输入值:'))
        self.input_val = QLineEdit('10')
        self.input_val.setPlaceholderText('请输入数值…')
        row1.addWidget(self.input_val, 1)
        layout.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel('从:'))
        self.combo_from = QComboBox()
        row2.addWidget(self.combo_from, 1)
        layout.addLayout(row2)

        row3 = QHBoxLayout()
        row3.addWidget(QLabel('到:'))
        self.combo_to = QComboBox()
        row3.addWidget(self.combo_to, 1)
        layout.addLayout(row3)

        # 主转换按钮 — 大号、醒目、不透明
        self.btn_calc = QPushButton('🔄 执行转换')
        self.btn_calc.clicked.connect(self._on_calc)
        style_calc_button(self.btn_calc)
        layout.addWidget(self.btn_calc)

        # 辅助按钮行
        quick_btn_layout = QHBoxLayout()
        self.btn_clear = QPushButton('🧹 清空')
        self.btn_clear.setStyleSheet("""
            QPushButton {
                background-color: #f1f5f9;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                padding: 6px 12px;
                min-height: 30px;
                font-size: 12px;
            }
            QPushButton:hover { background-color: #e2e8f0; border-color: #94a3b8; }
        """)
        self.btn_clear.clicked.connect(self._clear_input)
        quick_btn_layout.addWidget(self.btn_clear)

        self.btn_swap = QPushButton('↕ 互换单位')
        self.btn_swap.setStyleSheet("""
            QPushButton {
                background-color: #f1f5f9;
                border: 1px solid #cbd5e1;
                border-radius: 6px;
                padding: 6px 12px;
                min-height: 30px;
                font-size: 12px;
            }
            QPushButton:hover { background-color: #e2e8f0; border-color: #94a3b8; }
        """)
        self.btn_swap.clicked.connect(self._swap_units)
        quick_btn_layout.addWidget(self.btn_swap)
        quick_btn_layout.addStretch()
        layout.addLayout(quick_btn_layout)

        layout.addStretch()

        self.main_layout.addLayout(layout)
        self._update_units(0)

    def _clear_input(self):
        """清空输入框"""
        self.input_val.clear()
        self.input_val.setFocus()

    def _swap_units(self):
        """互换源单位和目标单位"""
        from_text = self.combo_from.currentText()
        to_text = self.combo_to.currentText()
        self.combo_from.setCurrentText(to_text)
        self.combo_to.setCurrentText(from_text)

    def _on_type_changed(self, idx):
        """转换类型切换时更新单位和公式"""
        self._update_units(idx)
        self._update_formula(idx)

    def _update_units(self, idx):
        self.combo_from.clear()
        self.combo_to.clear()
        units_map = {
            0: ['Hz', 'kHz', 'MHz', 'GHz', 'm', 'cm', 'mm'],
            1: ['W', 'mW', 'dBm', 'dBW'],
            2: ['°', 'rad', 'mrad'],
            3: ['dB', '倍数'],
            4: ['℃', '℉', 'K'],
            5: ['m', 'cm', 'mm', 'km', '英寸', '英尺'],
        }
        units = units_map.get(idx, ['m', 'cm'])
        self.combo_from.addItems(units)
        self.combo_to.addItems(units)
        if len(units) > 1:
            self.combo_to.setCurrentIndex(1)

    def _on_calc(self):
        try:
            val = float(self.input_val.text())
        except ValueError:
            self._show_result(['❌ 输入无效'])
            return
        t = self.combo_type.currentIndex()
        f = self.combo_from.currentText()
        to = self.combo_to.currentText()
        result = None

        if t == 0:
            if f in ('Hz', 'kHz', 'MHz', 'GHz') and to in ('m', 'cm', 'mm'):
                freq_hz = val * {'Hz': 1, 'kHz': 1e3, 'MHz': 1e6, 'GHz': 1e9}[f]
                lam = C / freq_hz
                result = lam * {'m': 1, 'cm': 100, 'mm': 1000}[to]
            elif f in ('m', 'cm', 'mm') and to in ('Hz', 'kHz', 'MHz', 'GHz'):
                lam_m = val / {'m': 1, 'cm': 100, 'mm': 1000}[f]
                freq = C / lam_m
                result = freq / {'Hz': 1, 'kHz': 1e3, 'MHz': 1e6, 'GHz': 1e9}[to]
            elif f in ('Hz', 'kHz', 'MHz', 'GHz') and to in ('Hz', 'kHz', 'MHz', 'GHz'):
                freq_hz = val * {'Hz': 1, 'kHz': 1e3, 'MHz': 1e6, 'GHz': 1e9}[f]
                result = freq_hz / {'Hz': 1, 'kHz': 1e3, 'MHz': 1e6, 'GHz': 1e9}[to]
            elif f in ('m', 'cm', 'mm') and to in ('m', 'cm', 'mm'):
                lam_m = val / {'m': 1, 'cm': 100, 'mm': 1000}[f]
                result = lam_m * {'m': 1, 'cm': 100, 'mm': 1000}[to]
            if result is not None:
                self._show_result([f'## 转换结果', f'{val} {f} = {result:.6f} {to}'])
            else:
                self._show_result(['❌ 不支持的转换组合'])
        elif t == 1:
            if f == 'W' and to == 'dBm':
                result = 10 * math.log10(val * 1000)
            elif f == 'mW' and to == 'dBm':
                result = 10 * math.log10(val)
            elif f == 'dBm' and to == 'W':
                result = 10 ** ((val - 30) / 10)
            elif f == 'dBm' and to == 'mW':
                result = 10 ** (val / 10)
            elif f == 'W' and to == 'dBW':
                result = 10 * math.log10(val)
            elif f == 'dBW' and to == 'W':
                result = 10 ** (val / 10)
            elif f == 'W' and to == 'mW':
                result = val * 1000
            elif f == 'mW' and to == 'W':
                result = val / 1000
            elif f == 'dBm' and to == 'dBW':
                result = val - 30
            elif f == 'dBW' and to == 'dBm':
                result = val + 30
            if result is not None:
                self._show_result([f'## 转换结果', f'{val} {f} = {result:.6f} {to}'])
            else:
                self._show_result(['❌ 不支持的转换组合'])
        elif t == 2:
            if f == '°' and to == 'rad':
                result = math.radians(val)
            elif f == 'rad' and to == '°':
                result = math.degrees(val)
            elif f == '°' and to == 'mrad':
                result = math.radians(val) * 1000
            elif f == 'mrad' and to == '°':
                result = math.degrees(val / 1000)
            else:
                result = val
            self._show_result([f'## 转换结果', f'{val} {f} = {result:.6f} {to}'])
        elif t == 3:
            if f == 'dB' and to == '倍数':
                result = 10 ** (val / 10)
            elif f == '倍数' and to == 'dB':
                result = 10 * math.log10(val) if val > 0 else 0
            else:
                result = val
            self._show_result([f'## 转换结果', f'{val} {f} = {result:.4f} {to}'])
        elif t == 4:
            if f == '℃' and to == '℉':
                result = val * 9/5 + 32
            elif f == '℉' and to == '℃':
                result = (val - 32) * 5/9
            elif f == '℃' and to == 'K':
                result = val + 273.15
            elif f == 'K' and to == '℃':
                result = val - 273.15
            elif f == 'K' and to == '℉':
                result = (val - 273.15) * 9/5 + 32
            elif f == '℉' and to == 'K':
                result = (val - 32) * 5/9 + 273.15
            else:
                result = val
            self._show_result([f'## 转换结果', f'{val} {f} = {result:.2f} {to}'])
        elif t == 5:
            factors = {'m': 1, 'cm': 100, 'mm': 1000, 'km': 0.001, '英寸': 39.3701, '英尺': 3.28084}
            result = val / factors[f] * factors[to]
            self._show_result([f'## 转换结果', f'{val} {f} = {result:.6f} {to}'])


# ==================== 2. 天线增益估算 ====================

class _AntennaGainCalc(_BaseCalc):
    def __init__(self, parent=None):
        super().__init__('📡 天线增益估算', parent)
        self.set_formula('G(dBi) = 10*log10(4pi*Ae/lam^2) = 10*log10(n*(pi*D/lam)^2)    |    theta3dB ~= 70*lam/D')

    def _build_inputs(self):
        layout = QGridLayout()
        layout.addWidget(QLabel('工作频率:'), 0, 0)
        self.spin_freq = QDoubleSpinBox()
        self.spin_freq.setRange(0.01, 1000)
        self.spin_freq.setValue(10)
        layout.addWidget(self.spin_freq, 0, 1)
        self.combo_freq_unit = QComboBox()
        self.combo_freq_unit.addItems(['GHz', 'MHz'])
        layout.addWidget(self.combo_freq_unit, 0, 2)

        layout.addWidget(QLabel('口径直径:'), 1, 0)
        self.spin_d = QDoubleSpinBox()
        self.spin_d.setRange(0.001, 100)
        self.spin_d.setValue(0.5)
        layout.addWidget(self.spin_d, 1, 1)
        self.combo_d_unit = QComboBox()
        self.combo_d_unit.addItems(['m', 'cm', 'mm'])
        layout.addWidget(self.combo_d_unit, 1, 2)

        layout.addWidget(QLabel('口径效率:'), 2, 0)
        self.spin_eff = QSpinBox()
        self.spin_eff.setRange(10, 100)
        self.spin_eff.setValue(60)
        self.spin_eff.setSuffix(' %')
        layout.addWidget(self.spin_eff, 2, 1)

        layout.addWidget(QLabel('口径形状:'), 3, 0)
        self.combo_shape = QComboBox()
        self.combo_shape.addItems(['圆形', '矩形', '椭圆形'])
        layout.addWidget(self.combo_shape, 3, 1, 1, 2)

        self.btn_calc = QPushButton('📡 计算增益')
        self.btn_calc.clicked.connect(self._on_calc)
        style_calc_button(self.btn_calc)
        layout.addWidget(self.btn_calc, 4, 0, 1, 3)

        self.main_layout.addLayout(layout)
        self.main_layout.addStretch()

    def _on_calc(self):
        f = self.spin_freq.value() * (1e9 if self.combo_freq_unit.currentText() == 'GHz' else 1e6)
        d = self.spin_d.value() / {'m': 1, 'cm': 100, 'mm': 1000}[self.combo_d_unit.currentText()]
        eff = self.spin_eff.value() / 100
        lam = C / f
        A_eff = eff * math.pi * (d / 2) ** 2
        G_lin = 4 * math.pi * A_eff / (lam ** 2)
        G_dBi = 10 * math.log10(G_lin) if G_lin > 0 else 0
        theta_3dB = 70 * lam / d if d > 0 else 0
        area = math.pi * (d / 2) ** 2
        self._show_result([
            f'## 天线增益计算结果',
            f'**工作频率**: {self.spin_freq.value()} {self.combo_freq_unit.currentText()}',
            f'**波长 λ**: {lam*1000:.2f} mm = {lam*100:.2f} cm',
            f'**口径面积**: {area:.4f} m²',
            f'**有效面积**: {A_eff:.4f} m²',
            f'', f'**天线增益**: {G_dBi:.2f} dBi ({G_lin:.1f}×)',
            f'**3dB波束宽度**: {theta_3dB:.2f}°',
            f'**第一副瓣电平**: -13.2 dB (均匀照射)',
            f'', f'💡 提示：实际增益需考虑馈线损耗、照射锥削等因素',
        ])


# ==================== 3. 作用距离估算 ====================

class _RadarRangeCalc(_BaseCalc):
    def __init__(self, parent=None):
        super().__init__('🎯 作用距离估算 (雷达方程)', parent)
        self.set_formula('Rmax = [Pt*Gt*Gr*lam^2*sigma / ((4pi)^3*k*T0*B*NF*SNRmin*L)]^(1/4)')

    def _build_inputs(self):
        layout = QGridLayout()
        params = [
            ('发射功率(W):', 0, 'power', 100),
            ('发射增益(dBi):', 1, 'gt', 30),
            ('接收增益(dBi):', 2, 'gr', 30),
            ('工作频率(GHz):', 3, 'freq', 10),
            ('目标RCS(m²):', 4, 'rcs', 1),
            ('带宽(MHz):', 5, 'bw', 10),
            ('噪声系数(dB):', 6, 'nf', 3),
            ('检测SNR(dB):', 7, 'snr', 10),
            ('系统损耗(dB):', 8, 'loss', 3),
        ]
        self.spins = {}
        for name, row, key, default in params:
            layout.addWidget(QLabel(name), row, 0)
            s = QDoubleSpinBox()
            s.setRange(0.001, 1e6)
            s.setValue(default)
            layout.addWidget(s, row, 1)
            self.spins[key] = s

        self.btn_calc = QPushButton('🎯 计算距离')
        self.btn_calc.clicked.connect(self._on_calc)
        style_calc_button(self.btn_calc)
        layout.addWidget(self.btn_calc, 9, 0, 1, 2)

        self.main_layout.addLayout(layout)
        self.main_layout.addStretch()

    def _on_calc(self):
        Pt = self.spins['power'].value()
        Gt = 10 ** (self.spins['gt'].value() / 10)
        Gr = 10 ** (self.spins['gr'].value() / 10)
        f = self.spins['freq'].value() * 1e9
        lam = C / f
        sigma = self.spins['rcs'].value()
        B = self.spins['bw'].value() * 1e6
        NF = 10 ** (self.spins['nf'].value() / 10)
        SNR_min = 10 ** (self.spins['snr'].value() / 10)
        L = 10 ** (self.spins['loss'].value() / 10)
        T0 = 290
        Pn = K_BOLTZ * T0 * B * NF
        R4 = (Pt * Gt * Gr * lam**2 * sigma) / ((4*math.pi)**3 * Pn * SNR_min * L)
        R_max = R4 ** 0.25 if R4 > 0 else 0
        R_10km = 10000
        Pr_10km = (Pt * Gt * Gr * lam**2 * sigma) / ((4*math.pi)**3 * R_10km**4 * L)
        SNR_10km = Pr_10km / Pn
        self._show_result([
            f'## 雷达作用距离计算结果',
            f'**最大探测距离**: {R_max/1000:.2f} km ({R_max:.0f} m)',
            f'**噪声功率 Pn**: {10*math.log10(Pn/0.001):.2f} dBm',
            f'**10km处接收功率**: {10*math.log10(Pr_10km/0.001):.2f} dBm',
            f'**10km处信噪比**: {10*math.log10(SNR_10km):.2f} dB',
            f'', f'## 参数变化影响',
            f'🟢 功率×4 → 距离×{4**0.25:.2f}',
            f'🟢 增益×4 → 距离×{4**0.25:.2f}',
            f'🔴 RCS×4 → 距离×{4**0.25:.2f}',
        ])


# ==================== 4. 链路预算 ====================

class _LinkBudgetCalc(_BaseCalc):
    def __init__(self, parent=None):
        super().__init__('📶 链路预算', parent)
        self.set_formula('Pr(dBm) = Pt+Gt-Lt-Lfs+Gr-Lr    |    Lfs = 20*log10(4pi*d/lam)    |    链路余量 = C/N - EbN0_req')

    def _build_inputs(self):
        layout = QGridLayout()
        params = [
            ('发射功率(dBm):', 0, 'pt', 30),
            ('发射增益(dBi):', 1, 'gt', 20),
            ('发射馈线损耗(dB):', 2, 'lt', 2),
            ('频率(GHz):', 3, 'freq', 10),
            ('距离(km):', 4, 'dist', 10),
            ('接收增益(dBi):', 5, 'gr', 20),
            ('接收馈线损耗(dB):', 6, 'lr', 2),
            ('噪声系数(dB):', 7, 'nf', 3),
            ('带宽(MHz):', 8, 'bw', 10),
            ('所需Eb/N0(dB):', 9, 'ebn0', 10),
        ]
        self.spins = {}
        for name, row, key, default in params:
            layout.addWidget(QLabel(name), row, 0)
            s = QDoubleSpinBox()
            s.setRange(-100, 200)
            s.setValue(default)
            layout.addWidget(s, row, 1)
            self.spins[key] = s

        self.btn_calc = QPushButton('📶 计算链路')
        self.btn_calc.clicked.connect(self._on_calc)
        style_calc_button(self.btn_calc)
        layout.addWidget(self.btn_calc, 10, 0, 1, 2)

        self.main_layout.addLayout(layout)
        self.main_layout.addStretch()

    def _on_calc(self):
        Pt = self.spins['pt'].value()
        Gt = self.spins['gt'].value()
        Lt = self.spins['lt'].value()
        f = self.spins['freq'].value() * 1e9
        d = self.spins['dist'].value() * 1000
        Gr = self.spins['gr'].value()
        Lr = self.spins['lr'].value()
        NF = self.spins['nf'].value()
        B = self.spins['bw'].value() * 1e6
        EbN0_req = self.spins['ebn0'].value()
        lam = C / f
        Lfs = 20 * math.log10(4 * math.pi * d / lam)
        Pr = Pt + Gt - Lt - Lfs + Gr - Lr
        kTB = -174 + 10 * math.log10(B)
        Pn = kTB + NF
        CN = Pr - Pn
        Rb = B
        EbN0 = CN + 10 * math.log10(B / Rb)
        margin = CN - EbN0_req
        status = '🟢 链路余量充足' if margin > 5 else '🟡 余量临界' if margin > 0 else '🔴 链路不足'
        self._show_result([
            f'## 链路预算结果 {status}',
            f'**发射端EIRP**: {Pt+Gt-Lt:.1f} dBm',
            f'**自由空间损耗**: {Lfs:.1f} dB',
            f'**接收功率 Pr**: {Pr:.1f} dBm',
            f'**噪声功率 Pn**: {Pn:.1f} dBm',
            f'**载噪比 C/N**: {CN:.1f} dB',
            f'**Eb/N0**: {EbN0:.1f} dB (需求: {EbN0_req} dB)',
            f'**链路余量**: {margin:.1f} dB',
            f'', f'## 链路瀑布',
            f'发射: {Pt} dBm → +{Gt}dBi -{Lt}dB = {Pt+Gt-Lt:.1f} dBm',
            f'信道: -{Lfs:.1f}dB (自由空间)',
            f'接收: +{Gr}dBi -{Lr}dB = {Pr:.1f} dBm',
        ])


# ==================== 5. 测向精度估算 ====================

class _DFAccuracyCalc(_BaseCalc):
    def __init__(self, parent=None):
        super().__init__('🧭 测向精度估算', parent)
        self.set_formula('sigma_int = 1/(2pi*d*cos(theta))*1/sqrt(2*SNR)    |    sigma_MUSIC = sigma_int/sqrt(N)    |    CRB ~= 1/(K*SNR*8pi^2*d^2*cos^2(theta))')

    def _build_inputs(self):
        layout = QGridLayout()
        params = [
            ('基线长度(λ):', 0, 'd', 0.5),
            ('阵元数:', 1, 'N', 4),
            ('信噪比(dB):', 2, 'snr', 20),
            ('快拍数:', 3, 'K', 100),
            ('来波方向(°):', 4, 'theta', 0),
        ]
        self.spins = {}
        for name, row, key, default in params:
            layout.addWidget(QLabel(name), row, 0)
            s = QDoubleSpinBox()
            s.setRange(0.01, 1000)
            s.setValue(default)
            s.setDecimals(1)
            layout.addWidget(s, row, 1)
            self.spins[key] = s

        self.combo_algo = QComboBox()
        self.combo_algo.addItems(['相位干涉仪', 'MUSIC算法'])
        layout.addWidget(QLabel('算法:'), 5, 0)
        layout.addWidget(self.combo_algo, 5, 1)

        self.btn_calc = QPushButton('🧭 计算精度')
        self.btn_calc.clicked.connect(self._on_calc)
        style_calc_button(self.btn_calc)
        layout.addWidget(self.btn_calc, 6, 0, 1, 2)

        self.main_layout.addLayout(layout)
        self.main_layout.addStretch()

    def _on_calc(self):
        d_lam = self.spins['d'].value()
        N = int(self.spins['N'].value())
        SNR = 10 ** (self.spins['snr'].value() / 10)
        K = int(self.spins['K'].value())
        theta = math.radians(self.spins['theta'].value())
        sigma_interfer = 1 / (2 * math.pi * d_lam * math.sqrt(2 * SNR))
        sigma_interfer_deg = math.degrees(sigma_interfer)
        CRB = 1 / (K * SNR) * (1 / (8 * math.pi**2 * d_lam**2 * math.cos(theta)**2))
        CRB_deg = math.degrees(math.sqrt(CRB)) if CRB > 0 else float('inf')
        sigma_music = sigma_interfer / math.sqrt(N)
        sigma_music_deg = math.degrees(sigma_music)
        ambig_range = math.degrees(math.asin(1 / (2 * d_lam))) if d_lam > 0.5 else 90
        algo = self.combo_algo.currentText()
        est = sigma_music_deg if 'MUSIC' in algo else sigma_interfer_deg
        self._show_result([
            f'## 测向精度估算结果',
            f'**算法**: {algo}',
            f'**理论测向精度 (RMSE)**: {est:.4f}°',
            f'**克拉美罗界 (CRB)**: {CRB_deg:.4f}°',
            f'', f'## 详细分析',
            f'**基线长度**: {d_lam:.2f} λ',
            f'**阵元数**: {N}',
            f'**无模糊范围**: ±{ambig_range:.1f}°',
            f'**SNR**: {self.spins["snr"].value():.0f} dB',
            f'**快拍数**: {K}',
            f'', f'💡 SNR提升10dB → 精度提高√10 ≈ 3.16倍',
        ])


# ==================== 6. 阵列参数计算 ====================

class _ArrayParamCalc(_BaseCalc):
    def __init__(self, parent=None):
        super().__init__('📊 阵列参数计算', parent)
        self.set_formula('G_array = Ge + 10*log10(N)    |    theta3dB ~= 50.8/(N*d/lam)    |    L_aper = N*d')

    def _build_inputs(self):
        layout = QGridLayout()

        layout.addWidget(QLabel('阵列构型:'), 0, 0)
        self.combo_config = QComboBox()
        self.combo_config.addItems(['均匀线阵(ULA)', '矩形面阵', '均匀圆阵(UCA)'])
        layout.addWidget(self.combo_config, 0, 1)

        layout.addWidget(QLabel('阵元数:'), 1, 0)
        self.spin_N = QSpinBox()
        self.spin_N.setRange(2, 256)
        self.spin_N.setValue(8)
        layout.addWidget(self.spin_N, 1, 1)

        layout.addWidget(QLabel('阵元间距:'), 2, 0)
        self.spin_d = QDoubleSpinBox()
        self.spin_d.setRange(0.1, 10)
        self.spin_d.setValue(0.5)
        layout.addWidget(self.spin_d, 2, 1)
        self.combo_d_unit = QComboBox()
        self.combo_d_unit.addItems(['λ', 'm'])
        layout.addWidget(self.combo_d_unit, 2, 2)

        layout.addWidget(QLabel('工作频率:'), 3, 0)
        self.spin_freq_arr = QDoubleSpinBox()
        self.spin_freq_arr.setRange(0.01, 100)
        self.spin_freq_arr.setValue(10)
        layout.addWidget(self.spin_freq_arr, 3, 1)
        self.combo_freq_arr = QComboBox()
        self.combo_freq_arr.addItems(['GHz', 'MHz'])
        layout.addWidget(self.combo_freq_arr, 3, 2)

        layout.addWidget(QLabel('阵元增益:'), 4, 0)
        self.spin_Ge = QDoubleSpinBox()
        self.spin_Ge.setRange(-10, 40)
        self.spin_Ge.setValue(5)
        self.spin_Ge.setSuffix(' dBi')
        layout.addWidget(self.spin_Ge, 4, 1)

        self.btn_calc = QPushButton('📊 计算阵列')
        self.btn_calc.clicked.connect(self._on_calc)
        style_calc_button(self.btn_calc)
        layout.addWidget(self.btn_calc, 5, 0, 1, 3)

        self.main_layout.addLayout(layout)
        self.main_layout.addStretch()

    def _on_calc(self):
        N = self.spin_N.value()
        d_val = self.spin_d.value()
        d_unit = self.combo_d_unit.currentText()
        f = self.spin_freq_arr.value() * (1e9 if self.combo_freq_arr.currentText() == 'GHz' else 1e6)
        lam = C / f
        Ge = self.spin_Ge.value()
        d_lam = d_val if d_unit == 'λ' else d_val / lam
        G_array = Ge + 10 * math.log10(N) if N > 0 else Ge
        theta_3dB = 50.8 / (N * d_lam)
        aperture = N * d_lam if d_unit == 'λ' else N * d_val
        grating_lobe = math.degrees(math.asin(1 / d_lam)) if d_lam > 1 else 90
        unambig = math.degrees(math.asin(1 / (2 * d_lam))) if d_lam > 0.5 else 90
        if d_lam > 1:
            warning = f'🔴 ⚠️ 栅瓣警告！间距 {d_lam:.2f}λ > 1λ，栅瓣在 {grating_lobe:.1f}°'
        elif d_lam > 0.5:
            warning = f'🟡 间距 {d_lam:.2f}λ > 0.5λ，无模糊范围 ±{unambig:.1f}°'
        else:
            warning = '🟢 间距 ≤0.5λ，无栅瓣风险'
        self._show_result([
            f'## 阵列参数计算结果',
            f'**阵列增益**: {G_array:.2f} dBi',
            f'**3dB波束宽度**: {theta_3dB:.2f}°',
            f'**阵列孔径**: {aperture:.2f} {d_unit}',
            f'', f'## 栅瓣分析',
            f'{warning}',
            f'**第一个栅瓣位置**: {grating_lobe:.1f}°',
            f'**无模糊范围**: ±{unambig:.1f}°',
        ])


# ==================== 7. 信噪比计算 ====================

class _SNRCalc(_BaseCalc):
    def __init__(self, parent=None):
        super().__init__('🔊 信噪比计算', parent)
        self.set_formula('Pn(dBm) = -174 + 10*log10(B) + NF    |    SNR(dB) = Pr - Pn    |    N0 = -174 dBm/Hz')

    def _build_inputs(self):
        layout = QGridLayout()
        params = [
            ('接收带宽(MHz):', 0, 'bw', 10),
            ('噪声系数(dB):', 1, 'nf', 3),
            ('接收功率(dBm):', 2, 'pr', -80),
            ('环境温度(K):', 3, 'temp', 290),
        ]
        self.spins = {}
        for name, row, key, default in params:
            layout.addWidget(QLabel(name), row, 0)
            s = QDoubleSpinBox()
            s.setRange(-200, 200)
            s.setValue(default)
            layout.addWidget(s, row, 1)
            self.spins[key] = s

        self.btn_calc = QPushButton('🔊 计算信噪比')
        self.btn_calc.clicked.connect(self._on_calc)
        style_calc_button(self.btn_calc)
        layout.addWidget(self.btn_calc, 4, 0, 1, 2)

        self.main_layout.addLayout(layout)
        self.main_layout.addStretch()

    def _on_calc(self):
        B = self.spins['bw'].value() * 1e6
        NF = self.spins['nf'].value()
        Pr = self.spins['pr'].value()
        T = self.spins['temp'].value()
        N0 = -174
        Pn_dBm = N0 + 10 * math.log10(B) + NF
        SNR = Pr - Pn_dBm
        sens_10dB = Pn_dBm + 10
        self._show_result([
            f'## 信噪比计算结果',
            f'**噪声谱密度 N0**: {N0} dBm/Hz',
            f'**总噪声功率 Pn**: {Pn_dBm:.2f} dBm',
            f'**输入信号功率**: {Pr:.2f} dBm',
            f'**接收信噪比 SNR**: {SNR:.2f} dB',
            f'', f'## 灵敏度',
            f'**灵敏度 (SNR=10dB)**: {sens_10dB:.2f} dBm',
            f'', f'## 噪声电压 (50Ω)',
            f'**噪声电压有效值**: {math.sqrt(K_BOLTZ*T*B*10**(NF/10)*50)*1e6:.2f} μV',
        ])