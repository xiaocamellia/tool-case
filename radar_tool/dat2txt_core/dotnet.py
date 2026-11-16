"""Numeric primitives reproducing .NET Framework behaviour used by the exporter.

Every helper in this module exists because the original RadarSimulator.exe is a
.NET Framework 4.6.2 application and its output text is produced by methods such
as ``Convert.ToInt32(string, int)``, ``long.TryParse(..., HexNumber)`` and
``string.Format("{0:F6}", double)``.  Those APIs have a few behaviours that a
naive Python port gets wrong, most notably:

* ``Convert.ToInt32("FFFFFFFF", 16)`` returns ``-1`` (32 bit wrap around) and
  throws ``OverflowException`` for more than eight hex digits,
* ``sbyte.TryParse("80", HexNumber)`` succeeds and returns ``-128``,
* ``double.ToString("F6")`` rounds away from zero on the *shortest round trip*
  decimal representation (so ``0.1234565`` becomes ``0.123457`` even though the
  exact binary value is slightly below the midpoint),
* ``double.ToString()`` (the default "G15" format) keeps 15 significant digits
  which is what ``Common.ToDouble`` sees before the final "F6" formatting,
* ``BitConverter.ToSingle`` interprets the hex value little endian.
"""

from __future__ import annotations

import decimal
import math
import struct
from decimal import Decimal
from typing import Optional

_HEX_DIGITS = frozenset("0123456789abcdefABCDEF")

#: 15 significant digits, the default .NET Framework double format ("G15").
_G15_PRECISION = 15

#: ``double.PositiveInfinity.ToString("F3")`` on a zh-CN .NET Framework host.
POSITIVE_INFINITY_TEXT = "∞"
NEGATIVE_INFINITY_TEXT = "-∞"
NAN_TEXT = "NaN"


def _clean_hex(text: Optional[str]) -> Optional[str]:
    """Return *text* stripped when it is a plain hexadecimal string."""
    if text is None:
        return None
    stripped = text.strip()
    if not stripped:
        return None
    for char in stripped:
        if char not in _HEX_DIGITS:
            return None
    return stripped


def wrap_signed(value: int, bits: int) -> int:
    """Interpret *value* as a two's complement integer of *bits* width."""
    mask = (1 << bits) - 1
    value &= mask
    sign = 1 << (bits - 1)
    if value & sign:
        return value - (1 << bits)
    return value


# ---------------------------------------------------------------------------
# integer parsing (NumberStyles.HexNumber / Convert.ToXxx(string, base 2|16))
# ---------------------------------------------------------------------------
def parse_unsigned_hex(text: Optional[str], max_digits: int) -> Optional[int]:
    """``uint.TryParse(text, NumberStyles.HexNumber)`` semantics."""
    cleaned = _clean_hex(text)
    if cleaned is None or len(cleaned) > max_digits:
        return None
    return int(cleaned, 16)


def parse_sbyte_hex(text: Optional[str]) -> Optional[int]:
    """``sbyte.TryParse(text, NumberStyles.HexNumber)`` semantics."""
    cleaned = _clean_hex(text)
    if cleaned is None or len(cleaned) > 2:
        return None
    value = int(cleaned, 16)
    if value >= 0x80:
        return value - 0x100
    return value


def parse_signed_hex(text: Optional[str], bits: int) -> Optional[int]:
    """``int/long.TryParse(text, NumberStyles.HexNumber)`` semantics."""
    cleaned = _clean_hex(text)
    if cleaned is None or len(cleaned) > bits // 4:
        return None
    return wrap_signed(int(cleaned, 16), bits)


def parse_radix(text: str, radix: int, bits: int) -> int:
    """``Convert.ToInt32/ToInt64(string, radix)`` with two's complement wrap.

    Raises :class:`ValueError` where the .NET method would raise
    ``FormatException``/``OverflowException``.
    """
    if not text:
        raise ValueError("empty numeric string")
    if radix == 16:
        if len(text) > bits // 4:
            raise ValueError("value too large for base 16 conversion")
        for char in text:
            if char not in _HEX_DIGITS:
                raise ValueError("invalid hex digit")
        value = int(text, 16)
    elif radix == 2:
        if len(text) > bits:
            raise ValueError("value too large for base 2 conversion")
        for char in text:
            if char not in "01":
                raise ValueError("invalid binary digit")
        value = int(text, 2)
    else:  # pragma: no cover - the exporter only uses base 2 and base 16
        raise ValueError("unsupported radix %r" % (radix,))
    return wrap_signed(value, bits)


def parse_int32_radix(text: str, radix: int) -> int:
    """``Convert.ToInt32(string, radix)`` (32 bit, wraps on 8/32 digits)."""
    return parse_radix(text, radix, 32)


def parse_int64_radix(text: str, radix: int) -> int:
    """``Convert.ToInt64(string, radix)`` (64 bit)."""
    return parse_radix(text, radix, 64)


def parse_convert(text: str, radix: int, bits: int, signed: bool) -> int:
    """``Convert.ToSByte/ToInt16/ToUInt16/ToInt32/ToInt64(string, radix)``.

    Signed targets wrap around (``Convert.ToInt16("FFFF", 16)`` is ``-1``),
    unsigned targets raise when the value does not fit, and both raise when the
    text has more digits than the target can hold.
    """
    if not text:
        raise ValueError("empty numeric string")
    if radix == 16:
        limit = bits // 4
        for char in text:
            if char not in _HEX_DIGITS:
                raise ValueError("invalid hex digit")
    elif radix == 2:
        limit = bits
        for char in text:
            if char not in "01":
                raise ValueError("invalid binary digit")
    else:  # pragma: no cover - the exporter only uses base 2 and base 16
        raise ValueError("unsupported radix %r" % (radix,))
    if len(text) > limit:
        raise ValueError("value too large for the target type")
    value = int(text, radix)
    if signed:
        return wrap_signed(value, bits)
    if value > (1 << bits) - 1:
        raise ValueError("value too large for the target type")
    return value


# ---------------------------------------------------------------------------
# floating point helpers
# ---------------------------------------------------------------------------
def hex_to_float(text: Optional[str]) -> float:
    """``HexToFloat``: 4 hex digits (max) reinterpreted as little endian float."""
    value = parse_unsigned_hex(text, 8)
    if value is None:
        value = 0
    return struct.unpack("<f", struct.pack("<I", value & 0xFFFFFFFF))[0]


def float32_of_bytes(raw: bytes) -> float:
    """Little endian ``BitConverter.ToSingle`` for the first four bytes."""
    padded = bytes(raw[:4]).ljust(4, b"\x00")
    return struct.unpack("<f", padded)[0]


def to_g15(value: float) -> float:
    """Round trip *value* through .NET's default double format ("G15")."""
    if value == 0.0 or not math.isfinite(value):
        return value
    return float("{0:.{1}e}".format(value, _G15_PRECISION - 1))


def to_double(text: Optional[str], default: float = 0.0) -> float:
    """``Common.ToDouble``: ``double.TryParse`` with a fallback default.

    ``double.TryParse`` accepts the ``NaN`` literal (verified on .NET
    Framework 4.6.2: ``TryParse("NaN")`` is ``true``) but rejects
    ``"Infinity"``/``"∞"``, so infinities fall back to *default* while ``NaN``
    survives and later formats as ``"NaN"``.
    """
    if text is None:
        return default
    stripped = text.strip()
    if not stripped:
        return default
    if stripped in ("NaN", "-NaN", "+NaN"):
        return float("nan")
    try:
        value = float(stripped)
    except ValueError:
        return default
    if math.isinf(value):
        return default
    return value


def format_fixed(value: float, digits: int) -> str:
    """``value.ToString("F<digits>")`` with .NET Framework rounding rules.

    .NET rounds half away from zero using the shortest round trip decimal
    representation of the value (``0.1234565.ToString("F6")`` == ``0.123457``),
    which is not what Python's ``format()`` does (it rounds the exact binary
    value half to even).
    """
    if math.isnan(value):
        return "NaN"
    if math.isinf(value):
        # string.Format("{0:F6}", double.PositiveInfinity) uses the culture's
        # NumberFormatInfo.PositiveInfinitySymbol; on zh-CN (.NET Framework)
        # that is "∞" (verified: [double]::PositiveInfinity.ToString("F3")).
        return POSITIVE_INFINITY_TEXT if value > 0 else NEGATIVE_INFINITY_TEXT
    if value == 0.0:  # normalise -0.0, .NET prints "0.000000"
        value = 0.0
    # .NET first reduces the double to 15 significant digits (its internal
    # double precision) and only then rounds to the requested decimals with
    # "round half away from zero".
    text = repr(to_g15(float(value)))
    number = Decimal(text)
    # Enough digits for the integer part plus the requested decimals.
    precision = max(60, number.adjusted() + digits + 12)
    with decimal.localcontext() as context:
        context.prec = precision
        context.rounding = decimal.ROUND_HALF_UP
        quantised = number.quantize(Decimal(1).scaleb(-digits))
    text = format(quantised, "f")
    if not quantised:
        # .NET drops the sign when the value rounds to zero ("0.000000").
        text = text.lstrip("-")
    return text


def format_f6(value: float) -> str:
    """``string.Format("{0:F6}", value)``."""
    return format_fixed(value, 6)


def format_f3(value: float) -> str:
    """``string.Format("{0:F3}", value)``."""
    return format_fixed(value, 3)


def decimal_to_double(value: Decimal) -> float:
    """``Common.ToDouble(decimal.ToString())``."""
    try:
        return float(value)
    except (ValueError, OverflowError):  # pragma: no cover - defensive
        return 0.0
