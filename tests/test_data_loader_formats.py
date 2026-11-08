import numpy as np
import pandas as pd
import pytest
from unittest.mock import patch

from radar_tool import data_loader
from radar_tool.calibration_data_loader import load_calibration_data
from radar_tool.data_loader import DataLoader, read_numeric_table
from radar_tool.errors import ValidationError
from radar_tool.visualization_panel import DatasetLoadWorker


def test_metadata_loader_accepts_comma_separated_radar_data(tmp_path):
    path = tmp_path / 'radar.csv'
    path.write_text('1,2,3,4\n5,6,7,8\n', encoding='utf-8')

    frame = DataLoader.load_data(path, ['距离', '速度', '俯仰角', '方位角'])

    assert list(frame.columns) == ['距离', '速度', '俯仰角', '方位角']
    np.testing.assert_allclose(frame.to_numpy(), [[1, 2, 3, 4], [5, 6, 7, 8]])


def test_text_loader_detects_header_and_semicolon_separator(tmp_path):
    path = tmp_path / 'truth.dat'
    path.write_text('time;distance;speed\n0;100;2\n1;101;3\n', encoding='utf-8')

    frame = read_numeric_table(path)

    assert list(frame.columns) == ['time', 'distance', 'speed']
    assert frame.shape == (2, 3)


def test_text_loader_detects_gb18030_header(tmp_path):
    path = tmp_path / 'truth_gb18030.csv'
    path.write_bytes('距离,速度\n100,2\n101,3\n'.encode('gb18030'))

    frame = read_numeric_table(path)

    assert list(frame.columns) == ['距离', '速度']
    assert frame.shape == (2, 2)


def test_loader_rejects_file_without_numeric_data(tmp_path):
    path = tmp_path / 'wrong.txt'
    path.write_text('this is a column name file\nnot measurement data\n', encoding='utf-8')

    with pytest.raises(ValueError, match='没有识别到数值数据'):
        read_numeric_table(path)


def test_dataset_load_worker_preserves_validation_error():
    expected = ValidationError('字段数量不一致')

    with patch(
        'radar_tool.visualization_panel._load_dataset_payload',
        side_effect=expected,
    ):
        worker = DatasetLoadWorker(['normal-data.csv'])
        failures = []
        worker.failed.connect(failures.append)
        worker.run()

    assert failures == [expected]


def test_text_loader_accepts_quoted_delimiters_and_trailing_separators(tmp_path):
    path = tmp_path / 'quoted.csv'
    path.write_text(
        '"距离, km",速度,\n100,2,\n101,3,\n',
        encoding='utf-8',
    )

    frame = read_numeric_table(path)

    assert list(frame.columns) == ['距离, km', '速度']
    assert frame.shape == (2, 2)


def test_text_loader_pads_short_rows_instead_of_rejecting_file(tmp_path):
    path = tmp_path / 'missing-values.csv'
    path.write_text(
        'a,b,c\n1,2,3\n4,5\n6,7,8\n',
        encoding='utf-8',
    )

    frame = read_numeric_table(path)

    assert frame.shape == (3, 3)
    assert frame.iloc[1].isna().tolist() == [False, False, True]


def test_column_name_count_mismatch_does_not_block_numeric_data(tmp_path):
    path = tmp_path / 'fewer-names.csv'
    path.write_text('1,2,3\n4,5,6\n', encoding='utf-8')

    frame = DataLoader.load_data(path, ['距离', '速度'])

    assert list(frame.columns) == ['距离', '速度', '列--3']


def test_numeric_loader_reads_sample_and_parses_table_only_once(tmp_path, monkeypatch):
    path = tmp_path / 'single-pass.csv'
    path.write_text('a,b\n1,2\n3,4\n', encoding='utf-8')
    sample_reads = []
    parse_calls = []
    original_read_sample = data_loader._read_text_sample
    original_read_csv = data_loader.pd.read_csv

    def counting_read_sample(filepath, sample_size=256 * 1024):
        sample_reads.append(filepath)
        return original_read_sample(filepath, sample_size)

    def counting_read_csv(*args, **kwargs):
        parse_calls.append(kwargs)
        return original_read_csv(*args, **kwargs)

    monkeypatch.setattr(
        data_loader, '_read_text_sample', counting_read_sample
    )
    monkeypatch.setattr(data_loader.pd, 'read_csv', counting_read_csv)

    frame = read_numeric_table(path)

    assert frame.shape == (2, 2)
    assert len(sample_reads) == 1
    assert len(parse_calls) == 1


def test_text_loader_rejects_row_limit_before_parsing(tmp_path, monkeypatch):
    monkeypatch.setattr('radar_tool.input_limits.MAX_ROWS', 2)
    path = tmp_path / 'dense.csv'
    path.write_text('1,2\n3,4\n5,6\n', encoding='utf-8')

    with pytest.raises(ValueError, match=r'行数超限.*允许 0~2'):
        read_numeric_table(path)


def test_text_loader_rejects_column_limit_before_parsing(tmp_path, monkeypatch):
    monkeypatch.setattr('radar_tool.input_limits.MAX_COLUMNS', 2)
    path = tmp_path / 'wide.csv'
    path.write_text('1,2,3\n', encoding='utf-8')

    with pytest.raises(ValueError, match=r'列数超限.*允许 0~2'):
        read_numeric_table(path)


def test_excel_loader_rejects_sheet_and_extracted_size_limits(tmp_path, monkeypatch):
    path = tmp_path / 'many_sheets.xlsx'
    with pd.ExcelWriter(path) as writer:
        for index in range(3):
            pd.DataFrame([[1, 2]]).to_excel(
                writer, sheet_name=f'sheet{index}', index=False)

    monkeypatch.setattr('radar_tool.input_limits.MAX_EXCEL_SHEETS', 2)
    with pytest.raises(ValueError, match=r'工作表数量超限.*允许 0~2'):
        read_numeric_table(path)

    monkeypatch.setattr('radar_tool.input_limits.MAX_EXTRACTED_SIZE', 1)
    with pytest.raises(ValueError, match=r'解压总大小超限.*允许 0~1'):
        read_numeric_table(path)


def test_calibration_loader_rejects_sample_limit(tmp_path, monkeypatch):
    path = tmp_path / 'samples.csv'
    path.write_text('1,2,1.1,2.1\n2,3,2.1,3.1\n', encoding='utf-8')
    monkeypatch.setattr('radar_tool.input_limits.MAX_SAMPLES', 1)

    with pytest.raises(ValueError, match=r'样本数超限.*允许 0~1'):
        load_calibration_data(str(path))
