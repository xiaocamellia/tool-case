"""Single frame decoding: a faithful port of ``ParseData`` + ``ConvertValue``.

The reference implementation is ``ReceiveProcess.ParseData`` (fills
``ParseSufTxt`` / ``ParseValType``) followed by ``RcvCsvRecordModel.ConvertValue``
(produces ``parseSaveDbSufExtendTxt``, the text that ends up in the txt file).
Every surprising detail of the original is preserved on purpose:

* single bit fields are rendered as ``"0"``/``"1"`` and never as ``True``,
* ``十六进制显示`` writes the *decimal* value of ``HexToInt`` (uint32, ``0`` when
  the value has more than eight hex digits),
* ``匹配显示`` writes the *decimal* value, never the Chinese description, because
  ``ParseSaveDbSufExtendTxt`` is assigned before the match table lookup,
* ``十进制显示`` on a field wider than eight bytes falls back to the raw
  upper-case hex string (``long.TryParse`` fails and the original returns the
  input text),
* ``二进制显示`` on a field wider than four bytes produces an empty cell
  (``Convert.ToInt32`` overflows and the exception leaves the cell untouched),
* a compute error inside a formula cell falls back to the raw hex string
  (``text = Format("{0}", value)`` in the catch block).

The fast decoders in this module are validated against :func:`convert_value`
by ``dat2txt.selftest`` on random data.
"""

from __future__ import annotations

import math
import struct
from functools import lru_cache
from typing import Callable, Iterable, Sequence

from . import dotnet
from .formula import FormulaError, compile_formula
from .spec_csv import (
    BRANCH_EMPTY,
    BRANCH_SAME_BYTE_BITS,
    BRANCH_SINGLE,
    BRANCH_SINGLE_BITS,
    BRANCH_SPAN,
    BRANCH_SPAN_BITS,
    DATA_TYPE_FLOAT,
    DATA_TYPE_TWOS_COMPLEMENT,
    SHOW_TYPE_BINARY,
    SHOW_TYPE_DECIMAL,
    SHOW_TYPE_FORMULA,
    SHOW_TYPE_HEX,
    SHOW_TYPE_MATCH,
    FieldSpec,
)

# ---------------------------------------------------------------------------
# bit helpers (StringUtils.ByteToBit)
# ---------------------------------------------------------------------------
#: ``ByteToBit(buff, 0x55)`` -> ``bit7 ... bit0``
_BITS_MSB: tuple[str, ...] = tuple(
    "".join(str((value >> bit) & 1) for bit in range(7, -1, -1))
    for value in range(256)
)
#: ``ByteToBit(buff, 0xAA)`` -> ``bit0 ... bit7``
_BITS_LSB: tuple[str, ...] = tuple(
    "".join(str((value >> bit) & 1) for bit in range(8)) for value in range(256)
)


def byte_to_bit(value: int, hltype: int) -> str:
    """Port of ``StringUtils.ByteToBit``; returns the eight bits as a string."""
    return _BITS_MSB[value] if hltype == 0x55 else _BITS_LSB[value]


def _bit_at(text: str, index: int) -> str:
    """``ElementAtOrDefault`` semantics: out of range yields an empty string."""
    if 0 <= index < len(text):
        return text[index]
    return ""


def to_hex_buffer(value: str) -> bytes:
    """``Common.ToHexBuffer``: hex text split in byte sized chunks."""
    result = bytearray()
    for index in range(0, len(value), 2):
        result.append(int(value[index : index + 2], 16))
    return bytes(result)


def get_bin_string(value: str) -> str:
    """``Common.GetBinString``: 8 bit groups, every nibble separated by a space."""
    groups: list[str] = []
    for byte in to_hex_buffer(value):
        bits = format(byte, "08b")
        groups.append(" ".join(bits[index : index + 4] for index in range(0, 8, 4)))
    return " ".join(groups)


@lru_cache(maxsize=256)
def _compiled(formula: str):
    return compile_formula(formula)


# ---------------------------------------------------------------------------
# reference implementation of ConvertValue
# ---------------------------------------------------------------------------
def _formula_raw(spec: FieldSpec, value: str) -> tuple[int, bool]:
    """Raw integer fed into the formula, following ConvertValue branch by branch."""
    data_type = spec.data_type
    if data_type == DATA_TYPE_TWOS_COMPLEMENT:
        byte_count = spec.byte_count
        if byte_count == 1:
            parsed = dotnet.parse_sbyte_hex(value)
            raw = 0 if parsed is None else parsed
            negative = False
            if raw >= 128:  # unreachable after a successful sbyte parse
                raw = 255 - raw + 1
                negative = True
            return raw, negative
        if byte_count == 2:
            raw = _try_parse(value, 16, 32)
            if raw >= 0x8000:
                return 0xFFFF - raw + 1, True
            return raw, False
        if byte_count == 3:
            raw = _try_parse(value, 16, 64)
            if raw >= 0x800000:
                return 0xFFFFFF - raw + 1, True
            return raw, False
        if byte_count == 4:
            raw = _try_parse(value, 16, 64)
            if raw >= 0x80000000:
                # IL: ldc.i4.m1 / conv.u8 / sub / add -> 0xFFFFFFFF - raw + 1.
                # ``conv.u8`` zero extends the int32 -1 to 0xFFFFFFFF, so the
                # four byte branch is exactly as wide as the 2/3/5 byte ones.
                return 0x100000000 - raw, True
            return raw, False
        if byte_count == 5:
            raw = _try_parse(value, 16, 64)
            if raw >= 0x8000000000:
                return 0xFFFFFFFFFF - raw + 1, True
            return raw, False
        return 0, False
    if data_type == DATA_TYPE_FLOAT:
        return int(dotnet.hex_to_float(value)), False
    parsed = dotnet.parse_signed_hex(value, 64)
    return (0 if parsed is None else parsed), False


def _try_parse(text: str, radix: int, bits: int) -> int:
    """``int/long.TryParse`` with a ``0`` fallback."""
    try:
        return dotnet.parse_radix(text, radix, bits)
    except ValueError:
        return 0


def _log_bit_length(spec: FieldSpec) -> int:
    """Bit width computed by the log/ln branch of ConvertValue."""
    byte_count = spec.suf_byte_no - spec.pre_byte_no  # note: no +1
    suffix_bit = spec.suf_start_bit if spec.suf_start_bit != -1 else 7
    prefix_bit = spec.pre_start_bit if spec.pre_start_bit != -1 else 0
    return (suffix_bit - prefix_bit + 1) + byte_count * 8


def _log_raw(spec: FieldSpec, value: str) -> int:
    """Raw integer used by the NCalc (log/ln) branch of ConvertValue."""
    bit_len = _log_bit_length(spec)
    # base 2 is used whenever the width is not a whole number of bytes.
    radix = 16 if bit_len % 8 == 0 else 2
    if bit_len <= 8:
        return dotnet.parse_convert(value, radix, 8, signed=True)
    if bit_len <= 16:
        raw = dotnet.parse_convert(value, radix, 16, signed=True)
        if raw < 0:
            raw += 65536
        return raw
    if bit_len <= 24:
        raw = dotnet.parse_convert(value, radix, 16, signed=False)
        if raw >= 8388608:  # Convert.ToInt32("FF" + value, radix)
            raw = dotnet.parse_convert("FF" + value, radix, 32, signed=True)
        return raw
    if bit_len <= 32:
        return dotnet.parse_convert(value, radix, 32, signed=True)
    return dotnet.parse_convert(value, radix, 64, signed=True)


def _formula_text(spec: FieldSpec, value: str) -> str:
    """Everything inside ``case 1`` of ConvertValue.

    Any exception raised here reaches the ``catch`` block that wraps the whole
    ``switch``, and because ``parseSaveDbSufExtendTxt`` is only assigned at the
    end of ``case 1`` the exported cell stays empty.  The exceptions are
    therefore propagated (never swallowed) and mapped to ``""`` by
    :func:`convert_value`.
    """
    if not spec.formula:
        return "无公式:%s" % value
    formula = _compiled(spec.formula)
    if formula.is_log:
        # The NCalc branch never sets the negative flag; the F3 value is
        # computed from the bit width based raw integer above.
        return formula.format_log(_log_raw(spec, value))
    raw, negative = _formula_raw(spec, value)
    text = formula.format(raw)
    return "-" + text if negative else text


def convert_value(spec: FieldSpec, value: str, val_type: int) -> str:
    """Reference port of ``RcvCsvRecordModel.ConvertValue``.

    ``value`` is ``ParseSufTxt`` (upper case hex or a binary string) and
    ``val_type`` is ``ParseValType`` (2 = binary string, 16 = hex string).
    Returns ``parseSaveDbSufExtendTxt``; ``""`` means the original never
    assigned the field, which exports an empty cell.
    """
    if not value:
        return ""
    try:
        show_type = spec.show_type
        if show_type == SHOW_TYPE_MATCH:
            # The match table only changes the on screen description
            # (parseSufExtendTxt), the exported column is always the number.
            base = 2 if spec.pre_start_bit >= 0 else 16
            return str(dotnet.parse_int32_radix(value, base))

        if show_type == SHOW_TYPE_FORMULA:
            text = _formula_text(spec, value)
            return text if text.strip() else value

        if show_type == SHOW_TYPE_BINARY:
            if spec.pre_start_bit == -1:
                stripped = get_bin_string(value).replace(" ", "")
                return str(dotnet.parse_int32_radix(stripped, 2))
            if spec.pre_start_bit >= 0:
                return str(dotnet.parse_int32_radix(value.replace(" ", ""), 2))
            return ""

        if show_type == SHOW_TYPE_DECIMAL:
            try:
                if spec.data_type == DATA_TYPE_FLOAT:
                    text = dotnet.format_f6(dotnet.hex_to_float(value))
                elif val_type == 2:
                    text = str(dotnet.parse_int64_radix(value, 2))
                elif val_type == 16:
                    parsed = dotnet.parse_signed_hex(value, 64)
                    text = str(parsed) if parsed is not None else value
                else:
                    text = value
            except (ValueError, ArithmeticError):
                text = value
            return text if text.strip() else value

        if show_type == SHOW_TYPE_HEX:
            if spec.data_type == DATA_TYPE_FLOAT:
                # parseSaveDbSufExtendTxt is never assigned in this branch.
                return ""
            amount = dotnet.parse_unsigned_hex(value, 8)
            return str(0 if amount is None else amount)

        return ""
    except (ValueError, ArithmeticError):
        # Outer catch of ConvertValue: the export cell keeps its empty default.
        return ""


# ---------------------------------------------------------------------------
# fast decoders
# ---------------------------------------------------------------------------
class FieldDecoder:
    """Decodes one CSV record for one frame payload."""

    __slots__ = ("spec", "required")

    def __init__(self, spec: FieldSpec, required: int) -> None:
        self.spec = spec
        self.required = required

    def decode(self, data: bytes) -> str:  # pragma: no cover - interface
        raise NotImplementedError


class _ConstantDecoder(FieldDecoder):
    """Fields the original leaves untouched (exported as an empty cell)."""

    __slots__ = ("_text",)

    def __init__(self, spec: FieldSpec, text: str = "") -> None:
        super().__init__(spec, 0)
        self._text = text

    def decode(self, data: bytes) -> str:
        return self._text


class _ByteTableDecoder(FieldDecoder):
    """Single byte fields (``byteN``, ``byteN:bM``, ``byteN:bM-byteN:bN``).

    ``ParseData`` only looks at one byte, so the whole conversion can be
    precomputed into a 256 entry lookup table.
    """

    __slots__ = ("_offset", "_table")

    def __init__(self, spec: FieldSpec, offset: int, table: Sequence[str]) -> None:
        super().__init__(spec, offset + 1)
        self._offset = offset
        self._table = table

    def decode(self, data: bytes) -> str:
        return self._table[data[self._offset]]


class _SpanIntDecoder(FieldDecoder):
    """Multi byte fields whose cell is a plain number."""

    __slots__ = ("_offset", "_end", "_render")

    def __init__(
        self,
        spec: FieldSpec,
        offset: int,
        length: int,
        render: Callable[[int], str],
    ) -> None:
        super().__init__(spec, offset + length)
        self._offset = offset
        self._end = offset + length
        self._render = render

    def decode(self, data: bytes) -> str:
        value = int.from_bytes(data[self._offset : self._end], "big")
        return self._render(value)


class _HexStringDecoder(FieldDecoder):
    """``十进制显示`` on a field wider than eight bytes: raw hex text."""

    __slots__ = ("_offset", "_end")

    def __init__(self, spec: FieldSpec, offset: int, length: int) -> None:
        super().__init__(spec, offset + length)
        self._offset = offset
        self._end = offset + length

    def decode(self, data: bytes) -> str:
        return data[self._offset : self._end].hex().upper()


class _Float32Decoder(FieldDecoder):
    """``浮点数`` fields rendered with ``F6`` (little endian float32)."""

    __slots__ = ("_offset",)

    def __init__(self, spec: FieldSpec, offset: int) -> None:
        super().__init__(spec, offset + 4)
        self._offset = offset

    def decode(self, data: bytes) -> str:
        value = struct.unpack_from("<f", data, self._offset)[0]
        if not math.isfinite(value):
            value = 0.0
        return dotnet.format_f6(value)


class _NoFormulaSpanDecoder(FieldDecoder):
    """``公式显示`` without a formula: the cell is ``无公式:{hex}``."""

    __slots__ = ("_offset", "_end")

    def __init__(self, spec: FieldSpec, offset: int, length: int) -> None:
        super().__init__(spec, offset + length)
        self._offset = offset
        self._end = offset + length

    def decode(self, data: bytes) -> str:
        return "无公式:" + data[self._offset : self._end].hex().upper()


class _SpanFormulaDecoder(FieldDecoder):
    """``公式显示`` on a multi byte field."""

    __slots__ = ("_offset", "_length", "_raw", "_formula", "_cache")

    def __init__(
        self,
        spec: FieldSpec,
        offset: int,
        length: int,
        formula,
    ) -> None:
        super().__init__(spec, offset + length)
        self._offset = offset
        self._length = length
        self._formula = formula
        self._raw = _make_span_raw(spec, offset, length)
        self._cache: dict[tuple[int, bool], str] = {}

    def decode(self, data: bytes) -> str:
        raw, negative = self._raw(data)
        key = (raw, negative)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        try:
            text = self._formula.format(raw)
            if negative:
                text = "-" + text
        except (FormulaError, ValueError, ArithmeticError):
            # Compute failed: case 1 never assigns parseSaveDbSufExtendTxt, so
            # the exported cell stays empty.
            text = ""
        if len(self._cache) >= 8192:
            self._cache.clear()
        self._cache[key] = text
        return text


class _LogSpanDecoder(FieldDecoder):
    """``公式显示`` with an NCalc ``log``/``ln`` formula on a multi byte field.

    The branch builds its raw integer from the field width (``8 * byteCount``
    bits) instead of the ``补码`` rules, then formats the result with ``F3``.
    """

    __slots__ = ("_offset", "_end", "_formula", "_read", "_cache")

    def __init__(
        self,
        spec: FieldSpec,
        offset: int,
        length: int,
        formula,
        read: Callable[[bytes], int],
    ) -> None:
        super().__init__(spec, offset + length)
        self._offset = offset
        self._end = offset + length
        self._formula = formula
        self._read = read
        self._cache: dict[bytes, str] = {}

    def decode(self, data: bytes) -> str:
        block = data[self._offset : self._end]
        cached = self._cache.get(block)
        if cached is not None:
            return cached
        try:
            text = self._formula.format_log(self._read(block))
        except (FormulaError, ValueError, ArithmeticError):
            text = ""
        if len(self._cache) >= 8192:
            self._cache.clear()
        self._cache[block] = text
        return text


class _SpanBitsDecoder(FieldDecoder):
    """``byteA:bM-byteB:bN`` - conservative port of the C3 branch."""

    __slots__ = (
        "_pre",
        "_suf",
        "_pre_bit",
        "_suf_bit",
        "_sequence",
        "_spec",
    )

    def __init__(self, spec: FieldSpec) -> None:
        super().__init__(spec, spec.suf_byte_no)
        self._pre = spec.pre_byte_no - 1
        self._suf = spec.suf_byte_no - 1
        self._pre_bit = spec.pre_start_bit
        self._suf_bit = spec.suf_start_bit
        self._sequence = spec.byte_seq
        self._spec = spec

    def decode(self, data: bytes) -> str:
        size = len(data)
        head_byte = data[self._pre] if self._pre < size else 0
        if self._pre_bit >= 0:
            order = 0x55 if self._sequence == 1 else 0xAA
            bits = byte_to_bit(head_byte, order)
            start = self._pre_bit if self._sequence == 1 else abs(self._pre_bit - 7)
            head = bits[start:]
        else:
            head = format(head_byte, "b")

        middle_parts: list[str] = []
        for index in range(self._pre + 1, self._suf):
            byte = data[index] if index < size else 0
            middle_parts.append(format(byte, "b").zfill(8))
        middle = "".join(middle_parts)

        tail_byte = data[self._suf] if self._suf < size else 0
        if self._suf_bit >= 0:
            if self._sequence == 1:
                bits = byte_to_bit(tail_byte, 0x55)
                tail = bits[: min(self._suf_bit, 7) + 1]
            else:
                bits = byte_to_bit(tail_byte, 0xAA)
                tail = "".join(
                    bits[7 - index] for index in range(min(self._suf_bit, 7) + 1)
                )
        else:
            tail = byte_to_bit(tail_byte, 0x55)

        return convert_value(self._spec, head + middle + tail, 2)


# ---------------------------------------------------------------------------
# decoder construction
# ---------------------------------------------------------------------------
def _render_int32(value: int) -> str:
    """``Convert.ToInt32`` result (two's complement wrap)."""
    if value >= 0x80000000:
        value -= 0x100000000
    return str(value)


def _render_uint32(value: int) -> str:
    return str(value)


def _render_int64(value: int) -> str:
    if value >= 0x8000000000000000:
        value -= 0x10000000000000000
    return str(value)


def _make_span_raw(
    spec: FieldSpec, offset: int, length: int
) -> Callable[[bytes], tuple[int, bool]]:
    """Raw value reader used by ``公式显示`` on multi byte fields."""
    data_type = spec.data_type
    if data_type == DATA_TYPE_FLOAT:
        if length > 4:
            return lambda data: (0, False)

        def read_float(data: bytes) -> tuple[int, bool]:
            value = struct.unpack_from("<f", data, offset)[0]
            if not math.isfinite(value):
                return 0, False
            return int(value), False

        return read_float

    if data_type == DATA_TYPE_TWOS_COMPLEMENT:
        if length == 2:

            def read_c2(data: bytes) -> tuple[int, bool]:
                raw = (data[offset] << 8) | data[offset + 1]
                if raw >= 0x8000:
                    return 0xFFFF - raw + 1, True
                return raw, False

            return read_c2
        if length == 3:

            def read_c3(data: bytes) -> tuple[int, bool]:
                raw = (
                    (data[offset] << 16)
                    | (data[offset + 1] << 8)
                    | data[offset + 2]
                )
                if raw >= 0x800000:
                    return 0xFFFFFF - raw + 1, True
                return raw, False

            return read_c3
        if length == 4:

            def read_c4(data: bytes) -> tuple[int, bool]:
                raw = int.from_bytes(data[offset : offset + 4], "big")
                if raw >= 0x80000000:
                    # 0xFFFFFFFF - raw + 1 (see _formula_raw): 2^32 - raw
                    return 0x100000000 - raw, True
                return raw, False

            return read_c4
        if length == 5:

            def read_c5(data: bytes) -> tuple[int, bool]:
                raw = int.from_bytes(data[offset : offset + 5], "big")
                if raw >= 0x8000000000:
                    return 0xFFFFFFFFFF - raw + 1, True
                return raw, False

            return read_c5
        # byte_count outside 1..5: the switch has no case, raw stays 0.
        return lambda data: (0, False)

    if length > 8:
        # long.TryParse fails on more than sixteen hex digits.
        return lambda data: (0, False)
    if length == 8:

        def read_signed(data: bytes) -> tuple[int, bool]:
            return _wrap64(int.from_bytes(data[offset : offset + 8], "big")), False

        return read_signed

    def read_unsigned(data: bytes) -> tuple[int, bool]:
        return int.from_bytes(data[offset : offset + length], "big"), False

    return read_unsigned


def _wrap64(value: int) -> int:
    if value >= 0x8000000000000000:
        return value - 0x10000000000000000
    return value


def _build_table(spec: FieldSpec) -> list[str]:
    """Precompute the 256 possible cells of a single byte field."""
    branch = spec.branch
    table: list[str] = []
    if branch == BRANCH_SINGLE:
        for value in range(256):
            table.append(convert_value(spec, "%02X" % value, 16))
    elif branch == BRANCH_SINGLE_BITS:
        for value in range(256):
            if spec.byte_seq == 1:
                bits = _BITS_MSB[value]
                index = spec.pre_start_bit
            else:
                bits = _BITS_LSB[value]
                index = abs(spec.pre_start_bit - 7)
            table.append(convert_value(spec, _bit_at(bits, index), 2))
    else:  # BRANCH_SAME_BYTE_BITS
        for value in range(256):
            if spec.byte_seq == 1:
                bits = _BITS_MSB[value]
                start = spec.pre_start_bit
                stop = min(spec.suf_start_bit, 7)
                text = bits[start : stop + 1] if start <= stop else ""
            else:
                bits = _BITS_LSB[value]
                start = abs(spec.pre_start_bit - 7)
                stop = min(abs(spec.suf_start_bit - 7), 7)
                text = bits[start : stop + 1] if start <= stop else ""
            table.append(convert_value(spec, text, 2))
    return table


def _build_log_span(
    spec: FieldSpec, offset: int, length: int, formula
) -> FieldDecoder:
    """Fast decoder for the NCalc branch on a byte aligned multi byte field.

    ``bitLen`` is ``8 * length`` here, so the branch uses base 16 and::

        length 2 -> Convert.ToInt16  (+65536 when negative)
        length 3 -> Convert.ToUInt16 (OverflowException: six hex digits)
        length 4 -> Convert.ToInt32  (32 bit wrap)
        length 5..8 -> Convert.ToInt64 (64 bit wrap)
        > 8      -> Convert.ToInt64  (OverflowException)
    """
    if length == 3 or length > 8:
        # The conversion throws before any text is assigned.
        return _ConstantDecoder(spec)

    if length == 2:

        def read_word(block: bytes) -> int:
            return (block[0] << 8) | block[1]

        return _LogSpanDecoder(spec, offset, length, formula, read_word)

    if length == 4:

        def read_dword(block: bytes) -> int:
            return dotnet.wrap_signed(int.from_bytes(block, "big"), 32)

        return _LogSpanDecoder(spec, offset, length, formula, read_dword)

    def read_qword(block: bytes) -> int:
        return dotnet.wrap_signed(int.from_bytes(block, "big"), 64)

    return _LogSpanDecoder(spec, offset, length, formula, read_qword)


def build_decoder(spec: FieldSpec) -> FieldDecoder:
    """Create the fastest decoder that is byte identical to the reference."""
    branch = spec.branch
    if branch == BRANCH_EMPTY:
        return _ConstantDecoder(spec)

    if branch in (BRANCH_SINGLE, BRANCH_SINGLE_BITS, BRANCH_SAME_BYTE_BITS):
        return _ByteTableDecoder(spec, spec.pre_byte_no - 1, _build_table(spec))

    if branch == BRANCH_SPAN_BITS:
        return _SpanBitsDecoder(spec)

    offset = spec.pre_byte_no - 1
    length = spec.suf_byte_no - spec.pre_byte_no + 1
    show_type = spec.show_type

    if show_type == SHOW_TYPE_FORMULA:
        if not spec.formula:
            return _NoFormulaSpanDecoder(spec, offset, length)
        try:
            formula = _compiled(spec.formula)
        except FormulaError:
            # The Computation throws, case 1 never assigns its cell.
            return _ConstantDecoder(spec)
        if formula.is_log:
            return _build_log_span(spec, offset, length, formula)
        return _SpanFormulaDecoder(spec, offset, length, formula)

    if show_type == SHOW_TYPE_DECIMAL:
        if spec.data_type == DATA_TYPE_FLOAT:
            return (
                _Float32Decoder(spec, offset)
                if length <= 4
                else _ConstantDecoder(spec, dotnet.format_f6(0.0))
            )
        if length <= 8:
            return _SpanIntDecoder(
                spec, offset, length, _render_int64 if length == 8 else _render_uint32
            )
        return _HexStringDecoder(spec, offset, length)

    if show_type in (SHOW_TYPE_MATCH, SHOW_TYPE_BINARY):
        if length <= 4:
            return _SpanIntDecoder(
                spec, offset, length, _render_int32 if length == 4 else _render_uint32
            )
        return _ConstantDecoder(spec)

    if show_type == SHOW_TYPE_HEX:
        if spec.data_type == DATA_TYPE_FLOAT:
            return _ConstantDecoder(spec)  # parseSaveDbSufExtendTxt unassigned
        if length <= 4:
            return _SpanIntDecoder(spec, offset, length, _render_uint32)
        return _ConstantDecoder(spec, "0")

    return _ConstantDecoder(spec)


class FrameDecoder:
    """Decodes the payload of one record into one cell per CSV record."""

    __slots__ = ("specs", "decoders", "required_length")

    def __init__(self, specs: Iterable[FieldSpec]) -> None:
        self.specs = list(specs)
        self.decoders: list[FieldDecoder] = [
            build_decoder(spec) for spec in self.specs
        ]
        self.required_length = max(
            [decoder.required for decoder in self.decoders] or [0]
        )

    def decode(self, data: bytes) -> list[str]:
        """Decode *data* (payload without the six BCD timestamp bytes)."""
        if len(data) < self.required_length:
            data = data + b"\x00" * (self.required_length - len(data))
        decoders = self.decoders
        return [decoder.decode(data) for decoder in decoders]

    def decode_selected(self, data: bytes, indices: Sequence[int]) -> list[str]:
        """Decode only the selected columns, in the given order."""
        if len(data) < self.required_length:
            data = data + b"\x00" * (self.required_length - len(data))
        decoders = self.decoders
        return [decoders[index].decode(data) for index in indices]


# ---------------------------------------------------------------------------
# slow reference implementation (ParseData) used by the self test
# ---------------------------------------------------------------------------
def parse_data_reference(spec: FieldSpec, data: bytes) -> tuple[str, int]:
    """Port of one ``ParseData`` iteration: returns (ParseSufTxt, ParseValType)."""

    def byte_at(one_based: int) -> int:
        index = one_based - 1
        return data[index] if 0 <= index < len(data) else 0

    pre = spec.pre_byte_no
    suf = spec.suf_byte_no

    if pre > 0 and suf < 0:  # branch A
        value = byte_at(pre)
        if spec.pre_start_bit >= 0:
            if spec.byte_seq == 1:
                bits = _BITS_MSB[value]
                text = _bit_at(bits, spec.pre_start_bit)
            else:
                bits = _BITS_LSB[value]
                text = _bit_at(bits, abs(spec.pre_start_bit - 7))
            return text, 2
        return "%02X" % value, 16

    if pre >= 0 and suf >= pre:
        if suf > pre:
            if spec.pre_start_bit >= 0 or spec.suf_start_bit >= 0:
                return _cross_byte_bits_reference(spec, data), 2
            text = "".join("%02X" % byte_at(index) for index in range(pre, suf + 1))
            return text, 16
        if spec.pre_start_bit >= 0:  # branch C1
            value = byte_at(pre)
            if spec.byte_seq == 1:
                bits = _BITS_MSB[value]
                start = spec.pre_start_bit
                stop = min(spec.suf_start_bit, 7)
                return (bits[start : stop + 1] if start <= stop else ""), 2
            bits = _BITS_LSB[value]
            start = abs(spec.pre_start_bit - 7)
            stop = min(abs(spec.suf_start_bit - 7), 7)
            return (bits[start : stop + 1] if start <= stop else ""), 2
    return "", 0


def _cross_byte_bits_reference(spec: FieldSpec, data: bytes) -> str:
    """Branch C3 of ParseData, kept literal for reference purposes."""

    def byte_at(one_based: int) -> int:
        index = one_based - 1
        return data[index] if 0 <= index < len(data) else 0

    pre = spec.pre_byte_no
    suf = spec.suf_byte_no
    head_byte = byte_at(pre)
    if spec.pre_start_bit >= 0:
        if spec.byte_seq == 1:
            bits = byte_to_bit(head_byte, 0x55)
            start = spec.pre_start_bit
        else:
            bits = byte_to_bit(head_byte, 0xAA)
            start = abs(spec.pre_start_bit - 7)
        head = bits[start:]
    else:
        head = format(head_byte, "b")

    middle = "".join(
        format(byte_at(index), "b").zfill(8) for index in range(pre + 1, suf)
    )

    tail_byte = byte_at(suf)
    if spec.suf_start_bit >= 0:
        if spec.byte_seq == 1:
            bits = byte_to_bit(tail_byte, 0x55)
            tail = "".join(bits[index] for index in range(0, spec.suf_start_bit + 1)
                           if index < 8)
        else:
            bits = byte_to_bit(tail_byte, 0xAA)
            tail = "".join(
                bits[7 - index]
                for index in range(0, spec.suf_start_bit + 1)
                if index <= 7
            )
    else:
        tail = byte_to_bit(tail_byte, 0x55)
    return head + middle + tail


def reference_decode_frame(specs: Sequence[FieldSpec], data: bytes) -> list[str]:
    """Decode a payload with the slow reference implementation."""
    cells: list[str] = []
    for spec in specs:
        value, val_type = parse_data_reference(spec, data)
        cells.append(convert_value(spec, value, val_type))
    return cells
