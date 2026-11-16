import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from radar_tool.run import configure_matplotlib

configure_matplotlib()
from PyQt5.QtWidgets import QApplication

APP = QApplication.instance() or QApplication([])
from radar_tool.main_window import MainWindow

window = MainWindow()
window.resize(1440, 900)
window.show()
APP.processEvents()

viz = window._tab_panels[0]
out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'shots')
os.makedirs(out_dir, exist_ok=True)

viz.workspace_tabs.setCurrentIndex(0)
APP.processEvents()
viz.grab().save(os.path.join(out_dir, 'viz_plot_tab.png'))

viz.workspace_tabs.setCurrentIndex(1)
APP.processEvents()
viz.grab().save(os.path.join(out_dir, 'viz_dat2txt_tab.png'))

print('shots saved to', out_dir, flush=True)
window.close()
APP.processEvents()
