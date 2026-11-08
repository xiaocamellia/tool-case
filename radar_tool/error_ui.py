"""统一 UI 异常页面与全局异常入口。"""

from __future__ import annotations

import sys
import uuid

from PyQt5.QtWidgets import QMessageBox

from .errors import (
    AppError,
    log_exception,
    safe_exception_message,
    safe_traceback,
)


def handle_ui_exception(parent, logger, context: str, exc: BaseException):
    """领域异常显示安全文本；未知异常进入统一错误页面。"""
    if isinstance(exc, (AppError, ValueError)):
        message = safe_exception_message(exc)
        log_exception(logger, context, exc)
        QMessageBox.warning(
            parent,
            "操作失败",
            f"{context}：{message}",
        )
        return message

    error_id = uuid.uuid4().hex[:12]
    log_exception(logger, f"{context}（错误编号 {error_id}）", exc)
    QMessageBox.critical(
        parent,
        "统一错误页面",
        f"{context}失败，发生未预期错误。\n"
        f"错误编号：{error_id}\n"
        "完整堆栈已安全记录到日志，未展示原始数据或敏感路径。",
    )
    return error_id


def install_global_error_handler(logger):
    """将未捕获异常路由到安全日志和统一错误页面。"""

    def _handler(exc_type, exc_value, exc_traceback):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        error_id = uuid.uuid4().hex[:12]
        logger.error(
            "未捕获异常（错误编号 %s） [%s]\n%s",
            error_id,
            exc_type.__name__,
            safe_traceback(exc_value),
        )
        QMessageBox.critical(
            None,
            "统一错误页面",
            "程序发生未预期错误。\n"
            f"错误编号：{error_id}\n"
            "完整堆栈已安全记录到日志，未展示原始数据或敏感路径。",
        )

    sys.excepthook = _handler
    return _handler
