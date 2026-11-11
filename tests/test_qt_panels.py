"""Offscreen initialization and key interaction tests for all Qt panels."""

from __future__ import annotations

import os
import tempfile
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pandas as pd
import pytest
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication

from radar_tool.calc_ui import CalcPanel
from radar_tool.exp_recorder import ExpRecorderPanel
from radar_tool.game_panel import GamePanel
from radar_tool.interferometer_sim import InterferometerSimPanel
from radar_tool.main_window import MainWindow
from radar_tool.run import configure_matplotlib
from radar_tool.smoke_test import run_smoke_test


def _app():
    configure_matplotlib()
    return QApplication.instance() or QApplication([])


def test_all_lazy_application_tabs_initialize_offscreen():
    run_smoke_test()


def test_calculator_navigation_switches_every_formula_page():
    app = _app()
    panel = CalcPanel()

    for row in range(panel.nav_list.count()):
        panel.nav_list.setCurrentRow(row)
        app.processEvents()
        assert panel.stack.currentIndex() == row

    panel.close()


def test_game_reset_control_rebuilds_valid_initial_grid():
    _app()
    panel = GamePanel()
    game = panel.game_tabs.widget(0)

    game.btn_reset.click()

    assert game.score == 0
    assert len(game.grid) == 4
    assert all(len(row) == 4 for row in game.grid)
    assert sum(value > 0 for row in game.grid for value in row) == 2
    panel.close()


def test_visualization_checked_columns_can_be_added_without_selection():
    app = _app()
    window = MainWindow()
    panel = window._tab_panels[0]
    dataset_id = panel._register_loaded_dataset({
        'filepath': 'test.csv',
        'label': 'test.csv',
        'col_file': '',
        'dataframe': pd.DataFrame({'alpha': [1, 2], 'beta': [3, 4]}),
    })
    panel.set_active_dataset(dataset_id)
    panel.list_columns.clearSelection()
    panel.list_columns.item(0).setCheckState(Qt.Checked)

    panel.add_selected_to_plot()

    assert [item.col_name for item in panel.plot_items] == ['alpha']
    window.close()


def test_visualization_table_mode_size_and_export_naming():
    """表格视图、图片尺寸预设与导出默认命名（文件名+字段名）。"""
    from radar_tool.plotting import compact_series_label, default_export_basename

    app = _app()
    window = MainWindow()
    panel = window._tab_panels[0]
    dataset_id = panel._register_loaded_dataset({
        'filepath': '飞测数据.txt',
        'label': '飞测数据.txt',
        'col_file': '',
        'dataframe': pd.DataFrame({'alpha': [1.0, 2.0, 3.0], 'beta': [4.0, 5.0, 6.0]}),
    })
    panel.set_active_dataset(dataset_id)
    panel.list_columns.clearSelection()
    panel.list_columns.item(0).setCheckState(Qt.Checked)
    panel.list_columns.item(1).setCheckState(Qt.Checked)
    panel.add_selected_to_plot()

    # 图例标签为 文件名|字段 的紧凑形式，不含采样区间
    assert panel.plot_items[0].label == compact_series_label('飞测数据.txt', 'alpha')
    assert '[' not in panel.plot_items[0].label

    panel.plot_data()
    view = panel._get_current_plot_view()

    # 切换到表格模式后模型须填充数据
    panel.combo_display_mode.setCurrentIndex(1)
    assert view.display_stack.currentIndex() == 1
    model = view.table_model
    assert model.rowCount() == 3
    assert model.columnCount() == 3  # 序号 + 两条曲线

    # 图片尺寸预设生效
    panel.combo_fig_size.setCurrentIndex(2)  # 宽幅
    w, h = view.canvas.figure.get_size_inches()
    assert (round(w, 1), round(h, 1)) == (14.0, 8.5)

    # 导出默认命名 = 数据文件名 + 字段名
    assert default_export_basename('飞测数据.txt', ['alpha', 'beta']) == '飞测数据_alpha_beta'
    window.close()


def test_interferometer_clear_control_resets_result_panels():
    _app()
    panel = InterferometerSimPanel()
    panel.sim_result = {'sentinel': True}

    panel.btn_clear.click()

    assert panel.sim_result is None
    assert panel.txt_stats.toPlainText() == '结果已清除。'
    panel.close()


def test_interferometer_custom_coords_and_default_snr_take_effect():
    import numpy as np

    _app()
    panel = InterferometerSimPanel()
    custom = np.array([[0.0, 0.0], [0.1, 0.0], [0.0, 0.1], [0.1, 0.1]])
    panel._custom_coords = custom
    panel.combo_array_type.setCurrentIndex(4)
    pos = panel.get_array_positions()
    assert pos.shape == custom.shape
    assert np.allclose(pos, custom)

    panel.spin_snr.setValue(5.0)
    assert panel.get_targets()[0]['snr'] == 5.0
    panel.close()


def test_interferometer_custom_frequency_rejects_invalid_text():
    _app()
    panel = InterferometerSimPanel()
    panel.combo_fc.setCurrentIndex(panel.combo_fc.count() - 1)
    panel.edit_fc_custom.setText('abc')
    with pytest.raises(ValueError):
        panel.get_fc()
    panel.edit_fc_custom.setText('3500000000')
    assert panel.get_fc() == pytest.approx(3.5e9)
    panel.close()


def test_experiment_tree_selection_survives_refresh():
    _app()
    panel = ExpRecorderPanel()
    with tempfile.TemporaryDirectory() as directory:
        data_dir = os.path.join(directory, 'data')
        images_dir = os.path.join(data_dir, 'images')
        os.makedirs(images_dir, exist_ok=True)
        panel.projects = {
            'p1': {
                'name': '项目A',
                'description': '',
                'tasks': {
                    't1': {
                        'name': '任务A',
                        'records': {
                            'r1': {
                                'title': '记录A',
                                'date': '2025-01-01',
                                'personnel': '',
                                'location': '',
                                'template': '通用试验记录',
                                'conditions': '',
                                'content': '',
                                'steps': [],
                                'conclusion': '',
                            }
                        },
                    }
                },
            }
        }
        with patch('radar_tool.exp_recorder.DATA_DIR', data_dir), patch(
            'radar_tool.exp_recorder.IMAGES_DIR', images_dir
        ):
            panel._refresh_tree()
            panel._load_record('p1', 't1', 'r1')

            panel.tree_projects.setCurrentRow(0)  # 点击项目节点

            current = panel.tree_projects.currentItem()
            assert current is not None
            assert current.data(Qt.UserRole)[0] == 'project'
    panel.close()


def test_experiment_save_control_handles_missing_selection_safely():
    _app()
    panel = ExpRecorderPanel()

    with patch(
        'radar_tool.exp_recorder.QMessageBox.information'
    ) as information:
        result = panel._save_current_record()

    assert result is False
    information.assert_called_once()
    panel.close()
