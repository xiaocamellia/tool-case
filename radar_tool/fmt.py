"""界面数值格式化的唯一出口（信息呈现规范 V2 §2）。

规则摘要
--------
* **R0**：``radar_tool/`` 下除本文件外不得出现裸格式说明符（``:.6g`` / ``:g`` 等）。
* **N1** 有效数字 3 位（首位为 1 时 4 位），不固定堆小数位。
* **N2** 不用 ``:g``：它会砍掉末尾零让列宽跳动，小量级还会跳成科学计数。
* **N5** 单位与数值之间 1 个半角空格，``%`` 与 ``°`` 例外（紧贴）。
* **N6** 缺省值只用 ``--``（:data:`MISSING`）。
* **N7** 区间用 `` ~ ``。
* **N9** 阈值用半角 ``< > ≥ ≤``，与数值间 1 空格。
* **N11** 计数不加千分位分隔符。

所有函数都先 ``round`` 再格式化（绝不截断），小数位 clamp 在 0~6。
"""

from __future__ import annotations

import math

#: 唯一缺省符（两个半角连字符）。禁止 N/A / None / — / 空白。
MISSING = '--'

_ND_MIN = 0
_ND_MAX = 6

#: 紧贴数值的单位（N5 例外）
_TIGHT_UNITS = {'%', '°', '°C', '″', "''", "'"}

_THRESHOLD_OPS = {
    '<': '<',
    '<=': '≤',
    '≤': '≤',
    '>': '>',
    '>=': '≥',
    '≥': '≥',
    '=': '=',
    '==': '=',
}


def _clamp_nd(nd):
    return max(_ND_MIN, min(_ND_MAX, int(nd)))


def _is_number(value):
    if value is None or isinstance(value, bool):
        return False
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number)


def _join(value_text, unit):
    """数值 + 单位，遵循 N5 的空格规则。"""
    if not unit:
        return value_text
    if unit in _TIGHT_UNITS:
        return f'{value_text}{unit}'
    return f'{value_text} {unit}'


def auto_decimals(value, sig=3):
    """按有效数字计算小数位（§2.1 伪代码）。"""
    if value == 0:
        return _clamp_nd(sig - 1)
    magnitude = abs(float(value))
    # N1：首位为 1 时用 4 位有效数字
    digits = sig
    leading = int(magnitude // (10 ** math.floor(math.log10(magnitude))))
    if leading == 1:
        digits = sig + 1
    if magnitude >= 10 ** digits:
        return 0
    nd = digits - 1 - math.floor(math.log10(magnitude))
    return _clamp_nd(nd)


def num(value, sig=3, *, unit=None, signed=False, missing=MISSING):
    """主格式化器：按有效数字输出，自动选小数位。

    >>> num(0.50504)
    '0.505'
    >>> num(29.9783, unit='mm')
    '30.0 mm'
    >>> num(15000.0)
    '15000'
    >>> num(None)
    '--'
    """
    if not _is_number(value):
        return missing
    value = float(value)
    nd = auto_decimals(value, sig)
    text = f'{round(value, nd):.{nd}f}'
    if nd > 0 and not signed:
        # 尾零只在自动选择小数位时裁掉；signed 保持定宽以便成对比较（N8）
        if '.' in text:
            text = text.rstrip('0').rstrip('.')
    if text in ('-0', ''):
        text = '0'
    if signed and value > 0 and not text.startswith('+'):
        text = '+' + text
    return _join(text, unit)


def num_fixed(value, nd, *, unit=None, signed=False, missing=MISSING):
    """固定小数位，只给"按物理量定死小数位"的场合（dB、角度、百分比）。"""
    if not _is_number(value):
        return missing
    value = float(value)
    nd = _clamp_nd(nd)
    text = f'{round(value, nd):.{nd}f}'
    if text in ('-0', '-0.0') and round(value, nd) == 0:
        text = text.lstrip('-')
    if signed and value > 0 and not text.startswith('+'):
        text = '+' + text
    return _join(text, unit)


def rng(lo, hi, unit=None, nd=None):
    """区间，用 `` ~ `` 连接（N7）。"""
    left = _fmt_optional(lo, nd)
    right = _fmt_optional(hi, nd)
    if left == MISSING and right == MISSING:
        return MISSING
    return _join(f'{left} ~ {right}', unit)


def delta(value, unit=None, nd=None):
    """带符号变化量（N8：成对出现才带 +，本函数即"成对"场景）。"""
    if not _is_number(value):
        return MISSING
    if nd is not None:
        text = num_fixed(value, nd, signed=True)
    else:
        text = num(value, signed=True)
    return _join(text, unit)


def thresh(op, value, unit=None, nd=None):
    """阈值：``thresh('<', 0.1, 'dB') -> '< 0.1 dB'``。"""
    symbol = _THRESHOLD_OPS.get(str(op).strip(), str(op).strip())
    body = _fmt_optional(value, nd)
    if body == MISSING:
        return MISSING
    return _join(f'{symbol} {body}', unit)


def count(value, unit=''):
    """计数：整数、不加千分位（N11）。"""
    if not _is_number(value):
        return MISSING
    return _join(f'{int(round(float(value)))}', unit)


def pct(ratio, nd=1, *, missing=MISSING):
    """比例 → 百分比：``pct(0.432) -> '43.2%'``。"""
    if not _is_number(ratio):
        return missing
    return num_fixed(float(ratio) * 100.0, nd, unit='%')


def sci(value, unit=None, missing=MISSING):
    """科学计数法的唯一用法（§2.4）：``1.23e-5``，小写 e、指数不带 +/前导零。

    仅用于无法换单位的中间量；不得出现在表格列里。
    """
    if not _is_number(value):
        return missing
    value = float(value)
    if value == 0:
        return _join('0', unit)
    mantissa = value
    exponent = 0
    while abs(mantissa) >= 10:
        mantissa /= 10.0
        exponent += 1
    while abs(mantissa) < 1:
        mantissa *= 10.0
        exponent -= 1
    return _join(f'{num_fixed(mantissa, 2)}e{exponent}', unit)


def scale(value, from_unit, to_unit):
    """量级换算的调用位（具体换算复用 ``calc_units``，本函数不复刻系数）。"""
    from .calc_units import convert_length

    return convert_length(float(value), from_unit, to_unit)


def _fmt_optional(value, nd):
    if nd is not None:
        return num_fixed(value, nd)
    return num(value)


__all__ = [
    'MISSING', 'auto_decimals', 'num', 'num_fixed', 'rng', 'delta', 'thresh',
    'count', 'pct', 'sci', 'scale',
]
