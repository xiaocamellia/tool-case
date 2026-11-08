"""Lifecycle tests for the unified Qt background-task registry."""

from __future__ import annotations

import os
import threading
import time
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PyQt5.QtCore import QObject, QThread, pyqtSignal
from PyQt5.QtGui import QCloseEvent
from PyQt5.QtWidgets import QApplication

from radar_tool.background_tasks import TaskPhase, TaskRegistry
from radar_tool.main_window import MainWindow


class _SuccessWorker(QObject):
    progress = pyqtSignal(int, str)
    succeeded = pyqtSignal()

    def run(self):
        self.progress.emit(45, '计算中')
        self.succeeded.emit()


class _CancelWorker(QObject):
    progress = pyqtSignal(int, str)
    cancelled = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.cancel_event = threading.Event()

    def cancel(self):
        self.cancel_event.set()

    def run(self):
        self.progress.emit(20, '等待取消')
        while not self.cancel_event.wait(0.005):
            pass
        self.cancelled.emit('测试任务已取消')


class BackgroundTaskRegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def _wait(self, predicate, timeout=3.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.app.processEvents()
            if predicate():
                return True
            time.sleep(0.01)
        self.app.processEvents()
        return predicate()

    def test_success_lifecycle_reports_all_public_states(self):
        owner = QObject()
        registry = TaskRegistry(owner)
        thread = QThread(owner)
        worker = _SuccessWorker()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.succeeded.connect(thread.quit)
        events = []
        registry.task_started.connect(lambda item: events.append(('started', item)))
        registry.task_progress.connect(lambda item: events.append(('progress', item)))
        registry.task_succeeded.connect(lambda item: events.append(('succeeded', item)))
        registry.task_completed.connect(lambda item: events.append(('completed', item)))
        registry.register('公式计算', owner, thread, worker)
        thread.start()

        self.assertTrue(registry.wait_for_tasks(owner, 2000))
        snapshot = registry.snapshots(owner)[0]
        self.assertEqual(snapshot.phase, TaskPhase.SUCCEEDED)
        self.assertEqual(snapshot.progress, 100)
        self.assertTrue(snapshot.completed)
        self.assertEqual(
            [name for name, _item in events],
            ['started', 'progress', 'succeeded', 'completed'],
        )
        worker.deleteLater()
        thread.deleteLater()

    def test_cancel_lifecycle_has_request_and_cancelled_states(self):
        owner = QObject()
        registry = TaskRegistry(owner)
        thread = QThread(owner)
        worker = _CancelWorker()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.cancelled.connect(thread.quit)
        events = []
        registry.task_cancel_requested.connect(
            lambda item: events.append(('cancel_requested', item))
        )
        registry.task_cancelled.connect(
            lambda item: events.append(('cancelled', item))
        )
        registry.task_completed.connect(
            lambda item: events.append(('completed', item))
        )
        registry.register(
            '可取消任务', owner, thread, worker, worker.cancel
        )
        thread.start()
        self.assertTrue(self._wait(
            lambda: registry.active_snapshots(owner)
            and registry.active_snapshots(owner)[0].progress == 20
        ))

        registry.cancel_active(owner)
        self.assertTrue(registry.wait_for_tasks(owner, 2000))
        snapshot = registry.snapshots(owner)[0]
        self.assertEqual(snapshot.phase, TaskPhase.CANCELLED)
        self.assertTrue(snapshot.cancel_requested)
        self.assertTrue(snapshot.completed)
        self.assertEqual(
            [name for name, _item in events],
            ['cancel_requested', 'cancelled', 'completed'],
        )
        self.assertIn('已取消', TaskRegistry.describe(snapshot))
        worker.deleteLater()
        thread.deleteLater()

    def test_duplicate_is_rejected_and_expired_result_is_discarded(self):
        owner = QObject()
        registry = TaskRegistry(owner)
        first_thread = QThread(owner)
        first_worker = _SuccessWorker()
        first_worker.moveToThread(first_thread)
        first_thread.started.connect(first_worker.run)
        first_worker.succeeded.connect(first_thread.quit)
        first_id = registry.register('版本任务', owner, first_thread, first_worker)

        duplicate_thread = QThread(owner)
        duplicate_worker = _SuccessWorker()
        duplicate_worker.moveToThread(duplicate_thread)
        with self.assertRaisesRegex(ValueError, '任务已在运行'):
            registry.register(
                '版本任务', owner, duplicate_thread, duplicate_worker
            )
        duplicate_thread.deleteLater()
        duplicate_worker.deleteLater()

        first_thread.start()
        self.assertTrue(registry.wait_for_tasks(owner, 2000))
        first_version = next(
            item.version for item in registry.snapshots(owner)
            if item.task_id == first_id
        )
        self.assertEqual(first_version, 1)

        second_thread = QThread(owner)
        second_worker = _SuccessWorker()
        second_worker.moveToThread(second_thread)
        second_thread.started.connect(second_worker.run)
        second_worker.succeeded.connect(second_thread.quit)
        second_id = registry.register(
            '版本任务', owner, second_thread, second_worker
        )
        self.assertFalse(registry.result_is_current(
            owner, '版本任务', first_version
        ))
        self.assertTrue(registry.result_is_current(owner, '版本任务', 2))
        first_snapshot = next(
            item for item in registry.snapshots(owner)
            if item.task_id == first_id
        )
        second_snapshot = next(
            item for item in registry.snapshots(owner)
            if item.task_id == second_id
        )
        self.assertTrue(first_snapshot.stale)
        self.assertFalse(second_snapshot.stale)
        self.assertEqual(second_snapshot.version, 2)

        second_thread.start()
        self.assertTrue(registry.wait_for_tasks(owner, 2000))
        first_worker.deleteLater()
        first_thread.deleteLater()
        second_worker.deleteLater()
        second_thread.deleteLater()

    def test_main_window_close_waits_and_names_cancelled_task(self):
        window = MainWindow()
        thread = QThread(window)
        worker = _CancelWorker()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.cancelled.connect(thread.quit)
        window.task_registry.register(
            '关闭测试任务', window, thread, worker, worker.cancel
        )
        thread.start()
        self.assertTrue(self._wait(
            lambda: window.task_registry.active_snapshots(window)
            and window.task_registry.active_snapshots(window)[0].progress == 20
        ))

        event = QCloseEvent()
        with patch('radar_tool.main_window.QMessageBox.information') as info:
            window.closeEvent(event)
        self.assertTrue(event.isAccepted())
        message = info.call_args.args[2]
        self.assertIn('关闭测试任务', message)
        self.assertIn('已取消', message)
        self.assertTrue(thread.wait(1000))
        worker.deleteLater()
        thread.deleteLater()
        window.deleteLater()


if __name__ == '__main__':
    unittest.main()
