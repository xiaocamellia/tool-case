#!/usr/bin/env python3
"""便携化工具箱主窗口 - Portable Radar Toolbox Main Window
基于 PyQt5 + matplotlib，主窗口负责页签管理和全局状态
所有面板采用延迟加载，仅首次点击时才创建。
"""

import os

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QTabWidget, QMessageBox, QApplication, QProgressBar,
)
from PyQt5.QtCore import Qt

from . import __version__
from .background_tasks import TaskRegistry
from .compare_analysis import CompareAnalysisMixin
from .ui_theme import MAIN_STYLESHEET, STATUSBAR_STYLE
from .logger import get_logger

logger = get_logger('main_window')


class MainWindow(QMainWindow, CompareAnalysisMixin):
    """便携化工具箱主窗口"""

    def __init__(self):
        super().__init__()
        self.task_registry = TaskRegistry(self)
        for signal in (
            self.task_registry.task_started,
            self.task_registry.task_progress,
            self.task_registry.task_succeeded,
            self.task_registry.task_failed,
            self.task_registry.task_cancel_requested,
            self.task_registry.task_cancelled,
            self.task_registry.task_completed,
        ):
            signal.connect(self._on_background_task_event)
        self.setWindowTitle(f'便携化工具箱 V{__version__}')
        # 显式最小尺寸防止子控件把窗口强制撑大；启动默认最大化以贴合屏幕，
        # 还原尺寸按屏幕比例预设，保证窗口模式下也足够宽敞
        screen = QApplication.primaryScreen().availableGeometry()
        self.setMinimumSize(1024, 640)
        self.resize(
            max(1152, int(screen.width() * 0.88)),
            max(720, int(screen.height() * 0.86)),
        )
        self.setWindowState(Qt.WindowMaximized)

        self.compare_test_df = None
        self.compare_test_original_df = None
        self.compare_test_source_indices = None
        self.compare_preprocess_revision = 0
        self.compare_truth_df = None
        self.compare_test_filepath = ''
        self.compare_truth_filepath = ''
        self.compare_meta_cols = None
        self.compare_meta_filepath = ''
        self.compare_last_result = None
        self.compare_last_output = None
        self.compare_last_metrics = None
        self.compare_last_interpolated_count = None
        self.compare_last_interpolated_valid_count = None
        self.compare_last_aligned_valid_count = None
        self.compare_last_paired_count = None
        self.compare_coarse_output = None
        self.compare_coarse_mapping = None

        self._init_ui()
        self._apply_theme()
        logger.info('程序启动 — 主窗口已创建 (仅初始化可视化面板)')

    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)

        self.feature_tabs = QTabWidget()
        # GM-01: 摸鱼栏按设置项决定是否注册（A-2，默认隐藏）
        from .settings_store import settings
        show_game = settings.get_bool('ui/show_game_tab', False)
        self._tab_factories = [
            self._create_viz_tab,
            self._create_compare_tab,
            self._create_interferometer_tab,
            self._create_calibration_tab,
            self._create_array_designer_tab,
            self._create_calc_tab,
            self._create_format_conversion_tab,
            self._create_recorder_tab,
            self._create_coord_ledger_tab,
        ]
        self._tab_names = [
            '数据可视化处理',
            '数据真值复核',
            '干涉仪测向仿真',
            '测向校正自动化',
            '📡 阵列设计助手',
            '🧮 指标计算器',
            '格式转换',
            '📋 试验记录助手',
            '📐 坐标系账本',
        ]
        if show_game:
            self._tab_factories.append(self._create_game_tab)
            self._tab_names.append('🎮 摸鱼游戏')
        self._tab_panels = [None] * len(self._tab_names)
        self._tab_loaded = [False] * len(self._tab_names)
        self._tab_failed = [False] * len(self._tab_names)  # G-02 第三态

        # 第 0 页（可视化）立即创建并添加到 tabs
        panel0 = self._lazy_create_or_get_panel(0)
        self.feature_tabs.addTab(panel0, self._tab_names[0])
        for i in range(1, len(self._tab_names)):
            self.feature_tabs.addTab(QWidget(), self._tab_names[i])

        self.feature_tabs.currentChanged.connect(self._on_tab_changed)
        main_layout.addWidget(self.feature_tabs, 1)
        logger.info('UI 初始化完成: 可视化(已加载) + %d个面板(延迟加载)',
                    max(len(self._tab_names) - 1, 0))

        self.status_label = QLabel('就绪')
        self.statusBar().addWidget(self.status_label)

        # G-06: 状态栏右侧常驻进度条 + 任务入口
        self._task_count_label = QLabel('')
        self._task_count_label.setStyleSheet(
            'color: #2563eb; font-size: 9pt; padding: 0 6px; cursor: pointer;'
        )
        self._task_count_label.mousePressEvent = self._open_task_center
        self._task_count_label.setVisible(False)
        self.statusBar().addPermanentWidget(self._task_count_label)

        self._progress_bar = QProgressBar()
        self._progress_bar.setFixedWidth(140)
        self._progress_bar.setFormat('%p%')
        self._progress_bar.setVisible(False)
        self.statusBar().addPermanentWidget(self._progress_bar)

        self.version_label = QLabel(f'v{__version__}')
        self.version_label.setObjectName('version_label')
        self.version_label.setStyleSheet(
            'color: #64748b; font-size: 9pt; padding-right: 12px;'
        )
        self.statusBar().addPermanentWidget(self.version_label)

    def _lazy_create_or_get_panel(self, index):
        if self._tab_loaded[index]:
            return self._tab_panels[index]
        if self._tab_failed[index]:
            # G-02: 已失败的页签，切回时直接显示缓存的错误页，不再重跑工厂
            return self._tab_panels[index]
        try:
            panel = self._tab_factories[index]()
        except Exception as exc:
            self._tab_failed[index] = True
            logger.error(f'页签加载失败: {self._tab_names[index]}: {exc}')
            error_page = self._build_error_page(index, exc)
            self._tab_panels[index] = error_page
            return error_page
        self._tab_loaded[index] = True
        self._tab_failed[index] = False
        self._tab_panels[index] = panel
        logger.info(f'延迟加载: {self._tab_names[index]}')
        return panel

    def _build_error_page(self, index, exc):
        """G-02: 内联错误页 — 摘要 + 重试 + 查看日志，不弹模态。"""
        from PyQt5.QtWidgets import QPushButton, QTextEdit
        from PyQt5.QtCore import QUrl
        from PyQt5.QtGui import QDesktopServices
        from .logger import LOG_DIR

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setAlignment(Qt.AlignCenter)

        title = QLabel(f'⚠ 「{self._tab_names[index]}」页面加载失败')
        title.setStyleSheet('color: #dc2626; font-size: 14pt; font-weight: bold;')
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        detail = QTextEdit()
        detail.setReadOnly(True)
        detail.setPlainText(str(exc))
        detail.setMaximumHeight(100)
        detail.setStyleSheet('color: #64748b; font-size: 10pt; border: 1px solid #e2e8f0;')
        layout.addWidget(detail)

        btn_row = QHBoxLayout()
        btn_retry = QPushButton('重试')
        btn_retry.setStyleSheet(
            'QPushButton { background: #2563eb; color: white; padding: 8px 24px; '
            'border-radius: 6px; font-size: 11pt; }'
            'QPushButton:hover { background: #1d4ed8; }'
        )
        btn_retry.clicked.connect(lambda: self._retry_tab(index))
        btn_row.addWidget(btn_retry)

        btn_log = QPushButton('查看日志')
        btn_log.setStyleSheet(
            'QPushButton { background: #f5f7fb; color: #334155; padding: 8px 24px; '
            'border: 1px solid #d7dee9; border-radius: 6px; font-size: 11pt; }'
        )
        btn_log.clicked.connect(lambda: QDesktopServices.openUrl(
            QUrl.fromLocalFile(LOG_DIR)
        ))
        btn_row.addWidget(btn_log)
        layout.addLayout(btn_row)
        return page

    def _retry_tab(self, index):
        """G-02: 重试 — 清除失败标志，重新构建面板。"""
        self._tab_failed[index] = False
        self._tab_loaded[index] = False
        self._tab_panels[index] = None
        self._on_tab_changed(index)

    def _on_tab_changed(self, index):
        if index < 0 or index >= len(self._tab_names):
            return
        if self._tab_loaded[index]:
            return
        if self._tab_failed[index]:
            # G-02: 已失败页签切回时不重跑工厂，错误页已在 _tab_panels 中
            return
        # G-07: 首次懒加载 — 等待光标 + 遮罩提示
        QApplication.setOverrideCursor(Qt.WaitCursor)
        # 在页签内容区临时显示遮罩（需先 repaint 才能绘制）
        placeholder = self.feature_tabs.widget(index)
        mask = QLabel(f'正在初始化「{self._tab_names[index]}」…')
        mask.setAlignment(Qt.AlignCenter)
        mask.setStyleSheet(
            'color: #64748b; font-size: 12pt; background: #f5f7fb;'
        )
        if placeholder is not None:
            placeholder_layout = placeholder.layout()
            if placeholder_layout is None:
                placeholder_layout = QVBoxLayout(placeholder)
            placeholder_layout.addWidget(mask)
        self.feature_tabs.repaint()
        QApplication.processEvents()
        try:
            panel = self._lazy_create_or_get_panel(index)
        finally:
            QApplication.restoreOverrideCursor()
            if placeholder is not None:
                placeholder_layout.removeWidget(mask)
                mask.deleteLater()
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

    def _create_calibration_tab(self):
        from .calibration_panel import CalibrationPanel
        return CalibrationPanel(self)

    def _create_array_designer_tab(self):
        from .array_designer import ArrayDesignerPanel
        return ArrayDesignerPanel(self)

    def _create_calc_tab(self):
        from .calc_panel import CalcPanel
        return CalcPanel(self)

    def _create_format_conversion_tab(self):
        from .format_conversion_panel import FormatConversionPanel
        return FormatConversionPanel(self)

    def _create_recorder_tab(self):
        from .exp_recorder import ExpRecorderPanel
        return ExpRecorderPanel(self)

    def _create_coord_ledger_tab(self):
        from .coord_ledger_panel import CoordinateLedgerPanel
        return CoordinateLedgerPanel(self)

    def _create_game_tab(self):
        from .game_panel import GamePanel
        return GamePanel(self)

    def _apply_theme(self):
        self.setStyleSheet(MAIN_STYLESHEET)
        self.statusBar().setStyleSheet(STATUSBAR_STYLE)
        logger.debug('主题样式已应用')

    def _on_background_task_event(self, snapshot):
        if hasattr(self, 'status_label'):
            self.status_label.setText(
                f'后台任务：{TaskRegistry.describe(snapshot)}'
            )
        self._update_progress_bar()

    def _update_progress_bar(self):
        """根据活动任务更新状态栏进度条与任务计数（G-06）。"""
        if not hasattr(self, '_progress_bar'):
            return
        active = self.task_registry.active_snapshots(self)
        if not active:
            self._progress_bar.setVisible(False)
            self._task_count_label.setVisible(False)
            return
        # 显示第一个活动任务的进度
        first = active[0]
        self._progress_bar.setVisible(True)
        self._progress_bar.setValue(first.progress)
        count = len(active)
        self._task_count_label.setVisible(True)
        self._task_count_label.setText(f'任务 ({count})' if count <= 1 else f'任务 (+{count - 1})')

    def _open_task_center(self, event=None):
        from .task_center import TaskCenterDialog
        dialog = TaskCenterDialog.get_instance(self.task_registry, self)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _running_background_threads(self):
        return [
            snapshot.name
            for snapshot in self.task_registry.active_snapshots(self)
        ]

    def closeEvent(self, event):
        """[G-01+ER-06] 关闭事务：① 脏数据检查 → ② 等后台任务 → ③ 退出。"""
        # ── 第 1 段：脏数据检查（必须在 wait_for_tasks 之前） ──
        dirty_panels = self._collect_dirty_panels()
        if dirty_panels:
            names = '、'.join(dirty_panels)
            reply = QMessageBox.question(
                self,
                '未保存的修改',
                f'以下页面有未保存的修改：\n{names}\n\n是否保存后退出？',
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                QMessageBox.Save,
            )
            if reply == QMessageBox.Cancel:
                event.ignore()
                return
            if reply == QMessageBox.Save:
                if not self._save_all_dirty_panels():
                    event.ignore()
                    return

        # ── 第 2 段：等后台任务 ──
        active = self.task_registry.active_snapshots(self)
        if not active:
            self._flush_loggers()
            super().closeEvent(event)
            return

        event.ignore()
        requested = self.task_registry.cancel_active(self)
        requested_ids = {snapshot.task_id for snapshot in requested}
        finished = self.task_registry.wait_for_tasks(self, timeout_ms=3000)
        snapshots = self.task_registry.active_snapshots(self)
        snapshots.extend(
            snapshot for snapshot in self.task_registry.snapshots(self)
            if snapshot.task_id in requested_ids and snapshot.completed
        )
        details = '\n'.join(TaskRegistry.describe(s) for s in snapshots)

        if finished:
            self._flush_loggers()
            super().closeEvent(event)
            return

        # ── 超时：三选一 ──
        msg = QMessageBox()
        msg.setWindowTitle('后台任务取消超时')
        msg.setText(
            '以下任务在 3 秒内仍未结束：\n' + details +
            '\n\n强制退出后，已产出的中间结果将丢失。'
        )
        btn_wait = msg.addButton('继续等待', QMessageBox.AcceptRole)
        btn_cancel_exit = msg.addButton('取消任务并退出', QMessageBox.DestructiveRole)
        btn_force = msg.addButton('强制退出', QMessageBox.RejectRole)
        msg.exec_()
        clicked = msg.clickedButton()

        if clicked == btn_wait:
            self.close()
            return
        if clicked == btn_cancel_exit:
            self.task_registry.cancel_active(self)
            self.task_registry.wait_for_tasks(self, timeout_ms=3000)
            self._flush_loggers()
            super().closeEvent(event)
            return
        # 强制退出
        self._flush_loggers()
        super().closeEvent(event)

    def _collect_dirty_panels(self):
        """遍历页签收集有未保存修改的页面名（ER-06）。"""
        dirty = []
        for i, panel in enumerate(self._tab_panels):
            if panel is None:
                continue
            check = getattr(panel, 'has_unsaved_changes', None)
            if callable(check):
                try:
                    if check():
                        dirty.append(self._tab_names[i])
                except Exception:
                    pass
        return dirty

    def _save_all_dirty_panels(self):
        """尝试保存所有有脏数据的面板，返回是否全部成功（ER-06）。"""
        for i, panel in enumerate(self._tab_panels):
            if panel is None:
                continue
            check = getattr(panel, 'has_unsaved_changes', None)
            save = getattr(panel, 'confirm_close', None)
            if callable(check) and callable(save):
                try:
                    if check():
                        if not save():
                            return False
                except Exception:
                    return False
        return True

    @staticmethod
    def _flush_loggers():
        """退出前强制刷新日志 handler，确保日志落盘。"""
        import logging
        for handler in logging.getLogger('radar_tool').handlers:
            try:
                handler.flush()
            except Exception:
                pass
