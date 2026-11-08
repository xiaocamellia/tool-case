"""统一注册、观察、取消和等待 Qt 后台任务。"""

from __future__ import annotations

import os
import time
import uuid
from enum import Enum
from typing import Callable, Dict, List, Optional

from PyQt5.QtCore import (
    QCoreApplication, QEventLoop, QObject, Qt, QThread, QTimer, pyqtSignal,
)


_NATIVE_THREADPOOL_LIMITER = None


def configure_native_threadpool_limits():
    global _NATIVE_THREADPOOL_LIMITER
    if _NATIVE_THREADPOOL_LIMITER is not None:
        return
    try:
        max_threads = max(1, int(os.environ.get('RADAR_TOOL_MAX_THREADS', '2')))
    except (TypeError, ValueError):
        max_threads = 2
    thread_count = str(max_threads)
    for variable in (
        'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS',
        'NUMEXPR_NUM_THREADS', 'KMP_NUM_THREADS',
    ):
        os.environ.setdefault(variable, thread_count)
    os.environ.setdefault('KMP_BLOCKTIME', '0')
    try:
        from threadpoolctl import threadpool_limits
    except ImportError:
        return
    limiter = threadpool_limits(limits=max_threads)
    limiter.__enter__()
    _NATIVE_THREADPOOL_LIMITER = limiter


class TaskPhase(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    PROGRESS = "progress"
    CANCEL_REQUESTED = "cancel_requested"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskSnapshot:
    """任务状态的不可变快照。"""

    __slots__ = (
        "task_id", "name", "phase", "progress", "message",
        "cancel_requested", "completed", "outcome", "error", "version", "stale",
    )

    def __init__(self, task_id, name, phase, progress, message,
                 cancel_requested, completed, outcome, error, version, stale):
        self.task_id = task_id
        self.name = name
        self.phase = phase
        self.progress = progress
        self.message = message
        self.cancel_requested = cancel_requested
        self.completed = completed
        self.outcome = outcome
        self.error = error
        self.version = version
        self.stale = stale


class TaskRegistry(QObject):
    """全局任务注册表，但按所属顶层窗口过滤活动任务。"""

    task_started = pyqtSignal(object)
    task_progress = pyqtSignal(object)
    task_succeeded = pyqtSignal(object)
    task_failed = pyqtSignal(object)
    task_cancel_requested = pyqtSignal(object)
    task_cancelled = pyqtSignal(object)
    task_completed = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        configure_native_threadpool_limits()
        self._records: Dict[str, dict] = {}

    def register(self, name, owner, thread, worker,
                 cancel_callback: Optional[Callable[[], object]] = None) -> str:
        """登记已经组装完成但尚未启动的 Worker/QThread。"""
        normalized_name = str(name).strip() or "后台任务"
        self.ensure_can_start(owner, normalized_name)
        task_id = uuid.uuid4().hex
        prior_versions = [
            record["version"] for record in self._records.values()
            if record["owner"] is owner and record["name"] == normalized_name
        ]
        version = max(prior_versions, default=0) + 1
        for record in self._records.values():
            if (
                record["owner"] is owner
                and record["name"] == normalized_name
                and record["version"] < version
            ):
                record["stale"] = True
        record = {
            "id": task_id, "name": normalized_name, "version": version,
            "stale": False,
            "owner": owner, "thread": thread, "worker": worker,
            "cancel_callback": cancel_callback, "phase": TaskPhase.QUEUED,
            "progress": 0, "message": "", "cancel_requested": False,
            "completed": False, "outcome": "", "error": "",
            "started_at": 0.0, "finished_at": 0.0,
        }
        self._records[task_id] = record
        thread.finished.connect(
            lambda task_id=task_id: self._on_thread_finished(task_id),
            Qt.QueuedConnection,
        )
        progress = getattr(worker, "progress", None)
        if progress is not None:
            progress.connect(
                lambda value, message="", task_id=task_id:
                self._on_progress(task_id, value, message),
                Qt.QueuedConnection,
            )
        succeeded = getattr(worker, "succeeded", None)
        if succeeded is None:
            succeeded = getattr(worker, "finished", None)
        if succeeded is not None:
            succeeded.connect(
                lambda *_args, task_id=task_id: self._on_succeeded(task_id),
                Qt.QueuedConnection,
            )
        failed = getattr(worker, "failed", None)
        if failed is not None:
            failed.connect(
                lambda message, task_id=task_id:
                self._on_failed(task_id, message),
                Qt.QueuedConnection,
            )
        cancelled = getattr(worker, "cancelled", None)
        if cancelled is not None:
            cancelled.connect(
                lambda message="", task_id=task_id:
                self._on_cancelled(task_id, message),
                Qt.QueuedConnection,
            )
        self._on_started(task_id)
        return task_id

    def ensure_can_start(self, owner, name) -> int:
        normalized_name = str(name).strip() or "后台任务"
        for snapshot in self.active_snapshots(owner):
            if snapshot.name == normalized_name:
                raise ValueError(f"任务已在运行：{normalized_name}")
        versions = [
            record["version"] for record in self._records.values()
            if record["owner"] is owner and record["name"] == normalized_name
        ]
        return max(versions, default=0) + 1

    def result_is_current(self, owner, name, version) -> bool:
        records = [
            record for record in self._records.values()
            if (
                record["owner"] is owner
                and record["name"] == name
                and record["version"] == version
            )
        ]
        return len(records) == 1 and not records[0]["stale"]

    @staticmethod
    def _matches(record, owner):
        return owner is None or record["owner"] is owner

    @staticmethod
    def _snapshot(record) -> TaskSnapshot:
        return TaskSnapshot(
            record["id"], record["name"], record["phase"], record["progress"],
            record["message"], record["cancel_requested"], record["completed"],
            record["outcome"], record["error"], record["version"],
            record["stale"],
        )

    def _on_thread_finished(self, task_id):
        self._finish_after_thread(task_id, retries=25)

    def _finish_after_thread(self, task_id, retries):
        record = self._records.get(task_id)
        if record is None or record["completed"]:
            return
        if record["phase"] in (
            TaskPhase.SUCCEEDED, TaskPhase.FAILED, TaskPhase.CANCELLED
        ):
            self._on_finished(task_id)
        elif retries > 0:
            QTimer.singleShot(
                20, lambda: self._finish_after_thread(task_id, retries - 1)
            )
        else:
            self._on_finished(task_id)

    def snapshots(self, owner=None) -> List[TaskSnapshot]:
        return [
            self._snapshot(record) for record in self._records.values()
            if self._matches(record, owner)
        ]

    def active_snapshots(self, owner=None) -> List[TaskSnapshot]:
        result = []
        for record in self._records.values():
            if not self._matches(record, owner):
                continue
            if record["completed"]:
                try:
                    if record["thread"].isFinished():
                        continue
                except RuntimeError:
                    continue
            result.append(self._snapshot(record))
        return result

    def _on_started(self, task_id):
        record = self._records.get(task_id)
        if (
            record is None
            or record["completed"]
            or record["phase"] is not TaskPhase.QUEUED
        ):
            return
        record.update(started_at=time.monotonic(), phase=TaskPhase.RUNNING,
                      message="已开始")
        self.task_started.emit(self._snapshot(record))

    def _on_progress(self, task_id, value, message):
        record = self._records.get(task_id)
        if record is None or record["completed"]:
            return
        try:
            record["progress"] = max(0, min(100, int(value)))
        except (TypeError, ValueError):
            pass
        record["message"] = str(message)
        if not record["cancel_requested"]:
            record["phase"] = TaskPhase.PROGRESS
        self.task_progress.emit(self._snapshot(record))

    def _on_succeeded(self, task_id):
        record = self._records.get(task_id)
        if record is None or record["completed"]:
            return
        record.update(phase=TaskPhase.SUCCEEDED, progress=100,
                      outcome="succeeded", message="已完成")
        self.task_succeeded.emit(self._snapshot(record))

    def _on_failed(self, task_id, message):
        record = self._records.get(task_id)
        if record is None or record["completed"]:
            return
        record.update(phase=TaskPhase.FAILED, outcome="failed",
                      message=str(message), error=str(message))
        self.task_failed.emit(self._snapshot(record))

    def _on_cancelled(self, task_id, message=""):
        record = self._records.get(task_id)
        if record is None or record["completed"]:
            return
        record.update(cancel_requested=True, phase=TaskPhase.CANCELLED,
                      outcome="cancelled", message=str(message) or "已取消")
        self.task_cancelled.emit(self._snapshot(record))

    def cancel_active(self, owner=None) -> List[TaskSnapshot]:
        """向当前窗口的全部活动任务发送协作式取消请求。"""
        result = []
        for record in list(self._records.values()):
            if record["completed"] or not self._matches(record, owner):
                continue
            if record["phase"] in (
                TaskPhase.SUCCEEDED, TaskPhase.FAILED, TaskPhase.CANCELLED
            ):
                result.append(self._snapshot(record))
                continue
            if not record["cancel_requested"]:
                record.update(cancel_requested=True,
                              phase=TaskPhase.CANCEL_REQUESTED,
                              message="已发送取消请求")
                callback = record["cancel_callback"]
                if callback is not None:
                    try:
                        callback()
                    except Exception as exc:
                        record["error"] = str(exc)
                self.task_cancel_requested.emit(self._snapshot(record))
            result.append(self._snapshot(record))
        return result

    def wait_for_tasks(self, owner=None, timeout_ms=3000) -> bool:
        """在有界时间内处理 Qt 事件，等待任务真正退出。"""
        deadline = time.monotonic() + max(0, timeout_ms) / 1000.0
        while self.active_snapshots(owner):
            QCoreApplication.processEvents(QEventLoop.AllEvents, 10)
            if not self.active_snapshots(owner):
                break
            if time.monotonic() >= deadline:
                return False
            QThread.yieldCurrentThread()
        return not self.active_snapshots(owner)

    @staticmethod
    def describe(snapshot) -> str:
        labels = {
            TaskPhase.QUEUED: "等待中",
            TaskPhase.RUNNING: "运行中",
            TaskPhase.PROGRESS: f"运行中 {snapshot.progress}%",
            TaskPhase.CANCEL_REQUESTED: "已请求取消，尚未结束",
            TaskPhase.SUCCEEDED: "成功完成",
            TaskPhase.FAILED: "失败",
            TaskPhase.CANCELLED: "已取消",
        }
        status = labels[snapshot.phase]
        if snapshot.cancel_requested and snapshot.phase == TaskPhase.SUCCEEDED:
            status = "取消请求后成功完成"
        elif snapshot.cancel_requested and snapshot.phase == TaskPhase.FAILED:
            status = "取消请求后失败"
        detail = f"（{snapshot.message}）" if snapshot.message else ""
        return f"{snapshot.name}: {status}{detail}"

    def _on_finished(self, task_id):
        record = self._records.get(task_id)
        if record is None or record["completed"]:
            return
        if record["phase"] not in (
            TaskPhase.SUCCEEDED, TaskPhase.FAILED, TaskPhase.CANCELLED
        ):
            if record["cancel_requested"]:
                record.update(phase=TaskPhase.CANCELLED, outcome="cancelled",
                              message="线程已响应取消")
                self.task_cancelled.emit(self._snapshot(record))
            else:
                error = "后台线程在未报告结果时结束"
                record.update(phase=TaskPhase.FAILED, outcome="failed",
                              error=error, message=error)
                self.task_failed.emit(self._snapshot(record))
        record.update(completed=True, finished_at=time.monotonic())
        self.task_completed.emit(self._snapshot(record))


def task_registry_for(owner) -> TaskRegistry:
    """取得顶层窗口的统一注册表；独立面板首次使用时自动建立。"""
    window = owner.window() if hasattr(owner, "window") else owner
    registry = getattr(window, "task_registry", None)
    if isinstance(registry, TaskRegistry):
        return registry
    registry = TaskRegistry(window)
    setattr(window, "task_registry", registry)
    return registry


def register_background_task(owner, name, thread, worker,
                             cancel_callback=None) -> int:
    """把任务登记到所属顶层窗口，不再扫描 `_thread` 属性。"""
    window = owner.window() if hasattr(owner, "window") else owner
    registry = task_registry_for(owner)
    task_id = registry.register(
        name, window, thread, worker, cancel_callback
    )
    return next(
        snapshot.version for snapshot in registry.snapshots(window)
        if snapshot.task_id == task_id
    )


def ensure_task_can_start(owner, name) -> int:
    """在创建线程前执行统一的同名任务重复启动检查。"""
    window = owner.window() if hasattr(owner, "window") else owner
    return task_registry_for(owner).ensure_can_start(window, name)


def task_result_is_current(owner, name, version) -> bool:
    """判断 UI 结果是否仍属于该窗口同名任务的最新版本。"""
    window = owner.window() if hasattr(owner, "window") else owner
    return task_registry_for(owner).result_is_current(window, name, version)
