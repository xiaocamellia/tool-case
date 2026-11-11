"""临时复现脚本：试验步骤内添加截图 -> 保存 -> 导出 Word 全链路。"""
import os
import sys
import struct
import zlib
import tempfile
import traceback
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt
import radar_tool.exp_recorder as er
from radar_tool.exp_recorder import ExpRecorderPanel


def make_png(path, w=8, h=8):
    """构造一张最小合法 PNG。"""
    def chunk(tag, data):
        c = struct.pack('>I', len(data)) + tag + data
        c += struct.pack('>I', zlib.crc32(tag + data) & 0xffffffff)
        return c

    raw = b''.join(b'\x00' + b'\xff\x00\x00' * w for _ in range(h))
    png = (b'\x89PNG\r\n\x1a\n'
           + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0))
           + chunk(b'IDAT', zlib.compress(raw))
           + chunk(b'IEND', b''))
    with open(path, 'wb') as f:
        f.write(png)


def main():
    app = QApplication.instance() or QApplication([])
    panel = ExpRecorderPanel()

    tmp = tempfile.mkdtemp()
    data_dir = os.path.join(tmp, 'data')
    images_dir = os.path.join(data_dir, 'images')
    os.makedirs(images_dir, exist_ok=True)

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

    src_img = os.path.join(tmp, '截图 测试.png')
    make_png(src_img)

    with patch('radar_tool.exp_recorder.DATA_DIR', data_dir), \
         patch('radar_tool.exp_recorder.IMAGES_DIR', images_dir), \
         patch('radar_tool.exp_recorder.QFileDialog.getOpenFileName',
               return_value=(src_img, '图片文件 (*.png)')), \
         patch('radar_tool.exp_recorder.QInputDialog.getText',
               return_value=('图注A', True)):
        panel._refresh_tree()
        panel._load_record('p1', 't1', 'r1')
        panel._add_step()
        frame = panel.step_widgets[-1]['frame']
        img_list = panel.step_widgets[-1]['img_list']

        print('before add: img_list.count =', img_list.count())
        try:
            panel._add_step_screenshot(frame)
        except Exception:
            print('!!! _add_step_screenshot 抛出异常:')
            traceback.print_exc()
        print('after add: img_list.count =', img_list.count())
        for i in range(img_list.count()):
            it = img_list.item(i)
            print('  item', i, repr(it.text()), '->', it.data(Qt.UserRole))

        # 保存
        try:
            ok = panel._save_current_record()
            print('save ok =', ok)
        except Exception:
            print('!!! _save_current_record 抛出异常:')
            traceback.print_exc()
            ok = False

        rec = panel.projects['p1']['tasks']['t1']['records']['r1']
        steps = rec.get('steps', [])
        print('saved steps =', steps)

        # 导出 Word
        docx_path = os.path.join(tmp, 'out.docx')
        try:
            export_ok = export_word(panel, rec, docx_path)
            print('export ok =', export_ok)
        except Exception:
            print('!!! 导出抛出异常:')
            traceback.print_exc()

        if os.path.exists(docx_path):
            from docx import Document
            doc = Document(docx_path)
            imgs = [r for r in doc.part.rels.values() if 'image' in r.reltype]
            print('docx 图片数量 =', len(imgs))
        else:
            print('docx 未生成')

    panel.close()
    print('tmp dir:', tmp)


def export_word(panel, rec, out_path):
    """直接调用内部导出布局，绕过对话框。"""
    from docx import Document
    from radar_tool import experiment_word_export as we

    doc = Document()
    ns = panel._create_named_styles(doc)
    fig = [0]
    panel._add_record_section(doc, ns, rec, 0, '标准', fig)
    doc.save(out_path)
    return True


if __name__ == '__main__':
    main()
