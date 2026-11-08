"""Shared resource limits and preflight checks for input files."""

from __future__ import annotations

import os
import re
import zipfile
import xml.etree.ElementTree as ET
from typing import Tuple


MAX_FILE_SIZE = None
MAX_ROWS = 1_000_000
MAX_COLUMNS = 10_000
MAX_SAMPLES = 1_000_000
MAX_BIN_FRAMES = 24
MAX_EXCEL_SHEETS = 16
MAX_EXTRACTED_SIZE = 200 * 1024 * 1024


from .errors import DataLimitError


class InputResourceError(DataLimitError):
    """Raised when an input exceeds a configured safety limit."""


def display_name(filepath) -> str:
    return os.path.basename(os.fspath(filepath)) or '输入文件'


def ensure_file_size(filepath, max_bytes=None, label: str = '输入文件') -> int:
    if max_bytes is None:
        max_bytes = MAX_FILE_SIZE
    try:
        size = os.path.getsize(filepath)
    except OSError as exc:
        raise InputResourceError(f'{label}大小无法检查') from exc
    if max_bytes is not None and size > max_bytes:
        raise InputResourceError(
            f'{label}大小超限：允许 0~{max_bytes} 字节，当前 {size} 字节'
        )
    return size


def validate_table_shape(
    shape: Tuple[int, int],
    max_rows=None,
    max_columns=None,
    label: str = '数据表',
) -> None:
    if max_rows is None:
        max_rows = MAX_ROWS
    if max_columns is None:
        max_columns = MAX_COLUMNS
    rows, columns = int(shape[0]), int(shape[1])
    if rows > max_rows:
        raise InputResourceError(
            f'{label}行数超限：允许 0~{max_rows} 行，当前 {rows} 行'
        )
    if columns > max_columns:
        raise InputResourceError(
            f'{label}列数超限：允许 0~{max_columns} 列，当前 {columns} 列'
        )


def validate_sample_count(count: int, max_samples=None) -> None:
    if max_samples is None:
        max_samples = MAX_SAMPLES
    if count > max_samples:
        raise InputResourceError(
            f'样本数超限：允许 0~{max_samples} 条，当前 {count} 条'
        )


def _decode_line(raw_line: bytes) -> str:
    for encoding in ('utf-8-sig', 'gb18030'):
        try:
            return raw_line.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw_line.decode('latin-1', errors='replace')


def preflight_text_table(
    filepath,
    max_rows=None,
    max_columns=None,
    allow_comments: bool = True,
) -> Tuple[int, int]:
    """Count text rows and columns before pandas allocates a table."""

    if max_rows is None:
        max_rows = MAX_ROWS
    if max_columns is None:
        max_columns = MAX_COLUMNS
    ensure_file_size(filepath)
    row_count = 0
    max_seen_columns = 0
    with open(filepath, 'rb') as source:
        for raw_line in source:
            line = _decode_line(raw_line).strip()
            if not line or (allow_comments and line.startswith('#')):
                continue
            row_count += 1
            if row_count > max_rows:
                raise InputResourceError(
                    f'文本文件行数超限：允许 0~{max_rows} 行，当前至少 {row_count} 行'
                )
            fields = [part for part in re.split(r'[,;，\s]+', line) if part]
            max_seen_columns = max(max_seen_columns, len(fields))
            if max_seen_columns > max_columns:
                raise InputResourceError(
                    f'文本文件列数超限：允许 0~{max_columns} 列，'
                    f'当前至少 {max_seen_columns} 列'
                )
    return row_count, max_seen_columns


def _excel_column_number(reference: str) -> int:
    match = re.match(r'([A-Za-z]+)', reference or '')
    if not match:
        return 0
    result = 0
    for character in match.group(1).upper():
        result = result * 26 + ord(character) - ord('A') + 1
    return result


def _preflight_xlsx_archive(
    filepath, scan_cells: bool = True
) -> Tuple[int, int, int]:
    try:
        with zipfile.ZipFile(filepath) as archive:
            infos = archive.infolist()
            extracted_size = sum(max(0, info.file_size) for info in infos)
            if extracted_size > MAX_EXTRACTED_SIZE:
                raise InputResourceError(
                    f'Excel 解压总大小超限：允许 0~{MAX_EXTRACTED_SIZE} 字节，'
                    f'当前 {extracted_size} 字节'
                )
            worksheets = [
                info for info in infos
                if re.fullmatch(r'xl/worksheets/sheet\d+\.xml', info.filename)
            ]
            if len(worksheets) > MAX_EXCEL_SHEETS:
                raise InputResourceError(
                    f'Excel 工作表数量超限：允许 0~{MAX_EXCEL_SHEETS} 个，'
                    f'当前 {len(worksheets)} 个'
                )
            if not scan_cells:
                return len(worksheets), 0, 0

            row_count = 0
            column_count = 0
            for worksheet in worksheets:
                worksheet_rows = 0
                worksheet_columns = 0
                current_row_columns = 0
                with archive.open(worksheet) as stream:
                    for event, element in ET.iterparse(stream, events=('start', 'end')):
                        tag = element.tag.rsplit('}', 1)[-1]
                        if event == 'end' and tag == 'c':
                            current_row_columns += 1
                            reference = element.attrib.get('r', '')
                            worksheet_columns = max(
                                worksheet_columns,
                                _excel_column_number(reference),
                                current_row_columns,
                            )
                            element.clear()
                        elif event == 'end' and tag == 'row':
                            worksheet_rows += 1
                            worksheet_columns = max(
                                worksheet_columns, current_row_columns)
                            current_row_columns = 0
                            element.clear()
                            if worksheet_rows > MAX_ROWS:
                                raise InputResourceError(
                                    f'Excel 行数超限：允许 0~{MAX_ROWS} 行，'
                                    f'当前至少 {worksheet_rows} 行'
                                )
                            if worksheet_columns > MAX_COLUMNS:
                                raise InputResourceError(
                                    f'Excel 列数超限：允许 0~{MAX_COLUMNS} 列，'
                                    f'当前至少 {worksheet_columns} 列'
                                )
                row_count += worksheet_rows
                column_count = max(column_count, worksheet_columns)
                if row_count > MAX_ROWS:
                    raise InputResourceError(
                        f'Excel 行数超限：允许 0~{MAX_ROWS} 行，当前至少 {row_count} 行'
                    )
                if column_count > MAX_COLUMNS:
                    raise InputResourceError(
                        f'Excel 列数超限：允许 0~{MAX_COLUMNS} 列，'
                        f'当前至少 {column_count} 列'
                    )
            return len(worksheets), row_count, column_count
    except zipfile.BadZipFile as exc:
        raise InputResourceError('Excel 文件结构损坏或不是有效 XLSX 文件') from exc


def preflight_excel(filepath, scan_cells: bool = True) -> None:
    """Validate archive size, sheet count, and worksheet dimensions."""

    ensure_file_size(filepath, label='Excel 文件')
    if zipfile.is_zipfile(filepath):
        _preflight_xlsx_archive(filepath, scan_cells=scan_cells)
        return

    try:
        import xlrd
    except ImportError:
        return
    try:
        workbook = xlrd.open_workbook(filepath, on_demand=True)
    except Exception as exc:
        raise InputResourceError('Excel 文件无法读取或结构损坏') from exc
    try:
        sheet_count = workbook.nsheets
        if sheet_count > MAX_EXCEL_SHEETS:
            raise InputResourceError(
                f'Excel 工作表数量超限：允许 0~{MAX_EXCEL_SHEETS} 个，'
                f'当前 {sheet_count} 个'
            )
        total_rows = 0
        max_columns = 0
        for index in range(sheet_count):
            sheet = workbook.sheet_by_index(index)
            total_rows += sheet.nrows
            max_columns = max(max_columns, sheet.ncols)
            if total_rows > MAX_ROWS:
                raise InputResourceError(
                    f'Excel 行数超限：允许 0~{MAX_ROWS} 行，当前 {total_rows} 行'
                )
            if max_columns > MAX_COLUMNS:
                raise InputResourceError(
                    f'Excel 列数超限：允许 0~{MAX_COLUMNS} 列，当前 {max_columns} 列'
                )
    finally:
        workbook.release_resources()
