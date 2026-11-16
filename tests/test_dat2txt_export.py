"""dat -> txt 导出核心（dat2txt_core）回归测试。

用合成的定长 .dat（真实单帧长度 + 合法 BCD 时间）跑完整导出管线，
校验 GBK/CRLF/行尾空格/列名文件/时间过滤/采样间隔/残帧告警等格式契约。
"""

from __future__ import annotations

import os
from datetime import datetime

import pytest

from radar_tool.dat2txt_core import (
    DATASETS,
    ExportRequest,
    bcd_bytes_to_datetime,
    column_file_path,
    config_root,
    default_output_path,
    export_dat,
    find_dataset,
    frame_count,
    load_dataset_specs,
    read_frame_time,
    summarize,
)

pytestmark = pytest.mark.skipif(
    not (config_root() / 'receive').is_dir(),
    reason='Config/receive 免远程同步，源码树缺失时跳过（本地提供字段定义后执行）',
)

DATASET = find_dataset(0x3014)
assert DATASET is not None, '内置数据类型 0x3014 必须存在'


def _bcd(value: int) -> int:
    return ((value // 10) << 4) | (value % 10)


def build_frame(second: int, payload: bytes) -> bytes:
    """一帧 = 6 字节 BCD 时间 + 载荷，载荷不足自动补零。"""
    stamp = bytes(
        [
            _bcd(26),
            _bcd(10),
            _bcd(22),
            _bcd(11),
            _bcd(57),
            _bcd(second),
        ]
    )
    payload = payload.ljust(DATASET.frame_data_length, b'\x00')
    return stamp + payload[: DATASET.frame_data_length]


def write_dat(path, frames, trailing=b''):
    with open(path, 'wb') as handle:
        for frame in frames:
            handle.write(frame)
        handle.write(trailing)
    return str(path)


def export_all(dat_path, txt_path, **kwargs):
    request = ExportRequest(
        dat_path=str(dat_path),
        txt_path=str(txt_path),
        code_id=DATASET.code_id,
        start_time=kwargs.pop('start_time', datetime(2000, 1, 1)),
        end_time=kwargs.pop('end_time', datetime(2099, 12, 31, 23, 59, 59)),
        **kwargs,
    )
    return export_dat(request)


def read_gbk_lines(path):
    with open(path, 'rb') as handle:
        text = handle.read().decode('gbk')
    return [line for line in text.split('\r\n') if line]


def test_specs_load_from_bundled_config():
    root = config_root()
    assert root.name == 'Config'
    assert (root / 'receive').is_dir()

    specs = load_dataset_specs(DATASET)
    assert len(specs) > 100
    assert all(spec.name for spec in specs)
    assert [spec.index for spec in specs] == list(range(len(specs)))


def test_export_writes_gbk_crlf_txt_and_column_file(tmp_path):
    dat_path = write_dat(tmp_path / 'sample.dat', [build_frame(s, b'') for s in (47, 48, 49)])
    txt_path = str(tmp_path / 'out.txt')

    result = export_all(dat_path, txt_path)

    assert result.written_lines == 3
    assert result.processed_frames == 3
    assert result.total_frames == 3
    assert result.residual_bytes == 0
    assert result.column_count == len(load_dataset_specs(DATASET))

    with open(txt_path, 'rb') as handle:
        raw = handle.read()
    assert b'\r\n' in raw
    assert raw.replace(b'\r\n', b'').find(b'\n') == -1

    body = read_gbk_lines(txt_path)
    assert len(body) == 3
    assert body[0].startswith('2026 10 22 11 57 47 ')
    assert body[1].startswith('2026 10 22 11 57 48 ')
    assert body[2].startswith('2026 10 22 11 57 49 ')
    for line in body:
        assert line.endswith(' '), '行尾必须带一个空格（与成熟软件一致）'

    column_path = column_file_path(txt_path)
    assert os.path.isfile(column_path)
    column_lines = read_gbk_lines(column_path)
    assert len(column_lines) == 6 + result.column_count
    assert column_lines[:6] == [
        '年--1', '月--2', '日--3', '时--4', '分--5', '秒--6',
    ]
    specs = load_dataset_specs(DATASET)
    assert column_lines[6] == '%s--7' % (specs[0].name,)
    assert column_lines[-1] == '%s--%d' % (
        specs[-1].name,
        6 + result.column_count,
    )

    summary = summarize(result)
    assert '共处理 3 帧数据' in summary


def test_export_time_filter_and_interval(tmp_path):
    frames = [build_frame(second, b'') for second in (47, 48, 49, 50)]
    dat_path = write_dat(tmp_path / 'sample.dat', frames)

    # 采样间隔 1 = 每 2 帧取 1 帧 → 保留第 0、2 帧
    result = export_all(
        dat_path,
        str(tmp_path / 'interval.txt'),
        interval=1,
    )
    assert result.written_lines == 2

    # 时间闭区间过滤：只保留 11:57:49 ~ 11:57:50
    result = export_all(
        dat_path,
        str(tmp_path / 'window.txt'),
        start_time=datetime(2026, 10, 22, 11, 57, 49),
        end_time=datetime(2026, 10, 22, 11, 57, 50),
    )
    assert result.written_lines == 2
    lines = read_gbk_lines(result.txt_path)
    assert lines[0].startswith('2026 10 22 11 57 49 ')
    assert lines[1].startswith('2026 10 22 11 57 50 ')


def test_export_reports_residual_trailing_bytes(tmp_path):
    dat_path = write_dat(
        tmp_path / 'sample.dat',
        [build_frame(47, b''), build_frame(48, b'')],
        trailing=b'\x00' * 5,
    )

    result = export_all(dat_path, str(tmp_path / 'out.txt'))

    assert result.written_lines == 2
    assert result.residual_bytes == 5
    assert any('残帧' in warning and '5' in warning for warning in result.warnings)


def test_export_column_subset(tmp_path):
    dat_path = write_dat(tmp_path / 'sample.dat', [build_frame(47, b'')])

    result = export_all(
        dat_path,
        str(tmp_path / 'subset.txt'),
        column_indices=[0, 5],
    )

    assert result.column_count == 2
    column_lines = read_gbk_lines(result.column_path)
    specs = load_dataset_specs(DATASET)
    assert len(column_lines) == 8
    assert column_lines[6] == '%s--7' % (specs[0].name,)
    assert column_lines[7] == '%s--8' % (specs[5].name,)


def test_export_rejects_out_of_range_column(tmp_path):
    dat_path = write_dat(tmp_path / 'sample.dat', [build_frame(47, b'')])
    with pytest.raises(Exception, match='越界'):
        export_all(dat_path, str(tmp_path / 'bad.txt'), column_indices=[10 ** 6])


def test_frame_helpers_and_bcd_roundtrip(tmp_path):
    dat_path = write_dat(
        tmp_path / 'sample.dat',
        [build_frame(47, b''), build_frame(48, b'')],
        trailing=b'\x01\x02',
    )

    total, remainder = frame_count(dat_path, DATASET.frame_length)
    assert (total, remainder) == (2, 2)

    first = read_frame_time(dat_path, DATASET.frame_length, 0)
    last = read_frame_time(dat_path, DATASET.frame_length, 1)
    assert first == datetime(2026, 10, 22, 11, 57, 47)
    assert last == datetime(2026, 10, 22, 11, 57, 48)
    assert bcd_bytes_to_datetime(build_frame(49, b'')[:6]) == datetime(
        2026, 10, 22, 11, 57, 49
    )

    default = default_output_path(DATASET, dat_path)
    assert os.path.dirname(default) == os.path.dirname(os.path.abspath(dat_path))
    assert DATASET.key in os.path.basename(default)
    assert default.endswith('_export.txt')


def test_every_registered_dataset_has_definition_csv():
    for dataset in DATASETS:
        specs = load_dataset_specs(dataset)
        assert specs, dataset.key
        assert dataset.frame_length > dataset.frame_data_length >= 6
