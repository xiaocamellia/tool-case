"""Strict converters for engineering data formats used by the toolbox."""

from __future__ import annotations

import math
import os
import struct
import tempfile
import threading
import time
from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Tuple

from .errors import ExportError, ValidationError
from .input_limits import (
    InputResourceError,
    MAX_BIN_FRAMES,
    MAX_FILE_SIZE,
    ensure_file_size,
    validate_sample_count,
)


FRAME_SIZE = 270
FRAME_HEAD = bytes((0x14, 0x6F))
COMMAND_INJECTION = bytes((0x44, 0x44))
TX_FLAG = 0x55
RX_FLAG = 0xAA
INITIAL_TEMPERATURE = 0x80
CHANNELS_PER_BLOCK = 64
MAX_BLOCKS = MAX_BIN_FRAMES


class FormatConversionError(ValidationError):
    """Raised when source data does not match the selected wire format."""


class FormatConversionCancelled(FormatConversionError):
    """Raised when a user cancels an active conversion parse."""


class FormatConversionTimeout(FormatConversionError):
    """Raised when a conversion parse exceeds its allowed duration."""


def _check_parse_control(
    cancel_event: Optional[threading.Event],
    deadline: Optional[float],
    timeout_seconds: Optional[float] = None,
) -> None:
    if deadline is not None and time.monotonic() >= deadline:
        allowed = (
            f'允许 0~{timeout_seconds:g} 秒'
            if timeout_seconds is not None
            else '已超过允许的解析时限'
        )
        raise FormatConversionTimeout(f'解析超时：{allowed}')
    if cancel_event is not None and cancel_event.is_set():
        raise FormatConversionCancelled('解析已取消')


@dataclass(frozen=True)
class FrameSummary:
    """Human-readable metadata for one encoded or decoded frame."""

    index: int
    mode: str
    description: str
    temperature: int
    checksum: int


@dataclass(frozen=True)
class TrConversionResult:
    """Result shared by conversion, preview, and protocol validation."""

    rows: Tuple[Tuple[int, float, float], ...]
    data: bytes
    frames: Tuple[FrameSummary, ...]

    @property
    def block_count(self) -> int:
        return len(self.frames)


def _decode_text(raw: bytes) -> str:
    for encoding in ('utf-8-sig', 'gb18030'):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise FormatConversionError('文本编码无法识别，请使用 UTF-8 或 GB18030 编码')


def _parse_number(token: str, line_number: int, column_name: str) -> float:
    try:
        value = float(token)
    except ValueError as exc:
        raise FormatConversionError(
            f'第 {line_number} 行的{column_name}不是数字：{token}'
        ) from exc
    if not math.isfinite(value):
        raise FormatConversionError(f'第 {line_number} 行的{column_name}必须是有限数值')
    return value


def parse_tr_amplitude_phase_text(
    text: str,
    cancel_event: Optional[threading.Event] = None,
    deadline: Optional[float] = None,
    timeout_seconds: Optional[float] = None,
) -> Tuple[Tuple[int, float, float], ...]:
    """Parse channel/amplitude/phase rows and enforce 64-channel blocks."""

    parsed: List[Tuple[int, float, float]] = []
    source_lines: List[int] = []
    for line_number, raw_line in enumerate(text.splitlines(), 1):
        _check_parse_control(cancel_event, deadline, timeout_seconds)
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 3:
            raise FormatConversionError(
                f'第 {line_number} 行格式错误：必须是“通道 幅度 相位”三列'
            )
        channel_value = _parse_number(parts[0], line_number, '通道号')
        amplitude = _parse_number(parts[1], line_number, '幅度')
        phase = _parse_number(parts[2], line_number, '相位')
        if not channel_value.is_integer():
            raise FormatConversionError(f'第 {line_number} 行的通道号必须是整数')
        parsed.append((int(channel_value), amplitude, phase))
        source_lines.append(line_number)

    if not parsed:
        raise FormatConversionError('输入文件没有有效数据行')
    try:
        validate_sample_count(len(parsed))
    except InputResourceError as exc:
        raise FormatConversionError(str(exc)) from exc
    if len(parsed) % CHANNELS_PER_BLOCK:
        raise FormatConversionError(
            f'有效数据共 {len(parsed)} 行，不是 {CHANNELS_PER_BLOCK} 的整数倍，存在通道缺失'
        )
    block_count = len(parsed) // CHANNELS_PER_BLOCK
    if block_count > MAX_BLOCKS:
        raise FormatConversionError(
            f'数据包含 {block_count} 个块，超过协议上限 {MAX_BLOCKS} 个块'
        )

    for block_index in range(block_count):
        start = block_index * CHANNELS_PER_BLOCK
        for offset in range(CHANNELS_PER_BLOCK):
            channel = parsed[start + offset][0]
            expected = offset + 1
            if channel != expected:
                line_number = source_lines[start + offset]
                raise FormatConversionError(
                    f'第 {block_index + 1} 块通道序列错误：第 {line_number} 行应为通道 '
                    f'{expected}，实际为 {channel}'
                )
    return tuple(parsed)


def load_tr_amplitude_phase_txt(
    filepath: str,
    cancel_event: Optional[threading.Event] = None,
    deadline: Optional[float] = None,
    timeout_seconds: Optional[float] = None,
) -> Tuple[Tuple[int, float, float], ...]:
    try:
        ensure_file_size(filepath, MAX_FILE_SIZE, label='幅相文本文件')
        _check_parse_control(cancel_event, deadline, timeout_seconds)
        with open(filepath, 'rb') as source:
            raw = source.read()
    except InputResourceError as exc:
        raise FormatConversionError(str(exc)) from exc
    except OSError as exc:
        raise FormatConversionError('无法读取输入文件（系统读取失败）') from exc
    _check_parse_control(cancel_event, deadline, timeout_seconds)
    return parse_tr_amplitude_phase_text(
        _decode_text(raw), cancel_event, deadline, timeout_seconds)


def _frame_parameters(block_index: int) -> Tuple[int, int, str, str]:
    packet_number = block_index + 1
    if block_index == 0:
        return TX_FLAG, INITIAL_TEMPERATURE, 'TX', '发射初始包'
    if block_index == 1:
        return RX_FLAG, INITIAL_TEMPERATURE, 'RX', '接收初始包'
    if 2 <= block_index <= 12:
        temperature = block_index - 2
        return TX_FLAG, temperature, 'TX', f'发射温度包 {temperature}'
    if 13 <= block_index <= 23:
        temperature = block_index - 13
        return RX_FLAG, temperature, 'RX', f'接收温度包 {temperature}'
    raise FormatConversionError(f'包序号 {packet_number} 超出协议范围 1~{MAX_BLOCKS}')


def _matlab_round(value: float) -> int:
    """Match MATLAB round(): half values are rounded away from zero."""

    if value >= 0:
        return int(math.floor(value + 0.5))
    return int(math.ceil(value - 0.5))


def _quantize_int16(value: float, block: int, channel: int, field: str) -> int:
    raw = _matlab_round(value / 0.1)
    if not -32768 <= raw <= 32767:
        raise FormatConversionError(
            f'第 {block} 块通道 {channel} 的{field} {value:g} 超出 int16/0.1 可表示范围'
        )
    return raw


def encode_tr_amplitude_phase(
    rows: Sequence[Tuple[int, float, float]],
) -> TrConversionResult:
    """Encode validated amplitude/phase rows into 270-byte TR frames."""

    # Reuse the public parser's structural validation for callers supplying rows.
    normalized_lines = '\n'.join(
        f'{channel} {amplitude!r} {phase!r}' for channel, amplitude, phase in rows
    )
    normalized_rows = parse_tr_amplitude_phase_text(normalized_lines)

    output = bytearray()
    summaries: List[FrameSummary] = []
    block_count = len(normalized_rows) // CHANNELS_PER_BLOCK
    for block_index in range(block_count):
        flag, temperature, mode, description = _frame_parameters(block_index)
        frame = bytearray()
        frame.extend(FRAME_HEAD)
        frame.extend(COMMAND_INJECTION)
        frame.extend((flag, temperature))
        start = block_index * CHANNELS_PER_BLOCK
        for channel, amplitude, phase in normalized_rows[start:start + CHANNELS_PER_BLOCK]:
            amplitude_raw = _quantize_int16(
                amplitude, block_index + 1, channel, '幅度')
            phase_raw = _quantize_int16(phase, block_index + 1, channel, '相位')
            frame.extend(struct.pack('>hh', amplitude_raw, phase_raw))
        frame.extend((0x00, 0x00, 0x00, 0x00, 0x00, 0x00, block_index + 1))
        if len(frame) != FRAME_SIZE - 1:
            raise AssertionError(f'内部组帧长度错误：{len(frame)}')
        checksum = sum(frame) % 256
        frame.append(checksum)
        output.extend(frame)
        summaries.append(FrameSummary(
            index=block_index + 1,
            mode=mode,
            description=description,
            temperature=temperature,
            checksum=checksum,
        ))

    return TrConversionResult(normalized_rows, bytes(output), tuple(summaries))


def build_tr_amplitude_phase_bin(
    filepath: str,
    cancel_event: Optional[threading.Event] = None,
    deadline: Optional[float] = None,
    timeout_seconds: Optional[float] = None,
) -> TrConversionResult:
    rows = load_tr_amplitude_phase_txt(
        filepath, cancel_event, deadline, timeout_seconds)
    return encode_tr_amplitude_phase(rows)


def decode_tr_amplitude_phase(
    data: bytes,
    cancel_event: Optional[threading.Event] = None,
    deadline: Optional[float] = None,
    timeout_seconds: Optional[float] = None,
) -> TrConversionResult:
    """Strictly validate and decode one merged TR amplitude/phase BIN stream."""

    _check_parse_control(cancel_event, deadline, timeout_seconds)
    if not data:
        raise FormatConversionError('BIN 文件为空')
    if len(data) % FRAME_SIZE:
        raise FormatConversionError(
            f'BIN 文件共 {len(data)} 字节，不是帧长 {FRAME_SIZE} 的整数倍'
        )
    block_count = len(data) // FRAME_SIZE
    if block_count > MAX_BLOCKS:
        raise FormatConversionError(
            f'BIN 文件包含 {block_count} 帧，超过协议上限 {MAX_BLOCKS} 帧'
        )

    rows: List[Tuple[int, float, float]] = []
    summaries: List[FrameSummary] = []
    for block_index in range(block_count):
        _check_parse_control(cancel_event, deadline, timeout_seconds)
        frame = data[block_index * FRAME_SIZE:(block_index + 1) * FRAME_SIZE]
        frame_number = block_index + 1
        expected_flag, expected_temp, mode, description = _frame_parameters(block_index)
        if frame[:2] != FRAME_HEAD:
            raise FormatConversionError(f'第 {frame_number} 帧帧头错误')
        if frame[2:4] != COMMAND_INJECTION:
            raise FormatConversionError(f'第 {frame_number} 帧命令字错误')
        if frame[4] != expected_flag:
            raise FormatConversionError(
                f'第 {frame_number} 帧收发标志错误：应为 0x{expected_flag:02X}'
            )
        if frame[5] != expected_temp:
            raise FormatConversionError(
                f'第 {frame_number} 帧温度字节错误：应为 0x{expected_temp:02X}'
            )
        if frame[262] != 0 or any(frame[263:268]):
            raise FormatConversionError(f'第 {frame_number} 帧版本号或保留字节非零')
        if frame[268] != frame_number:
            raise FormatConversionError(
                f'第 {frame_number} 帧包计数错误：实际为 {frame[268]}'
            )
        checksum = sum(frame[:269]) % 256
        if frame[269] != checksum:
            raise FormatConversionError(
                f'第 {frame_number} 帧累加和错误：应为 0x{checksum:02X}，'
                f'实际为 0x{frame[269]:02X}'
            )

        offset = 6
        for channel in range(1, CHANNELS_PER_BLOCK + 1):
            _check_parse_control(cancel_event, deadline, timeout_seconds)
            amplitude_raw, phase_raw = struct.unpack('>hh', frame[offset:offset + 4])
            rows.append((channel, amplitude_raw * 0.1, phase_raw * 0.1))
            offset += 4
        summaries.append(FrameSummary(
            index=frame_number,
            mode=mode,
            description=description,
            temperature=expected_temp,
            checksum=checksum,
        ))
    return TrConversionResult(tuple(rows), bytes(data), tuple(summaries))


def load_tr_amplitude_phase_bin(
    filepath: str,
    cancel_event: Optional[threading.Event] = None,
    deadline: Optional[float] = None,
    timeout_seconds: Optional[float] = None,
) -> TrConversionResult:
    try:
        ensure_file_size(filepath, MAX_FILE_SIZE, label='BIN 文件')
        ensure_file_size(
            filepath,
            MAX_BIN_FRAMES * FRAME_SIZE,
            label='BIN 文件',
        )
        _check_parse_control(cancel_event, deadline, timeout_seconds)
        with open(filepath, 'rb') as source:
            data = source.read()
    except InputResourceError as exc:
        raise FormatConversionError(str(exc)) from exc
    except OSError as exc:
        raise FormatConversionError('无法读取 BIN 文件（系统读取失败）') from exc
    _check_parse_control(cancel_event, deadline, timeout_seconds)
    return decode_tr_amplitude_phase(
        data, cancel_event, deadline, timeout_seconds)


def rows_to_tr_text(rows: Iterable[Tuple[int, float, float]]) -> str:
    return ''.join(
        f'{channel}\t{amplitude:.1f}\t{phase:.1f}\n'
        for channel, amplitude, phase in rows
    )


def write_bytes_atomic(filepath: str, data: bytes) -> None:
    directory = os.path.dirname(os.path.abspath(filepath))
    os.makedirs(directory, exist_ok=True)
    temporary_path = ''
    try:
        with tempfile.NamedTemporaryFile(dir=directory, delete=False) as temporary:
            temporary_path = temporary.name
            temporary.write(data)
        os.replace(temporary_path, filepath)
    except OSError as exc:
        if temporary_path and os.path.exists(temporary_path):
            try:
                os.unlink(temporary_path)
            except OSError:
                pass
        raise ExportError('无法写入输出文件，请检查目录权限和磁盘空间') from exc


def write_text_atomic(filepath: str, text: str) -> None:
    write_bytes_atomic(filepath, text.encode('utf-8-sig'))
