#!/usr/bin/env python3
import sys
import os

import matplotlib.pyplot as plt
from PyQt5.QtGui import QFont, QIcon
from PyQt5.QtWidgets import QApplication

# 处理 PyInstaller / Nuitka 打包后的路径
if getattr(sys, 'frozen', False) or hasattr(sys, '__compiled__'):
    # 打包后的 exe 运行
    _project_root = os.path.dirname(sys.executable)
    sys.path.insert(0, _project_root)
    # 设置 matplotlib 缓存目录避免写入权限问题
    os.environ['MPLCONFIGDIR'] = os.path.join(_project_root, '.matplotlib_cache')
else:
    # 正常 Python 运行
    _project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _project_root not in sys.path:
        sys.path.insert(0, _project_root)

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
    window.setWindowIcon(QIcon(os.path.join(_project_root, 'image', 'rose.ico')))
    app.setWindowIcon(QIcon(os.path.join(_project_root, 'image', 'rose.ico')))
    window.show()
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
