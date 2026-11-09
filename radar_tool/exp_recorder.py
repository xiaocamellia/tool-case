"""
试验记录助手 - Experiment Recording Assistant
基于 PyQt5，用于外场/暗室试验的结构化记录与报告导出
"""

import os
import json
import datetime
import hashlib
import shutil
import re
import stat
import struct
import copy
import ntpath
from typing import Any
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox,
    QPushButton, QLabel, QFileDialog, QComboBox, QDoubleSpinBox,
    QSpinBox, QMessageBox, QTextEdit, QTabWidget, QSplitter,
    QFrame, QListWidget, QListWidgetItem, QAbstractItemView,
    QLineEdit, QDialog, QFormLayout, QDialogButtonBox, QDateEdit,
    QScrollArea, QMenu, QAction, QInputDialog, QCheckBox
)
from PyQt5.QtCore import Qt, QDate, QTimer
from PyQt5.QtGui import QFont, QColor, QPixmap
from datetime import date

Document: Any = None
Inches: Any = lambda value: value
Pt: Any = lambda value: value
Cm: Any = lambda value: value
Emu: Any = lambda value: value
RGBColor: Any = lambda red, green, blue: (red, green, blue)
WD_ALIGN_PARAGRAPH: Any = None
WD_LINE_SPACING: Any = None
WD_TABLE_ALIGNMENT: Any = None
WD_ORIENT: Any = None
qn: Any = None
OxmlElement: Any = None

try:
    from docx import Document as _Document
    from docx.shared import Inches as _Inches, Pt as _Pt, Cm as _Cm
    from docx.shared import RGBColor as _RGBColor, Emu as _Emu
    from docx.enum.text import (
        WD_ALIGN_PARAGRAPH as _WD_ALIGN_PARAGRAPH,
        WD_LINE_SPACING as _WD_LINE_SPACING,
    )
    from docx.enum.table import WD_TABLE_ALIGNMENT as _WD_TABLE_ALIGNMENT
    from docx.enum.section import WD_ORIENT as _WD_ORIENT
    from docx.oxml.ns import qn as _qn
    from docx.oxml import OxmlElement as _OxmlElement

    Document = _Document
    Inches, Pt, Cm, Emu = _Inches, _Pt, _Cm, _Emu
    RGBColor = _RGBColor
    WD_ALIGN_PARAGRAPH = _WD_ALIGN_PARAGRAPH
    WD_LINE_SPACING = _WD_LINE_SPACING
    WD_TABLE_ALIGNMENT = _WD_TABLE_ALIGNMENT
    WD_ORIENT = _WD_ORIENT
    qn, OxmlElement = _qn, _OxmlElement
except ModuleNotFoundError:
    pass

from .ui_theme import (
    set_button_icon, style_primary_button, style_warning_button, style_calc_button
)
from .error_ui import handle_ui_exception
from .errors import ExportError, safe_exception_message
from .logger import get_logger
from .schemas import ProjectRecord, SCHEMA_VERSION, migrate_schema
from .runtime_paths import get_user_data_dir, get_resource_path

logger = get_logger('exp_recorder')

DATA_DIR = get_user_data_dir('试验数据')
os.makedirs(DATA_DIR, exist_ok=True)
IMAGES_DIR = os.path.join(DATA_DIR, 'images')
os.makedirs(IMAGES_DIR, exist_ok=True)

EXPERIMENTS_SCHEMA_VERSION = SCHEMA_VERSION
EXPERIMENTS_SCHEMA_KEYS = {'schema_version', 'projects'}
EXPERIMENT_ID_PATTERN = re.compile(r'[A-Za-z0-9_-]{1,128}')
SUPPORTED_IMAGE_FORMATS = {'.png', '.jpg', '.jpeg', '.bmp', '.tif', '.tiff', '.webp'}
MAX_IMAGE_FILE_SIZE = 50 * 1024 * 1024
MAX_IMAGE_PIXELS = 50_000_000
MAX_IMAGE_HEADER_BYTES = 1024 * 1024
MAX_TIFF_DIRECTORY_ENTRIES = 4096
MAX_JSON_FILE_SIZE = 10 * 1024 * 1024

from . import experiment_images as _image_helpers
from . import experiment_schema as _schema_helpers
from . import experiment_storage as _storage_helpers

def _reject_json_constant(value):
    return _storage_helpers._reject_json_constant(value)

def _validate_json_depth(value, depth=1):
    return _storage_helpers._validate_json_depth(value, depth)

def _read_json_with_limits(filepath, validator=None):
    return _storage_helpers._read_json_with_limits(filepath, validator)

def _quarantine_corrupt_file(filepath):
    return _storage_helpers._quarantine_corrupt_file(filepath)

def _backup_valid_json(filepath, validator):
    return _storage_helpers._backup_valid_json(filepath, validator)

def validate_experiment_id(value, field_name=None):
    if field_name is None:
        field_name = "ID"
    return _schema_helpers.validate_experiment_id(value, field_name)

def _normalize_text_fields(record, fields):
    return _schema_helpers._normalize_text_fields(record, fields)

def _normalize_record(record):
    return _schema_helpers._normalize_record(record)

def _normalize_projects_payload(payload):
    return _schema_helpers._normalize_projects_payload(payload)

def _is_within_directory(*args, **kwargs):
    return _image_helpers._is_within_directory(*args, **kwargs)

def _contains_symlink_component(*args, **kwargs):
    return _image_helpers._contains_symlink_component(*args, **kwargs)

def _resolve_images_root():
    return _image_helpers._resolve_images_root()

def _resolve_inside_images_dir(path, must_exist=True):
    return _image_helpers._resolve_inside_images_dir(path, must_exist)

def _tiff_dimensions(*args, **kwargs):
    return _image_helpers._tiff_dimensions(*args, **kwargs)

def _image_dimensions_from_header(*args, **kwargs):
    return _image_helpers._image_dimensions_from_header(*args, **kwargs)

def _validate_image_file(*args, **kwargs):
    return _image_helpers._validate_image_file(*args, **kwargs)

def _safe_image_path(path, validate_image=False):
    return _image_helpers._safe_image_path(path, validate_image)

def _validate_source_image(path):
    return _image_helpers._validate_source_image(path)

def _normalize_stored_image_path(path):
    return _image_helpers._normalize_stored_image_path(path)

def _normalize_image_reference(value):
    return _image_helpers._normalize_image_reference(value)


MAX_JSON_NESTING_DEPTH = 64










































from .experiment_word_export import WordExportMixin

class ExpRecorderPanel(WordExportMixin, QWidget):
    """试验记录助手主面板"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.projects = {}      # project_id -> project data
        self.current_project_id = None
        self.current_task_id = None
        self.current_record_id = None
        self._record_dirty = False
        self._data_load_blocked = False
        self._load_data()
        self._init_ui()
        logger.info('试验记录助手已创建')

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)

        # ===== 顶部工具栏 =====
        top_layout = QHBoxLayout()
        lbl_title = QLabel('📋 试验记录助手')
        lbl_title.setStyleSheet('font-size: 18px; font-weight: bold; color: #1e293b;')
        top_layout.addWidget(lbl_title)

        self.btn_new_project = QPushButton('📁 新建项目')
        self.btn_new_project.clicked.connect(self._new_project)
        style_primary_button(self.btn_new_project)
        top_layout.addWidget(self.btn_new_project)

        self.btn_new_task = QPushButton('📂 新建任务')
        self.btn_new_task.clicked.connect(self._new_task)
        top_layout.addWidget(self.btn_new_task)

        self.btn_new_record = QPushButton('📝 新建记录')
        self.btn_new_record.clicked.connect(self._new_record)
        style_primary_button(self.btn_new_record)
        top_layout.addWidget(self.btn_new_record)

        top_layout.addStretch()
        self.lbl_save_status = QLabel('')
        self.lbl_save_status.setStyleSheet('font-size: 10px; color: #94a3b8;')
        top_layout.addWidget(self.lbl_save_status)
        self.btn_save = QPushButton('💾 保存')
        self.btn_save.clicked.connect(self._save_current_record)
        style_primary_button(self.btn_save)
        top_layout.addWidget(self.btn_save)

        # 导出菜单
        self.btn_export_word = QPushButton('📤 导出 ▼')
        self.btn_export_word.clicked.connect(self._show_export_menu)
        style_calc_button(self.btn_export_word)
        self.export_menu = QMenu(self)
        act_export_record = QAction('📝 导出当前记录', self)
        act_export_record.triggered.connect(lambda: self._export_to_word('record'))
        self.export_menu.addAction(act_export_record)
        act_export_task = QAction('📂 导出当前任务（含所有记录）', self)
        act_export_task.triggered.connect(lambda: self._export_to_word('task'))
        self.export_menu.addAction(act_export_task)
        act_export_project = QAction('📁 导出当前项目（含所有任务和记录）', self)
        act_export_project.triggered.connect(lambda: self._export_to_word('project'))
        self.export_menu.addAction(act_export_project)
        top_layout.addWidget(self.btn_export_word)

        # 树右键菜单
        self.tree_context_menu = QMenu(self)
        act_export_rec = QAction('📝 导出此记录', self)
        act_export_rec.triggered.connect(lambda: self._export_tree_selected('record'))
        self.tree_context_menu.addAction(act_export_rec)
        act_export_tsk = QAction('📂 导出此任务', self)
        act_export_tsk.triggered.connect(lambda: self._export_tree_selected('task'))
        self.tree_context_menu.addAction(act_export_tsk)
        act_export_prj = QAction('📁 导出此项目', self)
        act_export_prj.triggered.connect(lambda: self._export_tree_selected('project'))
        self.tree_context_menu.addAction(act_export_prj)
        self.tree_context_menu.addSeparator()
        act_delete_tree = QAction('🗑️ 删除', self)
        act_delete_tree.triggered.connect(self._delete_selected)
        self.tree_context_menu.addAction(act_delete_tree)
        layout.addLayout(top_layout)

        # ===== 主分割器 =====
        splitter = QSplitter(Qt.Horizontal)

        # ---- 左侧项目树 ----
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)

        left_layout.addWidget(QLabel('📁 项目结构'))
        self.tree_projects = QListWidget()
        self.tree_projects.setMinimumWidth(200)
        self.tree_projects.currentItemChanged.connect(self._on_tree_selection)
        self.tree_projects.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree_projects.customContextMenuRequested.connect(self._show_tree_context_menu)
        left_layout.addWidget(self.tree_projects, 1)

        self.btn_delete_item = QPushButton('🗑️ 删除选中')
        self.btn_delete_item.clicked.connect(self._delete_selected)
        style_warning_button(self.btn_delete_item)
        left_layout.addWidget(self.btn_delete_item)

        splitter.addWidget(left_widget)

        # ---- 右侧编辑区 ----
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        right_layout.setContentsMargins(0, 0, 0, 0)

        # 页面切换
        self.stacked = QTabWidget()

        # 欢迎页面 - 功能特色介绍
        self.page_empty = QWidget()
        empty_layout = QVBoxLayout(self.page_empty)
        empty_layout.setContentsMargins(30, 30, 30, 30)

        # 标题区
        title_lbl = QLabel('📋 试验记录助手')
        title_lbl.setStyleSheet('font-size: 24px; font-weight: bold; color: #1e293b;')
        title_lbl.setAlignment(Qt.AlignCenter)
        empty_layout.addWidget(title_lbl)

        sub_lbl = QLabel('告别Word排版 · 一键生成规范试验报告')
        sub_lbl.setStyleSheet('font-size: 13px; color: #64748b; margin-bottom: 20px;')
        sub_lbl.setAlignment(Qt.AlignCenter)
        empty_layout.addWidget(sub_lbl)

        # 核心功能卡片
        features = [
            ('📁 三级项目管理', '项目 → 任务 → 记录，结构化组织试验数据'),
            ('📝 模板化记录', '暗室天线测试 / 外场雷达试验 / 系统联调 / 通用，填空式录入'),
            ('🖼️ 截图管理', '支持多种图片格式，自定义图注说明，自动排序编号'),
            ('📤 一键导出Word', '军工归档格式：标准封面 + 页眉页码 + 目录 + 图题注 + 尾注'),
            ('⚙️ 导出设置', '封面 / 页码 / 自动目录 / 图片质量 / 水印 可自由配置'),
            ('📂 数据持久化', '本地JSON存储，自动保存，重启不丢失'),
            ('🔍 快速导航', '左侧树形结构，右键菜单支持导出/删除'),
            ('🎯 工科规范', '宋体正文/黑体标题/1.5倍行距/首行缩进/纯黑灰配色'),
        ]

        # 用表格布局展示功能卡片
        from PyQt5.QtWidgets import QGridLayout
        grid = QGridLayout()
        grid.setSpacing(12)
        for i, (icon_title, desc) in enumerate(features):
            row, col = i // 2, i % 2
            card = QFrame()
            card.setStyleSheet("""
                QFrame {
                    background: #ffffff;
                    border: 1px solid #e2e8f0;
                    border-radius: 10px;
                    padding: 14px;
                }
                QFrame:hover {
                    border-color: #94a3b8;
                    background: #f8fafc;
                }
            """)
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(12, 10, 12, 10)
            card_layout.setSpacing(4)
            icon_lbl = QLabel(icon_title)
            icon_lbl.setStyleSheet('font-size: 14px; font-weight: bold; color: #1e293b;')
            card_layout.addWidget(icon_lbl)
            desc_lbl = QLabel(desc)
            desc_lbl.setStyleSheet('font-size: 11px; color: #64748b;')
            desc_lbl.setWordWrap(True)
            card_layout.addWidget(desc_lbl)
            grid.addWidget(card, row, col)

        empty_layout.addLayout(grid)

        # 底部操作提示
        empty_layout.addSpacing(20)
        tip_lbl = QLabel('💡 点击左侧「📁 项目结构」→ 右键或顶部按钮新建项目/任务/记录')
        tip_lbl.setStyleSheet('font-size: 12px; color: #94a3b8; padding: 8px; background: #f1f5f9; border-radius: 6px;')
        tip_lbl.setAlignment(Qt.AlignCenter)
        empty_layout.addWidget(tip_lbl)

        empty_layout.addStretch()
        self.stacked.addTab(self.page_empty, '欢迎')

        # 记录编辑页
        self.page_edit = QScrollArea()
        self.page_edit.setWidgetResizable(True)
        self.edit_container = QWidget()
        self.edit_layout = QVBoxLayout(self.edit_container)
        self._build_edit_form()
        self.page_edit.setWidget(self.edit_container)
        self.stacked.addTab(self.page_edit, '编辑记录')

        right_layout.addWidget(self.stacked, 1)
        splitter.addWidget(right_widget)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)

        layout.addWidget(splitter, 1)
        self._refresh_tree()

    def _build_edit_form(self):
        """构建记录编辑表单"""
        self.edit_form_widgets = {}

        # 标题
        self.edit_title = QLineEdit()
        self.edit_title.setPlaceholderText('请输入试验记录标题')
        self.edit_title.setStyleSheet('font-size: 16px; font-weight: bold; padding: 6px;')
        self.edit_layout.addWidget(self.edit_title)
        self.edit_title.textChanged.connect(self._mark_record_dirty)

        # 基本信息
        info_group = QGroupBox('基本信息')
        info_layout = QGridLayout(info_group)

        info_layout.addWidget(QLabel('试验日期:'), 0, 0)
        self.edit_date = QDateEdit()
        self.edit_date.setDate(QDate.currentDate())
        self.edit_date.setCalendarPopup(True)
        self.edit_date.dateChanged.connect(self._mark_record_dirty)
        info_layout.addWidget(self.edit_date, 0, 1)

        info_layout.addWidget(QLabel('试验人员:'), 0, 2)
        self.edit_personnel = QLineEdit()
        self.edit_personnel.setPlaceholderText('姓名1, 姓名2')
        self.edit_personnel.textChanged.connect(self._mark_record_dirty)
        info_layout.addWidget(self.edit_personnel, 0, 3)

        info_layout.addWidget(QLabel('试验地点:'), 1, 0)
        self.edit_location = QLineEdit()
        self.edit_location.setPlaceholderText('外场/暗室/实验室')
        self.edit_location.textChanged.connect(self._mark_record_dirty)
        info_layout.addWidget(self.edit_location, 1, 1)

        info_layout.addWidget(QLabel('模板选择:'), 1, 2)
        self.combo_template = QComboBox()
        self.combo_template.addItems(['暗室天线测试', '外场雷达试验', '系统联调测试', '通用试验记录'])
        self.combo_template.currentIndexChanged.connect(self._mark_record_dirty)
        info_layout.addWidget(self.combo_template, 1, 3)

        info_layout.addWidget(QLabel('环境条件:'), 2, 0)
        self.edit_conditions = QLineEdit()
        self.edit_conditions.setPlaceholderText('天气/温度/湿度等')
        self.edit_conditions.textChanged.connect(self._mark_record_dirty)
        info_layout.addWidget(self.edit_conditions, 2, 1, 1, 3)

        self.edit_layout.addWidget(info_group)

        # 试验内容 - 多行文本
        content_group = QGroupBox('试验内容')
        content_layout = QVBoxLayout(content_group)
        self.edit_content = QTextEdit()
        self.edit_content.setPlaceholderText('描述试验目的、测试项目、配置信息等...')
        self.edit_content.setMinimumHeight(100)
        self.edit_content.textChanged.connect(self._mark_record_dirty)
        content_layout.addWidget(self.edit_content)
        self.edit_layout.addWidget(content_group)

        # 试验步骤（循环添加）
        self.steps_group = QGroupBox('试验步骤')
        self.steps_layout = QVBoxLayout(self.steps_group)
        self.step_widgets = []
        self._add_step()
        btn_add_step = QPushButton('➕ 添加步骤')
        btn_add_step.clicked.connect(self._add_step)
        self.steps_layout.addWidget(btn_add_step)
        self.edit_layout.addWidget(self.steps_group)

        # 结论
        concl_group = QGroupBox('结论与问题')
        concl_layout = QVBoxLayout(concl_group)
        self.edit_conclusion = QTextEdit()
        self.edit_conclusion.setPlaceholderText('试验结论、问题汇总、后续计划...')
        self.edit_conclusion.setMinimumHeight(80)
        self.edit_conclusion.textChanged.connect(self._mark_record_dirty)
        concl_layout.addWidget(self.edit_conclusion)
        self.edit_layout.addWidget(concl_group)

        self.edit_layout.addStretch()

    def _add_step(self):
        """添加一个试验步骤（含数据记录和截图管理）"""
        step_id = len(self.step_widgets)
        frame = QFrame()
        frame.setFrameShape(QFrame.StyledPanel)
        frame.setStyleSheet('QFrame { border: 1px solid #e2e8f0; border-radius: 4px; padding: 4px; margin: 2px; }')
        step_layout = QVBoxLayout(frame)

        # 步骤标题行
        top_row = QHBoxLayout()
        lbl = QLabel(f'步骤 {step_id + 1}:')
        lbl.setStyleSheet('font-weight: bold;')
        top_row.addWidget(lbl)

        title_edit = QLineEdit()
        title_edit.setPlaceholderText('步骤名称（可选）')
        top_row.addWidget(title_edit, 1)

        btn_del = QPushButton('\u2715')
        btn_del.setFixedSize(24, 24)
        btn_del.setStyleSheet('background: #fee2e2; color: #ef4444; border: none; border-radius: 4px;')
        btn_del.clicked.connect(lambda: self._remove_step(frame))
        top_row.addWidget(btn_del)

        step_layout.addLayout(top_row)

        # 操作描述
        desc_edit = QTextEdit()
        desc_edit.setPlaceholderText('操作描述和现象...')
        desc_edit.setMaximumHeight(60)
        step_layout.addWidget(desc_edit)

        # ---- 步骤内数据记录 ----
        data_edit = QTextEdit()
        data_edit.setPlaceholderText('此步骤的测试数据、观测结果...（可粘贴Excel表格数据）')
        data_edit.setMaximumHeight(80)
        step_layout.addWidget(data_edit)

        # ---- 步骤内截图管理 ----
        img_row = QHBoxLayout()
        btn_add_img = QPushButton('\U0001f5bc\ufe0f 添加截图')
        from .ui_theme import style_primary_button, style_warning_button
        btn_add_img.clicked.connect(lambda f=frame: self._add_step_screenshot(f))
        style_primary_button(btn_add_img)
        img_row.addWidget(btn_add_img)
        btn_remove_img = QPushButton('\u2716 移除选中')
        btn_remove_img.clicked.connect(lambda f=frame: self._remove_step_screenshot(f))
        style_warning_button(btn_remove_img)
        img_row.addWidget(btn_remove_img)
        img_row.addStretch()
        step_layout.addLayout(img_row)

        img_list = QListWidget()
        img_list.setMaximumHeight(80)
        step_layout.addWidget(img_list)

        self.steps_layout.insertWidget(self.steps_layout.count() - 1, frame)
        self.step_widgets.append({
            'frame': frame,
            'title': title_edit,
            'desc': desc_edit,
            'data': data_edit,
            'img_list': img_list,
        })
        self._renumber_steps()

    def _remove_step(self, frame):
        """删除步骤"""
        for sw in self.step_widgets[:]:
            if sw['frame'] == frame:
                self.steps_layout.removeWidget(frame)
                frame.deleteLater()
                self.step_widgets.remove(sw)
        self._renumber_steps()


    def _add_step_screenshot(self, frame):
        """向指定步骤添加截图"""
        filepath, _ = QFileDialog.getOpenFileName(
            self, '选择截图', '',
            '图片文件 (*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.webp);;所有文件 (*.*)')
        if not filepath:
            return
        try:
            _validate_source_image(filepath)
        except ValueError as exc:
            QMessageBox.warning(self, '图片无法加载', f'所选图片不能使用：\n{exc}')
            return
        # 找到对应步骤的 widget
        for sw in self.step_widgets:
            if sw['frame'] == frame:
                caption, ok = QInputDialog.getText(self, '添加截图', '图注说明（可选）:')
                if not ok:
                    caption = ''
                basename = os.path.basename(filepath)
                display = f'🖼️ {basename}'
                if caption:
                    display += f' → {caption}'
                item = QListWidgetItem(display)
                item.setData(Qt.UserRole, {'path': filepath, 'caption': caption})
                item.setToolTip(f'{filepath}\n图注: {caption if caption else "（无）"}')
                sw['img_list'].addItem(item)
                break

    def _remove_step_screenshot(self, frame):
        """移除指定步骤的选中截图"""
        for sw in self.step_widgets:
            if sw['frame'] == frame:
                for item in sw['img_list'].selectedItems():
                    sw['img_list'].takeItem(sw['img_list'].row(item))
                break

    def _renumber_steps(self):
        """重新编号步骤"""
        for i, sw in enumerate(self.step_widgets):
            label = sw['frame'].layout().itemAt(0).layout().itemAt(0).widget()
            if isinstance(label, QLabel):
                label.setText(f'步骤 {i + 1}:')

    # ==================== 项目/任务/记录管理 ====================

    def _refresh_tree(self):
        """刷新项目树（保留当前选中项）"""
        current = self.tree_projects.currentItem()
        current_data = current.data(Qt.UserRole) if current is not None else None

        self.tree_projects.blockSignals(True)
        self.tree_projects.clear()

        for pid, proj in sorted(self.projects.items(), key=lambda x: x[1].get('name', '')):
            proj_item = QListWidgetItem(f'📁 {proj.get("name", "未命名")}')
            proj_item.setData(Qt.UserRole, ('project', pid))
            font = proj_item.font()
            font.setBold(True)
            proj_item.setFont(font)
            self.tree_projects.addItem(proj_item)

            for tid, task in sorted(proj.get('tasks', {}).items(), key=lambda x: x[1].get('name', '')):
                task_item = QListWidgetItem(f'  📂 {task.get("name", "未命名")}')
                task_item.setData(Qt.UserRole, ('task', pid, tid))
                self.tree_projects.addItem(task_item)

                for rid, rec in sorted(task.get('records', {}).items(), key=lambda x: x[1].get('title', '')):
                    rec_item = QListWidgetItem(f'    📝 {rec.get("title", "未命名")}')
                    rec_item.setData(Qt.UserRole, ('record', pid, tid, rid))
                    self.tree_projects.addItem(rec_item)

        if current_data is not None:
            for row in range(self.tree_projects.count()):
                item = self.tree_projects.item(row)
                if item.data(Qt.UserRole) == current_data:
                    self.tree_projects.setCurrentItem(item)
                    break
        self.tree_projects.blockSignals(False)

    def _on_tree_selection(self, current, previous):
        """树节点选择事件"""
        if not current:
            return
        data = current.data(Qt.UserRole)
        if not data:
            return

        if data[0] == 'record':
            validate_experiment_id(data[1], '项目 ID')
            validate_experiment_id(data[2], '任务 ID')
            validate_experiment_id(data[3], '记录 ID')
            _, pid, tid, rid = data
            if self._has_current_record() and (pid, tid, rid) != (self.current_project_id, self.current_task_id, self.current_record_id):
                self._save_current_record(quiet=True)
            self._load_record(pid, tid, rid)
        elif data[0] in ('project', 'task'):
            if self._has_current_record():
                self._save_current_record(quiet=True)
            self.stacked.setCurrentIndex(0)

    def _new_project(self):
        """新建项目"""
        name, ok = QInputDialog.getText(self, '新建项目', '项目名称:')
        if not ok or not name.strip():
            return
        desc, ok = QInputDialog.getText(self, '新建项目', '项目描述（可选）:')
        if not ok:
            desc = ''

        pid = hashlib.md5((name + str(datetime.datetime.now())).encode()).hexdigest()[:8]
        self.projects[pid] = {
            'name': name.strip(),
            'description': desc,
            'tasks': {}
        }
        self._save_data()
        self._refresh_tree()
        logger.info(f'新建项目: {name.strip()}')

    def _new_task(self):
        """新建任务"""
        if not self.projects:
            QMessageBox.information(self, '提示', '请先创建项目')
            return

        proj_names = [p['name'] for p in self.projects.values()]
        proj_name, ok = QInputDialog.getItem(self, '选择项目', '选择所属项目:', proj_names, 0, False)
        if not ok:
            return

        pid = None
        for k, v in self.projects.items():
            if v['name'] == proj_name:
                pid = k
                break
        if not pid:
            return
        validate_experiment_id(pid, '项目 ID')

        name, ok = QInputDialog.getText(self, '新建任务', '任务名称:')
        if not ok or not name.strip():
            return

        tid = hashlib.md5((name + str(datetime.datetime.now())).encode()).hexdigest()[:8]
        self.projects[pid].setdefault('tasks', {})[tid] = {
            'name': name,
            'records': {}
        }
        self._save_data()
        self._refresh_tree()
        logger.info(f'新建任务: {name}')

    def _new_record(self):
        """新建记录"""
        # 找到第一个有task的项目
        pid = None
        tid = None
        # 尝试获取当前选中的task
        current = self.tree_projects.currentItem()
        if current:
            data = current.data(Qt.UserRole)
            if data and data[0] == 'task':
                _, pid, tid = data
            elif data and data[0] == 'record':
                _, pid, tid, _ = data

        if not pid or not tid:
            QMessageBox.information(self, '提示', '请先在左侧选中一个任务（或展开项目下的任务）')
            return
        validate_experiment_id(pid, '项目 ID')
        validate_experiment_id(tid, '任务 ID')

        title, ok = QInputDialog.getText(self, '新建记录', '记录标题:')
        if not ok or not title.strip():
            return

        rid = hashlib.md5((title + str(datetime.datetime.now())).encode()).hexdigest()[:8]

        record = {
            'title': title,
            'date': datetime.date.today().isoformat(),
            'personnel': '',
            'location': '',
            'template': '通用试验记录',
            'conditions': '',
            'content': '',
            'steps': [],
            'conclusion': '',
            'created': datetime.datetime.now().isoformat(),
        }

        self.projects[pid].setdefault('tasks', {}).setdefault(tid, {}).setdefault(
            'records', {}
        )[rid] = record
        self._save_data()
        self._refresh_tree()
        self._load_record(pid, tid, rid)
        logger.info(f'新建记录: {title}')

    def _load_record(self, pid, tid, rid):
        """加载记录到编辑表单"""
        validate_experiment_id(pid, '项目 ID')
        validate_experiment_id(tid, '任务 ID')
        validate_experiment_id(rid, '记录 ID')
        try:
            rec = self.projects[pid]['tasks'][tid]['records'][rid]
        except KeyError:
            return

        self.current_project_id = pid
        self.current_task_id = tid
        self.current_record_id = rid

        self.edit_title.setText(rec.get('title', ''))
        try:
            self.edit_date.setDate(QDate.fromString(rec.get('date', datetime.date.today().isoformat()), 'yyyy-MM-dd'))
        except:
            self.edit_date.setDate(QDate.currentDate())
        self.edit_personnel.setText(rec.get('personnel', ''))
        self.edit_location.setText(rec.get('location', ''))
        idx = self.combo_template.findText(rec.get('template', '通用试验记录'))
        if idx >= 0:
            self.combo_template.setCurrentIndex(idx)
        self.edit_conditions.setText(rec.get('conditions', ''))
        self.edit_content.setText(rec.get('content', ''))
        self.edit_conclusion.setText(rec.get('conclusion', ''))

        # 步骤（含步骤内数据记录和截图）
        for sw in self.step_widgets[:]:
            self.steps_layout.removeWidget(sw['frame'])
            sw['frame'].deleteLater()
        self.step_widgets = []

        steps = rec.get('steps', [])
        skipped_images = 0
        if steps:
            for s in steps:
                self._add_step()
                if self.step_widgets:
                    sw = self.step_widgets[-1]
                    sw['title'].setText(s.get('title', ''))
                    sw['desc'].setText(s.get('desc', ''))
                    sw['data'].setText(s.get('data', ''))
                    # 加载步骤内截图
                    for img_data in s.get('images', []):
                        if isinstance(img_data, dict):
                            ipath = img_data.get('path', '')
                            icaption = img_data.get('caption', '')
                        elif isinstance(img_data, str):
                            ipath = img_data
                            icaption = ''
                        else:
                            continue
                        try:
                            ipath = _safe_image_path(ipath, validate_image=True)
                        except ValueError as exc:
                            skipped_images += 1
                            logger.warning('记录 %s 图片加载失败: %s', rid, exc)
                            continue
                        display = f'🖼️ {os.path.basename(ipath)}'
                        if icaption:
                            display += f' → {icaption}'
                        item = QListWidgetItem(display)
                        item.setData(Qt.UserRole, {'path': ipath, 'caption': icaption})
                        item.setToolTip(f'{ipath}\n图注: {icaption if icaption else "（无）"}')
                        sw['img_list'].addItem(item)
        else:
            self._add_step()


        self.stacked.setCurrentIndex(1)
        if skipped_images:
            self.lbl_save_status.setText(f'⚠️ {skipped_images} 张图片加载失败（已跳过）')
            QMessageBox.warning(
                self,
                '图片加载失败',
                f'有 {skipped_images} 张图片无法加载（文件缺失或格式不支持），已跳过。\n'
                '注意：若此时保存，失败的图片引用将被移除。',
            )
        else:
            self.lbl_save_status.setText('已加载')
        self._record_dirty = False

    def _save_current_record(self, quiet=False):
        """保存当前记录（含图注信息）"""
        if not all([self.current_project_id, self.current_task_id, self.current_record_id]):
            if not quiet:
                QMessageBox.information(self, '提示', '没有正在编辑的记录')
            return False
        validate_experiment_id(self.current_project_id, '项目 ID')
        validate_experiment_id(self.current_task_id, '任务 ID')
        validate_experiment_id(self.current_record_id, '记录 ID')

        steps_data = []
        for sw in self.step_widgets:
            step_images = []
            for i in range(sw['img_list'].count()):
                item = sw['img_list'].item(i)
                data = item.data(Qt.UserRole)
                if data:
                    normalized = self._normalize_image_item(data)
                    if normalized:
                        step_images.append(normalized)
            steps_data.append({
                'title': sw['title'].text(),
                'desc': sw['desc'].toPlainText(),
                'data': sw['data'].toPlainText(),
                'images': step_images,
            })

        try:
            rec = self.projects[self.current_project_id]['tasks'][self.current_task_id]['records'][self.current_record_id]
        except KeyError:
            return False

        rec['title'] = self.edit_title.text()
        rec['date'] = self.edit_date.date().toString('yyyy-MM-dd')
        rec['personnel'] = self.edit_personnel.text()
        rec['location'] = self.edit_location.text()
        rec['template'] = self.combo_template.currentText()
        rec['conditions'] = self.edit_conditions.text()
        rec['content'] = self.edit_content.toPlainText()
        rec['steps'] = steps_data
        rec['conclusion'] = self.edit_conclusion.toPlainText()
        rec['updated'] = datetime.datetime.now().isoformat()

        self._save_data()
        self._refresh_tree()
        self.lbl_save_status.setText('✅ 已保存 ' + datetime.datetime.now().strftime('%H:%M'))
        self._record_dirty = False
        logger.info(f'保存记录: {rec["title"]}')
        return True

    def _delete_selected(self):
        """删除选中的项目/任务/记录"""
        current = self.tree_projects.currentItem()
        if not current:
            return
        data = current.data(Qt.UserRole)
        if not data:
            return
        if data[0] == 'record':
            validate_experiment_id(data[1], '项目 ID')
            validate_experiment_id(data[2], '任务 ID')
            validate_experiment_id(data[3], '记录 ID')
        elif data[0] == 'task':
            validate_experiment_id(data[1], '项目 ID')
            validate_experiment_id(data[2], '任务 ID')
        elif data[0] == 'project':
            validate_experiment_id(data[1], '项目 ID')

        reply = QMessageBox.question(self, '确认删除', '确定要删除吗？\n此操作不可恢复！',
                                     QMessageBox.Yes | QMessageBox.No)
        if reply != QMessageBox.Yes:
            return

        if data[0] == 'record':
            _, pid, tid, rid = data
            del self.projects[pid]['tasks'][tid]['records'][rid]
            if self.current_record_id == rid:
                self.current_record_id = None
                self.stacked.setCurrentIndex(0)
        elif data[0] == 'task':
            _, pid, tid = data
            del self.projects[pid]['tasks'][tid]
        elif data[0] == 'project':
            pid = data[1]
            del self.projects[pid]
            if self.current_project_id == pid:
                self.current_project_id = None
                self.current_task_id = None
                self.current_record_id = None
                self.stacked.setCurrentIndex(0)

        self._save_data()
        self._refresh_tree()
        logger.info('删除成功')

    def closeEvent(self, event):
        if self._has_current_record():
            self._save_current_record(quiet=True)
        super().closeEvent(event)

    def _has_current_record(self):
        return all([self.current_project_id, self.current_task_id, self.current_record_id])

    def _mark_record_dirty(self, *args):
        if self._has_current_record():
            self._record_dirty = True
            self.lbl_save_status.setText('未保存')

    def _image_storage_dir(self, pid, tid, rid):
        validate_experiment_id(pid, '项目 ID')
        validate_experiment_id(tid, '任务 ID')
        validate_experiment_id(rid, '记录 ID')
        root = _resolve_images_root()
        candidate = os.path.join(root, pid, tid, rid)
        path = _resolve_inside_images_dir(candidate, must_exist=False)
        os.makedirs(path, exist_ok=True)
        if not os.path.isdir(path) or os.path.islink(path):
            raise ValueError('图片存储目录创建失败')
        return path

    def _normalize_image_item(self, data):
        if isinstance(data, str):
            data = {'path': data, 'caption': ''}
        if not isinstance(data, dict):
            return None
        src = data.get('path', '')
        caption = data.get('caption', '')
        if not isinstance(src, str) or not isinstance(caption, str):
            return None
        try:
            src = _validate_source_image(src)
        except ValueError as exc:
            logger.warning('拒绝无效截图: %s', exc)
            return None
        pid = self.current_project_id or 'unknown_project'
        tid = self.current_task_id or 'unknown_task'
        rid = self.current_record_id or 'unknown_record'
        storage_dir = self._image_storage_dir(pid, tid, rid)
        # 已经存放在本记录存储目录中的图片直接沿用，避免每次保存都重复复制
        src_abs = os.path.abspath(src)
        if os.path.dirname(src_abs) == os.path.abspath(storage_dir):
            return {
                'path': os.path.relpath(src_abs, _resolve_images_root()),
                'caption': caption,
            }
        base = os.path.basename(src_abs)
        stem, ext = os.path.splitext(base)
        digest = hashlib.md5(
            (src_abs + str(os.path.getmtime(src_abs))).encode('utf-8', 'ignore')
        ).hexdigest()[:8]
        dst = os.path.join(storage_dir, f'{stem}_{digest}{ext}')
        try:
            if src_abs != os.path.abspath(dst):
                shutil.copy2(src_abs, dst)
            dst = _safe_image_path(dst, validate_image=True)
            return {
                'path': os.path.relpath(dst, _resolve_images_root()),
                'caption': caption,
            }
        except Exception as exc:
            logger.warning('复制截图失败: %s', exc)
            return None

    # ==================== 工科报告内置样式模板 - 方案B（全黑/灰军工规范）====================

    # ---- 全局样式常量（修改此处即可全局调整，无需改动业务代码） ----
    _REPORT_STYLES = {
        # ── 页面 ──
        'page_top_margin': Cm(2.5),
        'page_bottom_margin': Cm(2.5),
        'page_left_margin': Cm(2.8),    # 左侧装订预留
        'page_right_margin': Cm(2.5),

        # ── 封面 ──
        'cover_title_font': '黑体',
        'cover_title_size': Pt(22),     # 二号
        'cover_title_color': RGBColor(0x00, 0x00, 0x00),  # 纯黑
        'cover_title_space_before': Pt(240),  # ≈12行间距
        'cover_subtitle_font': '黑体',
        'cover_subtitle_size': Pt(15),   # 小三号
        'cover_subtitle_color': RGBColor(0x66, 0x66, 0x66),  # 深灰
        'cover_subtitle_space_before': Pt(20),
        'cover_info_font': '宋体',
        'cover_info_size': Pt(12),       # 小四
        'cover_info_color': RGBColor(0x99, 0x99, 0x99),  # 浅灰
        'cover_info_space_before': Pt(60),

        # ── 一级标题 H1（项目总章节）黑体四号纯黑 ──
        'h1_font': '黑体',
        'h1_size': Pt(16),
        'h1_color': RGBColor(0x00, 0x00, 0x00),
        'h1_bold': True,
        'h1_space_before': Pt(18),
        'h1_space_after': Pt(12),

        # ── 二级标题 H2（单条记录）黑体小四纯黑 ──
        'h2_font': '黑体',
        'h2_size': Pt(14),
        'h2_color': RGBColor(0x00, 0x00, 0x00),
        'h2_bold': True,
        'h2_space_before': Pt(12),
        'h2_space_after': Pt(6),

        # ── 三级标题 H3（内容/步骤/数据/结论）黑体12pt纯黑 ──
        'h3_font': '黑体',
        'h3_size': Pt(12),
        'h3_color': RGBColor(0x00, 0x00, 0x00),
        'h3_bold': True,
        'h3_space_before': Pt(8),
        'h3_space_after': Pt(4),

        # ── 正文 Body（宋体小四、1.5倍行距、首行缩进2字符） ──
        'body_font': '宋体',
        'body_size': Pt(11),               # 小四
        'body_color': RGBColor(0x00, 0x00, 0x00),
        'body_line_spacing': 1.5,
        'body_first_line_indent': Cm(0.74), # ≈2字符
        'body_space_before': Pt(0),
        'body_space_after': Pt(0),

        # ── 试验基础信息字段（标签加粗、内容常规、无缩进紧凑） ──
        'field_font': '宋体',
        'field_size': Pt(11),
        'field_label_color': RGBColor(0x00, 0x00, 0x00),
        'field_value_color': RGBColor(0x00, 0x00, 0x00),
        'field_space_before': Pt(2),
        'field_space_after': Pt(2),

        # ── 图片题注（小五居中 #666666） ──
        'fig_caption_font': '宋体',
        'fig_caption_size': Pt(9),          # 小五
        'fig_caption_color': RGBColor(0x66, 0x66, 0x66),

        # ── 页眉（小五、居中、中度灰） ──
        'header_font': '宋体',
        'header_size': Pt(9),
        'header_color': RGBColor(0x99, 0x99, 0x99),

        # ── 页脚页码（小五、居中、中度灰） ──
        'footer_font': '宋体',
        'footer_size': Pt(9),
        'footer_color': RGBColor(0x99, 0x99, 0x99),

        # ── 尾注（浅灰小五居中） ──
        'endnote_font': '宋体',
        'endnote_size': Pt(9),
        'endnote_color': RGBColor(0x99, 0x99, 0x99),

        # ── 水印（浅灰色） ──
        'watermark_color': RGBColor(0xcc, 0xcc, 0xcc),
    }

    _IMG_WIDTH_MAP = {'高清': Inches(5.5), '标准': Inches(5.0), '压缩': Inches(4.0)}

    # ---- 内置命名样式创建（批量建立，后续全部引用样式名，无零散硬编码） ----
    @staticmethod
    def _set_cn_font(run, font_name):
        """设置中文字体（兼容WPS+Office）"""
        rPr = run._element.get_or_add_rPr()
        rFonts = rPr.find(qn('w:rFonts'))
        if rFonts is None:
            rFonts = OxmlElement('w:rFonts')
            rPr.insert(0, rFonts)
        rFonts.set(qn('w:eastAsia'), font_name)
        rFonts.set(qn('w:ascii'), 'Arial')
        rFonts.set(qn('w:hAnsi'), 'Arial')

    @staticmethod
    def _create_named_styles(doc):
        """在文档中批量创建预定义命名样式"""
        S = ExpRecorderPanel._REPORT_STYLES
        styles = doc.styles

        # CoverTitle 封面主标题
        s = styles.add_style('CoverTitle', 1)
        s.font.name = S['cover_title_font']
        s.font.size = S['cover_title_size']
        s.font.bold = True
        s.font.color.rgb = S['cover_title_color']
        s.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
        s.paragraph_format.space_before = S['cover_title_space_before']
        ExpRecorderPanel._set_font_rpr(s.element, S['cover_title_font'])

        # CoverSubtitle 封面子标题
        s = styles.add_style('CoverSubtitle', 1)
        s.font.name = S['cover_subtitle_font']
        s.font.size = S['cover_subtitle_size']
        s.font.color.rgb = S['cover_subtitle_color']
        s.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
        s.paragraph_format.space_before = S['cover_subtitle_space_before']
        ExpRecorderPanel._set_font_rpr(s.element, S['cover_subtitle_font'])

        # CoverInfo 封面附属信息
        s = styles.add_style('CoverInfo', 1)
        s.font.name = S['cover_info_font']
        s.font.size = S['cover_info_size']
        s.font.color.rgb = S['cover_info_color']
        s.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
        s.paragraph_format.space_before = S['cover_info_space_before']
        ExpRecorderPanel._set_font_rpr(s.element, S['cover_info_font'])

        # Report_H1 一级标题
        s = styles.add_style('Report_H1', 1)
        s.font.name = S['h1_font']
        s.font.size = S['h1_size']
        s.font.bold = S['h1_bold']
        s.font.color.rgb = S['h1_color']
        s.paragraph_format.space_before = S['h1_space_before']
        s.paragraph_format.space_after = S['h1_space_after']
        ExpRecorderPanel._set_font_rpr(s.element, S['h1_font'])

        # Report_H2 二级标题
        s = styles.add_style('Report_H2', 1)
        s.font.name = S['h2_font']
        s.font.size = S['h2_size']
        s.font.bold = S['h2_bold']
        s.font.color.rgb = S['h2_color']
        s.paragraph_format.space_before = S['h2_space_before']
        s.paragraph_format.space_after = S['h2_space_after']
        ExpRecorderPanel._set_font_rpr(s.element, S['h2_font'])

        # Report_H3 三级标题
        s = styles.add_style('Report_H3', 1)
        s.font.name = S['h3_font']
        s.font.size = S['h3_size']
        s.font.bold = S['h3_bold']
        s.font.color.rgb = S['h3_color']
        s.paragraph_format.space_before = S['h3_space_before']
        s.paragraph_format.space_after = S['h3_space_after']
        ExpRecorderPanel._set_font_rpr(s.element, S['h3_font'])

        # Report_Body 正文通用
        s = styles.add_style('Report_Body', 1)
        s.font.name = S['body_font']
        s.font.size = S['body_size']
        s.font.color.rgb = S['body_color']
        s.paragraph_format.first_line_indent = S['body_first_line_indent']
        s.paragraph_format.line_spacing = S['body_line_spacing']
        s.paragraph_format.space_before = S['body_space_before']
        s.paragraph_format.space_after = S['body_space_after']
        ExpRecorderPanel._set_font_rpr(s.element, S['body_font'])

        # Report_Field_Info 试验基础信息
        s = styles.add_style('Report_Field_Info', 1)
        s.font.name = S['field_font']
        s.font.size = S['field_size']
        s.font.color.rgb = S['field_value_color']
        s.paragraph_format.space_before = S['field_space_before']
        s.paragraph_format.space_after = S['field_space_after']
        ExpRecorderPanel._set_font_rpr(s.element, S['field_font'])

        # Report_Image_Caption 图片题注
        s = styles.add_style('Report_Image_Caption', 1)
        s.font.name = S['fig_caption_font']
        s.font.size = S['fig_caption_size']
        s.font.color.rgb = S['fig_caption_color']
        s.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
        ExpRecorderPanel._set_font_rpr(s.element, S['fig_caption_font'])

        # Report_Endnote 尾注
        s = styles.add_style('Report_Endnote', 1)
        s.font.name = S['endnote_font']
        s.font.size = S['endnote_size']
        s.font.color.rgb = S['endnote_color']
        s.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
        ExpRecorderPanel._set_font_rpr(s.element, S['endnote_font'])

        return {
            'CoverTitle': 'CoverTitle',
            'CoverSubtitle': 'CoverSubtitle',
            'CoverInfo': 'CoverInfo',
            'Report_H1': 'Report_H1',
            'Report_H2': 'Report_H2',
            'Report_H3': 'Report_H3',
            'Report_Body': 'Report_Body',
            'Report_Field_Info': 'Report_Field_Info',
            'Report_Image_Caption': 'Report_Image_Caption',
            'Report_Endnote': 'Report_Endnote',
        }

    @staticmethod
    def _set_font_rpr(style_element, font_name):
        """为样式element设置中文字体rPr"""
        rPr = style_element.find(qn('w:rPr'))
        if rPr is None:
            rPr = OxmlElement('w:rPr')
            style_element.insert(0, rPr)
        rFonts = rPr.find(qn('w:rFonts'))
        if rFonts is None:
            rFonts = OxmlElement('w:rFonts')
            rPr.insert(0, rFonts)
        rFonts.set(qn('w:eastAsia'), font_name)
        rFonts.set(qn('w:ascii'), 'Arial')
        rFonts.set(qn('w:hAnsi'), 'Arial')

    # ---- 导出内容生成方法（全部调用命名样式，无零散硬编码） ----












    # ---- 导出辅助 ----

    def _show_tree_context_menu(self, pos):
        """显示树右键菜单"""
        item = self.tree_projects.itemAt(pos)
        if item:
            self.tree_projects.setCurrentItem(item)
            self.tree_context_menu.exec_(self.tree_projects.mapToGlobal(pos))

    def _show_export_menu(self):
        """显示导出下拉菜单"""
        self.export_menu.exec_(self.btn_export_word.mapToGlobal(
            self.btn_export_word.rect().bottomLeft()))

    def _export_tree_selected(self, level):
        """从树右键菜单触发导出"""
        current = self.tree_projects.currentItem()
        if not current:
            QMessageBox.information(self, '提示', '请在左侧选择要导出的项目/任务/记录')
            return
        data = current.data(Qt.UserRole)
        if not data:
            return

        if level == 'record' and data[0] == 'record':
            _, pid, tid, rid = data
            self._load_record(pid, tid, rid)
            self._export_to_word('record', pid, tid, rid)
        elif level == 'task' and data[0] == 'task':
            _, pid, tid = data
            self._export_to_word('task', pid, tid)
        elif level == 'project' and data[0] == 'project':
            pid = data[1]
            self._export_to_word('project', pid)
        elif data[0] in ('record', 'task', 'project') and data[0] != level:
            QMessageBox.information(self, '提示', f'请选择对应的层级：\n当前选中的是{data[0]}，但您点击了{level}')
        else:
            QMessageBox.information(self, '提示', '请先在左侧选择对应的项目/任务/记录')


    # ==================== 数据持久化 ====================

    def _save_data(self):
        """保存数据到本地JSON文件（临时文件 + 原子替换）"""
        if self.__dict__.get('_data_load_blocked', False):
            raise RuntimeError('试验数据文件尚未成功隔离，禁止覆盖')
        try:
            projects = _normalize_projects_payload(self.projects)
        except ValueError as exc:
            logger.error('试验数据 Schema 校验失败: %s', exc)
            raise
        payload = {
            'schema_version': EXPERIMENTS_SCHEMA_VERSION,
            'projects': projects,
        }
        filepath = os.path.join(DATA_DIR, 'experiments.json')
        temporary_path = filepath + '.tmp'
        try:
            backup_status = _backup_valid_json(
                filepath, _normalize_projects_payload
            )
            if backup_status is False:
                if (
                    _quarantine_corrupt_file(filepath) is None
                    and os.path.lexists(filepath)
                ):
                    self._data_load_blocked = True
                    raise RuntimeError('无法隔离损坏的试验数据文件')
            os.makedirs(DATA_DIR, exist_ok=True)
            with open(temporary_path, 'w', encoding='utf-8') as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temporary_path, filepath)
        except Exception as e:
            logger.error(f'保存数据失败: {safe_exception_message(e)}')
            if os.path.exists(temporary_path):
                try:
                    os.remove(temporary_path)
                except OSError:
                    pass
            if isinstance(e, RuntimeError):
                raise

    def _load_data(self):
        """从本地JSON文件加载数据；失败时隔离损坏文件并保留内存数据"""
        filepath = os.path.join(DATA_DIR, 'experiments.json')
        if os.path.lexists(filepath):
            try:
                projects = _read_json_with_limits(
                    filepath, _normalize_projects_payload
                )
            except Exception as exc:
                quarantined = _quarantine_corrupt_file(filepath)
                blocked = quarantined is None and os.path.lexists(filepath)
                self._data_load_blocked = blocked
                logger.error(
                    '加载试验数据失败（%s），已保留当前内存数据',
                    type(exc).__name__,
                )
                if not isinstance(self.__dict__.get('projects'), dict):
                    self.projects = {}
            else:
                self._data_load_blocked = False
                self.projects = projects
                logger.info(f'已加载试验数据 ({len(self.projects)} 个项目)')
        else:
            self._data_load_blocked = False
            if not isinstance(self.__dict__.get('projects'), dict):
                self.projects = {}

    def statusBar(self):
        parent = self.parent()
        while parent is not None:
            if hasattr(parent, 'statusBar'):
                return parent.statusBar()
            parent = parent.parent()
        return None
