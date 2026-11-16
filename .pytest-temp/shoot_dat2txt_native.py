"""Render the visualization workspace tabs to PNG (native Windows platform, real fonts)."""
import os
import sys

os.environ.pop('QT_QPA_PLATFORM', None)
os.environ.setdefault('RADAR_TOOL_MAX_THREADS', '2')

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from PyQt5.QtWidgets import QApplication
from PyQt5.QtGui import QFont
from PyQt5.QtCore import QTimer

app = QApplication(sys.argv)
app.setStyle('Fusion')
app.setFont(QFont('Microsoft YaHei', 10))

import matplotlib

matplotlib.use('Qt5Agg')
from matplotlib import pyplot as _plt
from radar_tool.app_config import MATPLOTLIB_RC_PARAMS

for _k, _v in MATPLOTLIB_RC_PARAMS.items():
    try:
        _plt.rcParams[_k] = _v
    except Exception:
        pass

from radar_tool.main_window import MainWindow

OUT = os.path.join(ROOT, '.pytest-temp', 'shots')
os.makedirs(OUT, exist_ok=True)

w = MainWindow()
w.setWindowState(w.windowState() & ~0x00000002)
w.resize(1560, 960)
w.show()
w.raise_()

viz = w._tab_panels[0]
state = {'step': 0}


def shoot():
    steps = [
        (0, 'viz_plot_tab.png'),
        (1, 'viz_dat2txt_tab.png'),
    ]
    index, name = steps[state['step']]
    viz.workspace_tabs.setCurrentIndex(index)
    for _ in range(10):
        app.processEvents()
    pix = viz.grab()
    path = os.path.join(OUT, name)
    pix.save(path)
    print('saved', path, pix.width(), pix.height(), flush=True)
    state['step'] += 1
    if state['step'] < len(steps):
        QTimer.singleShot(400, shoot)
    else:
        w.close()
        app.quit()


QTimer.singleShot(1500, shoot)
app.exec_()
