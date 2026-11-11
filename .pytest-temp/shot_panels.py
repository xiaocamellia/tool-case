"""截图检查测向校正/指标计算器/格式转换的左右布局。"""
import os
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'windows')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt5.QtWidgets import QApplication, QSplitter
from radar_tool.main_window import MainWindow
from radar_tool.run import configure_matplotlib

TARGETS = {'测向校正自动化': 'calib', '🧮 指标计算器': 'calc', '格式转换': 'fmt'}


def main():
    configure_matplotlib()
    app = QApplication.instance() or QApplication([])
    w = MainWindow()
    w.show()
    app.processEvents()
    here = os.path.dirname(os.path.abspath(__file__))
    for index in range(len(w._tab_names)):
        name = w._tab_names[index]
        if name not in TARGETS:
            continue
        w.feature_tabs.setCurrentIndex(index)
        app.processEvents()
        panel = w._tab_panels[index]
        splitters = [s for s in panel.findChildren(QSplitter) if s.orientation() == 0x1]
        for s in splitters:
            print(f'[{name}] sizes={s.sizes()}')
        panel.grab().save(os.path.join(here, f'panel_{TARGETS[name]}.png'))
    w.close()
    print('done')


if __name__ == '__main__':
    main()
