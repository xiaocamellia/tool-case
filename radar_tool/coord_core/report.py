"""交付层导出：F1 变换报告 / F2 矢量表 / F3 一览表 / F4 矩阵表 / F7 复核报告。

Markdown 为底稿格式；Word 由 python-docx 生成（复用 experiment_word_export
的标题/正文风格，不引入 Jinja2）。CSV 一律走 ``export_safety.write_dataframe_csv``。
"""

from __future__ import annotations

import os
from typing import List, Optional, Sequence

import numpy as np
import pandas as pd

from ..errors import ValidationError
from .compare import VERDICT_LABELS, ComparisonResult, LimitCheckReport, LoopClosureReport
from .error_budget import FOOTER_NOTE, ErrorBudget
from . import formatting as fmt


# ---------------------------------------------------------------------------
# 表格行（CSV 用，F2/F3/F4）
# ---------------------------------------------------------------------------


def frame_table_rows(ledger) -> List[dict]:
    rows = []
    for frame in ledger.frames():
        rows.append({
            "id": frame.id,
            "name": frame.name,
            "axis": frame.axis,
            "unit": frame.unit,
            "definition": frame.definition,
            "note": frame.note,
        })
    return rows


def matrix_table_rows(ledger, status: Optional[str] = None) -> List[dict]:
    """全矩阵表（F4）：当前有效值下所有可达 ``(from, to)`` 的 4×4。"""
    graph = ledger.build_graph(status)
    rows = []
    for source in graph.frames:
        for target in graph.frames:
            if source == target:
                continue
            try:
                path = graph.resolve(source, target)
            except ValidationError:
                continue
            sigma_t, sigma_r = path.sigma_total()
            row = {
                "T": f"T_{target}_{source}",
                "from": target,
                "to": source,
                "path": " → ".join(path.frames),
                "sigma_t_m": sigma_t,
                "sigma_r_arcsec": sigma_r,
            }
            for i in range(4):
                for j in range(4):
                    row[f"m{i}{j}"] = float(path.matrix[i, j])
            rows.append(row)
    return rows


def write_rows_csv(rows: Sequence[dict], filepath: str) -> str:
    from ..export_safety import write_dataframe_csv

    if not rows:
        raise ValidationError("没有可导出的数据行")
    dataframe = pd.DataFrame(list(rows))
    directory = os.path.dirname(os.path.abspath(filepath))
    os.makedirs(directory, exist_ok=True)
    write_dataframe_csv(dataframe, filepath, index=False, encoding="utf-8-sig")
    return filepath


# ---------------------------------------------------------------------------
# Markdown 报告
# ---------------------------------------------------------------------------

_QUERY_HEAD = (
    "| 项目 | 值 |\n|---|---|\n"
)


def _matrix_markdown(matrix: np.ndarray, precision: int = 6) -> str:
    lines = ["| | | | |", "|---:|---:|---:|---:|"]
    for i in range(4):
        lines.append("| " + " | ".join(f"{matrix[i, j]:.{precision}g}" for j in range(4)) + " |")
    return "\n".join(lines)


def _query_section(ledger, query_result) -> str:
    lines = [
        "## 查询变换",
        "",
        f"- 变换：`T_{query_result.target}_{query_result.source}"
        f"（{query_result.source} → {query_result.target}）`",
        f"- 路径：{' → '.join(query_result.path)}",
        f"- 当前值来源：{query_result.source_line()}",
        f"- σ：平移 {query_result.sigma_t_m * 1000:.4g} mm，旋转 {query_result.sigma_r_arcsec:.4g}″",
        "",
        "齐次矩阵：",
        "",
        _matrix_markdown(query_result.matrix),
        "",
        f"- RPY（ZYX intrinsic, deg）：{fmt.fmt_vec3(query_result.rpy_deg, labels=('绕X', '绕Y', '绕Z'), unit='°', precision=4)}",
        f"- 四元数（wxyz）：{fmt.fmt_quaternion(query_result.quaternion, order='wxyz')}",
        "",
    ]
    return "\n".join(lines)


def _compare_section(result: ComparisonResult) -> str:
    lines = [
        f"## 变换对比：{result.baseline_id} vs {result.candidate_id}",
        "",
        f"- 对比对象：`{result.baseline_id}`（{fmt.fmt_status(result.baseline_status)}｜{result.baseline_source or '无'}）"
        f" → `{result.candidate_id}`（{fmt.fmt_status(result.candidate_status)}｜{result.candidate_source or '无'}）",
        f"- 关系：`T_{result.from_frame}_{result.to_frame}（{result.to_frame} → {result.from_frame}）`",
        "",
        "| 分量 | 偏差 δ | σ | z=δ/σ | 判定 |",
        "|---|---:|---:|---:|---|",
    ]
    for row in result.rows:
        lines.append(
            f"| {row.label}{'(″)' if row.name.startswith('rot_') else '(mm)'} | "
            f"{row.delta:+.4g} | {row.sigma:.4g} | {row.z:+.3f} | {VERDICT_LABELS.get(row.verdict, row.verdict)} |"
        )
    lines.extend([
        "",
        f"**结论**：{result.conclusion}",
        "",
    ])
    if result.suggestions:
        lines.append("**处置建议**：")
        for suggestion in result.suggestions:
            lines.append(f"- {suggestion}")
        lines.append("")
    return "\n".join(lines)


def _loop_section(report: LoopClosureReport) -> str:
    lines = [
        "## 环路闭合自检",
        "",
        f"{report.summary()}（阈值 = 回路各边 σ RSS × {report.sigma_multiplier:g}）",
        "",
    ]
    for item in report.items:
        lines.append(f"- {item.describe()}")
    if not report.items:
        lines.append("- 无可检回路")
    lines.append("")
    return "\n".join(lines)


def _limits_section(report: LimitCheckReport) -> str:
    lines = ["## 限值符合性", "", report.summary(), ""]
    for item in report.items:
        lines.append(f"- {item.describe()}")
    if not report.items:
        lines.append("- 未登记限值")
    lines.append("")
    return "\n".join(lines)


def _budget_section(budget: ErrorBudget) -> str:
    lines = [
        "## 误差预算分解",
        "",
        "| 路径段 | 平移σ(mm) | 旋转σ(″) | 方差占比 | 对最终指向贡献(″) |",
        "|---|---:|---:|---:|---:|",
    ]
    for segment in budget.segments:
        marker = " **← 主导段**" if segment.dominant else ""
        lines.append(
            f"| {segment.label}{marker} | {segment.sigma_t_m * 1000:.4g} | "
            f"{segment.sigma_r_arcsec:.4g} | {segment.variance_share:.0%} | "
            f"{segment.contribution_arcsec:.4g} |"
        )
    lines.append(
        f"| **合成（RSS）** | **{budget.sigma_t_total_m * 1000:.4g}** | "
        f"**{budget.sigma_r_total_arcsec:.4g}** | 100% | **{budget.sigma_r_total_arcsec:.4g}** |"
    )
    lines.append("")
    if budget.dominant_highlight:
        lines.append(
            f"> **注意：{budget.dominant_label} 主导合成误差（占比 {budget.dominant_share:.0%}）**，"
            "若合成指向误差不达标，优先收紧该段的安装/标定精度。"
        )
        lines.append("")
    return "\n".join(lines)


def build_transform_report_markdown(
    ledger,
    query_result=None,
    budget: Optional[ErrorBudget] = None,
    vector_rows: Optional[Sequence[dict]] = None,
    review_bundle: Optional[dict] = None,
    screenshot_path: Optional[str] = None,
) -> str:
    """F1 变换关系报告。"""
    meta = ledger.meta
    lines = [
        f"# 坐标系变换报告：{meta.name}",
        "",
        _QUERY_HEAD,
        f"| 账本版本 | {meta.version} |",
        "|---|---|",
        f"| 单位 | {meta.unit_default} / {meta.angle_default} |",
        f"| 四元数顺序 | {meta.quaternion_order} |",
        f"| 欧拉角 | 默认 {meta.euler_rotation} |",
        "",
        "## 坐标系清单",
        "",
        "| id | 名称 | 轴向 | 各轴定义 |",
        "|---|---|---|---|---|",
    ]
    for frame in ledger.frames():
        lines.append(
            f"| {frame.id} | {frame.name or '—'} | {frame.axis} | "
            f"{frame.definition or '—'} |"
        )
    lines.append("")

    if query_result is not None:
        lines.append(_query_section(ledger, query_result))
    if budget is not None:
        lines.append(_budget_section(budget))
    if review_bundle:
        if "compare" in review_bundle and review_bundle["compare"] is not None:
            lines.append(_compare_section(review_bundle["compare"]))
        if "loops" in review_bundle and review_bundle["loops"] is not None:
            lines.append(_loop_section(review_bundle["loops"]))
        if "limits" in review_bundle and review_bundle["limits"] is not None:
            lines.append(_limits_section(review_bundle["limits"]))
    if vector_rows:
        lines.extend([
            "## 矢量跨系表达",
            "",
            "| 坐标系 | x | y | z |",
            "|---|---:|---:|---:|",
        ])
        for row in vector_rows:
            lines.append(
                f"| {row['frame']} | {row['x']:.6g} | {row['y']:.6g} | {row['z']:.6g} |"
            )
        lines.append("")
    if screenshot_path:
        lines.extend(["## 3D 截图", "", f"![3D]({screenshot_path})", ""])
    lines.extend(["---", "", f"*{FOOTER_NOTE}*", ""])
    return "\n".join(lines)


def build_review_report_markdown(
    ledger,
    compare: Optional[ComparisonResult] = None,
    loops: Optional[LoopClosureReport] = None,
    limits: Optional[LimitCheckReport] = None,
) -> str:
    """F7 对比/复核报告：固定结构（6.6.5）。"""
    meta = ledger.meta
    lines = [
        f"# 坐标系复核报告：{meta.name}",
        "",
        _QUERY_HEAD,
        f"| 账本版本 | {meta.version} |",
        "|---|---|",
        "",
    ]
    if compare is not None:
        lines.append(_compare_section(compare))
        if compare.suggestions:
            pass  # 已在 _compare_section 输出
    if loops is not None:
        lines.append(_loop_section(loops))
    if limits is not None:
        lines.append(_limits_section(limits))
    lines.extend(["---", "", f"*{FOOTER_NOTE}*", ""])
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Word 导出（python-docx，复用 WordExportMixin 的标题风格）
# ---------------------------------------------------------------------------


def _docx_add_heading(doc, text: str, level: int) -> None:
    doc.add_heading(text, level=level)


def _docx_add_table(doc, headers: Sequence[str], rows: Sequence[Sequence]):
    table = doc.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    header_cells = table.rows[0].cells
    for index, header in enumerate(headers):
        header_cells[index].text = str(header)
    for row in rows:
        cells = table.add_row().cells
        for index, value in enumerate(row):
            cells[index].text = "" if value is None else str(value)
    return table


def write_transform_report_word(ledger, filepath: str, **options) -> str:
    """F1 的 Word 版本。"""
    from docx import Document

    query_result = options.get("query_result")
    budget = options.get("budget")
    vector_rows = options.get("vector_rows")
    review_bundle = options.get("review_bundle")
    screenshot_path = options.get("screenshot_path")

    meta = ledger.meta
    doc = Document()
    doc.add_heading(f"坐标系变换报告：{meta.name}", level=0)
    _docx_add_table(doc, ["项目", "值"], [
        ["账本版本", meta.version],
        ["单位", f"{meta.unit_default} / {meta.angle_default}"],
        ["四元数顺序", meta.quaternion_order],
        ["欧拉角默认", meta.euler_rotation],
    ])

    _docx_add_heading(doc, "坐标系清单", 1)
    _docx_add_table(doc, ["id", "名称", "轴向", "各轴定义"], [
        [frame.id, frame.name or "—", frame.axis, frame.definition or "—"]
        for frame in ledger.frames()
    ])

    if query_result is not None:
        _docx_add_heading(doc, "查询变换", 1)
        doc.add_paragraph(
            f"T_{query_result.target}_{query_result.source}"
            f"（{query_result.source} → {query_result.target}）"
        )
        doc.add_paragraph(f"路径：{' → '.join(query_result.path)}")
        doc.add_paragraph(f"当前值来源：{query_result.source_line()}")
        doc.add_paragraph(
            f"σ：平移 {query_result.sigma_t_m * 1000:.4g} mm，"
            f"旋转 {query_result.sigma_r_arcsec:.4g}″"
        )
        matrix = query_result.matrix
        _docx_add_table(
            doc,
            ["", "c1", "c2", "c3", "c4"],
            [[f"r{row + 1}"] + [f"{matrix[row, col]:.6g}" for col in range(4)]
             for row in range(4)],
        )
        doc.add_paragraph(
            "RPY（ZYX intrinsic, deg）："
            + fmt.fmt_vec3(query_result.rpy_deg, labels=("绕X", "绕Y", "绕Z"), unit="°", precision=4)
        )
        doc.add_paragraph(
            "四元数（wxyz）：" + fmt.fmt_quaternion(query_result.quaternion, order="wxyz")
        )

    if budget is not None:
        _docx_add_heading(doc, "误差预算分解", 1)
        _docx_add_table(
            doc,
            ["路径段", "平移σ(mm)", "旋转σ(″)", "方差占比", "对最终指向贡献(″)"],
            [
                [
                    segment.label + (" ← 主导段" if segment.dominant else ""),
                    f"{segment.sigma_t_m * 1000:.4g}",
                    f"{segment.sigma_r_arcsec:.4g}",
                    f"{segment.variance_share:.0%}",
                    f"{segment.contribution_arcsec:.4g}",
                ]
                for segment in budget.segments
            ],
        )
        if budget.dominant_highlight:
            doc.add_paragraph(
                f"注意：{budget.dominant_label} 主导合成误差（占比 {budget.dominant_share:.0%}）"
            )

    if review_bundle:
        compare = review_bundle.get("compare")
        if compare is not None:
            _docx_add_heading(doc, f"变换对比：{compare.baseline_id} vs {compare.candidate_id}", 1)
            _docx_add_table(
                doc,
                ["分量", "偏差 δ", "σ", "z=δ/σ", "判定"],
                [
                    [
                        f"{row.label}({'″' if row.name.startswith('rot_') else 'mm'})",
                        f"{row.delta:+.4g}",
                        f"{row.sigma:.4g}",
                        f"{row.z:+.3f}",
                        VERDICT_LABELS.get(row.verdict, row.verdict),
                    ]
                    for row in compare.rows
                ],
            )
            doc.add_paragraph(f"结论：{compare.conclusion}")
            for suggestion in compare.suggestions:
                doc.add_paragraph(suggestion, style="List Bullet")
        loops = review_bundle.get("loops")
        if loops is not None:
            _docx_add_heading(doc, "环路闭合自检", 1)
            doc.add_paragraph(loops.summary())
            for item in loops.items:
                doc.add_paragraph(item.describe(), style="List Bullet")
        limits = review_bundle.get("limits")
        if limits is not None:
            _docx_add_heading(doc, "限值符合性", 1)
            doc.add_paragraph(limits.summary())
            for item in limits.items:
                doc.add_paragraph(item.describe(), style="List Bullet")

    if vector_rows:
        _docx_add_heading(doc, "矢量跨系表达", 1)
        _docx_add_table(
            doc,
            ["坐标系", "x", "y", "z"],
            [[row["frame"], f"{row['x']:.6g}", f"{row['y']:.6g}", f"{row['z']:.6g}"]
             for row in vector_rows],
        )

    if screenshot_path and os.path.isfile(screenshot_path):
        _docx_add_heading(doc, "3D 截图", 1)
        doc.add_picture(screenshot_path)

    doc.add_paragraph("")
    doc.add_paragraph(FOOTER_NOTE)

    directory = os.path.dirname(os.path.abspath(filepath))
    os.makedirs(directory, exist_ok=True)
    doc.save(filepath)
    return filepath


def write_review_report_word(ledger, filepath: str,
                             compare: Optional[ComparisonResult] = None,
                             loops: Optional[LoopClosureReport] = None,
                             limits: Optional[LimitCheckReport] = None) -> str:
    """F7 的 Word 版本。"""
    from docx import Document

    meta = ledger.meta
    doc = Document()
    doc.add_heading(f"坐标系复核报告：{meta.name}", level=0)
    _docx_add_table(doc, ["项目", "值"], [
        ["账本版本", meta.version],
        ["复核范围", "D7 变换对比 / D8 环路闭合 / D9 限值符合性"],
    ])

    if compare is not None:
        _docx_add_heading(doc, f"变换对比：{compare.baseline_id} vs {compare.candidate_id}", 1)
        doc.add_paragraph(
            f"对比对象：{compare.baseline_id}（{fmt.fmt_status(compare.baseline_status)}｜{compare.baseline_source or '无'}）"
            f" → {compare.candidate_id}（{fmt.fmt_status(compare.candidate_status)}｜{compare.candidate_source or '无'}）"
        )
        _docx_add_table(
            doc,
            ["分量", "偏差 δ", "σ", "z=δ/σ", "判定"],
            [
                [
                    f"{row.label}({'″' if row.name.startswith('rot_') else 'mm'})",
                    f"{row.delta:+.4g}",
                    f"{row.sigma:.4g}",
                    f"{row.z:+.3f}",
                    VERDICT_LABELS.get(row.verdict, row.verdict),
                ]
                for row in compare.rows
            ],
        )
        doc.add_paragraph(f"结论：{compare.conclusion}")
        for suggestion in compare.suggestions:
            doc.add_paragraph(suggestion, style="List Bullet")

    if loops is not None:
        _docx_add_heading(doc, "环路闭合自检", 1)
        doc.add_paragraph(loops.summary())
        for item in loops.items:
            doc.add_paragraph(item.describe(), style="List Bullet")

    if limits is not None:
        _docx_add_heading(doc, "限值符合性", 1)
        doc.add_paragraph(limits.summary())
        for item in limits.items:
            doc.add_paragraph(item.describe(), style="List Bullet")

    doc.add_paragraph("")
    doc.add_paragraph(FOOTER_NOTE)
    directory = os.path.dirname(os.path.abspath(filepath))
    os.makedirs(directory, exist_ok=True)
    doc.save(filepath)
    return filepath
