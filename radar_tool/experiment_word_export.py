"""Word report export service for experiment records."""
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
from .export_safety import build_export_metadata
logger = get_logger("exp_recorder")
DATA_DIR = get_user_data_dir('试验数据')


def _safe_image_path(path, validate_image=False):
    """Resolve an image only through the application-managed image directory."""
    from .experiment_images import _safe_image_path as resolve_image_path

    return resolve_image_path(path, validate_image=validate_image)


def validate_experiment_id(value, field_name='ID'):
    """Validate experiment identifiers without creating an import cycle."""
    from .experiment_schema import validate_experiment_id as validate_id

    return validate_id(value, field_name)

class WordExportMixin:
    def _pstyle(self, doc, ns, style_name):
        """快捷获取段落样式"""
        return doc.styles[ns[style_name]]
    def _add_cover_page(self, doc, ns, title_text, include_cover):
        """添加封面（黑体二号纯黑 / 副标题深灰 / 日期浅灰）"""
        if not include_cover:
            return
        # 主标题
        p = doc.add_paragraph()
        p.style = self._pstyle(doc, ns, 'CoverTitle')
        p.add_run(title_text)

        # 副标题
        p = doc.add_paragraph()
        p.style = self._pstyle(doc, ns, 'CoverSubtitle')
        p.add_run('试验记录报告')

        # 附属信息
        now_str = datetime.datetime.now().strftime('%Y年%m月%d日')
        p = doc.add_paragraph()
        p.style = self._pstyle(doc, ns, 'CoverInfo')
        p.add_run(f'导出日期：{now_str}')

        doc.add_page_break()
    def _add_h1(self, doc, ns, text):
        """添加一级标题"""
        p = doc.add_paragraph()
        p.style = self._pstyle(doc, ns, 'Report_H1')
        p.add_run(text)
    def _add_h2(self, doc, ns, text):
        """添加二级标题"""
        p = doc.add_paragraph()
        p.style = self._pstyle(doc, ns, 'Report_H2')
        p.add_run(text)
    def _add_h3(self, doc, ns, text):
        """添加三级标题"""
        p = doc.add_paragraph()
        p.style = self._pstyle(doc, ns, 'Report_H3')
        p.add_run(text)
    def _add_body(self, doc, ns, text):
        """添加正文（带首行缩进）"""
        if not text.strip():
            return
        p = doc.add_paragraph()
        p.style = self._pstyle(doc, ns, 'Report_Body')
        p.add_run(text.strip())
    def _add_field_info(self, doc, ns, name, value):
        """添加试验基础信息（标签加粗、紧凑无缩进）"""
        if not value:
            return
        p = doc.add_paragraph()
        p.style = self._pstyle(doc, ns, 'Report_Field_Info')
        run = p.add_run(f'{name}：')
        run.font.bold = True
        run.font.color.rgb = self._REPORT_STYLES['field_label_color']
        p.add_run(str(value))
    def _add_step_item(self, doc, ns, index, title, desc):
        """添加有序试验步骤"""
        p = doc.add_paragraph()
        p.style = self._pstyle(doc, ns, 'Report_Body')
        p.paragraph_format.first_line_indent = None  # 取消缩进
        run = p.add_run(f'{index}. ')
        run.font.bold = True
        if title:
            run2 = p.add_run(f'{title}：')
            run2.font.bold = True
        if desc:
            p.add_run(desc)
    def _add_image_caption(self, doc, ns, fig_num, caption_text):
        """添加图片题注（图X 名称，居中#666666小五）"""
        p = doc.add_paragraph()
        p.style = self._pstyle(doc, ns, 'Report_Image_Caption')
        p.add_run(f'图{fig_num}  {caption_text}')
    def _add_endnote(self, doc, ns, text):
        """添加尾注"""
        p = doc.add_paragraph()
        p.style = self._pstyle(doc, ns, 'Report_Endnote')
        p.add_run(text)
    def _export_metadata_lines(self, metadata):
        """Format trace metadata for inclusion in a Word report."""
        metadata_header = {
            key: metadata[key]
            for key in ('version', 'schema_version', 'generated_at')
        }
        return [
            '导出元数据：'
            + json.dumps(metadata_header, ensure_ascii=False, sort_keys=True),
            '输入摘要：'
            + json.dumps(
                metadata['input_summary'], ensure_ascii=False, sort_keys=True
            ),
            '参数：'
            + json.dumps(
                metadata['parameters'], ensure_ascii=False, sort_keys=True
            ),
        ]
    def _add_record_section(self, doc, ns, record, record_index, img_quality, fig_counter):
        """完整单条记录布局"""
        rec_title = record.get('title', f'记录{record_index + 1}')
        self._add_h2(doc, ns, f'第{record_index + 1}条记录：{rec_title}')

        # 试验基础信息区块
        self._add_field_info(doc, ns, '试验日期', record.get('date', ''))
        self._add_field_info(doc, ns, '试验人员', record.get('personnel', ''))
        self._add_field_info(doc, ns, '试验地点', record.get('location', ''))
        self._add_field_info(doc, ns, '环境条件', record.get('conditions', ''))
        self._add_field_info(doc, ns, '模板类型', record.get('template', ''))

        # 试验内容
        content = record.get('content', '').strip()
        if content:
            self._add_h3(doc, ns, '试验内容')
            for line in content.split('\n'):
                self._add_body(doc, ns, line)

        # 标准化有序试验步骤（每一步包含自己的数据与截图）
        steps = record.get('steps', [])
        if steps:
            self._add_h3(doc, ns, '试验步骤')
            img_width = self._IMG_WIDTH_MAP.get(img_quality, Inches(5.0))
            for i, step in enumerate(steps):
                st = step.get('title', '').strip()
                sd = step.get('desc', '').strip()
                step_data = step.get('data', '').strip()
                step_images = step.get('images', [])
                if st or sd:
                    self._add_step_item(doc, ns, i + 1, st, sd)
                elif step_data or step_images:
                    self._add_step_item(doc, ns, i + 1, '未命名步骤', '')

                if step_data:
                    self._add_h3(doc, ns, f'步骤{i + 1}数据记录')
                    for line in step_data.split('\n'):
                        if line.strip():
                            self._add_body(doc, ns, line)

                if step_images:
                    self._add_h3(doc, ns, f'步骤{i + 1}截图附件')
                    for img_item in step_images:
                        if isinstance(img_item, str):
                            img_path = img_item
                            img_caption = ''
                        elif isinstance(img_item, dict):
                            img_path = img_item.get('path', '')
                            img_caption = img_item.get('caption', '')
                        else:
                            continue
                        try:
                            safe_img_path = _safe_image_path(img_path, validate_image=True)
                            doc.add_picture(safe_img_path, width=img_width)
                            last_p = doc.paragraphs[-1]
                            last_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                            fig_counter[0] += 1
                            caption_text = (
                                img_caption if img_caption else os.path.basename(safe_img_path)
                            )
                            self._add_image_caption(doc, ns, fig_counter[0], caption_text)
                        except Exception as e:
                            logger.warning('图片插入失败: %s', e)

        # 兼容旧版记录：旧数据可能仍保存在记录级 data/images
        legacy_data = record.get('data', '').strip()
        if legacy_data:
            self._add_h3(doc, ns, '未归属步骤数据记录')
            for line in legacy_data.split('\n'):
                if line.strip():
                    self._add_body(doc, ns, line)

        legacy_images = record.get('images', [])
        if legacy_images:
            self._add_h3(doc, ns, '未归属步骤截图附件')
            img_width = self._IMG_WIDTH_MAP.get(img_quality, Inches(5.0))
            for img_item in legacy_images:
                if isinstance(img_item, str):
                    img_path = img_item
                    img_caption = ''
                elif isinstance(img_item, dict):
                    img_path = img_item.get('path', '')
                    img_caption = img_item.get('caption', '')
                else:
                    continue
                try:
                    safe_img_path = _safe_image_path(img_path, validate_image=True)
                    doc.add_picture(safe_img_path, width=img_width)
                    last_p = doc.paragraphs[-1]
                    last_p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                    fig_counter[0] += 1
                    caption_text = (
                        img_caption if img_caption else os.path.basename(safe_img_path)
                    )
                    self._add_image_caption(doc, ns, fig_counter[0], caption_text)
                except Exception as e:
                    logger.warning('图片插入失败: %s', e)

        # 试验结论与问题汇总
        conclusion = record.get('conclusion', '').strip()
        if conclusion:
            self._add_h3(doc, ns, '结论与问题')
            for line in conclusion.split('\n'):
                if line.strip():
                    self._add_body(doc, ns, line)
    def _export_to_word(self, level='record', pid=None, tid=None, rid=None):
        """多级导出Word文档 - 重构版（全部调用命名样式，无零散硬编码）"""
        if Document is None:
            QMessageBox.warning(
                self,
                '缺少依赖',
                '导出 Word 需要安装 python-docx。\n请执行：pip install python-docx'
            )
            return

        # ---- 导出设置对话框 ----
        dlg = QDialog(self)
        dlg.setWindowTitle('导出设置')
        dlg.setMinimumWidth(420)
        dlg_layout = QFormLayout(dlg)

        combo_style = QComboBox()
        combo_style.addItems(['📄 标准正式（宋体/黑体/标准格式）', '🌿 简洁清爽（现代/留白）', '📦 紧凑密集（省纸/高密度）'])
        dlg_layout.addRow('报告风格:', combo_style)

        chk_cover = QCheckBox()
        chk_cover.setChecked(True)
        dlg_layout.addRow('包含封面:', chk_cover)

        chk_page_num = QCheckBox()
        chk_page_num.setChecked(True)
        dlg_layout.addRow('包含页码:', chk_page_num)

        chk_toc = QCheckBox()
        chk_toc.setChecked(False)
        dlg_layout.addRow('自动目录:', chk_toc)

        combo_img = QComboBox()
        combo_img.addItems(['高清', '标准', '压缩'])
        dlg_layout.addRow('图片质量:', combo_img)

        edit_watermark = QLineEdit()
        edit_watermark.setPlaceholderText('不加水印留空')
        dlg_layout.addRow('水印文字:', edit_watermark)

        btn_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btn_box.accepted.connect(dlg.accept)
        btn_box.rejected.connect(dlg.reject)
        dlg_layout.addRow(btn_box)

        if dlg.exec_() != QDialog.Accepted:
            return

        style_name = combo_style.currentText()
        include_cover = chk_cover.isChecked()
        include_page_num = chk_page_num.isChecked()
        include_toc = chk_toc.isChecked()
        img_quality = combo_img.currentText()
        watermark_text = edit_watermark.text().strip()

        # 确定导出范围
        if level == 'record':
            if pid is None or tid is None or rid is None:
                if not all([self.current_project_id, self.current_task_id, self.current_record_id]):
                    QMessageBox.information(self, '提示', '没有正在编辑的记录')
                    return
                self._save_current_record()
                pid = self.current_project_id
                tid = self.current_task_id
                rid = self.current_record_id
            validate_experiment_id(pid, '项目 ID')
            validate_experiment_id(tid, '任务 ID')
            validate_experiment_id(rid, '记录 ID')
            try:
                recs_to_export = {rid: self.projects[pid]['tasks'][tid]['records'][rid]}
            except KeyError:
                QMessageBox.warning(self, '错误', '无法获取记录数据')
                return

        elif level == 'task':
            if pid is None or tid is None:
                current = self.tree_projects.currentItem()
                if current:
                    data = current.data(Qt.UserRole)
                    if data and data[0] == 'task':
                        _, pid, tid = data
            if not pid or not tid:
                QMessageBox.information(self, '提示', '请先在左侧选中一个任务')
                return
            validate_experiment_id(pid, '项目 ID')
            validate_experiment_id(tid, '任务 ID')
            try:
                recs_to_export = self.projects[pid]['tasks'][tid].get('records', {})
            except KeyError:
                QMessageBox.warning(self, '错误', '无法获取任务数据')
                return
            if not recs_to_export:
                QMessageBox.information(self, '提示', '该任务下没有记录可导出')
                return

        elif level == 'project':
            if pid is None:
                current = self.tree_projects.currentItem()
                if current:
                    data = current.data(Qt.UserRole)
                    if data and data[0] == 'project':
                        pid = data[1]
            if not pid:
                QMessageBox.information(self, '提示', '请先在左侧选中一个项目')
                return
            validate_experiment_id(pid, '项目 ID')
            recs_to_export = {}
            try:
                for t_id in self.projects[pid].get('tasks', {}):
                    for r_id, rec in self.projects[pid]['tasks'][t_id].get('records', {}).items():
                        recs_to_export[(t_id, r_id)] = rec
            except KeyError:
                pass
            if not recs_to_export:
                QMessageBox.information(self, '提示', '该项目下没有记录可导出')
                return

        # 默认文件名
        if level == 'record':
            first_rec = list(recs_to_export.values())[0]
            default_name = first_rec.get('title', '试验记录').replace('/', '_').replace('\\', '_')
            default_name = f'{default_name}.docx'
        elif level == 'task':
            task_name = self.projects[pid]['tasks'][tid].get('name', '任务')
            default_name = f'{task_name}_汇总.docx'
        else:
            proj_name = self.projects[pid].get('name', '项目')
            default_name = f'{proj_name}_完整报告.docx'

        filepath, _ = QFileDialog.getSaveFileName(
            self, '导出Word文档', os.path.join(DATA_DIR, default_name), 'Word文档 (*.docx)')
        if not filepath:
            return

        try:
            # ---- 初始化文档 ----
            doc = Document()

            # ---- 页面统一设置 ----
            sec = doc.sections[0]
            sec.top_margin = self._REPORT_STYLES['page_top_margin']
            sec.bottom_margin = self._REPORT_STYLES['page_bottom_margin']
            sec.left_margin = self._REPORT_STYLES['page_left_margin']
            sec.right_margin = self._REPORT_STYLES['page_right_margin']

            # ---- 创建内置命名样式 ----
            ns = self._create_named_styles(doc)

            # ---- 封面标题文字 ----
            if level == 'project':
                proj_name = self.projects[pid].get('name', '项目')
                title_text = f'{proj_name} - 完整试验报告'
            elif level == 'task':
                task_name = self.projects[pid]['tasks'][tid].get('name', '任务')
                title_text = f'{task_name} - 汇总报告'
            else:
                first_rec = list(recs_to_export.values())[0]
                title_text = first_rec.get('title', '试验记录')

            # ---- 封面 ----
            self._add_cover_page(doc, ns, title_text, include_cover)

            # ---- 目录（可选） ----
            if include_toc:
                p = doc.add_paragraph()
                p.style = doc.styles[ns['CoverTitle']]
                run = p.add_run('目录')
                run.font.size = Pt(14)
                # Word 自动目录字段
                fldChar1 = OxmlElement('w:fldChar')
                fldChar1.set(qn('w:fldCharType'), 'begin')
                instrText = OxmlElement('w:instrText')
                instrText.text = ' TOC \\o "1-3" \\h \\z \\u '
                fldChar2 = OxmlElement('w:fldChar')
                fldChar2.set(qn('w:fldCharType'), 'separate')
                fldChar3 = OxmlElement('w:fldChar')
                fldChar3.set(qn('w:fldCharType'), 'end')
                run2 = p.add_run()
                run2._element.append(fldChar1)
                run2._element.append(instrText)
                run2._element.append(fldChar2)
                run2._element.append(fldChar3)
                doc.add_page_break()

            # ---- 写入所有记录 ----
            rec_idx = 0
            fig_counter = [0]  # 全局图号计数器（跨记录连续编号）
            for key, rec in recs_to_export.items():
                if rec_idx > 0:
                    doc.add_page_break()
                self._add_record_section(doc, ns, rec, rec_idx, img_quality, fig_counter)
                rec_idx += 1

            # ---- 生成页眉（项目/任务名称，宋体小五中度灰居中） ----
            header_text = ''
            if level == 'project':
                header_text = self.projects[pid].get('name', '')
            elif level == 'task':
                header_text = self.projects[pid]['tasks'][tid].get('name', '')
            else:
                first_rec = list(recs_to_export.values())[0]
                header_text = first_rec.get('title', '')
            if header_text:
                header = sec.header
                hp = header.paragraphs[0]
                hp.text = header_text
                hp.alignment = WD_ALIGN_PARAGRAPH.CENTER
                for run in hp.runs:
                    run.font.size = self._REPORT_STYLES['header_size']
                    run.font.color.rgb = self._REPORT_STYLES['header_color']
                    self._set_cn_font(run, self._REPORT_STYLES['header_font'])

            # ---- 页码（页脚，第 X 页 共 Y 页） ----
            if include_page_num:
                footer = sec.footer
                fp = footer.paragraphs[0]
                fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
                run = fp.add_run('第 ')
                run.font.size = self._REPORT_STYLES['footer_size']
                run.font.color.rgb = self._REPORT_STYLES['footer_color']
                self._set_cn_font(run, self._REPORT_STYLES['footer_font'])

                # PAGE 域
                run2 = fp.add_run()
                fldChar1 = OxmlElement('w:fldChar')
                fldChar1.set(qn('w:fldCharType'), 'begin')
                instrText = OxmlElement('w:instrText')
                instrText.text = ' PAGE '
                fldChar2 = OxmlElement('w:fldChar')
                fldChar2.set(qn('w:fldCharType'), 'separate')
                fldChar3 = OxmlElement('w:fldChar')
                fldChar3.set(qn('w:fldCharType'), 'end')
                run2._element.append(fldChar1)
                run2._element.append(instrText)
                run2._element.append(fldChar2)
                run2._element.append(fldChar3)

                run3 = fp.add_run(' 页 共 ')
                run3.font.size = self._REPORT_STYLES['footer_size']
                run3.font.color.rgb = self._REPORT_STYLES['footer_color']
                self._set_cn_font(run3, self._REPORT_STYLES['footer_font'])

                run4 = fp.add_run()
                fldChar1b = OxmlElement('w:fldChar')
                fldChar1b.set(qn('w:fldCharType'), 'begin')
                instrText2 = OxmlElement('w:instrText')
                instrText2.text = ' NUMPAGES '
                fldChar2b = OxmlElement('w:fldChar')
                fldChar2b.set(qn('w:fldCharType'), 'separate')
                fldChar3b = OxmlElement('w:fldChar')
                fldChar3b.set(qn('w:fldCharType'), 'end')
                run4._element.append(fldChar1b)
                run4._element.append(instrText2)
                run4._element.append(fldChar2b)
                run4._element.append(fldChar3b)

            # ---- 水印（可选，浅灰色底层） ----
            if watermark_text:
                for p in doc.paragraphs:
                    for run in p.runs:
                        if run.text.strip():
                            run.font.color.rgb = self._REPORT_STYLES['watermark_color']

            # ---- 报告尾注 ----
            doc.add_paragraph()
            total_records = len(recs_to_export)
            now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
            export_metadata = build_export_metadata(
                input_summary={
                    'scope': level,
                    'project_id': pid,
                    'task_id': tid,
                    'record_id': rid,
                    'record_count': total_records,
                },
                parameters={
                    'report_style': style_name,
                    'include_cover': include_cover,
                    'include_toc': include_toc,
                    'include_page_num': include_page_num,
                    'image_quality': img_quality,
                    'watermark_text': watermark_text,
                },
            )
            for metadata_line in self._export_metadata_lines(export_metadata):
                self._add_endnote(doc, ns, metadata_line)
            self._add_endnote(
                doc,
                ns,
                f'生成工具：试验记录助手 | 总记录数：{total_records} 条 '
                f'| 导出时间：{now_str}',
            )
            self._add_endnote(doc, ns, '— 本报告由「试验记录助手」自动生成 —')

            # ---- 保存 ----
            doc.save(filepath)
            logger.info(
                'Word导出成功 [%s]: %s',
                style_name,
                os.path.basename(filepath),
            )
            QMessageBox.information(
                self,
                '导出成功',
                f'Word文档已保存到:\n{os.path.basename(filepath)}',
            )

        except (OSError, ValueError, RuntimeError) as e:
            export_error = ExportError(
                'Word 文档导出失败，请检查目标目录权限和磁盘空间'
            )
            handle_ui_exception(self, logger, '导出 Word 文档', export_error)
        except Exception as e:
            handle_ui_exception(self, logger, '导出 Word 文档', e)
