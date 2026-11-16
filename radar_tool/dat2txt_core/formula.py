"""``DataTable.Compute`` compatible formula evaluation.

``RcvCsvRecordModel.ConvertValue`` substitutes the parsed raw value into the
formula text and hands the result to ``System.Data.DataTable.Compute``::

    table.Compute(Formula.Replace("a", raw).Replace("Code", raw), "false")

The .NET expression evaluator has typed arithmetic:

* integer literals are ``Int32`` (``Int64`` when they do not fit) and integer
  arithmetic throws ``OverflowException`` when it overflows,
* literals with a decimal point and **no** exponent are ``Decimal``
  (``1234 * 0.01`` is the decimal ``12.34``, not a double),
* literals with an exponent are ``Double`` (``82E6``),
* division always produces ``Double`` (``5 / 2`` == ``2.5``),
* the result is then converted with ``Object.ToString()`` and re-parsed by
  ``Common.ToDouble``, i.e. doubles travel through the 15 digit "G15" format.

This module compiles a formula once into a small Python lambda so that the
per-frame cost is a single function call.  Only whitelisted AST nodes are
accepted; the generated source is built exclusively from those nodes, therefore
no user supplied text is ever executed.
"""

from __future__ import annotations

import ast
import decimal
import math
import re
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_EVEN
from typing import Callable, Union

from .dotnet import decimal_to_double, format_f3, format_f6, to_g15

#: Placeholder inserted where the original code textually substituted the value.
RAW_TOKEN = "__RAW_VALUE__"

#: .NET's ``decimal`` has a 28-29 digit mantissa and rounds half to even.
DECIMAL_CONTEXT = decimal.Context(prec=28, rounding=ROUND_HALF_EVEN)
decimal.setcontext(DECIMAL_CONTEXT)

Number = Union[int, Decimal, float]

#: ``long.MaxValue + 1``; integer arithmetic beyond it throws in .NET.
_INT64_LIMIT = 1 << 63

_LITERAL_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_.])(?:\d+\.\d*|\.\d+|\d+)(?:[eE][+-]?\d+)?(?![A-Za-z0-9_.])"
)

_LOG_FUNCTIONS: dict[str, Callable[..., float]] = {}


def _net_log(x: float) -> float:
    """``Math.Log(double)``: NaN for negatives, ``-Infinity`` for zero."""
    if math.isnan(x):
        return math.nan
    if x < 0.0:
        return math.nan
    if x == 0.0:
        return -math.inf
    return math.log(x)


def _net_log10(x: float) -> float:
    """``Math.Log10(double)``."""
    if math.isnan(x):
        return math.nan
    if x < 0.0:
        return math.nan
    if x == 0.0:
        return -math.inf
    return math.log10(x)


def _net_sqrt(x: float) -> float:
    """``Math.Sqrt(double)`` returns NaN instead of raising."""
    if math.isnan(x) or x < 0.0:
        return math.nan
    return math.sqrt(x)


def _net_pow(base: float, exponent: float) -> float:
    """``Math.Pow(double, double)``."""
    try:
        return math.pow(base, exponent)
    except OverflowError:
        if base < 0.0 and float(exponent).is_integer() and int(exponent) % 2:
            return -math.inf
        return math.inf
    except ValueError:  # negative base with a fractional exponent
        return math.nan


def _net_exp(x: float) -> float:
    """``Math.Exp(double)`` saturates to ``Infinity``."""
    try:
        return math.exp(x)
    except OverflowError:
        return math.inf


def _net_div(numerator: float, denominator: float, strict: int) -> float:
    """Division with ``DataTable.Compute`` semantics.

    Verified against .NET Framework 4.6.2::

        Compute("1/0")   -> Double  Infinity
        Compute("0/0")   -> Double  NaN
        Compute("1.0/0") -> DivideByZeroException

    ``strict`` is non zero when a ``Decimal`` literal takes part in the
    division, in which case a zero divisor throws (the original then exports an
    empty cell).  Otherwise the IEEE result is produced; the caller's
    ``Common.ToDouble`` step later turns an infinity into ``0.0`` while ``NaN``
    survives.
    """
    left = float(numerator)
    right = float(denominator)
    if right == 0.0:
        if strict:
            raise ZeroDivisionError("Attempted to divide by zero.")
        if left == 0.0 or math.isnan(left):
            return math.nan
        return math.inf if left > 0.0 else -math.inf
    return left / right


_LOG_FUNCTIONS.update(
    {
        "log": _net_log10,
        "ln": _net_log,
        "abs": abs,
        "sqrt": _net_sqrt,
        "pow": _net_pow,
        "exp": _net_exp,
    }
)


def _net_mod(numerator: float, denominator: float) -> float:
    """IEEE remainder used by NCalc (``Math.IEEERemainder`` style sign rules)."""
    left = float(numerator)
    right = float(denominator)
    if right == 0.0 or math.isnan(left) or math.isnan(right):
        return math.nan
    if math.isinf(left):
        return math.nan
    if math.isinf(right):
        return left
    return math.fmod(left, right)

#: Functions that may appear in generated code (helpers only, never builtins).
_RUNTIME_GLOBALS: dict[str, object] = {
    "__builtins__": {},
    "float": float,  # needed for the Double coercions
    "_D": lambda text: Decimal(text),
    "_cmod": None,  # filled in below to allow a recursive reference free lambda
    "_ddiv": _net_div,
    "_nmod": _net_mod,
}


class FormulaError(ValueError):
    """Raised when a formula cannot be compiled or evaluated."""


def csharp_mod(a: Number, b: Number) -> Number:
    """``%`` with C# semantics (the remainder keeps the sign of the dividend)."""
    if b == 0:
        raise FormulaError("attempted modulo by zero")
    if isinstance(a, Decimal) or isinstance(b, Decimal):
        left, right = Decimal(a), Decimal(b)
        quotient = (left / right).to_integral_value(rounding=ROUND_DOWN)
        return left - quotient * right
    quotient = abs(a) // abs(b)
    if (a >= 0) != (b >= 0):
        quotient = -quotient
    return a - quotient * b


_RUNTIME_GLOBALS["_cmod"] = csharp_mod


def _prepare_text(formula: str) -> str:
    """Insert the raw placeholder and tag decimal literals as ``Decimal``."""
    # The original code calls Replace("a", raw) first and Replace("Code", raw)
    # second; the order only matters for pathological formulas, keep it.
    text = formula.replace("a", RAW_TOKEN).replace("Code", RAW_TOKEN)

    def replace(match: "re.Match[str]") -> str:
        literal = match.group(0)
        if "e" in literal or "E" in literal:
            return literal  # Double literal, keep as is
        if "." in literal:
            return '_D("%s")' % literal  # Decimal literal
        return literal  # Int32/Int64 literal

    return _LITERAL_PATTERN.sub(replace, text)


class _SourceBuilder:
    """Walks a validated AST and renders Python source plus its numeric kind."""

    _INT = 0
    _DEC = 1
    _DBL = 2

    def build(self, node: ast.AST) -> tuple[str, int]:
        if isinstance(node, ast.Expression):
            return self.build(node.body)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool):
                raise FormulaError("boolean literals are not supported")
            if isinstance(node.value, int):
                return repr(node.value), self._INT
            if isinstance(node.value, str):  # only used as _D argument
                raise FormulaError("unexpected string literal")
            if isinstance(node.value, float):
                return repr(node.value), self._DBL
            raise FormulaError("unsupported literal")
        if isinstance(node, ast.Name):
            if node.id == RAW_TOKEN:
                return "raw", self._INT
            raise FormulaError("unsupported identifier %r" % (node.id,))
        if isinstance(node, ast.UnaryOp):
            operand, kind = self.build(node.operand)
            if isinstance(node.op, ast.USub):
                return "(-%s)" % operand, kind
            if isinstance(node.op, ast.UAdd):
                return "(+%s)" % operand, kind
            raise FormulaError("unsupported unary operator")
        if isinstance(node, ast.BinOp):
            left, left_kind = self.build(node.left)
            right, right_kind = self.build(node.right)
            if isinstance(node.op, ast.Div):
                # DataTable always performs floating point division, but a
                # Decimal operand turns a zero divisor into an exception.
                strict = 1 if self._DEC in (left_kind, right_kind) else 0
                return "_ddiv(%s, %s, %d)" % (left, right, strict), self._DBL
            kind = max(left_kind, right_kind)
            if isinstance(node.op, ast.Mod):
                if kind == self._DBL:
                    raise FormulaError("modulo is not defined for doubles")
                return "_cmod(%s, %s)" % (left, right), kind
            symbol = self._symbol(node.op)
            if kind == self._DBL:
                return "(float(%s) %s float(%s))" % (left, symbol, right), kind
            return "(%s %s %s)" % (left, symbol, right), kind
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id != "_D":
                raise FormulaError("unsupported function call")
            if len(node.args) != 1 or not isinstance(node.args[0], ast.Constant):
                raise FormulaError("unsupported _D call")
            literal = node.args[0].value
            if not isinstance(literal, str):
                raise FormulaError("unsupported _D argument")
            Decimal(literal)  # validate
            return '_D("%s")' % literal, self._DEC
        raise FormulaError("unsupported syntax: %s" % type(node).__name__)

    @staticmethod
    def _symbol(op: ast.operator) -> str:
        if isinstance(op, ast.Add):
            return "+"
        if isinstance(op, ast.Sub):
            return "-"
        if isinstance(op, ast.Mult):
            return "*"
        raise FormulaError("unsupported operator")


class _LogSourceBuilder:
    """Renders an NCalc style expression (``Code`` parameter is a double)."""

    _FUNCTIONS = _LOG_FUNCTIONS

    def build(self, node: ast.AST) -> str:
        if isinstance(node, ast.Expression):
            return self.build(node.body)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(
                node.value, (int, float)
            ):
                raise FormulaError("unsupported literal")
            return repr(float(node.value))
        if isinstance(node, ast.Name):
            if node.id.upper() in ("CODE", RAW_TOKEN.upper()):
                return "code"
            raise FormulaError("unsupported identifier %r" % (node.id,))
        if isinstance(node, ast.UnaryOp):
            operand = self.build(node.operand)
            if isinstance(node.op, ast.USub):
                return "(-%s)" % operand
            if isinstance(node.op, ast.UAdd):
                return "(+%s)" % operand
            raise FormulaError("unsupported unary operator")
        if isinstance(node, ast.BinOp):
            left = self.build(node.left)
            right = self.build(node.right)
            symbol = {
                ast.Add: "+",
                ast.Sub: "-",
                ast.Mult: "*",
                ast.Div: "/",
                ast.Mod: "%",
            }.get(type(node.op))
            if symbol is None:
                raise FormulaError("unsupported operator")
            if symbol == "/":
                return "_ddiv(%s, %s, 0)" % (left, right)
            if symbol == "%":
                return "_nmod(%s, %s)" % (left, right)
            return "(float(%s) %s float(%s))" % (left, symbol, right)
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                raise FormulaError("unsupported function call")
            name = node.func.id.lower()
            function = self._FUNCTIONS.get(name)
            if function is None:
                raise FormulaError("unsupported function %r" % (node.func.id,))
            arguments = ", ".join(self.build(arg) for arg in node.args)
            global_name = "_fn_%s" % name
            _RUNTIME_GLOBALS.setdefault(global_name, function)
            return "%s(%s)" % (global_name, arguments)
        raise FormulaError("unsupported syntax: %s" % type(node).__name__)


class CompiledFormula:
    """A formula compiled into a callable that accepts the raw integer value."""

    __slots__ = ("text", "digits", "_func", "_kind", "is_log")

    def __init__(self, text: str):
        if not text or not text.strip():
            raise FormulaError("empty formula")
        self.text = text
        self.is_log = "log" in text.lower() or "ln" in text.lower()
        self.digits = 3 if self.is_log else 6
        if self.is_log:
            self._func, self._kind = self._compile_log(text)
        else:
            self._func, self._kind = self._compile_numeric(text)

    # -- compilation ------------------------------------------------------
    @staticmethod
    def _compile_numeric(text: str) -> tuple[Callable[[int], Number], int]:
        prepared = _prepare_text(text)
        try:
            tree = ast.parse(prepared, mode="eval")
        except SyntaxError as error:
            raise FormulaError("cannot parse formula %r: %s" % (text, error))
        source, kind = _SourceBuilder().build(tree)
        code = "lambda raw: (%s)" % source
        try:
            function = eval(  # noqa: S307 - source is generated from a whitelist
                compile(code, "<formula>", "eval"), dict(_RUNTIME_GLOBALS)
            )
        except Exception as error:  # pragma: no cover - defensive
            raise FormulaError("cannot compile formula %r: %s" % (text, error))
        return function, kind

    @staticmethod
    def _compile_log(text: str) -> tuple[Callable[[float], float], int]:
        # NCalc receives Formula.Replace("Code", "[Code]"); the brackets only
        # mark the parameter, Python parses the bare identifier instead.
        prepared = text.replace("[Code]", "Code")
        try:
            tree = ast.parse(prepared, mode="eval")
        except SyntaxError as error:
            raise FormulaError("cannot parse formula %r: %s" % (text, error))
        source = _LogSourceBuilder().build(tree)
        code = "lambda code: (%s)" % source
        try:
            function = eval(  # noqa: S307 - source is generated from a whitelist
                compile(code, "<formula-log>", "eval"), dict(_RUNTIME_GLOBALS)
            )
        except Exception as error:  # pragma: no cover - defensive
            raise FormulaError("cannot compile formula %r: %s" % (text, error))
        return function, _SourceBuilder._DBL

    # -- evaluation -------------------------------------------------------
    def evaluate(self, raw: int) -> float:
        """Evaluate and return the double that ``Common.ToDouble`` produced.

        The original does ``ToDouble(Compute(...).ToString(), 0.0)``, therefore
        the result travels through ``Object.ToString()`` before being parsed
        again: ``NaN`` survives (``double.TryParse("NaN")`` succeeds) while an
        infinity becomes ``0.0`` (``TryParse("∞")`` fails).
        """
        if self.is_log:
            return float(self._func(float(raw)))
        result = self._func(int(raw))
        if self._kind == _SourceBuilder._DBL:
            value = float(result)
            if math.isnan(value):
                return math.nan
            if math.isinf(value):
                return 0.0
            return to_g15(value)
        if self._kind == _SourceBuilder._DEC:
            return decimal_to_double(result)
        integer = int(result)
        if integer >= _INT64_LIMIT or integer < -_INT64_LIMIT:
            # long arithmetic overflows -> OverflowException -> empty cell.
            raise FormulaError("arithmetic overflow")
        return float(integer)

    def format(self, raw: int) -> str:
        """Evaluate and return the ``F3``/``F6`` text produced by ConvertValue."""
        value = self.evaluate(raw)
        return format_f3(value) if self.is_log else format_f6(value)

    def format_log(self, raw: int) -> str:
        """Text of the NCalc (log/ln) branch.

        That branch does ``string.Format("{0:F3}", Evaluate(...))`` directly on
        the NCalc double, so ``NaN``/``∞``/``-∞`` reach the output verbatim
        (``Ln`` of a negative argument is ``NaN`` in .NET, not an exception).
        """
        return format_f3(float(self._func(float(raw))))



def compile_formula(text: str) -> CompiledFormula:
    """Compile *text* or raise :class:`FormulaError`."""
    return CompiledFormula(text)
