import os

import pandas as pd


class DataLoader:
    """Data and metadata loader."""

    @staticmethod
    def load_column_names(col_filepath):
        if not os.path.isfile(col_filepath):
            raise FileNotFoundError(f"列名文件不存在: {col_filepath}")

        encodings = ['utf-8-sig', 'utf-8', 'gb18030', 'gbk', 'cp936']
        last_error = None
        lines = None
        for encoding in encodings:
            try:
                with open(col_filepath, 'r', encoding=encoding) as f:
                    lines = [line.strip() for line in f.readlines() if line.strip()]
                break
            except UnicodeDecodeError as e:
                last_error = e

        if lines is None:
            raise last_error

        return lines

    @staticmethod
    def load_data(data_filepath, col_names=None):
        if not os.path.isfile(data_filepath):
            raise FileNotFoundError(f"数据文件不存在: {data_filepath}")

        df = pd.read_csv(data_filepath, sep=r'\s+', header=None, dtype=str)
        df = df.apply(pd.to_numeric, errors='coerce')

        n_cols = df.shape[1]
        if col_names:
            normalized = [str(name).strip() for name in col_names if str(name).strip()]
        else:
            normalized = []

        if len(normalized) < n_cols:
            normalized.extend([f'列--{i+1}' for i in range(len(normalized), n_cols)])

        df.columns = normalized[:n_cols]
        return df

    @staticmethod
    def auto_find_column_file(data_filepath):
        base_dir = os.path.dirname(data_filepath)
        base_name = os.path.splitext(os.path.basename(data_filepath))[0]

        candidates = [
            os.path.join(base_dir, f"{base_name}列名.txt"),
            os.path.join(base_dir, f"{base_name}_列名.txt"),
            os.path.join(base_dir, f"{base_name}_columns.txt"),
            os.path.join(base_dir, f"{base_name}.columns.txt"),
        ]

        files = os.listdir(base_dir)
        for filename in files:
            if '列名' in filename and filename.endswith('.txt'):
                candidates.append(os.path.join(base_dir, filename))

        for candidate in candidates:
            if os.path.isfile(candidate):
                return candidate
        return None


def read_numeric_table(filepath):
    """Read generic numeric table separated by whitespace or comma."""
    if not os.path.isfile(filepath):
        raise FileNotFoundError(f'文件不存在: {filepath}')

    df = pd.read_csv(
        filepath,
        sep=r'[,\s]+',
        engine='python',
        header=None,
        comment='#',
        dtype=str,
    )
    df = df.apply(pd.to_numeric, errors='coerce')
    df = df.dropna(axis=1, how='all')
    if df.empty:
        raise ValueError('读取失败：文件中没有可用数值列')
    df.columns = [f'列--{i+1}' for i in range(df.shape[1])]
    return df
