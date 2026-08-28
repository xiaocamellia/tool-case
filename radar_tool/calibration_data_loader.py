"""Input loader for four-column direction-finding calibration data."""

from __future__ import annotations

import os

import numpy as np
import pandas as pd


FIELD_NAMES = ('az_true', 'el_true', 'az_meas', 'el_meas')
FIELD_ALIASES = {
    'az_true': {'az_true', 'azimuth_true', '方位角真值', '方位真值', '真值方位角'},
    'el_true': {'el_true', 'elevation_true', '俯仰角真值', '俯仰真值', '真值俯仰角'},
    'az_meas': {'az_meas', 'azimuth_meas', '方位角实测值', '方位实测值', '实测方位角'},
    'el_meas': {'el_meas', 'elevation_meas', '俯仰角实测值', '俯仰实测值', '实测俯仰角'},
}


def _normalized_header(value) -> str:
    return str(value).strip().lower().replace(' ', '').replace('-', '_')


def _read_table(filepath: str) -> pd.DataFrame:
    extension = os.path.splitext(filepath)[1].lower()
    if extension in ('.xlsx', '.xls', '.xlsm'):
        try:
            return pd.read_excel(filepath, header=None)
        except ImportError as exc:
            raise ValueError('读取 Excel 需要安装 openpyxl 或相应 Excel 引擎') from exc
    if extension in ('.csv', '.txt'):
        try:
            return pd.read_csv(filepath, header=None, sep=None, engine='python')
        except UnicodeDecodeError:
            return pd.read_csv(filepath, header=None, sep=None, engine='python', encoding='gbk')
    raise ValueError('仅支持 .xlsx、.xls、.xlsm、.csv 和 .txt 文件')


def load_calibration_data(filepath: str) -> dict:
    """Load and validate the first four calibration fields from a table."""
    if not filepath or not os.path.isfile(filepath):
        raise ValueError('请选择存在的数据文件')
    raw = _read_table(filepath).dropna(how='all').dropna(axis=1, how='all')
    if raw.shape[1] < 4:
        raise ValueError(f'数据文件至少需要 4 列，当前为 {raw.shape[1]} 列')

    first_row = [_normalized_header(value) for value in raw.iloc[0].tolist()]
    index_by_field = {}
    for field, aliases in FIELD_ALIASES.items():
        normalized_aliases = {_normalized_header(alias) for alias in aliases}
        matches = [index for index, value in enumerate(first_row) if value in normalized_aliases]
        if matches:
            index_by_field[field] = matches[0]

    has_named_header = len(index_by_field) == len(FIELD_NAMES)
    if has_named_header:
        selected = pd.DataFrame({
            field: raw.iloc[1:, index_by_field[field]] for field in FIELD_NAMES
        })
        source_columns = [str(raw.iloc[0, index_by_field[field]]) for field in FIELD_NAMES]
    else:
        first_four = raw.iloc[:, :4]
        numeric_first_row = pd.to_numeric(first_four.iloc[0], errors='coerce').notna().sum()
        data_start = 1 if numeric_first_row == 0 else 0
        selected = first_four.iloc[data_start:].copy()
        selected.columns = FIELD_NAMES
        source_columns = (
            list(FIELD_NAMES) if data_start == 0
            else [str(value) for value in first_four.iloc[0].tolist()]
        )

    numeric = selected.apply(pd.to_numeric, errors='coerce')
    invalid_rows = numeric.isna().any(axis=1)
    if invalid_rows.any():
        first_invalid = int(np.flatnonzero(invalid_rows.to_numpy())[0]) + 1
        raise ValueError(f'第 {first_invalid} 条数据存在空值或非数值内容')
    if numeric.empty:
        raise ValueError('数据文件中没有有效样本')

    result = {field: numeric[field].to_numpy(dtype=float) for field in FIELD_NAMES}
    result.update({
        'sample_count': int(len(numeric)),
        'source_path': os.path.abspath(filepath),
        'source_columns': source_columns,
        'small_sample_warning': len(numeric) < 30,
    })
    return result
