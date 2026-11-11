"""截图可视化面板检查排布。"""
import os
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'windows')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt5.QtWidgets import QApplication
from radar_tool.main_window import MainWindow
from radar_tool.run import configure_matplotlib


def main():
    configure_matplotlib()
    app = QApplication.instance() or QApplication([])
    w = MainWindow()
    w.show()
    app.processEvents()
    panel = w._tab_panels[0]
    splitter = panel.layout().itemAt(1).widget()
    print('splitter sizes (左, 右):', splitter.sizes())
    pix = panel.grab()
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'viz_panel.png')
    pix.save(out)
    left = splitter.widget(0)
    left.grab().save(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'viz_left.png'))
    print('saved', out)
    w.close()


if __name__ == '__main__':
    main()
