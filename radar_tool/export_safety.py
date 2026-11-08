"""Reliable and traceable export helpers."""

from __future__ import annotations

import os
import shutil
import tempfile
from datetime import datetime
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Sequence

import pandas as pd

from .errors import AppError, ExportError, safe_exception_message


APP_VERSION = '1.0.0'
EXPORT_SCHEMA_VERSION = 1
CSV_FORMULA_PREFIXES = ('=', '+', '-', '@')


class BatchExportError(ExportError):
    """Export failure that reports any temporary files which cannot be removed."""

    code = 'batch_export_error'

    def __init__(
        self,
        message: str,
        *,
        cause: Optional[BaseException] = None,
        residual_files: Sequence[str] = (),
    ):
        super().__init__(message)
        self.cause = cause
        self.residual_files = tuple(residual_files)


def escape_csv_cell(value: Any) -> Any:
    """Prefix dangerous user-controlled text with a CSV formula escape marker."""
    if isinstance(value, str) and value.startswith(CSV_FORMULA_PREFIXES):
        return "'" + value
    return value


def sanitize_dataframe_for_csv(dataframe: pd.DataFrame) -> pd.DataFrame:
    """Escape formula-like headers and string cells while preserving numbers."""
    sanitized = dataframe.copy()
    sanitized.rename(
        columns=lambda column: escape_csv_cell(column),
        inplace=True,
    )
    dataframe_mapper = getattr(sanitized, 'map', None)
    if dataframe_mapper is not None:
        return dataframe_mapper(escape_csv_cell)
    return sanitized.applymap(escape_csv_cell)


def write_dataframe_csv(
    dataframe: pd.DataFrame,
    filepath: str,
    **to_csv_options: Any,
) -> None:
    """Write a CSV after applying formula-injection escaping."""
    sanitize_dataframe_for_csv(dataframe).to_csv(filepath, **to_csv_options)


def build_export_metadata(
    input_summary: Optional[Mapping[str, Any]] = None,
    parameters: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Build trace metadata shared by all exported artifacts."""
    return {
        'version': APP_VERSION,
        'schema_version': EXPORT_SCHEMA_VERSION,
        'generated_at': datetime.now().astimezone().isoformat(timespec='seconds'),
        'input_summary': dict(input_summary or {}),
        'parameters': dict(parameters or {}),
    }


def _list_relative_files(root_directory: str) -> Sequence[str]:
    residuals = []
    for directory, _subdirectories, filenames in os.walk(root_directory):
        for filename in filenames:
            filepath = os.path.join(directory, filename)
            residuals.append(os.path.relpath(filepath, root_directory))
    return tuple(sorted(residuals, key=str.casefold))


def _failure_reason(cause: BaseException) -> str:
    if isinstance(cause, (AppError, ValueError)):
        return safe_exception_message(cause)
    if isinstance(cause, OSError):
        return cause.strerror or type(cause).__name__
    return f'{type(cause).__name__}（详细堆栈已记录到日志）'


def _raise_cleanup_failure(
    cause: BaseException,
    temporary_directory: str,
    cleanup_error: BaseException,
) -> None:
    residuals = _list_relative_files(temporary_directory)
    temporary_name = os.path.basename(temporary_directory)
    if residuals:
        residual_text = '、'.join(residuals)
        message = (
            f'导出失败：{_failure_reason(cause)}；'
            f'无法清理的残留文件（位于 {temporary_name}）：{residual_text}'
        )
    else:
        message = (
            f'导出失败：{_failure_reason(cause)}；'
            f'临时目录 {temporary_name} 清理失败，但未发现残留文件'
        )
    raise BatchExportError(
        message,
        cause=cleanup_error,
        residual_files=residuals,
    ) from cause


def _cleanup_failed_export(
    cause: BaseException,
    temporary_directory: str,
) -> None:
    try:
        shutil.rmtree(temporary_directory)
    except Exception as cleanup_error:
        _raise_cleanup_failure(cause, temporary_directory, cleanup_error)
    raise BatchExportError(
        f'导出失败：{_failure_reason(cause)}；'
        '已清理临时批次，无残留文件',
        cause=cause,
    ) from cause


def atomic_export_batch(
    target_directory: str,
    writer: Callable[[str], Any],
) -> str:
    """Write a complete batch in a sibling temp directory and rename it atomically."""
    target_directory = os.fspath(target_directory)
    parent_directory = os.path.dirname(os.path.abspath(target_directory))
    target_name = os.path.basename(target_directory)
    try:
        temporary_directory = tempfile.mkdtemp(
            prefix=f'.{target_name}.tmp-',
            dir=parent_directory,
        )
    except Exception as cause:
        raise BatchExportError(
            f'无法创建临时导出目录：{_failure_reason(cause)}',
            cause=cause,
        ) from cause

    try:
        writer(temporary_directory)
        os.replace(temporary_directory, target_directory)
    except Exception as cause:
        _cleanup_failed_export(cause, temporary_directory)
    return target_directory
