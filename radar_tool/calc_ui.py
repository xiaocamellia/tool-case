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
from .ui_theme import set_variant, SIZES_PX
from .ui_result_card import PageHeader, ResultCard
from .fmt import num, num_fixed, count, sci
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

#: 界面显示单位 → 计算内核单位（N4：界面用 °C，内核历史实现用 ℃）
_UI_UNIT_TO_CALC = {'°C': '℃'}


def _ui_unit_to_calc(text):
    return _UI_UNIT_TO_CALC.get(text, text)

class CalcPanel(QWidget):
    """指标计算器合集主面板"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()
        logger.info('计算器合集已创建')

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # 页头（V2 §4.2：每页仅 1 个标题区）
        header = PageHeader('指标计算器', '7 个常用射频参数计算器；结果区为 L1 主结果 + 参数 + 提示')
        layout.addWidget(header)

        # 主区域
        splitter = QSplitter(Qt.Horizontal)

        # 左侧导航
        nav_widget = QWidget()
        nav_layout = QVBoxLayout(nav_widget)
        nav_layout.setContentsMargins(0, 0, 0, 0)
        nav_layout.setSpacing(6)
        nav_label = QLabel('计算器分类')
        nav_label.setObjectName('textMuted')
        nav_layout.addWidget(nav_label)

        self.nav_list = QListWidget()
        self.nav_list.setMinimumWidth(160)
        self.nav_list.setMaximumWidth(240)

        calculators = [
            ('单位转换器', 0),
            ('天线增益估算', 1),
            ('作用距离估算', 2),
            ('链路预算', 3),
            ('测向精度估算', 4),
            ('阵列参数计算', 5),
            ('信噪比计算', 6),
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
        splitter.setStretchFactor(1, 2)
        splitter.setChildrenCollapsible(False)
        splitter.setSizes([300, 1400])
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
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # 标题（--fs-15 / --n-800）
        lbl = QLabel(self.title)
        lbl.setObjectName('sectionTitle')
        layout.addWidget(lbl)

        # 可滚动的中间区
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        container = QWidget()
        self.main_layout = QVBoxLayout(container)
        self._build_inputs()
        scroll.setWidget(container)
        layout.addWidget(scroll, 1)

        # 公式显示区（--fs-12 等宽 / --info-bg 底，不再抢 L1 焦点）
        self.formula_label = QLabel()
        self.formula_label.setObjectName('formulaLabel')
        self.formula_label.setWordWrap(True)
        layout.addWidget(self.formula_label)

        # 结果区：L1 主结果 / L2 徽章 / L3 参数 / L4 提示
        # 属性名保持 result_text（测试与其它模块按此名引用，含 toPlainText()）
        self.result_text = ResultCard(title='计算结果')
        self.result_text.set_empty('录入参数后自动计算')
        layout.addWidget(self.result_text)

    def _build_inputs(self):
        """子类重写此方法构建输入控件，使用 self.main_layout 添加内容"""
        pass

    def set_formula(self, text):
        """设置当前显示的公式（去 emoji，公式用 `→` 不用 `->`）"""
        if text:
            self.formula_label.setText(str(text).replace('->', '→'))
        else:
            self.formula_label.setText('')

    def _show_result(self, lines):
        """显示结果 —— 阶段 A 迁移：旧 ## / ** / emoji 协议交给 ResultCard 解析。"""
        self.result_text.render_legacy(lines)

    # -- 阶段 B 助手：显式四层写入 ------------------------------------------
    def _set_error(self, message):
        self.result_text.set_error(safe_exception_message(message)
                                   if isinstance(message, BaseException)
                                   else str(message))

    def _set_result(self, title, value, unit=None, *, note=None, status=None,
                    params=None, hint=None, hint_kind='info', group=None):
        self.result_text.set_title(title)
        self.result_text.set_primary(value, unit, note=note, status=status)
        self.result_text.set_params(params or [], group=group)
        if hint:
            self.result_text.set_hint(hint_kind, hint)
class _UnitConverter(_BaseCalc):
    def __init__(self, parent=None):
        super().__init__('单位转换器', parent)
        self._update_formula(0)

    def _update_formula(self, idx):
        formulas = [
            '频率 → 波长: λ = c/f    |    波长 → 频率: f = c/λ',
            'dBm = 10·log10(P/1mW)    |    P(mW) = 10^(dBm/10)    |    P(W) = 10^((dBm-30)/10)',
            'rad = deg·π/180    |    deg = rad·180/π    |    mrad = rad·1000    |    rad = mrad/1000',
            '倍数 = 10^(dB/10)    |    dB = 10·log10(倍数)，倍数必须 > 0',
            'F = C·9/5+32    |    K = C+273.15    |    C = (F-32)·5/9',
            'V2 = V1 · (factor2/factor1)',
        ]
        self.set_formula(formulas[idx] if 0 <= idx < len(formulas) else '')

    def _build_inputs(self):
        layout = QVBoxLayout()
        layout.setSpacing(8)

        row0 = QHBoxLayout()
        type_label = QLabel('转换类型')
        type_label.setFixedWidth(96)
        row0.addWidget(type_label)
        self.combo_type = QComboBox()
        self.combo_type.addItems([
            '频率 ↔ 波长', '功率 ↔ dBm', '角度 ↔ 弧度',
            '增益 ↔ 倍数', '温度转换', '长度转换'
        ])
        self.combo_type.setMaximumWidth(320)
        self.combo_type.currentIndexChanged.connect(self._on_type_changed)
        row0.addWidget(self.combo_type)
        row0.addStretch(1)
        layout.addLayout(row0)

        row1 = QHBoxLayout()
        value_label = QLabel('输入值')
        value_label.setFixedWidth(96)
        row1.addWidget(value_label)
        self.input_val = QLineEdit('10')
        self.input_val.setPlaceholderText('请输入数值…')
        self.input_val.setMaximumWidth(320)
        row1.addWidget(self.input_val)
        row1.addStretch(1)
        layout.addLayout(row1)

        row2 = QHBoxLayout()
        from_label = QLabel('从')
        from_label.setFixedWidth(96)
        row2.addWidget(from_label)
        self.combo_from = QComboBox()
        self.combo_from.setMaximumWidth(320)
        row2.addWidget(self.combo_from)
        row2.addStretch(1)
        layout.addLayout(row2)

        row3 = QHBoxLayout()
        to_label = QLabel('到')
        to_label.setFixedWidth(96)
        row3.addWidget(to_label)
        self.combo_to = QComboBox()
        self.combo_to.setMaximumWidth(320)
        row3.addWidget(self.combo_to)
        row3.addStretch(1)
        layout.addLayout(row3)

        # 主转换按钮（每页唯一 primary 实心按钮）
        self.btn_calc = QPushButton('执行转换')
        self.btn_calc.clicked.connect(self._on_calc)
        style_calc_button(self.btn_calc)
        layout.addWidget(self.btn_calc)

        # 辅助按钮行（secondary）
        quick_btn_layout = QHBoxLayout()
        quick_btn_layout.setSpacing(8)
        self.btn_clear = QPushButton('清空')
        set_variant(self.btn_clear, 'secondary')
        self.btn_clear.clicked.connect(self._clear_input)
        quick_btn_layout.addWidget(self.btn_clear)

        self.btn_swap = QPushButton('互换单位')
        set_variant(self.btn_swap, 'secondary')
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
            4: ['°C', '℉', 'K'],
            5: ['m', 'cm', 'mm', 'km', '英寸', '英尺'],
        }
        units = units_map.get(idx, ['m', 'cm'])
        self.combo_from.addItems(units)
        self.combo_to.addItems(units)
        if len(units) > 1:
            self.combo_to.setCurrentIndex(1)

    def _on_calc(self):
        source_display = self.combo_from.currentText()
        target_display = self.combo_to.currentText()
        try:
            value = float(self.input_val.text())
            category = self.combo_type.currentIndex()
            source_unit = _ui_unit_to_calc(source_display)
            target_unit = _ui_unit_to_calc(target_display)
            result = convert_unit(
                category, value, source_unit, target_unit)
        except (ValueError, OverflowError, ZeroDivisionError) as exc:
            self._set_error(exc)
            logger.warning('单位转换输入无效: %s', exc)
            return False

        hint = ('按 c = 2.998×10⁸ m/s 计算的近似值，有效数字 3 位。'
                if category in (0, 5) else '有效数字 3 位；单位与数值已分离显示。')
        self._set_result(
            '转换结果',
            num(result),
            target_display,
            params=[
                ('输入值', f'{num(value)} {source_display}'),
                ('换算类型', self.combo_type.currentText()),
            ],
            hint=hint,
        )
        return True
class _AntennaGainCalc(_BaseCalc):
    def __init__(self, parent=None):
        super().__init__('天线增益估算', parent)
        self.set_formula('G(dBi) = 10·log10(4π·Ae/λ²) = 10·log10(η·(π·D/λ)²)    |    θ3dB ≈ 70·λ/D')

    def _build_inputs(self):
        layout = QGridLayout()
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(8)
        for row, text in enumerate(('工作频率', '口径直径', '口径效率', '口径形状')):
            label = QLabel(text)
            label.setObjectName('textMuted')
            layout.addWidget(label, row, 0)
        self.spin_freq = QDoubleSpinBox()
        self.spin_freq.setRange(0.01, 1000)
        self.spin_freq.setValue(10)
        self.spin_freq.setMaximumWidth(320)
        layout.addWidget(self.spin_freq, 0, 1)
        self.combo_freq_unit = QComboBox()
        self.combo_freq_unit.addItems(['GHz', 'MHz'])
        self.combo_freq_unit.setMaximumWidth(96)
        layout.addWidget(self.combo_freq_unit, 0, 2)

        self.spin_d = QDoubleSpinBox()
        self.spin_d.setRange(0.001, 100)
        self.spin_d.setValue(0.5)
        self.spin_d.setMaximumWidth(320)
        layout.addWidget(self.spin_d, 1, 1)
        self.combo_d_unit = QComboBox()
        self.combo_d_unit.addItems(['m', 'cm', 'mm'])
        self.combo_d_unit.setMaximumWidth(96)
        layout.addWidget(self.combo_d_unit, 1, 2)

        self.spin_eff = QSpinBox()
        self.spin_eff.setRange(10, 100)
        self.spin_eff.setValue(60)
        self.spin_eff.setSuffix(' %')
        self.spin_eff.setMaximumWidth(320)
        layout.addWidget(self.spin_eff, 2, 1)

        self.combo_shape = QComboBox()
        self.combo_shape.addItems(['圆形', '矩形', '椭圆形'])
        self.combo_shape.setMaximumWidth(320)
        layout.addWidget(self.combo_shape, 3, 1, 1, 2)

        self.btn_calc = QPushButton('计算增益')
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
            self._set_error(exc)
            logger.warning('天线增益输入无效: %s', exc)
            return False

        self._set_result(
            '天线增益',
            num_fixed(G_dBi, 1),
            'dBi',
            note=f'= {num_fixed(G_lin, 1)} 倍',
            params=[
                ('3dB 波束宽度', num_fixed(theta_3dB, 1, unit='°')),
                ('第一副瓣电平', num_fixed(-13.2, 1, unit='dB')),
                ('工作频率', f'{num(self.spin_freq.value())} '
                             f'{self.combo_freq_unit.currentText()}'),
                ('波长 λ', num_fixed(lam * 1000, 2, unit='mm')),
                ('口径直径', f'{num(self.spin_d.value())} '
                             f'{self.combo_d_unit.currentText()}'),
                ('口径效率', num_fixed(eff, 2)),
                ('口径面积', num(area, unit='m²')),
                ('有效面积', num(A_eff, unit='m²')),
            ],
            hint='均匀照射假设；实际增益需计入馈线损耗与照射锥削。',
        )
        return True
class _RadarRangeCalc(_BaseCalc):
    def __init__(self, parent=None):
        super().__init__('作用距离估算（雷达方程）', parent)
        self.set_formula('Rmax = [Pt·Gt·Gr·λ²·σ / ((4π)³·k·T0·B·NF·SNRmin·L)]^(1/4)')

    def _build_inputs(self):
        layout = QGridLayout()
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(8)
        params = [
            ('发射功率 (W)', 0, 'power', 100),
            ('发射增益 (dBi)', 1, 'gt', 30),
            ('接收增益 (dBi)', 2, 'gr', 30),
            ('工作频率 (GHz)', 3, 'freq', 10),
            ('目标 RCS (m²)', 4, 'rcs', 1),
            ('带宽 (MHz)', 5, 'bw', 10),
            ('噪声系数 (dB)', 6, 'nf', 3),
            ('检测 SNR (dB)', 7, 'snr', 10),
            ('系统损耗 (dB)', 8, 'loss', 3),
        ]
        self.spins = {}
        for name, row, key, default in params:
            label = QLabel(name)
            label.setObjectName('textMuted')
            layout.addWidget(label, row, 0)
            s = QDoubleSpinBox()
            s.setRange(0.001, 1e6)
            s.setValue(default)
            s.setMaximumWidth(320)
            layout.addWidget(s, row, 1)
            self.spins[key] = s

        self.btn_calc = QPushButton('计算距离')
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
            self._set_error(exc)
            logger.warning('作用距离输入无效: %s', exc)
            return False

        self._set_result(
            '雷达作用距离',
            num_fixed(R_max / 1000, 1),
            'km',
            note=f'= {num(R_max, unit="m")}',
            params=[
                ('10 km 处 SNR', num_fixed(10 * math.log10(SNR_10km), 1, unit='dB')),
                ('噪声功率 Pn', num_fixed(10 * math.log10(Pn / 0.001), 1, unit='dBm')),
                ('10 km 处接收功率',
                 num_fixed(10 * math.log10(Pr_10km / 0.001), 1, unit='dBm')),
                ('功率 ×4 的距离倍率', num_fixed(4 ** 0.25, 2)),
                ('增益 ×4 的距离倍率', num_fixed(4 ** 0.25, 2)),
                ('RCS ×4 的距离倍率', num_fixed(4 ** 0.25, 2)),
            ],
            hint='探测距离对 RCS 呈 4 次根关系，RCS 项灵敏度最高，参数不确定时优先核定 RCS。',
            hint_kind='warning',
        )
        return True
class _LinkBudgetCalc(_BaseCalc):
    def __init__(self, parent=None):
        super().__init__('链路预算', parent)
        self.last_result = None
        self.set_formula(
            'Pr(dBm) = Pt+Gt-Lt-Lfs+Gr-Lr    |    '
            'Lfs = 20·log10(4πd/λ)    |    '
            'Eb/N0 = C/N - 10·log10(B/Rb)    |    '
            '余量 = Eb/N0 - EbN0_req'
        )

    def _build_inputs(self):
        layout = QGridLayout()
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(8)
        params = [
            ('发射功率 (dBm)', 0, 'pt', 30),
            ('发射增益 (dBi)', 1, 'gt', 20),
            ('发射馈线损耗 (dB)', 2, 'lt', 2),
            ('频率 (GHz)', 3, 'freq', 10),
            ('距离 (km)', 4, 'dist', 10),
            ('接收增益 (dBi)', 5, 'gr', 20),
            ('接收馈线损耗 (dB)', 6, 'lr', 2),
            ('噪声系数 (dB)', 7, 'nf', 3),
            ('带宽 (MHz)', 8, 'bw', 10),
            ('所需 Eb/N0 (dB)', 9, 'ebn0', 10),
            ('码率 (bps)', 10, 'rb', 10_000_000),
        ]
        self.spins = {}
        for name, row, key, default in params:
            label = QLabel(name)
            label.setObjectName('textMuted')
            layout.addWidget(label, row, 0)
            s = QDoubleSpinBox()
            if key == 'rb':
                s.setRange(-1e12, 1e12)
                s.setDecimals(0)
            else:
                s.setRange(-100, 200)
            s.setValue(default)
            s.setMaximumWidth(320)
            layout.addWidget(s, row, 1)
            self.spins[key] = s

        self.btn_calc = QPushButton('计算链路')
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
            self._set_error(exc)
            logger.warning('链路预算输入无效: %s', exc)
            return False

        self.last_result = result
        margin = result['margin_db']
        if margin > 5:
            status = ('余量充足', 'success')
            hint_kind, hint = 'info', f'余量 {num_fixed(margin, 1, unit="dB")}，满足 3 dB 门限。'
        elif margin > 0:
            status = ('余量临界', 'warning')
            hint_kind, hint = 'warning', (
                f'余量 {num_fixed(margin, 1, unit="dB")} 低于 5 dB 建议值，'
                '优先提高 EIRP 或缩短距离。')
        else:
            status = ('链路不足', 'danger')
            hint_kind, hint = 'danger', (
                f'余量 {num_fixed(margin, 1, unit="dB")} 小于 0，'
                '链路无法闭合：需提高 EIRP、降低码率或缩短距离。')

        self._set_result(
            '链路预算',
            num_fixed(margin, 1),
            'dB',
            note='链路余量',
            status=status,
            params=[
                ('发射端 EIRP',
                 num_fixed(self.spins['pt'].value() + self.spins['gt'].value()
                           - self.spins['lt'].value(), 1, unit='dBm')),
                ('自由空间损耗', num_fixed(result['free_space_loss_db'], 1, unit='dB')),
                ('接收功率 Pr', num_fixed(result['receive_power_dbm'], 1, unit='dBm')),
                ('噪声功率 Pn', num_fixed(result['noise_power_dbm'], 1, unit='dBm')),
                ('载噪比 C/N', num_fixed(result['carrier_to_noise_db'], 1, unit='dB')),
                ('Eb/N0', num_fixed(result['eb_to_n0_db'], 1, unit='dB')),
                ('Eb/N0 需求', num_fixed(result['ebn0_req_db'], 1, unit='dB')),
                ('频率', num(self.spins['freq'].value(), unit='GHz')),
                ('带宽', num(self.spins['bw'].value(), unit='MHz')),
                ('码率', count(result['rate_bps'], 'bps')),
            ],
            hint=hint,
            hint_kind=hint_kind,
        )
        return True
class _DFAccuracyCalc(_BaseCalc):
    def __init__(self, parent=None):
        super().__init__('测向精度估算', parent)
        self.last_result = None
        self.set_formula(
            'σ_int(rad) = 1/[2π·d·cos(θ)·√(2·SNR_lin)]    |    '
            'CRB(rad²) = 1/[K·SNR_lin·8π²·d²·cos²(θ)]    |    '
            'SNR_lin = 10^(SNR_dB/10)，K = 快拍数'
        )

    def _build_inputs(self):
        layout = QGridLayout()
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(8)
        params = [
            ('基线长度 (λ)', 0, 'd', 0.5, 0.01, 1000, 1),
            ('阵元数', 1, 'N', 4, 2, 1000, 0),
            ('信噪比 (dB)', 2, 'snr', 20, -200, 200, 1),
            ('快拍数', 3, 'K', 100, 1, 1_000_000, 0),
            ('来波方向 (°)', 4, 'theta', 0, -180, 180, 1),
        ]
        self.spins = {}
        for name, row, key, default, minimum, maximum, decimals in params:
            label = QLabel(name)
            label.setObjectName('textMuted')
            layout.addWidget(label, row, 0)
            s = QDoubleSpinBox()
            s.setRange(minimum, maximum)
            s.setValue(default)
            s.setDecimals(decimals)
            s.setMaximumWidth(320)
            layout.addWidget(s, row, 1)
            self.spins[key] = s

        self.combo_algo = QComboBox()
        self.combo_algo.addItems(['相位干涉仪', 'MUSIC算法'])
        self.combo_algo.setMaximumWidth(320)
        algo_label = QLabel('算法')
        algo_label.setObjectName('textMuted')
        layout.addWidget(algo_label, 5, 0)
        layout.addWidget(self.combo_algo, 5, 1)

        self.btn_calc = QPushButton('计算精度')
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
            self._set_error(exc)
            logger.warning('测向精度输入无效: %s', exc)
            return False

        self.last_result = result
        hint_kind = 'info'
        hints = []
        if result['singular']:
            status = ('奇异', 'danger')
            hint_kind = 'danger'
            hints.append('来波方向接近 ±90°，干涉仪公式奇异，误差发散。')
        elif result['side_fire_warning']:
            status = ('临界', 'warning')
            hint_kind = 'warning'
            hints.append(
                f'来波方向 {num_fixed(result["theta_deg"], 1, unit="°")} 接近正侧射，'
                f'cos(θ)={num(result["cos_theta"])}，误差显著放大。')
        else:
            status = ('正常', 'success')

        if result['is_music'] and not result['music_applicable']:
            music_line = f'{result["music_status"]}，未施加 √N 增益'
        elif result['is_music']:
            music_line = (f'{result["music_status"]}，近似增益 '
                          f'√N={num_fixed(result["music_gain"], 3)}')
        else:
            music_line = '未选择（单基线干涉仪模型）'

        hints.append('CRB 是方差下界；显示值为 √CRB 换算的角度 RMSE（°）。')
        self._set_result(
            '测向精度估算',
            num_fixed(result['estimated_rmse_deg'], 2),
            '°',
            note='RMSE',
            status=status,
            params=[
                ('克拉美罗界 (CRB)', num_fixed(result['crb_deg'], 2, unit='°')),
                ('来波方位 θ', num_fixed(result['theta_deg'], 1, unit='°')),
                ('基线 d/λ', num_fixed(result['baseline_lam'], 2)),
                ('阵元数', count(result['element_count'])),
                ('快拍数 K', count(result['snapshots'])),
                ('SNR', num_fixed(result['snr_db'], 1, unit='dB')),
                ('无模糊范围', f'±{num_fixed(result["ambiguity_range_deg"], 1, unit="°")}'),
                ('算法', result['algorithm']),
                ('MUSIC 适用条件', music_line),
            ],
            hint=' '.join(hints),
            hint_kind=hint_kind,
        )
        return True
class _ArrayParamCalc(_BaseCalc):
    def __init__(self, parent=None):
        super().__init__('阵列参数计算', parent)
        self.last_result = None
        self.set_formula(
            'ULA: θ3dB ≈ 50.8/(N·d)    |    '
            'RECT: θ3dB = 50.8/(M·dx), 50.8/(N·dy)    |    '
            'UCA: θ3dB ≈ 50.8/(2R)'
        )

    def _build_inputs(self):
        layout = QGridLayout()

        layout.addWidget(QLabel('阵列构型'), 0, 0)
        self.combo_config = QComboBox()
        self.combo_config.addItems(['均匀线阵(ULA)', '矩形面阵', '均匀圆阵(UCA)'])
        self.combo_config.currentIndexChanged.connect(self._on_config_change)
        layout.addWidget(self.combo_config, 0, 1)

        layout.addWidget(QLabel('阵元数'), 1, 0)
        self.spin_N = QSpinBox()
        self.spin_N.setRange(2, 256)
        self.spin_N.setValue(8)
        layout.addWidget(self.spin_N, 1, 1)

        self.ula_d_label = QLabel('阵元间距')
        self.spin_d = QDoubleSpinBox()
        self.spin_d.setRange(0.1, 10)
        self.spin_d.setValue(0.5)
        self.combo_d_unit = QComboBox()
        self.combo_d_unit.addItems(['λ', 'm'])
        layout.addWidget(self.ula_d_label, 2, 0)
        layout.addWidget(self.spin_d, 2, 1)
        layout.addWidget(self.combo_d_unit, 2, 2)

        self.uca_radius_label = QLabel('UCA半径(λ)')
        self.spin_radius = QDoubleSpinBox()
        self.spin_radius.setRange(0.1, 100)
        self.spin_radius.setValue(2.0)
        layout.addWidget(self.uca_radius_label, 5, 0)
        layout.addWidget(self.spin_radius, 5, 1)

        self.rect_rows_label = QLabel('行数')
        self.spin_rows = QSpinBox()
        self.spin_rows.setRange(1, 256)
        self.spin_rows.setValue(2)
        layout.addWidget(self.rect_rows_label, 6, 0)
        layout.addWidget(self.spin_rows, 6, 1)

        self.rect_cols_label = QLabel('列数')
        self.spin_cols = QSpinBox()
        self.spin_cols.setRange(1, 256)
        self.spin_cols.setValue(4)
        layout.addWidget(self.rect_cols_label, 7, 0)
        layout.addWidget(self.spin_cols, 7, 1)

        self.rect_dx_label = QLabel('X间距')
        self.spin_dx = QDoubleSpinBox()
        self.spin_dx.setRange(0.1, 10)
        self.spin_dx.setValue(0.5)
        layout.addWidget(self.rect_dx_label, 8, 0)
        layout.addWidget(self.spin_dx, 8, 1)

        self.rect_dy_label = QLabel('Y间距')
        self.spin_dy = QDoubleSpinBox()
        self.spin_dy.setRange(0.1, 10)
        self.spin_dy.setValue(0.5)
        layout.addWidget(self.rect_dy_label, 9, 0)
        layout.addWidget(self.spin_dy, 9, 1)

        layout.addWidget(QLabel('工作频率'), 3, 0)
        self.spin_freq_arr = QDoubleSpinBox()
        self.spin_freq_arr.setRange(0.01, 100)
        self.spin_freq_arr.setValue(10)
        layout.addWidget(self.spin_freq_arr, 3, 1)
        self.combo_freq_arr = QComboBox()
        self.combo_freq_arr.addItems(['GHz', 'MHz'])
        layout.addWidget(self.combo_freq_arr, 3, 2)

        layout.addWidget(QLabel('阵元增益'), 4, 0)
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
                self.combo_d_unit,  # CC-02: 矩形模式也显示单位框
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
            self._set_error(exc)
            logger.warning('阵列参数输入无效: %s', exc)
            return False

        self.last_result = result
        params = [
            ('阵列构型', str(result['array_type'])),
            ('阵元数', count(result['element_count'])),
            ('3dB 波束宽度', num_fixed(result['beamwidth_deg'], 1, unit='°')),
            ('阵列孔径', num_fixed(result['aperture'], 2, unit='λ')),
        ]
        if result['array_type'] == 'RECT':
            params.extend([
                ('方位波束宽度', num_fixed(result['beamwidth_az_deg'], 1, unit='°')),
                ('俯仰波束宽度', num_fixed(result['beamwidth_el_deg'], 1, unit='°')),
                ('X 孔径', num_fixed(result['aperture_x'], 2, unit='λ')),
                ('Y 孔径', num_fixed(result['aperture_y'], 2, unit='λ')),
            ])
        params.extend([
            ('栅瓣状态', str(result['warning'])),
            ('第一个栅瓣位置',
             num_fixed(result['grating_angle_deg'], 1, unit='°')
             if result['grating_angle_deg'] is not None else '不适用'),
            ('无模糊范围',
             f'±{num_fixed(result["unambig_deg"], 1, unit="°")}'
             if result['unambig_deg'] is not None else '圆阵按全角方向图评估'),
        ])
        self._set_result(
            '阵列参数',
            num_fixed(result['gain_db'], 1),
            'dBi',
            note='阵列增益',
            params=params,
            hint=f'波束宽度估算式：{result["formula"]}',
        )
        return True
class _SNRCalc(_BaseCalc):
    def __init__(self, parent=None):
        super().__init__('信噪比计算', parent)
        self.set_formula('Pn(dBm) = -174 + 10·log10(B) + NF    |    SNR(dB) = Pr - Pn    |    N0 = -174 dBm/Hz')

    def _build_inputs(self):
        layout = QGridLayout()
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(8)
        params = [
            ('接收带宽 (MHz)', 0, 'bw', 10),
            ('噪声系数 (dB)', 1, 'nf', 3),
            ('接收功率 (dBm)', 2, 'pr', -80),
            ('环境温度 (K)', 3, 'temp', 290),
        ]
        self.spins = {}
        for name, row, key, default in params:
            label = QLabel(name)
            label.setObjectName('textMuted')
            layout.addWidget(label, row, 0)
            s = QDoubleSpinBox()
            s.setRange(-200, 200)
            s.setValue(default)
            s.setMaximumWidth(320)
            layout.addWidget(s, row, 1)
            self.spins[key] = s

        self.btn_calc = QPushButton('计算信噪比')
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
            self._set_error(exc)
            logger.warning('信噪比输入无效: %s', exc)
            return False

        self._set_result(
            '接收信噪比',
            num_fixed(SNR, 1),
            'dB',
            params=[
                ('灵敏度（SNR=10 dB）', num_fixed(sens_10dB, 1, unit='dBm')),
                ('噪声谱密度 N0', num_fixed(N0, 1, unit='dBm/Hz')),
                ('总噪声功率 Pn', num_fixed(Pn_dBm, 1, unit='dBm')),
                ('输入信号功率', num_fixed(Pr, 1, unit='dBm')),
                ('噪声电压有效值', num_fixed(noise_voltage, 2, unit='μV')),
            ],
        )
        return True
