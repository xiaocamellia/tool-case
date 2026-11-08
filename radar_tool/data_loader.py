import codecs
import csv
import os
import re
from collections import Counter

import pandas as pd

from .errors import ValidationError

from .input_limits import (
    InputResourceError,
    MAX_COLUMNS,
    ensure_file_size,
    preflight_excel,
    validate_table_shape,
)


TEXT_EXTENSIONS = {'.txt', '.csv', '.dat', '.log'}
EXCEL_EXTENSIONS = {'.xlsx', '.xls'}
TEXT_SEPARATOR = r'[,;，\s]+'
SIMPLE_TEXT_DELIMITERS = (',', ';', '，', '\t')


class DataLoader:
    """Data and metadata loader."""

    @staticmethod
    def normalize_column_names(names, count):
        return _unique_column_names(names or [], count)

    @staticmethod
    def load_column_names(col_filepath):
        if not os.path.isfile(col_filepath):
            raise ValidationError('列名文件不存在')

        ensure_file_size(col_filepath, label='列名文件')
        encodings = ['utf-8-sig', 'utf-8', 'gb18030', 'gbk', 'cp936']
        for encoding in encodings:
            try:
                names = []
                with open(col_filepath, 'r', encoding=encoding) as handle:
                    for line in handle:
                        name = line.strip()
                        if not name:
                            continue
                        names.append(name)
                        if len(names) > MAX_COLUMNS:
                            raise InputResourceError(
                                f'列名文件行数超限：允许 0~{MAX_COLUMNS} 行，'
                                f'当前至少 {len(names)} 行'
                            )
                return names
            except UnicodeDecodeError:
                continue
        raise ValidationError('列名文件编码无法识别，请使用 UTF-8 或 GB18030 编码')

    @staticmethod
    def load_data(data_filepath, col_names=None, validate_limits=True):
        return read_numeric_table(
            data_filepath,
            col_names=col_names,
            validate_limits=validate_limits,
        )

    @staticmethod
    def auto_find_column_file(data_filepath):
        base_dir = os.path.dirname(data_filepath)
        base_name = os.path.splitext(os.path.basename(data_filepath))[0]
        candidates = [
            os.path.join(base_dir, f'{base_name}列名.txt'),
            os.path.join(base_dir, f'{base_name}_列名.txt'),
            os.path.join(base_dir, f'{base_name}_columns.txt'),
            os.path.join(base_dir, f'{base_name}.columns.txt'),
        ]
        for filename in os.listdir(base_dir):
            if '列名' in filename and filename.lower().endswith('.txt'):
                candidates.append(os.path.join(base_dir, filename))
        return next((path for path in candidates if os.path.isfile(path)), None)


def _read_text_sample(filepath, sample_size=256 * 1024):
    with open(filepath, 'rb') as source:
        return source.read(sample_size)


def _detect_text_encoding(sample):
    sample_size = 256 * 1024
    if sample.startswith(codecs.BOM_UTF8):
        return 'utf-8-sig'
    try:
        codecs.getincrementaldecoder('utf-8')().decode(
            sample, final=len(sample) < sample_size
        )
    except UnicodeDecodeError:
        return 'gb18030'
    return 'utf-8'


def _meaningful_text_lines(sample_text):
    return [
        line.strip()
        for line in sample_text.splitlines()
        if line.strip() and not line.lstrip().startswith('#')
    ]


def _detect_text_separator(lines, delimiter_candidates):
    if not lines:
        return None

    return _choose_text_separator(lines, delimiter_candidates)


def _split_text_line(line, separator, delimiter_candidates):
    if separator is None:
        return [line.strip()]
    if separator == r'\s+':
        return line.split()
    if separator in delimiter_candidates and len(separator) == 1:
        try:
            fields = next(
                csv.reader(
                    [line],
                    delimiter=separator,
                    skipinitialspace=True,
                    strict=False,
                )
            )
        except (csv.Error, StopIteration):
            fields = line.split(separator)
    else:
        fields = re.split(separator, line)
    normalized = [field.strip() for field in fields]
    while normalized and not normalized[-1]:
        normalized.pop()
    return normalized or ['']


def _choose_text_separator(lines, delimiter_candidates):
    candidates = list(delimiter_candidates)
    candidates.append(r'\s+')
    best_separator = None
    best_score = None
    for separator in candidates:
        counts = [
            len(_split_text_line(line, separator, delimiter_candidates))
            for line in lines[:256]
        ]
        if not counts or max(counts) <= 1:
            continue
        common_count, frequency = Counter(counts).most_common(1)[0]
        coverage = frequency / len(counts)
        score = (common_count > 1, coverage, common_count, frequency)
        if best_score is None or score > best_score:
            best_score = score
            best_separator = separator
    return best_separator


def _build_text_read_plan(filepath, delimiter_candidates):
    sample = _read_text_sample(filepath)
    detected_encoding = _detect_text_encoding(sample)
    sample_text = sample.decode(detected_encoding, errors='replace')
    sample_lines = _meaningful_text_lines(sample_text)
    separator = _detect_text_separator(sample_lines, delimiter_candidates)
    encodings = (
        [detected_encoding, 'gb18030']
        if detected_encoding.startswith('utf-8')
        else [detected_encoding, 'utf-8-sig']
    )
    return detected_encoding, separator, encodings, sample_lines


def _read_lenient_text_table(
    filepath,
    encoding,
    delimiter_candidates,
    fallback_separator,
    dtype,
    header,
    nrows,
    validate_limits,
    label,
):
    source_limit = None if nrows is None else nrows + (1 if header == 0 else 0)
    lines = []
    with open(filepath, 'r', encoding=encoding, newline='') as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped or stripped.startswith('#'):
                continue
            lines.append(line.rstrip('\r\n'))
            if source_limit is not None and len(lines) >= source_limit:
                break
    if not lines:
        raise ValidationError('文本文件为空或没有有效数据行')

    separator = _choose_text_separator(lines, delimiter_candidates)
    if separator is None:
        separator = fallback_separator
    rows = [
        _split_text_line(line, separator, delimiter_candidates)
        for line in lines
    ]
    width = max(len(row) for row in rows)
    normalized_rows = [
        row + [None] * (width - len(row))
        for row in rows
    ]
    if validate_limits:
        validate_table_shape((len(normalized_rows), width), label=label)

    if header == 0:
        columns = normalized_rows[0]
        data_rows = normalized_rows[1:]
    else:
        columns = None
        data_rows = normalized_rows
    table = pd.DataFrame(data_rows, columns=columns, dtype=object)
    if dtype is not str:
        table = table.astype(dtype)
    return table


def _read_text_table_with_plan(
    filepath,
    read_plan,
    *,
    label='文本数据表',
    fallback_separator=TEXT_SEPARATOR,
    delimiter_candidates=SIMPLE_TEXT_DELIMITERS,
    dtype=str,
    header=None,
    nrows=None,
    validate_limits=True,
):
    _detected_encoding, separator, encodings, _sample_lines = read_plan
    for encoding in encodings:
        parser_separator = (
            separator if separator is not None else fallback_separator
        )
        engine = (
            'c'
            if parser_separator in delimiter_candidates
            or parser_separator == r'\s+'
            else 'python'
        )
        try:
            table = pd.read_csv(
                filepath,
                sep=parser_separator,
                engine=engine,
                header=header,
                comment='#',
                dtype=dtype,
                encoding=encoding,
                skip_blank_lines=True,
                skipinitialspace=True,
                nrows=nrows,
            )
            if validate_limits:
                validate_table_shape(table.shape, label=label)
            return table
        except UnicodeDecodeError:
            continue
        except pd.errors.EmptyDataError as exc:
            raise ValidationError('文本文件为空或没有有效数据行') from exc
        except pd.errors.ParserError:
            try:
                return _read_lenient_text_table(
                    filepath,
                    encoding,
                    delimiter_candidates,
                    fallback_separator,
                    dtype,
                    header,
                    nrows,
                    validate_limits,
                    label,
                )
            except UnicodeDecodeError:
                continue
            except InputResourceError:
                raise
            except (ValidationError, ValueError, TypeError) as lenient_exc:
                raise ValidationError(
                    '文本文件解析失败：请检查分隔符、引号和每行字段数量'
                ) from lenient_exc
    raise ValidationError('文本文件编码无法识别，请使用 UTF-8 或 GB18030 编码')


def read_text_table(
    filepath,
    *,
    label='文本数据表',
    fallback_separator=TEXT_SEPARATOR,
    delimiter_candidates=SIMPLE_TEXT_DELIMITERS,
    dtype=str,
    header=None,
    nrows=None,
    validate_limits=True,
):
    ensure_file_size(filepath, label=label)
    read_plan = _build_text_read_plan(filepath, delimiter_candidates)
    return _read_text_table_with_plan(
        filepath,
        read_plan,
        label=label,
        fallback_separator=fallback_separator,
        delimiter_candidates=delimiter_candidates,
        dtype=dtype,
        header=header,
        nrows=nrows,
        validate_limits=validate_limits,
    )


def _detect_header(raw):
    if raw.empty or len(raw) < 2:
        return None, raw
    first_numeric = pd.to_numeric(raw.iloc[0], errors='coerce').notna().mean()
    following_numeric = raw.iloc[1:min(len(raw), 8)].apply(
        pd.to_numeric, errors='coerce'
    ).notna().to_numpy().mean()
    if first_numeric < 0.5 and following_numeric >= 0.5:
        headers = [str(value).strip() for value in raw.iloc[0]]
        return headers, raw.iloc[1:].reset_index(drop=True)
    return None, raw


def _detect_header_from_sample(sample_lines, separator, delimiter_candidates):
    if len(sample_lines) < 2:
        return None
    rows = [
        _split_text_line(line, separator, delimiter_candidates)
        for line in sample_lines[:8]
    ]
    first_numeric = pd.to_numeric(
        pd.Series(rows[0]), errors='coerce'
    ).notna().mean()
    following_values = [
        value
        for row in rows[1:]
        for value in row
    ]
    following_numeric = pd.to_numeric(
        pd.Series(following_values), errors='coerce'
    ).notna().mean()
    if first_numeric < 0.5 and following_numeric >= 0.5:
        return [value.strip() for value in rows[0]]
    return None


def _unique_column_names(names, count):
    normalized = []
    used = {}
    for index in range(count):
        base = str(names[index]).strip() if index < len(names) else ''
        if not base or base.lower() == 'nan':
            base = f'列--{index + 1}'
        occurrence = used.get(base, 0) + 1
        used[base] = occurrence
        normalized.append(base if occurrence == 1 else f'{base}_{occurrence}')
    return normalized


def _read_text_numeric_table(filepath, validate_limits=True):
    ensure_file_size(filepath, label='数据文件')
    read_plan = _build_text_read_plan(filepath, SIMPLE_TEXT_DELIMITERS)
    separator = read_plan[1] or TEXT_SEPARATOR
    detected_headers = _detect_header_from_sample(
        read_plan[3], separator, SIMPLE_TEXT_DELIMITERS
    )
    try:
        numeric = _read_text_table_with_plan(
            filepath,
            read_plan,
            label='数据文件',
            dtype='float64',
            header=0 if detected_headers else None,
            validate_limits=validate_limits,
        )
    except (ValidationError, ValueError, TypeError):
        raw = _read_text_table_with_plan(
            filepath,
            read_plan,
            label='数据文件',
            validate_limits=validate_limits,
        )
        detected_headers, raw = _detect_header(raw)
        numeric = raw.apply(pd.to_numeric, errors='coerce')
    return detected_headers, numeric


def read_excel_table(filepath, validate_limits=True):
    extension = os.path.splitext(filepath)[1].lower()
    ensure_file_size(filepath, label='Excel 文件')
    if validate_limits:
        preflight_excel(filepath, scan_cells=False)
    if extension == '.xls':
        try:
            return pd.read_excel(filepath, header=None, dtype=object)
        except Exception as exc:
            raise ValidationError('Excel 文件无法读取或结构损坏') from exc

    try:
        from openpyxl import load_workbook

        workbook = load_workbook(
            filepath, read_only=True, data_only=True, keep_links=False
        )
    except Exception as exc:
        raise ValidationError('Excel 文件无法读取或结构损坏') from exc

    selected_rows = []
    try:
        total_rows = 0
        max_columns = 0
        worksheets = (
            workbook.worksheets
            if validate_limits
            else workbook.worksheets[:1]
        )
        for sheet_index, worksheet in enumerate(worksheets):
            worksheet_rows = 0
            worksheet_columns = 0
            for row in worksheet.iter_rows(values_only=True):
                worksheet_rows += 1
                worksheet_columns = max(worksheet_columns, len(row))
                if worksheet_rows == 1 or worksheet_rows % 1024 == 0:
                    validate_table_shape(
                        (worksheet_rows, worksheet_columns),
                        label='Excel 数据表',
                    )
                if sheet_index == 0:
                    selected_rows.append(row)
            total_rows += worksheet_rows
            max_columns = max(max_columns, worksheet_columns)
            validate_table_shape(
                (total_rows, max_columns), label='Excel 数据表'
            )
    except InputResourceError:
        raise
    except Exception as exc:
        raise ValidationError('Excel 文件无法读取或结构损坏') from exc
    finally:
        workbook.close()

    if not selected_rows:
        return pd.DataFrame()
    width = max(len(row) for row in selected_rows)
    normalized_rows = [
        row + (None,) * (width - len(row))
        for row in selected_rows
    ]
    return pd.DataFrame(normalized_rows, dtype=object)


def read_numeric_table(filepath, col_names=None, validate_limits=True):
    """Read a numeric TXT/CSV/DAT or Excel table."""
    if not os.path.isfile(filepath):
        raise ValidationError('数据文件不存在')

    extension = os.path.splitext(filepath)[1].lower()
    if extension in EXCEL_EXTENSIONS:
        raw = read_excel_table(filepath, validate_limits=validate_limits)
        if validate_limits:
            validate_table_shape(raw.shape, label='Excel 数据表')
        detected_headers, raw = _detect_header(raw)
        numeric = raw.apply(pd.to_numeric, errors='coerce')
    elif extension in TEXT_EXTENSIONS or not extension:
        detected_headers, numeric = _read_text_numeric_table(
            filepath, validate_limits=validate_limits
        )
    else:
        raise ValidationError(
            f'不支持的数据格式“{extension or "无扩展名"}”；'
            '请选择 TXT、CSV、DAT、XLSX 或 XLS 文件'
        )

    numeric = numeric.dropna(axis=0, how='all').dropna(axis=1, how='all')
    if numeric.empty or int(numeric.notna().sum().sum()) == 0:
        raise ValidationError(
            '文件中没有识别到数值数据。请检查文件格式、分隔符，'
            '或确认选择的是数据文件而不是列名文件。'
        )
    numeric = numeric.reset_index(drop=True)
    if validate_limits:
        validate_table_shape(numeric.shape, label='数值数据表')

    names = col_names if col_names else detected_headers
    if not names:
        names = []
    numeric.columns = _unique_column_names(names, numeric.shape[1])
    return numeric
