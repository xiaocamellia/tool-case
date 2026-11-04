import numpy as np
import pytest

from radar_tool.data_loader import DataLoader, read_numeric_table


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


def test_loader_rejects_file_without_numeric_data(tmp_path):
    path = tmp_path / 'wrong.txt'
    path.write_text('this is a column name file\nnot measurement data\n', encoding='utf-8')

    with pytest.raises(ValueError, match='没有识别到数值数据'):
        read_numeric_table(path)
