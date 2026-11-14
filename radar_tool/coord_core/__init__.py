"""坐标系账本纯计算内核（禁止 Qt / PyVista / matplotlib 依赖）。

公开入口：``Ledger``（设计文档 8.1 SDK）。
"""

from __future__ import annotations

from .compare import (
    ComparisonResult,
    ComponentRow,
    LimitCheckItem,
    LimitCheckReport,
    LoopClosureItem,
    LoopClosureReport,
)
from .error_budget import ErrorBudget, FOOTER_NOTE
from .graph import PathSegment, TransformGraph, TransformPath
from .ledger import (
    Ledger,
    PointingResult,
    QueryResult,
    TransformPointResult,
    VectorExpression,
)
from .schema import (
    SCHEMA_NAME,
    SCHEMA_VERSION,
    Frame,
    JudgeThresholds,
    LedgerDocument,
    LedgerMeta,
    Limit,
    Sigma,
    TransformRecord,
    ValidationResult,
    make_blank_document,
    make_sample_document,
)

__all__ = [
    "Ledger",
    "LedgerDocument",
    "LedgerMeta",
    "Frame",
    "TransformRecord",
    "Sigma",
    "Limit",
    "JudgeThresholds",
    "ValidationResult",
    "QueryResult",
    "PointingResult",
    "TransformPointResult",
    "VectorExpression",
    "ComparisonResult",
    "ComponentRow",
    "LoopClosureReport",
    "LoopClosureItem",
    "LimitCheckReport",
    "LimitCheckItem",
    "ErrorBudget",
    "TransformGraph",
    "TransformPath",
    "PathSegment",
    "SCHEMA_NAME",
    "SCHEMA_VERSION",
    "FOOTER_NOTE",
    "make_sample_document",
    "make_blank_document",
]
