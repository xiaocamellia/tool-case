#!/usr/bin/env python3
"""便携化工具箱主窗口 - Portable Radar Toolbox Main Window
基于 PyQt5 + matplotlib，主窗口负责页签管理和全局状态
所有面板采用延迟加载，仅首次点击时才创建。
"""

import os

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout,
    QLabel, QTabWidget, QMessageBox,
)
from PyQt5.QtCore import Qt

from .compare_analysis import CompareAnalysisMixin
from .ui_theme import MAIN_STYLESHEET, STATUSBAR_STYLE
from .logger import get_logger

logger = get_logger('main_window')


class MainWindow(QMainWindow, CompareAnalysisMixin):
    """便携化工具箱主窗口"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle('便携化工具箱V1.0.0')
        self.setGeometry(100, 100, 1400, 900)

        self.compare_test_df = None
        self.compare_truth_df = None
        self.compare_test_filepath = ''
        self.compare_truth_filepath = ''
        self.compare_meta_cols = None
        self.compare_last_result = None
        self.compare_last_metrics = None

        self._init_ui()
        self._apply_theme()
        logger.info('程序启动 — 主窗口已创建 (仅初始化可视化面板)')

    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)

        self.feature_tabs = QTabWidget()
        self._tab_panels = [None] * 7
        self._tab_loaded = [False] * 7
        self._tab_factories = [
            self._create_viz_tab,
            self._create_compare_tab,
            self._create_interferometer_tab,
            self._create_array_designer_tab,
            self._create_calc_tab,
            self._create_recorder_tab,
            self._create_game_tab,
        ]
        self._tab_names = [
            '数据可视化处理',
            '挂飞对比分析',
            '干涉仪测向仿真',
            '📡 阵列设计助手',
            '🧮 指标计算器',
            '📋 试验记录助手',
            '🎮 摸鱼游戏',
        ]

        # 第 0 页（可视化）立即创建并添加到 tabs
        panel0 = self._lazy_create_or_get_panel(0)
        self.feature_tabs.addTab(panel0, self._tab_names[0])
        for i in range(1, 7):
            self.feature_tabs.addTab(QWidget(), self._tab_names[i])

        self.feature_tabs.currentChanged.connect(self._on_tab_changed)
        main_layout.addWidget(self.feature_tabs, 1)
        logger.info('UI 初始化完成: 可视化(已加载) + 6个面板(延迟加载)')

        self.status_label = QLabel('就绪')
        self.statusBar().addWidget(self.status_label)

    def _lazy_create_or_get_panel(self, index):
        if self._tab_loaded[index]:
            return self._tab_panels[index]
        try:
            panel = self._tab_factories[index]()
        except Exception as exc:
            logger.exception(f'延迟加载失败: {self._tab_names[index]}')
            QMessageBox.critical(
                self,
                '页面加载失败',
                f'{self._tab_names[index]} 加载失败：\n{exc}\n\n详细错误已写入日志。'
            )
            return None
        self._tab_loaded[index] = True
        self._tab_panels[index] = panel
        logger.info(f'延迟加载: {self._tab_names[index]}')
        return panel

    def _on_tab_changed(self, index):
        if index < 0 or index >= 7:
            return
        if self._tab_loaded[index]:
            return
        panel = self._lazy_create_or_get_panel(index)
        if panel is None:
            self.feature_tabs.blockSignals(True)
            self.feature_tabs.setCurrentIndex(0)
            self.feature_tabs.blockSignals(False)
            return
        self.feature_tabs.blockSignals(True)
        self.feature_tabs.removeTab(index)
        self.feature_tabs.insertTab(index, panel, self._tab_names[index])
        self.feature_tabs.setCurrentIndex(index)
        self.feature_tabs.blockSignals(False)

    def _create_viz_tab(self):
        from .visualization_panel import VisualizationPanel
        return VisualizationPanel(self)

    def _create_compare_tab(self):
        return self._create_compare_analysis_page()

    def _create_interferometer_tab(self):
        from .interferometer_sim import InterferometerSimPanel
        return InterferometerSimPanel(self)

    def _create_array_designer_tab(self):
        from .array_designer import ArrayDesignerPanel
        return ArrayDesignerPanel(self)

    def _create_calc_tab(self):
        from .calc_panel import CalcPanel
        return CalcPanel(self)

    def _create_recorder_tab(self):
        from .exp_recorder import ExpRecorderPanel
        return ExpRecorderPanel(self)

    def _create_game_tab(self):
        from .game_panel import GamePanel
        return GamePanel(self)

    def _apply_theme(self):
        self.setStyleSheet(MAIN_STYLESHEET)
        self.statusBar().setStyleSheet(STATUSBAR_STYLE)
        logger.debug('主题样式已应用')
