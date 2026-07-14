"""
UI theme, styles, and button helper utilities.
"""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QStyle


# ========== Theme Stylesheet ==========

MAIN_STYLESHEET = """
QMainWindow {
    background: #f5f7fb;
}
QWidget {
    font-family: 'Microsoft YaHei', 'PingFang SC', 'Noto Sans CJK SC', sans-serif;
    font-size: 10pt;
    color: #1f2937;
}
QGroupBox {
    border: 1px solid #d7dee9;
    border-radius: 10px;
    margin-top: 14px;
    background: #ffffff;
    font-weight: 600;
    padding-top: 10px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: #0f172a;
}
QPushButton {
    background: #ffffff;
    color: #1f2937;
    border: 1px solid #cfd8e3;
    border-radius: 8px;
    padding: 6px 10px;
    min-height: 28px;
}
QPushButton:hover {
    background: #eef4ff;
    color: #1e40af;
    border-color: #7c9cff;
}
QPushButton:pressed {
    background: #dbe7ff;
    color: #1e3a8a;
}
QPushButton:disabled {
    background: #f3f4f6;
    color: #9ca3af;
}
QLineEdit, QComboBox, QSpinBox, QTextEdit, QListWidget {
    background: #ffffff;
    border: 1px solid #d7dee9;
    border-radius: 8px;
    padding: 4px 8px;
    selection-background-color: #dbeafe;
    selection-color: #111827;
}
QListWidget::item {
    padding: 6px 8px;
    border-radius: 6px;
}
QListWidget::item:selected {
    background: #dbeafe;
    color: #111827;
}
QCheckBox {
    spacing: 6px;
}
QStatusBar {
    background: #eef2f7;
    border-top: 1px solid #d7dee9;
}
"""

STATUSBAR_STYLE = "color: #334155; font-size: 9pt;"

PRIMARY_BUTTON_STYLE = """
QPushButton {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #4f8cff, stop:1 #2f6fe4);
    color: white;
    border: 1.5px solid #1d4ed8;
    border-radius: 8px;
    padding: 7px 14px;
    min-height: 30px;
    font-weight: 600;
}
QPushButton:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #5f97ff, stop:1 #3b78eb);
    border: 1.5px solid #1e40af;
}
QPushButton:pressed {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #2563eb, stop:1 #1d4ed8);
    border: 1.5px solid #1e3a8a;
}
"""

WARNING_BUTTON_STYLE = """
QPushButton {
    background: #fff7ed;
    color: #9a3412;
    border: 1px solid #fdba74;
    border-radius: 8px;
    padding: 7px 12px;
    min-height: 30px;
    font-weight: 600;
}
QPushButton:hover {
    background: #ffedd5;
}
QPushButton:pressed {
    background: #fed7aa;
}
"""

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
}


def set_button_icon(button, icon_name):
    """Set a standard icon on a button by name."""
    icon_id = ICON_MAP.get(icon_name, QStyle.SP_FileIcon)
    button.setIcon(button.style().standardIcon(icon_id))


def style_primary_button(button):
    """Apply primary (blue) style to a button."""
    button.setStyleSheet(PRIMARY_BUTTON_STYLE)


def style_warning_button(button):
    """Apply warning (orange) style to a button."""
    button.setStyleSheet(WARNING_BUTTON_STYLE)


# ========== 计算器统一按钮风格 ==========

CALC_BUTTON_STYLE = """
QPushButton {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #2563eb, stop:1 #1d4ed8);
    color: white;
    border: 2px solid #1e40af;
    border-radius: 10px;
    padding: 12px 20px;
    min-height: 44px;
    font-size: 16px;
    font-weight: bold;
}
QPushButton:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #3b82f6, stop:1 #2563eb);
    border: 2px solid #1d4ed8;
}
QPushButton:pressed {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #1d4ed8, stop:1 #1e3a8a);
}
QPushButton:disabled {
    background: #94a3b8;
    border-color: #64748b;
    color: #e2e8f0;
}
"""


def style_calc_button(button):
    """为计算器按钮应用统一的醒目标记（大号蓝底渐变 + 白字）"""
    button.setStyleSheet(CALC_BUTTON_STYLE)
    button.setCursor(Qt.PointingHandCursor)
