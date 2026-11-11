"""试验记录助手截图链路回归测试（添加入库、持久化、导出嵌图）。"""
from __future__ import annotations

import os
import struct
import zlib
import tempfile
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt5.QtWidgets import QApplication, QPushButton
from PyQt5.QtCore import Qt

from radar_tool.exp_recorder import ExpRecorderPanel


def _app():
    return QApplication.instance() or QApplication([])


def _make_png(path, w=8, h=8):
    def chunk(tag, data):
        block = struct.pack('>I', len(data)) + tag + data
        block += struct.pack('>I', zlib.crc32(tag + data) & 0xffffffff)
        return block

    raw = b''.join(b'\x00' + b'\xff\x00\x00' * w for _ in range(h))
    png = (b'\x89PNG\r\n\x1a\n'
           + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0))
           + chunk(b'IDAT', zlib.compress(raw))
           + chunk(b'IEND', b''))
    with open(path, 'wb') as handle:
        handle.write(png)


def _make_panel_with_record():
    panel = ExpRecorderPanel()
    panel.projects = {
        'p1': {
            'name': '项目A', 'description': '',
            'tasks': {'t1': {
                'name': '任务A',
                'records': {'r1': {
                    'title': '记录A', 'date': '2026-01-01', 'personnel': 'x',
                    'location': '', 'template': '通用试验记录', 'conditions': '',
                    'content': '', 'steps': [], 'conclusion': '',
                }},
            }},
        }
    }
    panel.current_project_id = 'p1'
    panel.current_task_id = 't1'
    panel.current_record_id = 'r1'
    panel._refresh_tree()
    panel._load_record('p1', 't1', 'r1')
    return panel


def _find_add_button(frame):
    for button in frame.findChildren(QPushButton):
        if '添加截图' in button.text():
            return button
    raise AssertionError('未找到添加截图按钮')


def test_step_screenshot_button_persists_and_exports():
    """点击按钮添加截图后：列表有反馈、图片入库、保存后导出 Word 含图。"""
    app = _app()
    panel = _make_panel_with_record()
    tmp = tempfile.mkdtemp()
    data_dir = os.path.join(tmp, 'data')
    images_dir = os.path.join(data_dir, 'images')
    os.makedirs(images_dir, exist_ok=True)
    src_img = os.path.join(tmp, 'shot.png')
    _make_png(src_img)

    with patch('radar_tool.exp_recorder.DATA_DIR', data_dir), \
         patch('radar_tool.exp_recorder.IMAGES_DIR', images_dir), \
         patch('radar_tool.exp_recorder.QFileDialog.getOpenFileName',
               return_value=(src_img, '图片文件 (*.png)')), \
         patch('radar_tool.exp_recorder.QInputDialog.getText',
               return_value=('图注A', True)):
        frame = panel.step_widgets[-1]['frame']
        img_list = panel.step_widgets[-1]['img_list']

        _find_add_button(frame).click()
        app.processEvents()

        # 添加后列表必须有可见反馈（回归 clicked(bool) 覆盖 lambda 参数的缺陷）
        assert img_list.count() == 1
        item_data = img_list.item(0).data(Qt.UserRole)
        assert item_data['caption'] == '图注A'

        # 图片必须已复制到后台管理目录（而非仅记录外部源路径）
        stored_rel = item_data['path']
        assert not os.path.isabs(stored_rel)
        stored_abs = os.path.join(images_dir, stored_rel)
        assert os.path.isfile(stored_abs)

        # 保存后记录数据必须包含图片引用
        assert panel._save_current_record() is True
        steps = panel.projects['p1']['tasks']['t1']['records']['r1']['steps']
        images = [img for step in steps for img in step.get('images', [])]
        assert len(images) == 1
        assert os.path.isfile(os.path.join(images_dir, images[0]['path']))

        # 导出 Word 必须嵌入该图片
        docx_path = os.path.join(tmp, 'out.docx')
        from docx import Document
        doc = Document()
        ns = panel._create_named_styles(doc)
        fig = [0]
        panel._add_record_section(
            doc, ns, panel.projects['p1']['tasks']['t1']['records']['r1'], 0, '标准', fig)
        doc.save(docx_path)
        saved = Document(docx_path)
        image_rels = [r for r in saved.part.rels.values() if 'image' in r.reltype]
        assert len(image_rels) == 1

    panel.close()


def test_step_screenshot_invalid_file_shows_feedback():
    """非法图片必须弹窗提示而不是静默失败。"""
    app = _app()
    panel = _make_panel_with_record()
    tmp = tempfile.mkdtemp()
    bad = os.path.join(tmp, 'bad.png')
    with open(bad, 'wb') as handle:
        handle.write(b'not an image')

    with patch('radar_tool.exp_recorder.QFileDialog.getOpenFileName',
               return_value=(bad, '图片文件 (*.png)')), \
         patch('radar_tool.exp_recorder.QMessageBox.warning') as warning:
        frame = panel.step_widgets[-1]['frame']
        img_list = panel.step_widgets[-1]['img_list']
        _find_add_button(frame).click()
        app.processEvents()

        assert img_list.count() == 0
        warning.assert_called_once()
    panel.close()


def test_project_export_has_task_levels_and_no_metadata_hints():
    """项目导出必须是 项目→任务→记录 三级结构，且不含元数据小字提示。"""
    from PyQt5.QtWidgets import QDialog
    from docx import Document

    app = _app()
    panel = ExpRecorderPanel()
    panel.projects = {
        'p1': {
            'name': '项目A', 'description': '',
            'tasks': {
                't1': {'name': '任务A', 'records': {'r1': {
                    'title': '记录A1', 'date': '2026-01-01', 'personnel': '',
                    'location': '', 'template': '通用试验记录', 'conditions': '',
                    'content': '', 'steps': [], 'conclusion': '',
                }}},
                't2': {'name': '任务B', 'records': {'r2': {
                    'title': '记录B1', 'date': '2026-01-02', 'personnel': '',
                    'location': '', 'template': '通用试验记录', 'conditions': '',
                    'content': '', 'steps': [], 'conclusion': '',
                }}},
            },
        }
    }
    tmp = tempfile.mkdtemp()
    out_docx = os.path.join(tmp, 'out.docx')

    with patch('radar_tool.experiment_word_export.QDialog.exec_',
               return_value=QDialog.Accepted), \
         patch('radar_tool.experiment_word_export.QFileDialog.getSaveFileName',
               return_value=(out_docx, 'Word文档 (*.docx)')), \
         patch('radar_tool.experiment_word_export.QMessageBox.information'):
        panel._export_to_word('project', pid='p1')

    doc = Document(out_docx)
    texts = [p.text for p in doc.paragraphs if p.text.strip()]
    assert any('任务：任务A' in t for t in texts)
    assert any('任务：任务B' in t for t in texts)
    assert any('记录A1' in t for t in texts)
    assert any('记录B1' in t for t in texts)
    banned = ('导出元数据', '输入摘要', '参数：', '本报告由', '生成工具')
    assert not any(b in t for t in texts for b in banned)
    panel.close()
