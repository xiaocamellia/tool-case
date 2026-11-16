"""dat -> txt export pipeline.

Structure mirrors ``SQLiteControl.ExportDatFrameToTxt``:

* one reader walks the file in ``frameByteLength`` steps,
* every selected frame is decoded (time filter + sampling interval),
* lines are written in frame order, GBK encoded, ``\\r\\n`` terminated, each
  value followed by a single space (so every line ends with a space),
* a companion ``...列名.txt`` lists the exported column numbers.

The original uses one reader thread, ``ProcessorCount`` parser tasks and one
writer task.  The result is purely sequential, so this implementation decodes
inline in the calling thread (the GUI runs it in a worker thread) which keeps
frame order and the byte layout identical.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional, Sequence

from .datasets import Dataset, find_dataset, load_dataset_specs
from .decoder import FrameDecoder

ENCODING = "gbk"
NEWLINE = "\r\n"
#: ``StreamWriter`` buffer size used by the original (kept for reference only).
WRITER_BUFFER = 65536
#: How many frames are read from disk at once.
READ_BLOCK_FRAMES = 2048
#: Flush the text buffer once it holds this many characters.
FLUSH_CHARS = 1 << 18

COLUMN_HEADER = ("年", "月", "日", "时", "分", "秒")


def header_names() -> tuple[str, ...]:
    """Names of the six fixed leading columns (``年--1`` ... ``秒--6``)."""
    return COLUMN_HEADER


class ExportError(RuntimeError):
    """Raised when the export cannot be completed."""


class ExportCancelled(ExportError):
    """Raised when the caller cancelled the export."""


@dataclass
class ExportRequest:
    """Everything needed for one export run."""

    dat_path: str
    txt_path: str
    code_id: int
    start_time: datetime
    end_time: datetime
    interval: int = 0
    #: Zero based CSV record indices to export; ``None`` exports every column.
    column_indices: Optional[Sequence[int]] = None
    #: Debug helper: stop after this many frames (``None`` = whole file).
    max_frames: Optional[int] = None


@dataclass
class ExportResult:
    """Statistics of a finished export."""

    dat_path: str
    txt_path: str
    column_path: str
    total_frames: int = 0
    processed_frames: int = 0
    written_lines: int = 0
    residual_bytes: int = 0
    elapsed_ms: int = 0
    column_count: int = 0
    cancelled: bool = False
    warnings: list[str] = field(default_factory=list)

    @property
    def frames_per_second(self) -> float:
        if self.elapsed_ms <= 0:
            return 0.0
        return self.processed_frames * 1000.0 / self.elapsed_ms


def bcd_bytes_to_datetime(raw: bytes) -> datetime:
    """Port of ``Bcd6BytesToDateTime`` (raises ``ValueError`` when invalid)."""
    if len(raw) != 6:
        raise ValueError("数组长度必须为6")
    year = (raw[0] >> 4) * 10 + (raw[0] & 0x0F)
    month = (raw[1] >> 4) * 10 + (raw[1] & 0x0F)
    day = (raw[2] >> 4) * 10 + (raw[2] & 0x0F)
    hour = (raw[3] >> 4) * 10 + (raw[3] & 0x0F)
    minute = (raw[4] >> 4) * 10 + (raw[4] & 0x0F)
    second = (raw[5] >> 4) * 10 + (raw[5] & 0x0F)
    return datetime(2000 + year, month, day, hour, minute, second)


def read_frame_time(
    dat_path: str, frame_length: int, frame_index: int
) -> Optional[datetime]:
    """Read the BCD timestamp of one frame without loading the whole file."""
    try:
        with open(dat_path, "rb") as handle:
            handle.seek(frame_index * frame_length)
            raw = handle.read(6)
        if len(raw) < 6:
            return None
        return bcd_bytes_to_datetime(raw)
    except (OSError, ValueError):
        return None


def frame_count(dat_path: str, frame_length: int) -> tuple[int, int]:
    """Return ``(total_frames, bytes_per_frame_remainder)``."""
    size = os.path.getsize(dat_path)
    return size // frame_length, size % frame_length


def default_output_path(dataset: Dataset, dat_path: str) -> str:
    """``{表名}_{yyyyMMddHHmmss}_export.txt`` next to the dat file."""
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    directory = os.path.dirname(os.path.abspath(dat_path)) or "."
    return os.path.join(directory, "%s_%s_export.txt" % (dataset.key, stamp))


def column_file_path(txt_path: str) -> str:
    """``txtPath.Replace(".txt", "") + "列名.txt"`` (all occurrences)."""
    return txt_path.replace(".txt", "") + "列名.txt"


def write_column_file(path: str, names: Sequence[str]) -> None:
    """Write ``年--1 ... 秒--6`` plus the exported field names."""
    lines = ["%s--%d" % (name, index + 1) for index, name in enumerate(COLUMN_HEADER)]
    for offset, name in enumerate(names):
        lines.append("%s--%d" % (name, len(COLUMN_HEADER) + offset + 1))
    with open(path, "wb") as handle:
        handle.write(NEWLINE.join(lines).encode(ENCODING) + NEWLINE.encode(ENCODING))


def _progress_text(processed: int, total: int) -> str:
    percent = round(processed * 100.0 / total, 2) if total else 0.0
    return "当前进度：%d/%d  %s%%" % (processed, total, _format_percent(percent))


def _format_percent(value: float) -> str:
    """Format like ``double.ToString()`` (G15) for the progress label."""
    text = repr(float(value))
    if text.endswith(".0"):
        text = text[:-2]
    return text


def export_dat(
    request: ExportRequest,
    progress: Optional[Callable[[str], None]] = None,
    cancel: Optional[Callable[[], bool]] = None,
) -> ExportResult:
    """Run one export; raises :class:`ExportError` on invalid input."""
    dataset = find_dataset(request.code_id)
    if dataset is None:
        raise ExportError("未知的数据类型 codeId=0x%X" % (request.code_id,))
    if not os.path.isfile(request.dat_path):
        raise ExportError("dat源文件不存在！\n%s" % (request.dat_path,))
    if dataset.frame_length <= 0:
        raise ExportError("单帧读取长度必须大于0")

    specs = load_dataset_specs(dataset)
    decoder = FrameDecoder(specs)

    if request.column_indices is None:
        indices = list(range(len(specs)))
    else:
        indices = sorted({int(index) for index in request.column_indices})
        for index in indices:
            if not 0 <= index < len(specs):
                raise ExportError("导出列序号越界：%d" % (index,))
    names = [specs[index].name for index in indices]

    column_path = column_file_path(request.txt_path)
    write_column_file(column_path, names)

    if progress is not None:
        progress("开始加载文件...")

    frame_length = dataset.frame_length
    size = os.path.getsize(request.dat_path)
    # The original reads whole frames and, when the last read cannot be filled,
    # warns about the trailing bytes and drops them (spec §1.2).
    full_frames, residual_bytes = divmod(size, frame_length)
    total_frames = full_frames
    if request.max_frames is not None:
        total_frames = min(total_frames, int(request.max_frames))
    # Residual bytes only exist at the physical end of the file, so a truncated
    # debug export (``max_frames``) must not report them.
    report_residual = residual_bytes if total_frames == full_frames else 0
    interval = max(0, int(request.interval))
    step = interval + 1
    start_time = request.start_time
    end_time = request.end_time

    result = ExportResult(
        dat_path=request.dat_path,
        txt_path=request.txt_path,
        column_path=column_path,
        total_frames=total_frames,
        column_count=len(indices),
    )

    started = time.perf_counter()
    buffer: list[str] = []
    buffer_chars = 0
    last_report = -1

    def flush(handle) -> None:
        nonlocal buffer, buffer_chars
        if buffer:
            handle.write("".join(buffer).encode(ENCODING))
            buffer = []
            buffer_chars = 0

    try:
        with open(request.dat_path, "rb") as source, open(request.txt_path, "wb") as sink:
            index = 0
            while index < total_frames:
                if cancel is not None and cancel():
                    raise ExportCancelled("导出已取消")
                want = min(READ_BLOCK_FRAMES, total_frames - index)
                blob = source.read(want * frame_length)
                complete = len(blob) // frame_length
                leftover = len(blob) - complete * frame_length
                if complete < want:
                    # Short read: only possible when the file shrank while
                    # exporting; mimic the original warning and stop.
                    if leftover:
                        result.residual_bytes = leftover
                        message = (
                            "警告：文件末尾存在 %d 字节残帧，不足单帧长度%d，已忽略"
                            % (leftover, frame_length)
                        )
                        result.warnings.append(message)
                        if progress is not None:
                            progress(message)
                    want = complete

                for offset in range(want):
                    frame_index = index + offset
                    base = offset * frame_length
                    if interval and frame_index % step:
                        continue
                    timestamp = bcd_bytes_to_datetime(
                        blob[base : base + 6]
                    )
                    if timestamp < start_time or timestamp > end_time:
                        continue
                    payload = blob[base + 6 : base + frame_length]
                    cells = decoder.decode_selected(payload, indices)
                    line = (
                        "%04d %02d %02d %02d %02d %02d "
                        % (
                            timestamp.year,
                            timestamp.month,
                            timestamp.day,
                            timestamp.hour,
                            timestamp.minute,
                            timestamp.second,
                        )
                    )
                    line = line + " ".join(cells) + " "
                    buffer.append(line)
                    buffer.append(NEWLINE)
                    buffer_chars += len(line) + 2
                    result.written_lines += 1
                    if buffer_chars >= FLUSH_CHARS:
                        flush(sink)

                index += want
                result.processed_frames = index
                if progress is not None:
                    if index % 500 == 0 or index == total_frames:
                        if index != last_report:
                            last_report = index
                            progress(_progress_text(index, total_frames))
                if want == 0:
                    break
                if leftover:
                    break
            flush(sink)
            if report_residual:
                message = (
                    "警告：文件末尾存在 %d 字节残帧，不足单帧长度%d，已忽略"
                    % (report_residual, frame_length)
                )
                if message not in result.warnings:
                    result.residual_bytes = report_residual
                    result.warnings.append(message)
                    if progress is not None:
                        progress(message)
    except OSError as error:
        raise ExportError("导出失败：%s" % (error,)) from error
    except ValueError as error:
        raise ExportError(
            "第 %d 帧时间戳非法：%s" % (result.processed_frames, error)
        ) from error
    except ExportCancelled:
        result.cancelled = True
        result.elapsed_ms = int((time.perf_counter() - started) * 1000)
        raise

    result.elapsed_ms = int((time.perf_counter() - started) * 1000)
    return result


def summarize(result: ExportResult) -> str:
    """Human readable one-liner used by the CLI and the GUI log."""
    return (
        "导出完成！共处理 %d 帧数据，写出 %d 行，%d 列；耗时 %d ms（%.0f 帧/秒）"
        % (
            result.processed_frames,
            result.written_lines,
            result.column_count,
            result.elapsed_ms,
            result.frames_per_second,
        )
    )


def ensure_parent(path: str) -> None:
    """Create the output directory when it does not exist yet."""
    parent = Path(path).expanduser().resolve().parent
    if not parent.is_dir():
        parent.mkdir(parents=True, exist_ok=True)
