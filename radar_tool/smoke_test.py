"""Headless smoke checks shared by source runs and packaged executables."""

from __future__ import annotations

import os
import importlib.util


def run_smoke_test() -> None:
    """Initialize every application tab and validate packaged runtime paths."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PyQt5.QtGui import QPixmap
    from PyQt5.QtWidgets import QApplication

    from .main_window import MainWindow
    from .run import configure_matplotlib
    from .runtime_paths import (
        get_resource_path,
        get_user_data_dir,
        get_user_data_root,
        is_frozen,
    )

    configure_matplotlib()
    app = QApplication.instance() or QApplication([])
    resource_path = get_resource_path("image", "rose.ico")
    if not os.path.isfile(resource_path):
        raise FileNotFoundError(f"缺少应用图标资源: {resource_path}")
    if QPixmap(resource_path).isNull():
        raise RuntimeError("应用图标资源无法解析")

    if importlib.util.find_spec("docx") is not None:
        from docx import Document

        Document()
    elif is_frozen():
        raise RuntimeError("python-docx 未打包")
    if importlib.util.find_spec("openpyxl") is not None:
        from openpyxl import Workbook

        Workbook()
    elif is_frozen():
        raise RuntimeError("openpyxl 未打包")
    if importlib.util.find_spec("xlrd") is not None:
        import xlrd

        if not xlrd.__version__:
            raise RuntimeError("Excel 引擎版本不可用")
    elif is_frozen():
        raise RuntimeError("xlrd 未打包")
    from matplotlib import font_manager

    if not os.path.isfile(font_manager.findfont("DejaVu Sans")):
        raise RuntimeError("matplotlib 字体资源不可用")

    user_data_dir = get_user_data_dir(".smoke-test")
    user_data_root = os.path.abspath(get_user_data_root())
    if os.path.commonpath(
        [os.path.abspath(user_data_dir), user_data_root]
    ) != user_data_root:
        raise RuntimeError("用户数据目录未落在受管运行目录内")

    window = MainWindow()
    window.show()
    for index in range(1, len(window._tab_names)):
        window.feature_tabs.setCurrentIndex(index)
        app.processEvents()
    if not all(window._tab_loaded):
        missing = [
            name
            for name, loaded in zip(window._tab_names, window._tab_loaded)
            if not loaded
        ]
        raise RuntimeError(f"离屏初始化失败的页签: {'、'.join(missing)}")

    window.close()
    app.processEvents()
