"""验证 PyQt clicked(bool) 覆盖 lambda 默认参数的 bug。"""
import os
import sys
import struct
import zlib
import tempfile
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt
from radar_tool.exp_recorder import ExpRecorderPanel


def make_png(path, w=8, h=8):
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
        'p1': {'name': '项目A', 'description': '', 'tasks': {'t1': {
            'name': '任务A', 'records': {'r1': {
                'title': '记录A', 'date': '2026-01-01', 'personnel': 'x',
                'location': '', 'template': '通用试验记录', 'conditions': '',
                'content': '', 'steps': [], 'conclusion': '',
            }}}}}
    }
    panel.current_project_id = 'p1'
    panel.current_task_id = 't1'
    panel.current_record_id = 'r1'

    src_img = os.path.join(tmp, 'shot.png')
    make_png(src_img)

    # 通过 _add_step 找到真实的按钮并 click()，复现用户操作
    panel._refresh_tree()
    panel._load_record('p1', 't1', 'r1')
    sw = panel.step_widgets[-1]
    frame = sw['frame']
    img_list = sw['img_list']

    # 找到「添加截图」按钮
    from PyQt5.QtWidgets import QPushButton
    btn = None
    for b in frame.findChildren(QPushButton):
        if '添加截图' in b.text():
            btn = b
            break
    assert btn is not None, '未找到添加截图按钮'

    print('button found:', repr(btn.text()))

    with patch('radar_tool.exp_recorder.DATA_DIR', data_dir), \
         patch('radar_tool.exp_recorder.IMAGES_DIR', images_dir), \
         patch('radar_tool.exp_recorder.QFileDialog.getOpenFileName',
               return_value=(src_img, '图片文件 (*.png)')), \
         patch('radar_tool.exp_recorder.QInputDialog.getText',
               return_value=('图注A', True)):
        print('img_list count BEFORE click:', img_list.count())
        captured = {}
        orig = ExpRecorderPanel._add_step_screenshot

        def spy(self, f):
            captured['arg'] = f
            captured['repr'] = repr(f)
            return orig(self, f)
        with patch.object(ExpRecorderPanel, '_add_step_screenshot', spy):
            btn.click()
            app.processEvents()
        print('传给 _add_step_screenshot 的参数:', captured.get('repr'))
        print('是同一个 frame 吗:', captured.get('arg') is frame)
        print('img_list count AFTER click:', img_list.count())
        for i in range(img_list.count()):
            print('  item', i, img_list.item(i).text())

    panel.close()


if __name__ == '__main__':
    main()
