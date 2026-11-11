"""探测主窗口最小尺寸构成，定位横向过宽来源。"""
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
    screen = app.primaryScreen().availableGeometry()
    print(f'屏幕可用区域: {screen.width()}x{screen.height()}')

    window = MainWindow()
    window.show()
    app.processEvents()

    print(f'主窗口 sizeHint: {window.sizeHint().width()}x{window.sizeHint().height()}')
    print(f'主窗口 minimumSizeHint: {window.minimumSizeHint().width()}x{window.minimumSizeHint().height()}')

    panel = window._tab_panels[0]
    print(f'可视化面板 minimumSizeHint: {panel.minimumSizeHint().width()}x{panel.minimumSizeHint().height()}')
    print(f'feature_tabs minimumSizeHint: {window.feature_tabs.minimumSizeHint().width()}x{window.feature_tabs.minimumSizeHint().height()}')

    ctrl = getattr(panel, 'btn_plot', None)
    if ctrl is not None:
        group = ctrl.parent()
        while group is not None and not hasattr(group, 'title'):
            group = group.parent()
        if group is not None:
            print(f'绘图控制组 minimumSizeHint: {group.minimumSizeHint().width()}x{group.minimumSizeHint().height()}')
            row = group.layout()
            total = 0
            for i in range(row.count()):
                item = row.itemAt(i)
                w = item.widget()
                if w is not None:
                    m = w.minimumSizeHint().width()
                    total += m
                    print(f'  控件 {w.__class__.__name__} {getattr(w, "text", lambda: "")()!r:30} minW={m}')
                else:
                    sub = item.layout()
                    if sub is not None:
                        print(f'  子布局 {sub.__class__.__name__}')
            print(f'  行内控件最小宽度合计: {total}')

    window.close()


if __name__ == '__main__':
    main()
