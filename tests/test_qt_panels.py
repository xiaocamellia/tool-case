"""Offscreen initialization and key interaction tests for all Qt panels."""

from __future__ import annotations

import os
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pandas as pd
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


def test_interferometer_clear_control_resets_result_panels():
    _app()
    panel = InterferometerSimPanel()
    panel.sim_result = {'sentinel': True}

    panel.btn_clear.click()

    assert panel.sim_result is None
    assert panel.txt_stats.toPlainText() == '结果已清除。'
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
