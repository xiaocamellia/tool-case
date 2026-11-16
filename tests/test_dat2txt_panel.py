"""DAT 导出 TXT 辅助面板与数据可视化双子页的离屏交互测试。"""

from __future__ import annotations

import os
from datetime import datetime
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PyQt5.QtWidgets import QApplication

from radar_tool.dat2txt_core import DATASETS, config_root, find_dataset
from radar_tool.dat2txt_panel import Dat2TxtPanel, parse_time_text
from radar_tool.main_window import MainWindow
from radar_tool.run import configure_matplotlib

pytestmark = pytest.mark.skipif(
    not (config_root() / 'receive').is_dir(),
    reason='Config/receive 免远程同步，源码树缺失时跳过（本地提供字段定义后执行）',
)

DATASET = find_dataset(0x3014)
assert DATASET is not None

# QApplication 由 sip 所有权管理：Python 侧引用一旦被 GC，Qt 应用对象随之销毁，
# 后续控件构建会 fastfail（0xC0000409）。必须在模块级长期持有。
_APP = None


def _app():
    global _APP
    configure_matplotlib()
    if _APP is None:
        _APP = QApplication.instance() or QApplication([])
    return _APP


def _bcd(value: int) -> int:
    return ((value // 10) << 4) | (value % 10)


def write_dat(path):
    """两帧 11:57:47 / 11:57:48 的合成 dat。"""
    payload = b'\x00' * DATASET.frame_data_length
    frames = []
    for second in (47, 48):
        frames.append(
            bytes([_bcd(26), _bcd(10), _bcd(22), _bcd(11), _bcd(57), _bcd(second)])
            + payload
        )
    with open(path, 'wb') as handle:
        handle.write(b''.join(frames))
    return str(path)


def _wait_thread(app, thread, timeout_ms=15000):
    if thread is None:
        return True
    steps = timeout_ms // 20
    for _ in range(max(1, steps)):
        app.processEvents()
        if thread.wait(20):
            app.processEvents()
            return True
    return False


def test_dat2txt_panel_offscreen_init_and_column_selection():
    _app()
    panel = Dat2TxtPanel(None)
    try:
        assert panel.combo_dataset.count() == len(DATASETS)
        assert panel.list_columns.count() == len(panel._specs) > 100
        assert panel.lbl_col_count.text().startswith('已选 %d /' % panel.list_columns.count())

        panel._select_no_columns()
        assert panel.lbl_col_count.text() == '已选 0 / %d 列' % panel.list_columns.count()
        assert panel._selected_column_indices() == []

        panel._invert_columns()
        assert len(panel._selected_column_indices()) == panel.list_columns.count()

        panel._select_all_columns()
        assert len(panel._selected_column_indices()) == panel.list_columns.count()
    finally:
        panel.close()


def test_dat2txt_panel_reads_time_range_and_default_output(tmp_path):
    _app()
    panel = Dat2TxtPanel(None)
    try:
        dat_path = write_dat(tmp_path / 'sample.dat')
        panel.edit_dat_path.setText(dat_path)
        panel.edit_txt_path.setText('')
        panel._on_dat_path_edited()

        assert panel.edit_start.text() == '2026-10-22 11:57:47'
        assert panel.edit_end.text() == '2026-10-22 11:57:48'
        assert panel.edit_txt_path.text().endswith('_export.txt')
        assert DATASET.key in panel.edit_txt_path.text()
        assert '共 2 帧' in panel.txt_log.toPlainText()
    finally:
        panel.close()


def test_dat2txt_panel_export_end_to_end(tmp_path):
    app = _app()
    panel = Dat2TxtPanel(None)
    try:
        dat_path = write_dat(tmp_path / 'sample.dat')
        txt_path = str(tmp_path / 'export.txt')
        panel.edit_dat_path.setText(dat_path)
        panel.edit_txt_path.setText(txt_path)
        panel.edit_start.setText('2026-10-22 11:57:47')
        panel.edit_end.setText('2026-10-22 11:57:48')
        panel.spin_interval.setValue(0)

        with patch('radar_tool.dat2txt_panel.QMessageBox') as _box:
            panel._start_export()
            assert panel._export_thread is not None
            assert _wait_thread(app, panel._export_thread)

        assert panel._last_result is not None
        assert panel._last_result.written_lines == 2
        assert os.path.isfile(txt_path)
        assert os.path.isfile(panel._last_result.column_path)
        assert panel.btn_export.isEnabled()
        assert not panel.btn_cancel.isEnabled()
        assert panel.btn_load_result.isEnabled()
        assert '导出完成' in panel.lbl_status.text()
    finally:
        panel.close()


def test_dat2txt_panel_forwards_exported_result_to_workspace():
    _app()
    calls = []

    class _FakeWorkspace:
        def __init__(self):
            self.currentIndex = 0

        def setCurrentIndex(self, index):
            self.currentIndex = index

    class _FakeViz:
        def __init__(self):
            self.workspace_tabs = _FakeWorkspace()

        def load_dataset_paths(self, paths):
            calls.append(list(paths))

    viz = _FakeViz()
    panel = Dat2TxtPanel(viz)
    try:
        panel._last_result = type('R', (), {'txt_path': 'C:/tmp/out.txt'})()
        panel._load_exported_result()
        assert calls == [['C:/tmp/out.txt']]
        assert viz.workspace_tabs.currentIndex == 0
    finally:
        panel.close()


def test_visualization_panel_exposes_two_workspace_tabs_and_loads_txt(tmp_path):
    app = _app()
    window = MainWindow()
    try:
        viz = window._tab_panels[0]
        assert viz.workspace_tabs.count() == 2
        assert viz.workspace_tabs.tabText(0) == '数据绘图'
        assert viz.workspace_tabs.tabText(1) == 'DAT 导出 TXT'
        assert isinstance(viz.dat2txt_panel, Dat2TxtPanel)

        dat_path = write_dat(tmp_path / 'sample.dat')
        txt_path = str(tmp_path / 'export.txt')
        exporter = viz.dat2txt_panel
        exporter.edit_dat_path.setText(dat_path)
        exporter.edit_txt_path.setText(txt_path)
        exporter.edit_start.setText('2026-10-22 11:57:47')
        exporter.edit_end.setText('2026-10-22 11:57:48')
        with patch('radar_tool.dat2txt_panel.QMessageBox') as _box:
            exporter._start_export()
            assert _wait_thread(app, exporter._export_thread)
        assert os.path.isfile(txt_path)

        viz.load_dataset_paths([txt_path])
        for _ in range(200):
            app.processEvents()
            if viz._dataset_load_thread is None:
                break
            viz._dataset_load_thread.wait(20)
        app.processEvents()

        assert len(viz.datasets) == 1
        dataset = next(iter(viz.datasets.values()))
        assert dataset.data_filepath == txt_path
        assert dataset.col_filepath.endswith('列名.txt')
    finally:
        window.close()
        app.processEvents()


def test_parse_time_text_accepts_cli_formats():
    assert parse_time_text('2026-10-22 11:57:47') == datetime(2026, 10, 22, 11, 57, 47)
    assert parse_time_text('2026-10-22 11:57') == datetime(2026, 10, 22, 11, 57)
    assert parse_time_text('2026/10/22 11:57:47') == datetime(2026, 10, 22, 11, 57, 47)
    assert parse_time_text('20261022115747') == datetime(2026, 10, 22, 11, 57, 47)
    try:
        parse_time_text('10/22/2026')
    except ValueError:
        pass
    else:
        raise AssertionError('非法时间应抛出 ValueError')
