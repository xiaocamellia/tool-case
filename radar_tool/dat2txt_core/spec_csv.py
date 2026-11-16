"""Reader for the ``Config/receive/**.csv`` field definition tables.

The CSV files are GBK encoded and start with a header row::

    序号,字节内顺序,名称,数据类型,显示类型,扩展信息1,备注[,参数代号]

``序号`` describes the byte/bit window of the field (see ``ParseCsvByteInfo``
in the specification) and ``扩展信息1`` holds either a formula (for
``公式显示``) or a ``id:text;`` match table (for ``匹配显示``).
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from typing import Iterable, Optional

# -- 数据类型 ---------------------------------------------------------------
DATA_TYPE_UNSIGNED = 0
DATA_TYPE_SIGNED = 1
DATA_TYPE_TWOS_COMPLEMENT = 2
DATA_TYPE_FLOAT = 3

# -- 显示类型 ---------------------------------------------------------------
SHOW_TYPE_MATCH = 0
SHOW_TYPE_FORMULA = 1
SHOW_TYPE_BINARY = 2
SHOW_TYPE_DECIMAL = 10
SHOW_TYPE_HEX = 16

_BYTE_SEQUENCE = {"正": 1, "反": -1}

_HEADER_ALIASES = {
    "序号": "seq",
    "字节内顺序": "byte_seq",
    "名称": "name",
    "数据类型": "data_type",
    "显示类型": "show_type",
    "扩展信息1": "extend1",
    "备注": "remark",
    "参数代号": "param_code",
}

_POSITIONAL_ORDER = ("seq", "byte_seq", "name", "data_type", "show_type", "extend1")

#: Branch names matching the ParseData decision tree.
BRANCH_EMPTY = "empty"
BRANCH_SINGLE = "single"            # byteN            (branch A)
BRANCH_SINGLE_BITS = "single_bits"  # byteN:bM         (branch A with bit)
BRANCH_SAME_BYTE_BITS = "same_bits"  # byteA:bM-byteA:bN (branch C1)
BRANCH_SPAN = "span"                # byteA-byteB      (branch C2)
BRANCH_SPAN_BITS = "span_bits"      # byteA:bM-byteB:bN (branch C3)


@dataclass(frozen=True)
class MatchEntry:
    """One ``id:text`` pair of a 匹配显示 table."""

    descrip_id: str
    descrip_text: str


@dataclass(frozen=True)
class FieldSpec:
    """One CSV record (= one output column)."""

    index: int
    seq_text: str
    byte_seq: int
    name: str
    data_type: int
    show_type: int
    formula: str
    match_entries: tuple[MatchEntry, ...]
    pre_byte_no: int
    pre_start_bit: int
    suf_byte_no: int
    suf_start_bit: int

    # -- derived helpers --------------------------------------------------
    @property
    def branch(self) -> str:
        """Which ParseData branch handles this field."""
        if self.pre_byte_no > 0 and self.suf_byte_no < 0:
            return (
                BRANCH_SINGLE_BITS
                if self.pre_start_bit >= 0
                else BRANCH_SINGLE
            )
        if self.pre_byte_no >= 0 and self.suf_byte_no >= self.pre_byte_no:
            if self.suf_byte_no > self.pre_byte_no:
                if self.pre_start_bit >= 0 or self.suf_start_bit >= 0:
                    return BRANCH_SPAN_BITS
                return BRANCH_SPAN
            # Same byte: C1 needs a start bit, otherwise ParseData ignores it.
            if self.pre_start_bit >= 0:
                return BRANCH_SAME_BYTE_BITS
            return BRANCH_EMPTY
        return BRANCH_EMPTY

    @property
    def byte_count(self) -> int:
        """``SufByteNo - PreByteNo + 1`` with the ``SufByteNo == -1`` fixup."""
        if self.suf_byte_no == -1:
            return 1
        return self.suf_byte_no - self.pre_byte_no + 1

    @property
    def last_byte_no(self) -> int:
        """Highest 1-based byte index the field touches (0 when unused)."""
        if self.suf_byte_no >= 0:
            return self.suf_byte_no
        if self.pre_byte_no > 0:
            return self.pre_byte_no
        return 0


def parse_byte_info(text: str) -> tuple[int, int, int, int]:
    """Port of ``ParseCsvByteInfo``; returns (pre, preBit, suf, sufBit)."""
    pre_byte_no = 0
    pre_start_bit = -1
    suf_byte_no = -1
    suf_start_bit = -1
    value = (text or "").strip()
    if not value:
        return pre_byte_no, pre_start_bit, suf_byte_no, suf_start_bit

    if "-" in value:
        parts = value.split("-")
        first = parts[0].strip()
        if first:
            if ":" in first:
                head = first.split(":")
                pre_byte_no = _to_int(head[0].replace("byte", ""))
                pre_start_bit = _to_int(head[1].replace("b", ""))
            else:
                pre_byte_no = _to_int(first.replace("byte", ""))
        second = parts[1].strip() if len(parts) > 1 else ""
        if second:
            if ":" in second:
                tail = second.split(":")
                suf_byte_no = _to_int(tail[0].replace("byte", ""))
                suf_start_bit = _to_int(tail[1].replace("b", ""))
            else:
                suf_byte_no = _to_int(second.replace("byte", ""))
        return pre_byte_no, pre_start_bit, suf_byte_no, suf_start_bit

    if ":" in value:
        head = value.split(":")
        pre_byte_no = _to_int(head[0].replace("byte", ""))
        pre_start_bit = _to_int(head[1].replace("b", ""))
    else:
        pre_byte_no = _to_int(value.replace("byte", ""))
    return pre_byte_no, pre_start_bit, suf_byte_no, suf_start_bit


def _to_int(text: str) -> int:
    stripped = text.strip()
    if not stripped:
        return 0
    return int(stripped, 10)


def parse_data_type(text: str) -> int:
    """Map the 数据类型 column onto the model enum.

    The original code compares the cell against the literals ``"补码"`` and
    ``"符号数"`` with an exact string comparison.  The CSVs however contain
    ``"有符号数"`` (two occurrences in the whole corpus), which does **not**
    equal ``"符号数"`` -- those two fields therefore keep ``DataType == 0``
    (无符号数).  Reproducing that mismatch is mandatory: matching
    ``"有符号数"`` would change the exported numbers.

    Measured distribution over the 21 definition files: 无符号数 774,
    补码 350, 有符号数 2 (→ stays 0).  ``DataType == 1`` and ``DataType == 3``
    are kept for defensiveness although they never trigger.
    """
    value = (text or "").strip()
    if value == "补码":
        return DATA_TYPE_TWOS_COMPLEMENT
    if value == "符号数":
        return DATA_TYPE_SIGNED
    if value == "浮点数":
        return DATA_TYPE_FLOAT
    return DATA_TYPE_UNSIGNED


def parse_show_type(text: str) -> int:
    """Map the 显示类型 column onto the model enum."""
    value = (text or "").strip()
    if not value:
        return SHOW_TYPE_MATCH
    if "十六进制" in value:
        return SHOW_TYPE_HEX
    if "十进制" in value:
        return SHOW_TYPE_DECIMAL
    if "二进制" in value:
        return SHOW_TYPE_BINARY
    if "公式" in value:
        return SHOW_TYPE_FORMULA
    return SHOW_TYPE_MATCH


def parse_match_entries(text: str) -> tuple[MatchEntry, ...]:
    """Parse a ``id:text;id:text;`` match table (trailing ``;`` tolerated)."""
    entries: list[MatchEntry] = []
    if not text:
        return tuple(entries)
    for chunk in text.split(";"):
        piece = chunk.strip()
        if not piece:
            continue
        if ":" in piece:
            descrip_id, descrip_text = piece.split(":", 1)
            entries.append(MatchEntry(descrip_id.strip(), descrip_text.strip()))
        else:
            entries.append(MatchEntry(piece, ""))
    return tuple(entries)


def _resolve_header(row: Iterable[str]) -> Optional[list[str]]:
    names = [cell.strip() for cell in row]
    mapped: list[str] = []
    for name in names:
        mapped.append(_HEADER_ALIASES.get(name, ""))
    if "seq" in mapped and "name" in mapped:
        # Fill unknown columns with a harmless placeholder.
        return [value or "ignore" for value in mapped]
    return None


def load_specs(csv_path: str) -> list[FieldSpec]:
    """Load the field definitions of *csv_path* (GBK encoded)."""
    with open(csv_path, "rb") as handle:
        raw = handle.read()
    text = raw.decode("gbk")
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        raise ValueError("字段定义文件为空: %s" % csv_path)

    columns = _resolve_header(rows[0])
    if columns is None:
        columns = list(_POSITIONAL_ORDER) + ["ignore"] * max(
            0, len(rows[0]) - len(_POSITIONAL_ORDER)
        )
        data_rows = rows
    else:
        data_rows = rows[1:]

    specs: list[FieldSpec] = []
    for row in data_rows:
        if not row or not any(cell.strip() for cell in row):
            continue
        record = {name: "" for name in columns if name != "ignore"}
        for name, cell in zip(columns, row):
            if name != "ignore":
                record[name] = cell
        pre_byte_no, pre_start_bit, suf_byte_no, suf_start_bit = parse_byte_info(
            record.get("seq", "")
        )
        show_type = parse_show_type(record.get("show_type", ""))
        extend = record.get("extend1", "")
        formula = extend.strip() if show_type == SHOW_TYPE_FORMULA else ""
        match_entries = (
            parse_match_entries(extend) if show_type == SHOW_TYPE_MATCH else ()
        )
        specs.append(
            FieldSpec(
                index=len(specs),
                seq_text=record.get("seq", "").strip(),
                byte_seq=_BYTE_SEQUENCE.get(record.get("byte_seq", "").strip(), 1),
                name=record.get("name", "").strip(),
                data_type=parse_data_type(record.get("data_type", "")),
                show_type=show_type,
                formula=formula,
                match_entries=match_entries,
                pre_byte_no=pre_byte_no,
                pre_start_bit=pre_start_bit,
                suf_byte_no=suf_byte_no,
                suf_start_bit=suf_start_bit,
            )
        )
    if not specs:
        raise ValueError("字段定义文件没有有效记录: %s" % csv_path)
    return specs
