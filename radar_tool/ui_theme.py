"""UI 主题令牌、全局 QSS 模板与按钮变体工具。

设计依据：``docs/设计文档/UI视觉规范V2.md`` §3（令牌）、§4（组件 QSS）、§6.2（插值）。

约定
----
* **颜色 / 字号 / 间距 / 圆角只有一个来源**：``TOKENS``。任何面板都不得写
  ``#RRGGBB`` 字面值，也不得写 ``setStyleSheet(...)``（``game_panel.py`` 豁免）。
* 需要"变体"时用属性选择器：``set_variant(btn, 'primary')`` 内部即
  ``setProperty('variant', ...)`` + ``repolish()``，QSS 侧是
  ``QPushButton[variant="primary"]``。
* 全局样式由 :func:`apply_global_theme` 挂到 ``QApplication`` 上，这样
  ``TaskCenterDialog`` 这类独立顶层窗口也能拿到同一套样式。
"""

from __future__ import annotations

from string import Template

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication, QStyle

# ==========================================================================
# §3 设计令牌（唯一真源）
# ==========================================================================

#: 字体族：中文/混排 与 纯数值（等宽）分开声明。
FONT_CJK = "'Microsoft YaHei UI', 'Microsoft YaHei', 'PingFang SC', 'Noto Sans CJK SC', sans-serif"
FONT_MONO = "'Cascadia Mono', 'Consolas', 'JetBrains Mono', monospace"

TOKENS = {
    # ---- §3.1 中性灰阶（10 档，冷灰 blue-cast，hue 210）----
    'n0': '#FFFFFF',
    'n100': '#F5F7FA',
    'n200': '#E7ECF2',
    'n300': '#D2DAE3',
    'n400': '#AEB9C6',
    'n500': '#8592A2',
    'n600': '#64717F',
    'n700': '#47525F',
    'n800': '#2C353F',
    'n900': '#111820',
    # ---- §3.2 表面与层次 ----
    'sApp': '#F5F7FA',      # L0 窗口
    'sPanel': '#FFFFFF',    # L1/L2/L4 白底
    'sInset': '#F7F9FB',    # L3 内嵌凹陷（表格区/结果区/图区/只读文本）
    'sHover': '#EFF3F8',    # 悬停底
    'sSel': '#E4EEF6',      # 选中底
    # ---- §3.3 语义色（4 组，每组 4 档）----
    'primary': '#2F6A8C',
    'primaryHv': '#3A7B9F',
    'primaryActive': '#24546F',
    'primaryBg': '#EAF2F7',
    'primaryBorder': '#BFD5E2',
    'primaryText': '#1F4A62',
    'success': '#1F7A57',
    'successBg': '#EAF3EE',
    'successBorder': '#A8CDBC',
    'successText': '#175C42',
    'warning': '#B07C16',
    'warningBg': '#FBF2DE',
    'warningBorder': '#E4C88C',
    'warningText': '#7A5409',
    'warningBgHv': '#F7E7CB',
    'danger': '#AC3B41',
    'dangerBg': '#FBEBEC',
    'dangerBorder': '#E2B0B3',
    'dangerText': '#85272C',
    'info': '#33668F',
    'infoBg': '#EDF2F8',
    'infoBorder': '#B9CCDF',
    'infoText': '#244C6D',
    # ---- §3.4 图表色板（matplotlib 专用，按序分配）----
    'chart1': '#2F6A8C',
    'chart2': '#C4661F',
    'chart3': '#2E8A6E',
    'chart4': '#A34A50',
    'chart5': '#6A5AA8',
    'chart6': '#7A6B3F',
    'chart7': '#3E8BA6',
    'chart8': '#6E6259',
    # ---- §3.5 字阶（QSS 值：pt）----
    'fs32': '24pt',
    'fs26': '19.5pt',
    'fs17': '13pt',
    'fs15': '11pt',
    'fs14': '10.5pt',
    'fs13': '10pt',
    'fs12': '9pt',
    'fs12s': '9pt',
    'fs11': '8.5pt',
    # ---- §3.6 间距 / 圆角 / 描边 / 尺寸 ----
    'sp1': '2px',
    'sp2': '4px',
    'sp3': '6px',
    'sp4': '8px',
    'sp5': '12px',
    'sp6': '16px',
    'r1': '2px',
    'r2': '4px',
    'r3': '6px',
    'bw': '1px',
    'hSm': '28px',
    'hMd': '32px',
    'hLg': '36px',
    'hPageHeader': '44px',
    'hKpi': '76px',
    'hStatus': '26px',
    'hTab': '36px',
    # ---- 字体族（供 QSS 插值）----
    'fontCJK': FONT_CJK,
    'fontMono': FONT_MONO,
}

#: 代码里（非 QSS）需要用到数值时走这两个表，避免面板出现魔法值。
FONT_SIZES_PX = {
    'fs32': 32, 'fs26': 26, 'fs17': 17, 'fs15': 15, 'fs14': 14,
    'fs13': 13, 'fs12': 12, 'fs12s': 12, 'fs11': 11,
}

SPACING_PX = {
    'sp1': 2, 'sp2': 4, 'sp3': 6, 'sp4': 8, 'sp5': 12, 'sp6': 16,
    'sp7': 20, 'sp8': 24, 'sp9': 32, 'sp10': 40,
}

SIZES_PX = {
    'hSm': 28, 'hMd': 32, 'hLg': 36, 'hPageHeader': 44, 'hKpi': 76,
    'hStatus': 26, 'hTab': 36, 'rowForm': 32, 'rowTable': 26, 'rowHead': 30,
    'iconSm': 14, 'iconMd': 16,
}

#: 图表色板（供 ``plotting`` / ``app_config`` / 3D 场景使用，禁止面板自取色）。
CHART_COLORS = [
    TOKENS['chart1'], TOKENS['chart2'], TOKENS['chart3'], TOKENS['chart4'],
    TOKENS['chart5'], TOKENS['chart6'], TOKENS['chart7'], TOKENS['chart8'],
]

# ==========================================================================
# §4 组件 QSS 模板（$name 占位，string.Template 插值）
# ==========================================================================

MAIN_STYLESHEET_TEMPLATE = """
/* ---------- 外壳 ---------- */
QMainWindow, QDialog {
    background: $sApp;
}
/* §6.4：QWidget 选择器只允许写 font-family，颜色/字号逐个控件 */
QWidget {
    font-family: $fontCJK;
}
QLabel { color: $n700; font-size: $fs13; background: transparent; }
QLabel:disabled { color: $n400; }

/* ---------- §4.1 页签 ---------- */
QTabWidget::pane {
    border: none;
    border-top: 1px solid $n200;
    background: $sPanel;
}
QTabWidget::tab-bar { background: transparent; }
QTabBar { background: transparent; }
QTabBar::tab {
    background: transparent;
    color: $n600;
    border: none;
    border-bottom: 2px solid transparent;
    padding: 0 14px;
    min-height: 34px;
    font-size: $fs13;
}
QTabBar::tab:hover { color: $n800; background: $sHover; }
QTabBar::tab:selected {
    color: $primary;
    border-bottom: 2px solid $primary;
    font-weight: 600;
}
QTabBar::tab:disabled { color: $n400; }
/* 窄屏（<1280px）：短页签名 + 9pt + 8px 内边距。
   实测 Microsoft YaHei 10pt 下 9 个全称页签共需 1471px，1024 窗口必然出
   滚动箭头；短名 + 9pt 后为 942px，可完整显示。全称由 tooltip 与页头承载。 */
QTabBar[compact="true"]::tab { padding: 0 8px; font-size: $fs12s; }
QTabBar[compact="true"]::tab:selected { font-weight: 600; }
QTabBar QToolButton {
    background: $n100;
    border: 1px solid $n200;
    border-radius: 2px;
    width: 24px;
}

/* ---------- §4.2 页面标题区 ---------- */
QWidget#pageHeader {
    background: $sPanel;
    border-bottom: 1px solid $n200;
    min-height: 43px;
}
QLabel#pageTitle { font-size: $fs17; font-weight: 600; color: $n900; }
QLabel#pageSubtitle { font-size: $fs12; color: $n600; }

/* ---------- §4.3 组框 / 卡头 ---------- */
QGroupBox {
    background: $sPanel;
    border: 1px solid $n200;
    border-radius: $r2;
    margin-top: 10px;
    padding: 10px 12px 12px 12px;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 10px;
    padding: 0 6px;
    background: $sPanel;
    color: $n800;
    font-size: $fs14;
    font-weight: 600;
}
QGroupBox:disabled { color: $n500; }

/* ---------- §4.7 按钮四变体 ---------- */
QPushButton {
    min-height: 30px;
    padding: 0 14px;
    background: $n0;
    color: $n800;
    border: 1px solid $n300;
    border-radius: $r2;
    font-size: $fs13;
}
QPushButton:hover { background: $sHover; border-color: $n400; }
QPushButton:pressed { background: $sSel; border-color: $primary; }
QPushButton:disabled {
    background: $n100; border-color: $n200; color: $n400;
}
QPushButton[variant="primary"] {
    background: $primary;
    border: 1px solid $primary;
    color: $n0;
    font-weight: 600;
}
QPushButton[variant="primary"]:hover {
    background: $primaryHv; border-color: $primaryHv;
}
QPushButton[variant="primary"]:pressed {
    background: $primaryActive; border-color: $primaryActive;
}
QPushButton[variant="primary"]:disabled {
    background: $n400; border-color: $n400; color: $n0;
}
QPushButton[variant="secondary"] {
    background: $n0; border: 1px solid $n300; color: $n800;
}
QPushButton[variant="ghost"] {
    background: transparent;
    border: 1px solid transparent;
    color: $primary;
    padding: 0 8px;
}
QPushButton[variant="ghost"]:hover { background: $sHover; }
QPushButton[variant="ghost"]:pressed { background: $sSel; }
QPushButton[variant="danger"] {
    background: $n0; border: 1px solid $dangerBorder; color: $dangerText;
}
QPushButton[variant="danger"]:hover { background: $dangerBg; }
QPushButton[variant="danger"]:pressed { background: $dangerBg; border-color: $danger; }
QPushButton[variant="warning"] {
    background: $warningBg; border: 1px solid $warningBorder; color: $warningText;
}
QPushButton[variant="warning"]:hover { background: $warningBgHv; }
QPushButton[variant="warning"]:pressed { background: $warningBgHv; border-color: $warning; }
QPushButton[compact="true"] { min-height: 24px; padding: 0 8px; }

QToolButton {
    background: transparent;
    border: 1px solid transparent;
    border-radius: $r1;
    padding: 2px 4px;
    color: $n700;
}
QToolButton:hover { background: $sHover; border-color: $n200; }
QToolButton:pressed { background: $sSel; }

/* ---------- §4.9 输入控件 ---------- */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateTimeEdit {
    min-height: 26px;
    padding: 0 8px;
    background: $n0;
    color: $n800;
    border: 1px solid $n300;
    border-radius: $r1;
    font-size: $fs13;
    selection-background-color: $sSel;
    selection-color: $n900;
}
QLineEdit:hover, QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover {
    border-color: $n400;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border-color: $primary;
}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {
    background: $n100; border-color: $n200; color: $n400;
}
QLineEdit[state="error"] { border-color: $danger; }
QLineEdit[readOnly="true"] { background: $sInset; color: $n600; }
QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: center right;
    width: 18px;
    border: none;
    background: transparent;
}
QComboBox QAbstractItemView {
    background: $n0;
    border: 1px solid $n300;
    border-radius: $r1;
    selection-background-color: $sSel;
    selection-color: $n900;
    outline: none;
}
QCheckBox, QRadioButton { spacing: 6px; font-size: $fs13; color: $n700; }
QCheckBox::indicator, QRadioButton::indicator {
    width: 14px; height: 14px;
    border: 1px solid $n300;
    border-radius: $r1;
    background: $n0;
}
QRadioButton::indicator { border-radius: 7px; }
QCheckBox::indicator:checked, QRadioButton::indicator:checked {
    background: $primary; border-color: $primary;
}
QCheckBox:disabled, QRadioButton:disabled { color: $n400; }

/* ---------- 只读文本 / 日志区（L3 凹陷） ---------- */
QTextEdit, QPlainTextEdit {
    background: $sInset;
    color: $n700;
    border: 1px solid $n200;
    border-radius: $r1;
    padding: 4px 6px;
    font-size: $fs13;
    selection-background-color: $sSel;
    selection-color: $n900;
}
QTextEdit[readOnly="true"], QPlainTextEdit[readOnly="true"] {
    background: $sInset; color: $n700;
}
QTextEdit[flat="true"], QPlainTextEdit[flat="true"] {
    border: none; background: transparent;
}

/* ---------- 列表 ---------- */
QListWidget, QTreeWidget, QTreeView {
    background: $n0;
    border: 1px solid $n200;
    border-radius: $r1;
    font-size: $fs13;
    outline: none;
    alternate-background-color: $sInset;
}
QListWidget::item, QTreeWidget::item {
    min-height: 26px;
    padding: 2px 8px;
    border: none;
    color: $n700;
}
QListWidget::item:hover, QTreeWidget::item:hover { background: $sHover; }
QListWidget::item:selected, QTreeWidget::item:selected {
    background: $sSel; color: $n900;
}
QHeaderView { background: $n100; }
QHeaderView::section {
    background: $n100;
    color: $n600;
    border: none;
    border-bottom: 1px solid $n300;
    padding: 0 10px;
    min-height: 29px;
    font-size: $fs12s;
    font-weight: 600;
}

/* ---------- §4.6 表格 ---------- */
QTableWidget, QTableView {
    background: $n0;
    alternate-background-color: $sInset;
    border: 1px solid $n200;
    border-radius: $r1;
    gridline-color: transparent;
    selection-background-color: $sSel;
    selection-color: $n900;
    font-size: $fs13;
    outline: none;
}
QTableWidget::item, QTableView::item {
    /* 6px 而非 10px：数值列在 10pt 等宽字体下 "-0.052" 占 78px，
       过多 padding 会把 88px 列的有效内容区压到 68px 并触发 Qt elide。 */
    padding: 0 6px;
    border: none;
    border-bottom: 1px solid $n200;
}
QTableWidget::item:selected, QTableView::item:selected {
    background: $sSel; color: $n900;
}
QTableCornerButton::section { background: $n100; border: none; }

/* ---------- §4.10 滚动条 ---------- */
QScrollBar:vertical {
    background: transparent; width: 10px; margin: 0; border: none;
}
QScrollBar::handle:vertical {
    background: $n300; min-height: 32px; border-radius: 5px;
}
QScrollBar::handle:vertical:hover { background: $n400; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0; width: 0; border: none;
}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }
QScrollBar:horizontal {
    background: transparent; height: 10px; margin: 0; border: none;
}
QScrollBar::handle:horizontal {
    background: $n300; min-width: 32px; border-radius: 5px;
}
QScrollBar::handle:horizontal:hover { background: $n400; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    height: 0; width: 0; border: none;
}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: none; }

/* ---------- 分隔条 ---------- */
QSplitter::handle { background: $n200; }
QSplitter::handle:horizontal { width: 1px; }
QSplitter::handle:vertical { height: 1px; }
QSplitter::handle:hover { background: $n300; }

/* ---------- §4.11 状态栏 ---------- */
QStatusBar {
    background: $n100;
    border-top: 1px solid $n200;
    min-height: 25px;
}
QStatusBar::item { border: none; }
QStatusBar QLabel { color: $n600; font-size: $fs12; }
QStatusBar QLabel#statusVersion {
    font-family: $fontMono;
    padding-right: 12px;
}
QStatusBar QLabel#statusTask { color: $primary; padding: 0 6px; }
QProgressBar {
    border: none;
    background: $n200;
    border-radius: $r1;
    max-height: 6px;
    text-align: center;
    font-size: $fs11;
    color: $n600;
}
QProgressBar::chunk { background: $primary; border-radius: 2px; }

/* ---------- §4 浮层：菜单 / 提示 / 对话框 ---------- */
QMenu {
    background: $sPanel;
    border: 1px solid $n300;
    border-radius: $r3;
    padding: 4px;
}
QMenu::item {
    padding: 6px 20px 6px 12px;
    border-radius: $r1;
    color: $n800;
    font-size: $fs13;
}
QMenu::item:selected { background: $sSel; color: $n900; }
QMenu::separator { height: 1px; background: $n200; margin: 4px 8px; }
QToolTip {
    background: $n800;
    color: $n0;
    border: none;
    border-radius: $r1;
    padding: 4px 6px;
    font-size: $fs12;
}

/* ---------- 结果卡（§4.5 / 信息呈现规范 §3） ---------- */
QFrame#resultCard {
    background: $sPanel;
    border: 1px solid $n200;
    border-radius: $r2;
}
QLabel#resultCardTitle { color: $n800; font-size: $fs14; font-weight: 600; }
QLabel#resultValue {
    color: $n900; font-size: $fs32; font-weight: 700; font-family: $fontMono;
}
QLabel#resultValue[state="empty"] { color: $n500; }
QLabel#resultValue[dense="true"] { font-size: $fs26; }
QLabel#resultValue[state="loading"] { color: $n600; font-size: $fs17; }
QLabel#resultValue[state="error"] { color: $dangerText; font-size: $fs17; }
QLabel#resultUnit { color: $n600; font-size: $fs14; }
QLabel#resultNote { color: $n600; font-size: $fs12; }
QFrame#paramRow { background: transparent; border: none; }
QFrame#paramRow[alt="true"] { background: $sInset; }
QLabel#paramKey { color: $n600; font-size: $fs13; }
QLabel#paramVal {
    color: $n800; font-size: $fs13; font-family: $fontMono;
}
QLabel#paramVal[state="muted"] { color: $n500; }
QLabel#paramGroup {
    color: $n600; font-size: $fs12s; font-weight: 600;
}
QFrame#hintBar {
    background: $infoBg;
    border: none;
    border-left: 3px solid $info;
    border-radius: $r1;
}
QFrame#hintBar[kind="warning"] {
    background: $warningBg; border-left: 3px solid $warning;
}
QFrame#hintBar[kind="danger"] {
    background: $dangerBg; border-left: 3px solid $danger;
}
QFrame#hintBar[kind="neutral"] {
    background: $n100; border-left: 3px solid $n300;
}
QLabel#hintText { color: $infoText; font-size: $fs12; }
QLabel#hintText[kind="warning"] { color: $warningText; }
QLabel#hintText[kind="danger"] { color: $dangerText; }
QLabel#hintText[kind="neutral"] { color: $n600; }

/* ---------- §4.4 KPI 卡 ---------- */
QFrame#kpiCard {
    background: $n0;
    border: 1px solid $n200;
    border-radius: $r2;
}
QFrame#kpiAccent { border: none; border-radius: 0; }
QFrame#kpiAccent[tone="primary"] { background: $primary; }
QFrame#kpiAccent[tone="success"] { background: $success; }
QFrame#kpiAccent[tone="warning"] { background: $warning; }
QFrame#kpiAccent[tone="neutral"] { background: $n300; }
QLabel#kpiLabel { color: $n600; font-size: $fs12s; font-weight: 600; }
QLabel#kpiValue {
    color: $n900; font-size: $fs26; font-weight: 700; font-family: $fontMono;
}
QLabel#kpiValue[state="empty"] { color: $n500; }
QLabel#kpiUnit { color: $n600; font-size: $fs12; }
QLabel#kpiHint { color: $n500; font-size: $fs12; }

/* ---------- §4.8 徽章 ---------- */
QLabel#badge {
    min-height: 18px;
    padding: 0 6px;
    border-radius: $r1;
    border: 1px solid $n200;
    background: $n100;
    color: $n600;
    font-size: $fs11;
    font-weight: 600;
}
QLabel#badge[tone="primary"] {
    background: $primaryBg; border-color: $primaryBorder; color: $primaryText;
}
QLabel#badge[tone="success"] {
    background: $successBg; border-color: $successBorder; color: $successText;
}
QLabel#badge[tone="warning"] {
    background: $warningBg; border-color: $warningBorder; color: $warningText;
}
QLabel#badge[tone="danger"] {
    background: $dangerBg; border-color: $dangerBorder; color: $dangerText;
}

/* ---------- §4.12 空态 / §4.13 错误态 ---------- */
QFrame#emptyState {
    background: $sInset;
    border: 1px dashed $n300;
    border-radius: $r1;
}
QLabel#emptyTitle { color: $n600; font-size: $fs13; }
QLabel#emptyHint { color: $n500; font-size: $fs12; }
QFrame#errorBar {
    background: $dangerBg;
    border: none;
    border-left: 3px solid $danger;
    border-radius: $r1;
    min-height: 28px;
}
QLabel#errorText { color: $dangerText; font-size: $fs12; }
QLabel#sectionTitle { color: $n800; font-size: $fs15; font-weight: 600; }
QLabel#errorPageTitle { color: $dangerText; font-size: $fs15; font-weight: 600; }
QLabel#textMuted { color: $n600; font-size: $fs12; }
QLabel#textMuted[tone="success"] { color: $successText; }
QLabel#textMuted[tone="warning"] { color: $warningText; }
QLabel#textMuted[tone="danger"] { color: $dangerText; }
QLabel#textMuted[tone="primary"] { color: $primaryText; }
QLabel#textMuted[tone="muted"] { color: $n500; }
QLabel#textHint { color: $n500; font-size: $fs12; }
QLabel#textStrong { color: $n800; font-weight: 600; }
/* 语义文字色：供状态标签使用，避免面板里再写 color: #RRGGBB */
QLabel#textPrimary { color: $primaryText; }
QLabel#textSuccess { color: $successText; }
QLabel#textWarning { color: $warningText; }
QLabel#textDanger { color: $dangerText; }
QLabel#textInfo { color: $infoText; }
QLabel#monoValue { font-family: $fontMono; color: $n800; }
QLabel#formulaLabel {
    background: $infoBg;
    color: $infoText;
    border: 1px solid $infoBorder;
    border-radius: $r1;
    padding: 6px 10px;
    font-family: $fontMono;
    font-size: $fs12;
}
QFrame#welcomeCard {
    background: $sPanel;
    border: 1px solid $n200;
    border-radius: $r2;
}
QFrame#card { background: $sPanel; border: 1px solid $n200; border-radius: $r2; }
QFrame#inset { background: $sInset; border: 1px solid $n200; border-radius: $r1; }

/* ---- 面板级语义组件：供各页替换历史内联 setStyleSheet 使用 ---- */
/* 语义文字色。tone 用 set_text_tone() / set_prop() 切换并自动 repolish。 */
QLabel#textTone { color: $n700; }
QLabel#textTone[tone="muted"]   { color: $n600; }
QLabel#textTone[tone="hint"]    { color: $n500; }
QLabel#textTone[tone="primary"] { color: $primaryText; }
QLabel#textTone[tone="success"] { color: $successText; }
QLabel#textTone[tone="warning"] { color: $warningText; }
QLabel#textTone[tone="danger"]  { color: $dangerText; }
QLabel#textBody { color: $n700; }

QFrame#featureCard {
    background: $sPanel;
    border: 1px solid $n200;
    border-radius: $r2;
    padding: 14px;
}
QFrame#featureCard:hover { background: $sInset; border-color: $n400; }
QFrame#stepCard {
    background: $sPanel;
    border: 1px solid $n200;
    border-radius: $r2;
    padding: 4px;
    margin: 2px;
}
QLabel#summaryTile {
    background: $sInset;
    border: 1px solid $n200;
    border-radius: $r2;
    padding: 5px;
    color: $n800;
}
QLabel#statusBadge {
    background: $n100; color: $n600;
    border: 1px solid $n200; border-radius: $r2;
    padding: 6px 10px; font-weight: 600;
}
QLabel#statusBadge[tone="running"] { background: $primaryBg; color: $primaryText; border-color: $primaryBorder; }
QLabel#statusBadge[tone="success"] { background: $successBg; color: $successText; border-color: $successBorder; }
QLabel#statusBadge[tone="error"]   { background: $dangerBg;  color: $dangerText;  border-color: $dangerBorder; }
QLabel#tipBar {
    background: $sInset; color: $n600;
    border: 1px solid $n200; border-radius: $r2;
    padding: 8px; font-size: $fs12;
}
QWidget#warningBanner { background: $warningBg; border-bottom: 2px solid $warning; }
QWidget#errorBanner   { background: $dangerBg;  border-bottom: 2px solid $danger; }
QPushButton#dangerIconButton {
    background: $dangerBg; color: $dangerText;
    border: none; border-radius: $r2;
}
QPushButton#dangerIconButton:hover { background: $dangerBorder; }
"""

MAIN_STYLESHEET = Template(MAIN_STYLESHEET_TEMPLATE).substitute(TOKENS)

#: 兼容旧名（历史上被 import 过）
STATUSBAR_STYLE = ''


# ==========================================================================
# §6.3 属性 + 重新抛光
# ==========================================================================

def repolish(widget):
    """属性变更后重新抛光，否则 QSS 属性选择器不会重绘。"""
    if widget is None:
        return
    style = widget.style()
    if style is not None:
        style.unpolish(widget)
        style.polish(widget)
    widget.update()


def set_variant(widget, variant):
    """设置 QSS 变体：``primary`` / ``secondary`` / ``ghost`` / ``danger`` / ``warning``。"""
    if widget is None:
        return
    widget.setProperty('variant', variant)
    repolish(widget)


def set_prop(widget, name, value):
    """设置任意 QSS 属性并重新抛光。"""
    if widget is None:
        return
    widget.setProperty(name, value)
    repolish(widget)


def set_text_tone(label, tone=''):
    """设置语义文字色，替代面板里的 ``setStyleSheet('color: #RRGGBB')``。

    ``tone`` ∈ {'', 'muted', 'hint', 'primary', 'success', 'warning', 'danger'}。
    内部走 ``set_prop`` 重新抛光，因此同一 label 在运行时反复切换状态也能生效。
    """
    if label is None:
        return
    label.setObjectName('textTone')
    set_prop(label, 'tone', tone)


def apply_global_theme(app=None):
    """把主题挂到 ``QApplication``（独立窗口也能拿到样式）。"""
    app = app or QApplication.instance()
    if app is None:
        return None
    app.setStyle('Fusion')
    app.setStyleSheet(MAIN_STYLESHEET)
    return app


# ==========================================================================
# 图标
# ==========================================================================

ICON_MAP = {
    'open': QStyle.SP_DialogOpenButton,
    'file': QStyle.SP_FileIcon,
    'delete': QStyle.SP_TrashIcon,
    'clear': QStyle.SP_DialogResetButton,
    'reload': QStyle.SP_BrowserReload,
    'apply': QStyle.SP_DialogApplyButton,
    'save': QStyle.SP_DialogSaveButton,
    'play': QStyle.SP_MediaPlay,
    'refresh': QStyle.SP_BrowserReload,
    'export': QStyle.SP_DialogSaveButton,
    'run': QStyle.SP_MediaPlay,
    'copy': QStyle.SP_FileDialogDetailedView,
}


def set_button_icon(button, icon_name):
    """Set a standard icon on a button by name."""
    icon_id = ICON_MAP.get(icon_name, QStyle.SP_FileIcon)
    button.setIcon(button.style().standardIcon(icon_id))


# ==========================================================================
# 按钮变体助手（函数名保持不变，内部改为 property + repolish）
# ==========================================================================

def style_primary_button(button):
    """主操作按钮（每页最多 1 个 primary 实心按钮）。"""
    set_variant(button, 'primary')
    button.setCursor(Qt.PointingHandCursor)


def style_warning_button(button):
    """警告/需确认动作：描边形态，不整块填充。"""
    set_variant(button, 'warning')
    button.setCursor(Qt.PointingHandCursor)


def style_calc_button(button):
    """计算器主执行按钮：primary 变体 + 36px 高（--h-lg）。

    V2 §4.7 / §8 禁止「控件拉满整行」：主按钮按内容定宽，上限 240px，
    而不是跟着 1000px 宽的表单容器一起拉伸。
    """
    set_variant(button, 'primary')
    button.setMinimumHeight(SIZES_PX['hLg'])
    button.setMaximumWidth(240)
    button.setCursor(Qt.PointingHandCursor)


# 历史常量：保留名字以免外部 import 失败，内容改为"空样式"提示。
PRIMARY_BUTTON_STYLE = ''
WARNING_BUTTON_STYLE = ''
CALC_BUTTON_STYLE = ''
