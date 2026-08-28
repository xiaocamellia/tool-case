import os

import pandas as pd


TEXT_EXTENSIONS = {'.txt', '.csv', '.dat', '.log'}
EXCEL_EXTENSIONS = {'.xlsx', '.xls'}


class DataLoader:
    """Data and metadata loader."""

    @staticmethod
    def load_column_names(col_filepath):
        if not os.path.isfile(col_filepath):
            raise FileNotFoundError(f'列名文件不存在: {col_filepath}')

        encodings = ['utf-8-sig', 'utf-8', 'gb18030', 'gbk', 'cp936']
        last_error = None
        for encoding in encodings:
            try:
                with open(col_filepath, 'r', encoding=encoding) as handle:
                    return [line.strip() for line in handle if line.strip()]
            except UnicodeDecodeError as exc:
                last_error = exc
        raise last_error

    @staticmethod
    def load_data(data_filepath, col_names=None):
        return read_numeric_table(data_filepath, col_names=col_names)

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


def _read_text_table(filepath):
    encodings = ['utf-8-sig', 'utf-8', 'gb18030', 'gbk', 'cp936']
    last_error = None
    for encoding in encodings:
        try:
            # The regex covers whitespace, ASCII/Chinese commas, and semicolons.
            return pd.read_csv(
                filepath,
                sep=r'[,;，\s]+',
                engine='python',
                header=None,
                comment='#',
                dtype=str,
                encoding=encoding,
                skip_blank_lines=True,
            )
        except UnicodeDecodeError as exc:
            last_error = exc
        except pd.errors.ParserError as exc:
            last_error = exc
    if last_error is not None:
        raise ValueError(f'文本文件解析失败: {last_error}') from last_error
    raise ValueError('文本文件解析失败')


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


def read_numeric_table(filepath, col_names=None):
    """Read a numeric TXT/CSV/DAT or Excel table."""
    if not os.path.isfile(filepath):
        raise FileNotFoundError(f'文件不存在: {filepath}')

    extension = os.path.splitext(filepath)[1].lower()
    if extension in EXCEL_EXTENSIONS:
        raw = pd.read_excel(filepath, header=None, dtype=object)
    elif extension in TEXT_EXTENSIONS or not extension:
        raw = _read_text_table(filepath)
    else:
        raise ValueError(
            f'不支持的数据格式“{extension or "无扩展名"}”；'
            '请选择 TXT、CSV、DAT、XLSX 或 XLS 文件'
        )

    detected_headers, raw = _detect_header(raw)
    numeric = raw.apply(pd.to_numeric, errors='coerce')
    numeric = numeric.dropna(axis=0, how='all').dropna(axis=1, how='all')
    if numeric.empty or int(numeric.notna().sum().sum()) == 0:
        raise ValueError(
            '文件中没有识别到数值数据。请检查文件格式、分隔符，'
            '或确认选择的是数据文件而不是列名文件。'
        )
    numeric = numeric.reset_index(drop=True)

    names = col_names if col_names else detected_headers
    if not names:
        names = []
    numeric.columns = _unique_column_names(names, numeric.shape[1])
    return numeric
