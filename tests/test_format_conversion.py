"""Regression tests for the TR amplitude/phase wire format."""

from __future__ import annotations

import os
import struct
import tempfile
import unittest
from unittest.mock import patch

from radar_tool.format_conversion import (
    FRAME_SIZE,
    FormatConversionError,
    load_tr_amplitude_phase_bin,
    build_tr_amplitude_phase_bin,
    decode_tr_amplitude_phase,
    encode_tr_amplitude_phase,
    load_tr_amplitude_phase_txt,
    parse_tr_amplitude_phase_text,
    rows_to_tr_text,
)


def make_rows(block_count=1, amplitude=0.0, phase=0.0):
    return tuple(
        (channel, amplitude, phase)
        for _block in range(block_count)
        for channel in range(1, 65)
    )


class TrAmplitudePhaseProtocolTests(unittest.TestCase):
    def test_single_frame_matches_protocol_layout_and_matlab_rounding(self):
        rows = list(make_rows())
        rows[0] = (1, 1.25, -1.25)
        result = encode_tr_amplitude_phase(rows)

        self.assertEqual(len(result.data), 270)
        self.assertEqual(result.data[:6], bytes((0x14, 0x6F, 0x44, 0x44, 0x55, 0x80)))
        self.assertEqual(result.data[6:10], struct.pack('>hh', 13, -13))
        self.assertEqual(result.data[262:269], bytes((0, 0, 0, 0, 0, 0, 1)))
        self.assertEqual(result.data[269], sum(result.data[:269]) % 256)
        self.assertEqual(result.frames[0].description, '发射初始包')

    def test_all_24_packet_assignments_match_matlab_source(self):
        result = encode_tr_amplitude_phase(make_rows(24))

        self.assertEqual(len(result.data), 24 * 270)
        self.assertEqual(
            [(item.index, item.mode, item.temperature) for item in result.frames],
            [(1, 'TX', 0x80), (2, 'RX', 0x80)]
            + [(index, 'TX', index - 3) for index in range(3, 14)]
            + [(index, 'RX', index - 14) for index in range(14, 25)],
        )

    def test_round_trip_preserves_quantized_values(self):
        rows = tuple(
            (channel, channel * 0.13 - 5.0, 180.0 - channel * 0.27)
            for channel in range(1, 65)
        )
        encoded = encode_tr_amplitude_phase(rows)
        decoded = decode_tr_amplitude_phase(encoded.data)

        self.assertEqual(decoded.frames, encoded.frames)
        self.assertEqual(decoded.rows[0], (1, -4.9, 179.70000000000002))
        self.assertEqual(len(rows_to_tr_text(decoded.rows).splitlines()), 64)

    def test_parser_accepts_blank_lines_and_gb18030_files(self):
        text = '\n' + '\n'.join(
            f'{channel}\u30000.1\u3000-0.2' for channel in range(1, 65)
        ) + '\n'
        with tempfile.TemporaryDirectory() as directory:
            filepath = os.path.join(directory, '幅相.txt')
            with open(filepath, 'wb') as output:
                output.write(text.encode('gb18030'))
            rows = load_tr_amplitude_phase_txt(filepath)

        self.assertEqual(len(rows), 64)
        self.assertEqual(rows[-1], (64, 0.1, -0.2))

    def test_parser_rejects_missing_and_out_of_order_channels(self):
        missing = '\n'.join(f'{channel} 0 0' for channel in range(1, 64))
        with self.assertRaisesRegex(FormatConversionError, '不是 64 的整数倍'):
            parse_tr_amplitude_phase_text(missing)

        rows = [f'{channel} 0 0' for channel in range(1, 65)]
        rows[10] = '12 0 0'
        with self.assertRaisesRegex(FormatConversionError, '应为通道 11'):
            parse_tr_amplitude_phase_text('\n'.join(rows))

    def test_parser_rejects_bad_columns_nonfinite_values_and_too_many_blocks(self):
        with self.assertRaisesRegex(FormatConversionError, '三列'):
            parse_tr_amplitude_phase_text('1 2')
        with self.assertRaisesRegex(FormatConversionError, '有限数值'):
            parse_tr_amplitude_phase_text(
                '\n'.join(f'{channel} nan 0' for channel in range(1, 65)))
        with self.assertRaisesRegex(FormatConversionError, '超过协议上限'):
            encode_tr_amplitude_phase(make_rows(25))

    def test_encoder_rejects_values_outside_wire_range(self):
        with self.assertRaisesRegex(FormatConversionError, '超出 int16'):
            encode_tr_amplitude_phase(make_rows(amplitude=4000.0))

    def test_decoder_rejects_length_header_and_checksum_corruption(self):
        encoded = encode_tr_amplitude_phase(make_rows()).data
        with self.assertRaisesRegex(FormatConversionError, '不是帧长'):
            decode_tr_amplitude_phase(encoded[:-1])

        bad_header = bytearray(encoded)
        bad_header[0] = 0
        with self.assertRaisesRegex(FormatConversionError, '帧头错误'):
            decode_tr_amplitude_phase(bytes(bad_header))

        bad_checksum = bytearray(encoded)
        bad_checksum[-1] ^= 0x01
        with self.assertRaisesRegex(FormatConversionError, '累加和错误'):
            decode_tr_amplitude_phase(bytes(bad_checksum))

    def test_file_loaders_reject_size_and_frame_limits_without_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            text_path = os.path.join(directory, 'oversized.txt')
            with open(text_path, 'wb') as output:
                output.write(b'0 0 0\n' * 20)
            with patch('radar_tool.format_conversion.MAX_FILE_SIZE', 10):
                with self.assertRaisesRegex(
                    FormatConversionError, r'大小超限.*允许 0~10'):
                    load_tr_amplitude_phase_txt(text_path)

            bin_path = os.path.join(directory, 'oversized.bin')
            with open(bin_path, 'wb') as output:
                output.write(bytes(FRAME_SIZE * 25))
            with self.assertRaisesRegex(
                FormatConversionError,
                rf'大小超限.*允许 0~{FRAME_SIZE * 24}',
            ):
                load_tr_amplitude_phase_bin(bin_path)

    def test_file_builder_returns_no_side_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            filepath = os.path.join(directory, 'source.txt')
            with open(filepath, 'w', encoding='utf-8') as output:
                output.write('\n'.join(f'{channel} 0 0' for channel in range(1, 65)))
            result = build_tr_amplitude_phase_bin(filepath)

            self.assertEqual(os.listdir(directory), ['source.txt'])
            self.assertEqual(len(result.data), 270)


if __name__ == '__main__':
    unittest.main()
