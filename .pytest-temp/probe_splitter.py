"""细测 splitter 两侧最小宽度。"""
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

    def mins(widget, name):
        m = widget.minimumSizeHint()
        print(f'{name:30s} min={m.width():5d}x{m.height():5d}')
        return m.width()

    top = panel.layout().itemAt(0).widget()
    mins(top, '数据控制组(2行)')
    splitter = panel.layout().itemAt(1).widget()
    for i in range(splitter.count()):
        side = splitter.widget(i)
        mins(side, f'splitter[{i}] ' + side.__class__.__name__)
        lay = side.layout()
        if lay is not None:
            for j in range(lay.count()):
                it = lay.itemAt(j)
                child = it.widget()
                if child is not None:
                    mm = child.minimumSizeHint()
                    title = ''
                    if isinstance(child, type(top)):
                        title = child.title()
                    print(f'    child[{j}] {child.__class__.__name__:16s} {title[:18]:20s} min={mm.width()}')
    print('--- 实际窗口 ---', w.width(), 'x', w.height(),
          '| minimumSize', w.minimumSize().width(), 'x', w.minimumSize().height())
    w.close()


if __name__ == '__main__':
    main()
