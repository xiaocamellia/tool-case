"""F6 代码常量导出：C 头文件 / Python dict / MATLAB。

直接消灭"魔法数字"：导出形如 ``T_BODY_CAM`` 的命名常量，
载荷软件可直接包含，不再手抄矩阵。
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional

from ..errors import ValidationError

LANGUAGES = ("c", "python", "matlab")

_NON_ALNUM = re.compile(r"[^0-9A-Za-z]+")


def constant_name(from_frame: str, to_frame: str, status: str = "") -> str:
    """变换 id → 常量名：``T_BODY_CAM``（大写下划线，16.3）。"""
    def clean(text: str) -> str:
        return _NON_ALNUM.sub("_", text).strip("_").upper()

    name = f"T_{clean(from_frame)}_{clean(to_frame)}"
    if status and status != "design":
        name = f"{name}_{clean(status)}"
    return name


def generate(ledger, language: str = "python", status: Optional[str] = None,
             precision: int = 12) -> str:
    language_text = (language or "python").strip().lower()
    aliases = {"c": "c", "h": "c", "cpp": "c", "python": "python", "py": "python",
               "matlab": "matlab", "m": "matlab"}
    if language_text not in aliases:
        raise ValidationError(f"不支持的导出语言: {language}，可选 {' / '.join(LANGUAGES)}")
    kind = aliases[language_text]

    graph = ledger.build_graph(status)
    entries: List[dict] = []
    used_names: Dict[str, int] = {}
    for record in graph.records:
        matrix = record.homogeneous(ledger.meta)
        name = constant_name(record.from_frame, record.to_frame, record.status)
        if name in used_names:
            used_names[name] += 1
            name = f"{name}_{used_names[name]}"
        else:
            used_names[name] = 1
        entries.append({
            "name": name,
            "matrix": matrix,
            "record_id": record.id,
            "status": record.status,
            "source": record.source,
            "label": record.matrix_label(),
        })

    if kind == "python":
        return _render_python(entries, precision)
    if kind == "matlab":
        return _render_matlab(entries, precision)
    return _render_c(entries, precision)


def _format_rows(matrix, precision: int, indent: str, style: str) -> List[str]:
    rows = []
    for i in range(4):
        values = [f"{matrix[i, j]:.{precision}g}" for j in range(4)]
        if style == "c":
            rows.append(indent + ", ".join(values) + ("," if i < 3 else ""))
        else:
            rows.append(indent + ", ".join(values) + (";" if style == "matlab" else ","))
    return rows


def _render_python(entries, precision: int) -> str:
    lines = [
        '"""坐标系账本变换常量（自动生成，勿手改）。"""',
        "",
        "TRANSFORMS = {",
    ]
    for entry in entries:
        lines.append(f"    # {entry['label']} [{entry['status']}] {entry['source']}")
        lines.append(f"    '{entry['name']}': (")
        lines.extend(_format_rows(entry["matrix"], precision, " " * 8, "python"))
        lines.append("    ),")
    lines.append("}")
    lines.append("")
    return "\n".join(lines)


def _render_matlab(entries, precision: int) -> str:
    lines = ["% 坐标系账本变换常量（自动生成，勿手改）"]
    for entry in entries:
        lines.append(f"% {entry['label']} [{entry['status']}] {entry['source']}")
        lines.append(f"{entry['name']} = [")
        for i in range(4):
            values = [f"{entry['matrix'][i, j]:.{precision}g}" for j in range(4)]
            suffix = ";" if i < 3 else ""
            lines.append("    " + " ".join(values) + suffix)
        lines.append("];")
        lines.append("")
    return "\n".join(lines)


def _render_c(entries, precision: int) -> str:
    lines = [
        "/* 坐标系账本变换常量（自动生成，勿手改） */",
        "#ifndef COORD_LEDGER_TRANSFORMS_H",
        "#define COORD_LEDGER_TRANSFORMS_H",
        "",
    ]
    for entry in entries:
        lines.append(f"/* {entry['label']} [{entry['status']}] {entry['source']} */")
        lines.append(f"static const double {entry['name']}[4][4] = {{")
        for i in range(4):
            values = [f"{entry['matrix'][i, j]:.{precision}g}" for j in range(4)]
            lines.append("    {" + ", ".join(values) + "}" + ("," if i < 3 else ""))
        lines.append("};")
        lines.append("")
    lines.append("#endif /* COORD_LEDGER_TRANSFORMS_H */")
    lines.append("")
    return "\n".join(lines)
