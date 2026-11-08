"""统一领域异常与敏感信息清理。"""

from __future__ import annotations

import re
import traceback
from typing import Optional


class AppError(Exception):
    """所有面向用户领域异常的基类。"""

    code = "app_error"

    def __init__(self, message: str, code: Optional[str] = None):
        super().__init__(message)
        self.user_message = str(message)
        if code is not None:
            self.code = code


class ValidationError(ValueError, AppError):
    """输入、Schema 或参数校验失败。"""

    code = "validation_error"


class DataLimitError(ValidationError):
    """输入超过资源或数据量限制。"""

    code = "data_limit_error"


class ExportError(AppError):
    """导出或持久化失败。"""

    code = "export_error"


_WINDOWS_FILE_PATH = re.compile(
    r"(?i)(?:[a-z]:[\\/]|\\\\)[^\r\n\"'<>]*?\.[a-z0-9]{1,12}"
    r"(?=$|[\s,;)\]}])"
)
_WINDOWS_PATH = re.compile(
    r"(?i)(?:[a-z]:[\\/]|\\\\)[^\r\n\"'<>]+"
)
_FILE_URL = re.compile(r"(?i)file://[^\s\"'<>]+")
_POSIX_FILE_PATH = re.compile(
    r"(?<![:\w])/(?:[^/\s:*?\"'<>|]+/)*"
    r"[^/\s:*?\"'<>|]+\.[a-z0-9]{1,12}(?=$|[\s,;)\]}])"
)
_POSIX_PATH = re.compile(
    r"(?<![:\w])/[^\r\n\"'<>]+"
)
_DATA_SEQUENCE = re.compile(
    r"(?<![\w.])[-+]?(?:\d+(?:\.\d*)?|\.\d+)"
    r"(?:[eE][-+]?\d+)?"
    r"(?:\s*[,;\t]\s*[-+]?(?:\d+(?:\.\d*)?|\.\d+)"
    r"(?:[eE][-+]?\d+)?){4,}"
)


def sanitize_sensitive_text(value, max_length: int = 800) -> str:
    """隐藏绝对路径、文件 URL 和较长的原始数值序列。"""
    text = str(value)
    text = _FILE_URL.sub("<文件路径>", text)
    text = _WINDOWS_FILE_PATH.sub("<文件路径>", text)
    text = _WINDOWS_PATH.sub("<文件路径>", text)
    text = _POSIX_FILE_PATH.sub("<文件路径>", text)
    text = _POSIX_PATH.sub("<文件路径>", text)
    text = _DATA_SEQUENCE.sub("<原始数据已隐藏>", text)
    if len(text) > max_length:
        text = text[:max_length].rstrip() + "…"
    return text


def safe_exception_message(exc: BaseException) -> str:
    """返回可安全显示的异常文本；未知异常不透传原始内容。"""
    if isinstance(exc, (AppError, ValueError)):
        return sanitize_sensitive_text(str(exc))
    return "发生未预期错误，详细堆栈已记录到日志。"


def safe_traceback(exc: BaseException) -> str:
    """生成保留堆栈结构、但隐藏敏感路径和原始数据的文本。"""
    stack = "".join(
        traceback.format_exception(type(exc), exc, exc.__traceback__)
    )
    return sanitize_sensitive_text(stack, max_length=1_000_000)


def log_exception(logger, context: str, exc: BaseException) -> None:
    """按异常类型记录安全日志；未知异常保留完整堆栈结构。"""
    if isinstance(exc, AppError):
        logger.error("%s: %s", context, safe_exception_message(exc))
        return
    logger.error(
        "%s [%s]\n%s",
        context,
        type(exc).__name__,
        safe_traceback(exc),
    )
