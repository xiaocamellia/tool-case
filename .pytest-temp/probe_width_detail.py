"""细探可视化面板宽度构成。"""
import os
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'windows')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt5.QtWidgets import QApplication, QSplitter
from radar_tool.main_window import MainWindow
from radar_tool.run import configure_matplotlib


def main():
    configure_matplotlib()
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.show()
    app.processEvents()
    panel = window._tab_panels[0]

    def dump(widget, name, depth=0):
        m = widget.minimumSizeHint()
        s = widget.sizeHint()
        print(f'{"  "*depth}{name} ({widget.__class__.__name__}) min={m.width()}x{m.height()} hint={s.width()}x{s.height()}')
        layout = widget.layout()
        if layout is not None and depth < 2:
            for i in range(layout.count()):
                item = layout.itemAt(i)
                child = item.widget()
                if child is not None:
                    dump(child, getattr(child, 'objectName', lambda: '')() or child.__class__.__name__, depth+1)

    dump(panel, '可视化面板')
    for i in range(panel.count() if hasattr(panel, 'count') else 0):
        pass

    canvas = None
    for view in panel.plot_views.values():
        canvas = view.canvas
        break
    if canvas is not None:
        print(f'画布 minimumSizeHint: {canvas.minimumSizeHint().width()}x{canvas.minimumSizeHint().height()}')
        print(f'画布 minimumSize: {canvas.minimumSize().width()}x{canvas.minimumSize().height()}')
        print(f'画布 figure size px: {canvas.figure.get_size_inches()[0]*canvas.figure.dpi:.0f}x{canvas.figure.get_size_inches()[1]*canvas.figure.dpi:.0f}')

    window.close()


if __name__ == '__main__':
    main()
