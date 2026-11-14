"""任务中心非模态对话框（G-05）。

提供统一的任务列表、进度显示与取消入口。
用法::

    from .task_center import TaskCenterDialog
    dialog = TaskCenterDialog(registry, parent)
    dialog.show()  # 非模态
"""

from __future__ import annotations

import time

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QPushButton, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QHeaderView, QAbstractItemView,
)

from .background_tasks import TaskPhase, TaskRegistry


class TaskCenterDialog(QDialog):
    """任务中心：显示当前窗口的全部后台任务，支持取消与清空已完成。"""

    _instance = None

    def __init__(self, registry: TaskRegistry, parent=None):
        super().__init__(parent)
        self._registry = registry
        self.setWindowTitle('任务中心')
        self.setMinimumSize(640, 360)
        self.setModal(False)
        self._init_ui()
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(200)
        self._refresh_timer.timeout.connect(self._refresh_table)
        self._refresh_timer.start()
        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(1000)
        self._elapsed_timer.timeout.connect(self._refresh_elapsed)
        self._elapsed_timer.start()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        self._table = QTableWidget(0, 6)
        self._table.setHorizontalHeaderLabels(
            ['任务名', '所属页签', '阶段', '进度', '耗时', '操作']
        )
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        layout.addWidget(self._table)

        btn_row = QHBoxLayout()
        self._btn_cancel_all = QPushButton('全部取消')
        self._btn_cancel_all.clicked.connect(self._cancel_all)
        btn_row.addWidget(self._btn_cancel_all)
        self._btn_clear = QPushButton('清空已完成')
        self._btn_clear.clicked.connect(self._clear_completed)
        btn_row.addWidget(self._btn_clear)
        btn_row.addStretch()
        self._btn_close = QPushButton('后台运行')
        self._btn_close.clicked.connect(self.hide)
        btn_row.addWidget(self._btn_close)
        layout.addLayout(btn_row)

    def _refresh_table(self):
        snapshots = self._registry.snapshots()
        self._table.setRowCount(len(snapshots))
        for row, snap in enumerate(snapshots):
            self._table.setItem(row, 0, QTableWidgetItem(snap.name))
            self._table.setItem(row, 1, QTableWidgetItem(snap.tab_name or '—'))
            self._table.setItem(row, 2, QTableWidgetItem(self._phase_text(snap)))
            progress_item = QTableWidgetItem(f'{snap.progress}%')
            self._table.setItem(row, 3, progress_item)
            self._table.setItem(row, 4, QTableWidgetItem(self._elapsed_text(snap)))
            # 操作列：取消按钮
            if snap.completed:
                btn_text = '已结束'
                btn = QPushButton(btn_text)
                btn.setEnabled(False)
            elif snap.cancel_requested:
                btn = QPushButton('已取消')
                btn.setEnabled(False)
            else:
                btn = QPushButton('取消')
                btn.clicked.connect(
                    lambda checked=False, tid=snap.task_id: self._cancel_task(tid)
                )
            self._table.setCellWidget(row, 5, btn)

    def _refresh_elapsed(self):
        """每秒刷新耗时列。"""
        snapshots = self._registry.snapshots()
        for row, snap in enumerate(snapshots):
            if row < self._table.rowCount():
                item = self._table.item(row, 4)
                if item is not None:
                    item.setText(self._elapsed_text(snap))

    @staticmethod
    def _phase_text(snap) -> str:
        labels = {
            TaskPhase.QUEUED: '等待中',
            TaskPhase.RUNNING: '运行中',
            TaskPhase.PROGRESS: f'运行中 {snap.progress}%',
            TaskPhase.CANCEL_REQUESTED: '已请求取消',
            TaskPhase.SUCCEEDED: '成功完成',
            TaskPhase.FAILED: '失败',
            TaskPhase.CANCELLED: '已取消',
        }
        return labels.get(snap.phase, str(snap.phase))

    @staticmethod
    def _elapsed_text(snap) -> str:
        if snap.started_at <= 0:
            return '—'
        if snap.finished_at > 0:
            elapsed = snap.finished_at - snap.started_at
        else:
            elapsed = time.monotonic() - snap.started_at
        if elapsed < 60:
            return f'{elapsed:.1f}s'
        minutes = int(elapsed // 60)
        seconds = int(elapsed % 60)
        return f'{minutes}m{seconds}s'

    def _cancel_task(self, task_id):
        for record in list(self._registry._records.values()):
            if record['id'] == task_id:
                self._registry.cancel_active(record['owner'])
                break

    def _cancel_all(self):
        self._registry.cancel_active()

    def _clear_completed(self):
        self._registry.clear_completed()
        self._refresh_table()

    def closeEvent(self, event):
        self._refresh_timer.stop()
        self._elapsed_timer.stop()
        super().closeEvent(event)

    def showEvent(self, event):
        self._refresh_timer.start()
        self._elapsed_timer.start()
        self._refresh_table()
        super().showEvent(event)

    @classmethod
    def get_instance(cls, registry, parent=None):
        if cls._instance is None or not cls._instance.isVisible():
            cls._instance = cls(registry, parent)
        return cls._instance
