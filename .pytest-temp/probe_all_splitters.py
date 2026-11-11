"""探测各页面左右 splitter 的尺寸构成。"""
import os
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'windows')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt5.QtWidgets import QApplication, QSplitter
from radar_tool.main_window import MainWindow
from radar_tool.run import configure_matplotlib


def find_splitters(widget):
    return widget.findChildren(QSplitter)


def main():
    configure_matplotlib()
    app = QApplication.instance() or QApplication([])
    w = MainWindow()
    w.show()
    app.processEvents()

    for index in range(len(w._tab_names)):
        panel = w._lazy_create_or_get_panel(index)
        name = w._tab_names[index]
        if panel is None:
            print(f'[{name}] 加载失败')
            continue
        app.processEvents()
        splitters = [
            s for s in find_splitters(panel)
            if s.orientation() == 0x1  # Qt.Horizontal
        ]
        if not splitters:
            print(f'[{name}] 无横向 splitter')
            continue
        for s in splitters:
            sizes = s.sizes()
            parts = []
            for i in range(s.count()):
                child = s.widget(i)
                hint = child.sizeHint()
                mhint = child.minimumSizeHint()
                parts.append(f'child{i}: hint={hint.width()}x{hint.height()} minHint={mhint.width()} cur={sizes[i] if i < len(sizes) else "?"}')
            print(f'[{name}] splitter sizes={sizes} | ' + ' | '.join(parts))
    w.close()


if __name__ == '__main__':
    main()
