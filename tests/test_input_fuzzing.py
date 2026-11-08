"""Deterministic malformed-input and resource-boundary regression tests."""

from __future__ import annotations

import random

import pytest

from radar_tool.data_loader import read_numeric_table
from radar_tool.errors import ValidationError
from radar_tool.format_conversion import (
    FRAME_SIZE,
    FormatConversionError,
    decode_tr_amplitude_phase,
)


def test_large_text_file_is_rejected_before_parsing(tmp_path, monkeypatch):
    path = tmp_path / 'large.csv'
    path.write_text('1,2\n3,4\n', encoding='utf-8')
    monkeypatch.setattr('radar_tool.input_limits.MAX_FILE_SIZE', 4)

    with pytest.raises(ValidationError, match='大小超限'):
        read_numeric_table(path)


def test_corrupt_xlsx_is_rejected_as_structural_error(tmp_path):
    path = tmp_path / 'broken.xlsx'
    path.write_bytes(b'PK\x03\x04not-a-real-workbook')

    with pytest.raises(ValidationError, match='结构损坏'):
        read_numeric_table(path)


@pytest.mark.parametrize('payload', [
    b'',
    b'\x00' * (FRAME_SIZE - 1),
    b'\xff' * FRAME_SIZE,
    b'\x00' * (FRAME_SIZE * 25),
])
def test_bin_decoder_rejects_known_boundary_payloads(payload):
    with pytest.raises(FormatConversionError):
        decode_tr_amplitude_phase(payload)


def test_bin_decoder_contains_deterministic_malformed_fuzz_corpus():
    random_source = random.Random(20261105)

    for _ in range(256):
        payload = bytes(
            random_source.randrange(256) for _ in range(FRAME_SIZE)
        )
        try:
            decode_tr_amplitude_phase(payload)
        except FormatConversionError:
            continue
        else:
            raise AssertionError('随机损坏的 BIN 帧不应通过严格解析')
