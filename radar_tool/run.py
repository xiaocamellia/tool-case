#!/usr/bin/env python3
import sys
import os

_current_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.dirname(_current_dir)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

import matplotlib.pyplot as plt
from PyQt5.QtGui import QFont, QIcon
from PyQt5.QtWidgets import QApplication
from radar_tool.runtime_paths import (
    get_launcher_dir,
    get_resource_path,
    get_user_data_dir,
    is_frozen,
)

os.environ['MPLCONFIGDIR'] = get_user_data_dir('.matplotlib_cache')

from radar_tool.main_window import MainWindow
from radar_tool.app_config import MATPLOTLIB_RC_PARAMS


def configure_matplotlib():
    for key, value in MATPLOTLIB_RC_PARAMS.items():
        plt.rcParams[key] = value


def main():
    configure_matplotlib()
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    app.setFont(QFont('Microsoft YaHei', 10))

    window = MainWindow()
    icon_path = get_resource_path('image', 'rose.ico')
    window.setWindowIcon(QIcon(icon_path))
    app.setWindowIcon(QIcon(icon_path))
    window.show()
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
