"""PyQt calculator controls kept separate from pure formulas."""
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
from .errors import safe_exception_message
from .calc_formulas import (
    calculate_array_parameters, calculate_df_accuracy, calculate_link_budget,
)
from .calc_units import (
    C, K_BOLTZ, _finite_value, _positive_value, convert_angle,
    convert_frequency_wavelength, convert_gain_ratio, convert_length,
    convert_power, convert_temperature, convert_unit,
)

logger = get_logger("calc_panel")

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
class _UnitConverter(_BaseCalc):
    def __init__(self, parent=None):
        super().__init__('🔧 单位转换器', parent)
        self._update_formula(0)

    def _update_formula(self, idx):
        formulas = [
            '频率 -> 波长: lam = c/f    |    波长 -> 频率: f = c/lam',
            'dBm = 10*log10(P/1mW)    |    P(mW) = 10^(dBm/10)    |    P(W) = 10^((dBm-30)/10)',
            'rad = deg * pi/180    |    deg = rad * 180/pi    |    mrad = rad * 1000    |    rad = mrad/1000',
            '倍数 = 10^(dB/10)    |    dB = 10*log10(倍数)，倍数必须 > 0',
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
            value = float(self.input_val.text())
            category = self.combo_type.currentIndex()
            source_unit = self.combo_from.currentText()
            target_unit = self.combo_to.currentText()
            result = convert_unit(
                category, value, source_unit, target_unit)
        except (ValueError, OverflowError, ZeroDivisionError) as exc:
            self._show_result([f'❌ {safe_exception_message(exc)}'])
            logger.warning('单位转换输入无效: %s', exc)
            return False

        self._show_result([
            '## 转换结果',
            f'{value:g} {source_unit} = {result:.6g} {target_unit}',
        ])
        return True
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
        try:
            frequency_factor = (
                1e9 if self.combo_freq_unit.currentText() == 'GHz' else 1e6)
            f = _positive_value(
                self.spin_freq.value() * frequency_factor, '工作频率')
            length_factor = {
                'm': 1.0, 'cm': 100.0, 'mm': 1000.0,
            }[self.combo_d_unit.currentText()]
            d = _positive_value(
                self.spin_d.value() / length_factor, '口径直径')
            eff = _finite_value(self.spin_eff.value(), '口径效率') / 100
            if not 0 < eff <= 1:
                raise ValueError('口径效率必须在 0~100% 之间')
            lam = C / f
            A_eff = eff * math.pi * (d / 2) ** 2
            G_lin = 4 * math.pi * A_eff / (lam ** 2)
            G_dBi = 10 * math.log10(G_lin)
            theta_3dB = 70 * lam / d
            area = math.pi * (d / 2) ** 2
        except (ValueError, OverflowError, ZeroDivisionError) as exc:
            self._show_result([f'❌ {safe_exception_message(exc)}'])
            logger.warning('天线增益输入无效: %s', exc)
            return False

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
        return True
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
        try:
            Pt = _positive_value(self.spins['power'].value(), '发射功率')
            gt_db = _finite_value(self.spins['gt'].value(), '发射增益')
            gr_db = _finite_value(self.spins['gr'].value(), '接收增益')
            f = _positive_value(self.spins['freq'].value() * 1e9, '工作频率')
            sigma = _positive_value(self.spins['rcs'].value(), '目标RCS')
            B = _positive_value(self.spins['bw'].value() * 1e6, '带宽')
            nf_db = _finite_value(self.spins['nf'].value(), '噪声系数')
            snr_db = _finite_value(self.spins['snr'].value(), '检测SNR')
            loss_db = _finite_value(self.spins['loss'].value(), '系统损耗')
            Gt = 10 ** (gt_db / 10)
            Gr = 10 ** (gr_db / 10)
            lam = C / f
            NF = 10 ** (nf_db / 10)
            SNR_min = 10 ** (snr_db / 10)
            L = 10 ** (loss_db / 10)
            T0 = 290
            Pn = K_BOLTZ * T0 * B * NF
            R4 = (
                Pt * Gt * Gr * lam ** 2 * sigma
                / ((4 * math.pi) ** 3 * Pn * SNR_min * L)
            )
            R_max = R4 ** 0.25 if R4 > 0 else 0
            R_10km = 10000
            Pr_10km = (
                Pt * Gt * Gr * lam ** 2 * sigma
                / ((4 * math.pi) ** 3 * R_10km ** 4 * L)
            )
            SNR_10km = Pr_10km / Pn
        except (ValueError, OverflowError, ZeroDivisionError) as exc:
            self._show_result([f'❌ {safe_exception_message(exc)}'])
            logger.warning('作用距离输入无效: %s', exc)
            return False

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
        return True
class _LinkBudgetCalc(_BaseCalc):
    def __init__(self, parent=None):
        super().__init__('📶 链路预算', parent)
        self.last_result = None
        self.set_formula(
            'Pr(dBm) = Pt+Gt-Lt-Lfs+Gr-Lr    |    '
            'Lfs = 20*log10(4πd/λ)    |    '
            'Eb/N0 = C/N - 10*log10(B/Rb)    |    '
            '余量 = Eb/N0 - EbN0_req'
        )

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
            ('码率(bps):', 10, 'rb', 10_000_000),
        ]
        self.spins = {}
        for name, row, key, default in params:
            layout.addWidget(QLabel(name), row, 0)
            s = QDoubleSpinBox()
            if key == 'rb':
                s.setRange(-1e12, 1e12)
                s.setDecimals(0)
            else:
                s.setRange(-100, 200)
            s.setValue(default)
            layout.addWidget(s, row, 1)
            self.spins[key] = s

        self.btn_calc = QPushButton('📶 计算链路')
        self.btn_calc.clicked.connect(self._on_calc)
        style_calc_button(self.btn_calc)
        layout.addWidget(self.btn_calc, 11, 0, 1, 2)

        self.main_layout.addLayout(layout)
        self.main_layout.addStretch()

    def _on_calc(self):
        try:
            result = calculate_link_budget(
                pt_dbm=self.spins['pt'].value(),
                gt_dbi=self.spins['gt'].value(),
                lt_db=self.spins['lt'].value(),
                freq_ghz=self.spins['freq'].value(),
                distance_km=self.spins['dist'].value(),
                gr_dbi=self.spins['gr'].value(),
                lr_db=self.spins['lr'].value(),
                nf_db=self.spins['nf'].value(),
                bandwidth_mhz=self.spins['bw'].value(),
                ebn0_req_db=self.spins['ebn0'].value(),
                rate_bps=self.spins['rb'].value(),
            )
        except (ValueError, OverflowError) as exc:
            self.last_result = None
            self._show_result([f'❌ {safe_exception_message(exc)}'])
            logger.warning('链路预算输入无效: %s', exc)
            return False

        self.last_result = result
        margin = result['margin_db']
        status = (
            '🟢 链路余量充足' if margin > 5
            else '🟡 余量临界' if margin > 0
            else '🔴 链路不足'
        )
        self._show_result([
            f'## 链路预算结果 {status}',
            f'**发射端EIRP**: '
            f"{self.spins['pt'].value() + self.spins['gt'].value() - self.spins['lt'].value():.1f} dBm",
            f'**自由空间损耗**: {result["free_space_loss_db"]:.1f} dB',
            f'**接收功率 Pr**: {result["receive_power_dbm"]:.1f} dBm '
            f'({result["receive_power_dbw"]:.1f} dBW)',
            f'**噪声功率 Pn**: {result["noise_power_dbm"]:.1f} dBm '
            f'({result["noise_power_dbw"]:.1f} dBW)',
            f'**载噪比 C/N**: {result["carrier_to_noise_db"]:.1f} dB',
            f'**Eb/N0**: {result["eb_to_n0_db"]:.1f} dB '
            f'(需求: {result["ebn0_req_db"]:.1f} dB)',
            f'**链路余量**: {margin:.1f} dB',
            f'**频率**: {self.spins["freq"].value():g} GHz = '
            f'{result["frequency_hz"]:g} Hz',
            f'**带宽**: {self.spins["bw"].value():g} MHz = '
            f'{result["bandwidth_hz"]:g} Hz',
            f'**码率**: {result["rate_bps"]:g} bps',
            f'', f'## 链路瀑布',
            f'发射: {self.spins["pt"].value()} dBm → '
            f'+{self.spins["gt"].value()}dBi '
            f'-{self.spins["lt"].value()}dB = '
            f'{self.spins["pt"].value() + self.spins["gt"].value() - self.spins["lt"].value():.1f} dBm',
            f'信道: -{result["free_space_loss_db"]:.1f}dB (自由空间)',
            f'接收: +{self.spins["gr"].value()}dBi '
            f'-{self.spins["lr"].value()}dB = '
            f'{result["receive_power_dbm"]:.1f} dBm',
        ])
        return True
class _DFAccuracyCalc(_BaseCalc):
    def __init__(self, parent=None):
        super().__init__('🧭 测向精度估算', parent)
        self.last_result = None
        self.set_formula(
            'σ_int(rad) = 1/[2π·d·cos(θ)·√(2·SNR_lin)]    |    '
            'CRB(rad²) = 1/[K·SNR_lin·8π²·d²·cos²(θ)]    |    '
            'SNR_lin = 10^(SNR_dB/10)，K = 快拍数'
        )

    def _build_inputs(self):
        layout = QGridLayout()
        params = [
            ('基线长度(λ):', 0, 'd', 0.5, 0.01, 1000, 1),
            ('阵元数:', 1, 'N', 4, 2, 1000, 0),
            ('信噪比(dB):', 2, 'snr', 20, -200, 200, 1),
            ('快拍数:', 3, 'K', 100, 1, 1_000_000, 0),
            ('来波方向(°):', 4, 'theta', 0, -180, 180, 1),
        ]
        self.spins = {}
        for name, row, key, default, minimum, maximum, decimals in params:
            layout.addWidget(QLabel(name), row, 0)
            s = QDoubleSpinBox()
            s.setRange(minimum, maximum)
            s.setValue(default)
            s.setDecimals(decimals)
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
        try:
            result = calculate_df_accuracy(
                baseline_lam=self.spins['d'].value(),
                element_count=self.spins['N'].value(),
                snr_db=self.spins['snr'].value(),
                snapshots=self.spins['K'].value(),
                theta_deg=self.spins['theta'].value(),
                algorithm=self.combo_algo.currentText(),
            )
        except (ValueError, OverflowError) as exc:
            self.last_result = None
            self._show_result([f'❌ {safe_exception_message(exc)}'])
            logger.warning('测向精度输入无效: %s', exc)
            return False

        self.last_result = result
        if result['singular']:
            error_line = '🔴 来波方向接近 ±90°，干涉仪公式奇异，误差发散'
        elif result['side_fire_warning']:
            error_line = (
                f'🟡 来波方向 {result["theta_deg"]:.1f}° 接近正侧射，'
                f'cos(θ)={result["cos_theta"]:.6g}，误差显著放大'
            )
        else:
            error_line = ''

        if result['is_music'] and not result['music_applicable']:
            music_line = f'🟡 MUSIC {result["music_status"]}，未施加 √N 增益'
        elif result['is_music']:
            music_line = (
                f'🟢 MUSIC {result["music_status"]}，'
                f'近似增益 √N={result["music_gain"]:.3f}'
            )
        else:
            music_line = 'MUSIC 未选择；当前结果为单基线干涉仪模型'

        lines = [
            '## 测向精度估算结果',
            f'**算法**: {result["algorithm"]}',
            f'**理论测向精度 (RMSE)**: {result["estimated_rmse_deg"]:.4f}°',
            f'**克拉美罗界 (CRB)**: {result["crb_deg"]:.4f}°',
            f'**CRB 中间量**: {result["crb_rad2"]:.6e} rad²',
            f'**角度误差单位**: RMSE/CRB 均换算为度（°）',
            '',
            '## 详细分析',
            f'**基线长度**: {result["baseline_lam"]:.2f} λ',
            f'**阵元数**: {result["element_count"]}',
            f'**无模糊范围**: ±{result["ambiguity_range_deg"]:.1f}°',
            f'**SNR 定义**: {result["snr_db"]:.1f} dB = '
            f'{result["snr_linear"]:.4g}（线性功率比）',
            f'**快拍数 K**: {result["snapshots"]}',
            f'**来波方向 θ**: {result["theta_deg"]:.1f}°，'
            f'cos(θ)={result["cos_theta"]:.6g}',
            f'**MUSIC 适用条件**: {music_line}',
        ]
        if error_line:
            lines.extend(['', error_line])
        lines.extend([
            '',
            '💡 CRB 是方差下界；显示值为 √CRB 换算的角度 RMSE（°）。',
            '💡 SNR提升10dB → 理论误差约降低√10 ≈ 3.16倍。',
        ])
        self._show_result(lines)
        return True
class _ArrayParamCalc(_BaseCalc):
    def __init__(self, parent=None):
        super().__init__('📊 阵列参数计算', parent)
        self.last_result = None
        self.set_formula(
            'ULA: θ3dB≈50.8/(N·d)    |    '
            'RECT: θ3dB=50.8/(M·dx), 50.8/(N·dy)    |    '
            'UCA: θ3dB≈50.8/(2R)'
        )

    def _build_inputs(self):
        layout = QGridLayout()

        layout.addWidget(QLabel('阵列构型:'), 0, 0)
        self.combo_config = QComboBox()
        self.combo_config.addItems(['均匀线阵(ULA)', '矩形面阵', '均匀圆阵(UCA)'])
        self.combo_config.currentIndexChanged.connect(self._on_config_change)
        layout.addWidget(self.combo_config, 0, 1)

        layout.addWidget(QLabel('阵元数:'), 1, 0)
        self.spin_N = QSpinBox()
        self.spin_N.setRange(2, 256)
        self.spin_N.setValue(8)
        layout.addWidget(self.spin_N, 1, 1)

        self.ula_d_label = QLabel('阵元间距:')
        self.spin_d = QDoubleSpinBox()
        self.spin_d.setRange(0.1, 10)
        self.spin_d.setValue(0.5)
        self.combo_d_unit = QComboBox()
        self.combo_d_unit.addItems(['λ', 'm'])
        layout.addWidget(self.ula_d_label, 2, 0)
        layout.addWidget(self.spin_d, 2, 1)
        layout.addWidget(self.combo_d_unit, 2, 2)

        self.uca_radius_label = QLabel('UCA半径(λ):')
        self.spin_radius = QDoubleSpinBox()
        self.spin_radius.setRange(0.1, 100)
        self.spin_radius.setValue(2.0)
        layout.addWidget(self.uca_radius_label, 5, 0)
        layout.addWidget(self.spin_radius, 5, 1)

        self.rect_rows_label = QLabel('行数:')
        self.spin_rows = QSpinBox()
        self.spin_rows.setRange(1, 256)
        self.spin_rows.setValue(2)
        layout.addWidget(self.rect_rows_label, 6, 0)
        layout.addWidget(self.spin_rows, 6, 1)

        self.rect_cols_label = QLabel('列数:')
        self.spin_cols = QSpinBox()
        self.spin_cols.setRange(1, 256)
        self.spin_cols.setValue(4)
        layout.addWidget(self.rect_cols_label, 7, 0)
        layout.addWidget(self.spin_cols, 7, 1)

        self.rect_dx_label = QLabel('X间距:')
        self.spin_dx = QDoubleSpinBox()
        self.spin_dx.setRange(0.1, 10)
        self.spin_dx.setValue(0.5)
        layout.addWidget(self.rect_dx_label, 8, 0)
        layout.addWidget(self.spin_dx, 8, 1)

        self.rect_dy_label = QLabel('Y间距:')
        self.spin_dy = QDoubleSpinBox()
        self.spin_dy.setRange(0.1, 10)
        self.spin_dy.setValue(0.5)
        layout.addWidget(self.rect_dy_label, 9, 0)
        layout.addWidget(self.spin_dy, 9, 1)

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
        layout.addWidget(self.btn_calc, 10, 0, 1, 3)

        self._on_config_change()
        self.main_layout.addLayout(layout)
        self.main_layout.addStretch()

    def _on_config_change(self):
        config = self.combo_config.currentText()
        is_ula = config.startswith('均匀线阵')
        is_rect = config.startswith('矩形面阵')
        is_uca = config.startswith('均匀圆阵')
        for widget in (
            self.ula_d_label, self.spin_d, self.combo_d_unit,
            self.uca_radius_label, self.spin_radius,
            self.rect_rows_label, self.spin_rows,
            self.rect_cols_label, self.spin_cols,
            self.rect_dx_label, self.spin_dx,
            self.rect_dy_label, self.spin_dy,
        ):
            widget.hide()
        if is_ula:
            for widget in (self.ula_d_label, self.spin_d, self.combo_d_unit):
                widget.show()
        elif is_rect:
            for widget in (
                self.rect_rows_label, self.spin_rows,
                self.rect_cols_label, self.spin_cols,
                self.rect_dx_label, self.spin_dx,
                self.rect_dy_label, self.spin_dy,
            ):
                widget.show()
        elif is_uca:
            self.uca_radius_label.show()
            self.spin_radius.show()

    def _spacing_lam(self, value):
        if self.combo_d_unit.currentText() == 'λ':
            return float(value)
        frequency_hz = self.spin_freq_arr.value() * (
            1e9 if self.combo_freq_arr.currentText() == 'GHz' else 1e6)
        return float(value) / (C / frequency_hz)

    def _on_calc(self):
        config = self.combo_config.currentText()
        frequency_hz = self.spin_freq_arr.value() * (
            1e9 if self.combo_freq_arr.currentText() == 'GHz' else 1e6)
        try:
            if config.startswith('矩形面阵'):
                rows = self.spin_rows.value()
                cols = self.spin_cols.value()
                result = calculate_array_parameters(
                    config=config,
                    element_count=rows * cols,
                    spacing_lam=self._spacing_lam(self.spin_d.value()),
                    frequency_hz=frequency_hz,
                    element_gain=self.spin_Ge.value(),
                    rows=rows,
                    cols=cols,
                    dx_lam=self._spacing_lam(self.spin_dx.value()),
                    dy_lam=self._spacing_lam(self.spin_dy.value()),
                )
            elif config.startswith('均匀圆阵'):
                result = calculate_array_parameters(
                    config=config,
                    element_count=self.spin_N.value(),
                    spacing_lam=self._spacing_lam(self.spin_d.value()),
                    frequency_hz=frequency_hz,
                    element_gain=self.spin_Ge.value(),
                    radius_lam=self.spin_radius.value(),
                )
            else:
                result = calculate_array_parameters(
                    config=config,
                    element_count=self.spin_N.value(),
                    spacing_lam=self._spacing_lam(self.spin_d.value()),
                    frequency_hz=frequency_hz,
                    element_gain=self.spin_Ge.value(),
                )
        except (ValueError, OverflowError) as exc:
            self.last_result = None
            self._show_result([f'❌ {safe_exception_message(exc)}'])
            logger.warning('阵列参数输入无效: %s', exc)
            return False

        self.last_result = result
        lines = [
            '## 阵列参数计算结果',
            f'**阵列构型**: {result["array_type"]}',
            f'**阵元数**: {result["element_count"]}',
            f'**阵列增益**: {result["gain_db"]:.2f} dBi',
            f'**3dB波束宽度**: {result["beamwidth_deg"]:.2f}°',
            f'**公式**: {result["formula"]}',
            f'**阵列孔径**: {result["aperture"]:.2f} λ',
        ]
        if result['array_type'] == 'RECT':
            lines.extend([
                f'**方位/俯仰波束宽度**: '
                f'{result["beamwidth_az_deg"]:.2f}° / '
                f'{result["beamwidth_el_deg"]:.2f}°',
                f'**X/Y孔径**: {result["aperture_x"]:.2f}λ / '
                f'{result["aperture_y"]:.2f}λ',
            ])
        lines.extend([
            '',
            '## 栅瓣分析',
            f'**状态**: {result["warning"]}',
            f'**第一个栅瓣位置**: '
            + (
                f'{result["grating_angle_deg"]:.1f}°'
                if result['grating_angle_deg'] is not None
                else '不适用'
            ),
            f'**无模糊范围**: '
            + (
                f'±{result["unambig_deg"]:.1f}°'
                if result['unambig_deg'] is not None
                else '圆阵按全角方向图评估'
            ),
        ])
        self._show_result(lines)
        return True
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
        try:
            B = _positive_value(self.spins['bw'].value() * 1e6, '接收带宽')
            NF = _finite_value(self.spins['nf'].value(), '噪声系数')
            Pr = _finite_value(self.spins['pr'].value(), '接收功率')
            T = _positive_value(self.spins['temp'].value(), '环境温度')
            N0 = -174
            Pn_dBm = N0 + 10 * math.log10(B) + NF
            SNR = Pr - Pn_dBm
            sens_10dB = Pn_dBm + 10
            noise_voltage = math.sqrt(
                K_BOLTZ * T * B * 10 ** (NF / 10) * 50) * 1e6
        except (ValueError, OverflowError, ZeroDivisionError) as exc:
            self._show_result([f'❌ {safe_exception_message(exc)}'])
            logger.warning('信噪比输入无效: %s', exc)
            return False

        self._show_result([
            f'## 信噪比计算结果',
            f'**噪声谱密度 N0**: {N0} dBm/Hz',
            f'**总噪声功率 Pn**: {Pn_dBm:.2f} dBm',
            f'**输入信号功率**: {Pr:.2f} dBm',
            f'**接收信噪比 SNR**: {SNR:.2f} dB',
            f'', f'## 灵敏度',
            f'**灵敏度 (SNR=10dB)**: {sens_10dB:.2f} dBm',
            f'', f'## 噪声电压 (50Ω)',
            f'**噪声电压有效值**: {noise_voltage:.2f} μV',
        ])
        return True
