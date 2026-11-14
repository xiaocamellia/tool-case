"""面向界面 / CLI / 报告的可读性格式化（不倾倒原始 tuple / dict）。

约定与展示口径（与 6.6.2 表格一致）：
- 平移与 σ_t 用 mm 展示；旋转与 σ_r 用角秒 ″ 或度 °；
- 欧拉角按账本 value 顺序展示，轴标来自 ``order`` 字母逆序
  （ZYX → value=[绕X, 绕Y, 绕Z]，见 conventions.to_scipy_seq 文档）；
- 状态附中文含义：design=设计值 / calibrated=标定值 / as_built=实装值。
"""

from __future__ import annotations

import math
import unicodedata
from typing import Iterable, Sequence

STATUS_LABELS = {
    "design": "设计值",
    "calibrated": "标定值",
    "as_built": "实装值",
    "obsolete": "作废",
}
ROTATION_KIND_LABELS = {
    "rpy": "欧拉角",
    "euler": "欧拉角",
    "quaternion": "四元数",
    "matrix": "旋转矩阵",
}
UNIT_LABELS = {"deg": "°", "rad": "rad", "arcsec": "″", "m": "m", "mm": "mm"}


def fmt_number(value, precision: int = 6, trim: bool = True, tiny_tol: float = 1e-9) -> str:
    """有限浮点 → 紧凑数字文本（消除 0.0010000000000037544 类噪声）。"""
    number = float(value)
    if not math.isfinite(number):
        return str(number)
    if abs(number) < tiny_tol:
        return "0"
    text = f"{number:.{precision}g}"
    if trim and "." in text and "e" not in text:
        text = text.rstrip("0").rstrip(".")
    return text


def fmt_fixed(value, decimals: int = 4) -> str:
    """定小数位（表格对齐用），如 0.0010。"""
    return f"{float(value):.{decimals}f}"


def fmt_signed(value, decimals: int = 4) -> str:
    """带符号定小数位（偏差类数值），如 +2.0210 / -0.0012。"""
    return f"{float(value):+.{decimals}f}"


def fmt_vec3(values: Sequence, labels: Sequence[str] = ("X", "Y", "Z"),
             unit: str = "", precision: int = 4) -> str:
    """``X=0.000, Y=2.000, Z=1201.000 mm``。"""
    parts = [
        f"{label}={float(value):.{precision}f}"
        for label, value in zip(labels, values)
    ]
    return ", ".join(parts) + (f" {unit}" if unit else "")


def fmt_euler(values: Sequence, order: str = "ZYX",
              rotation_type: str = "intrinsic", unit: str = "deg") -> str:
    """``欧拉角 ZYX·内旋（deg）：绕X=0.001°, 绕Y=-0.001°, 绕Z=89.998°``。

    ``values`` 为账本 value 顺序（[α, β, γ]），轴标 = order 字母逆序。
    """
    order_text = (order or "ZYX").upper()
    axis_labels = [f"绕{letter}" for letter in reversed(order_text)]
    type_text = "内旋" if (rotation_type or "intrinsic").startswith("in") else "外旋"
    unit_text = UNIT_LABELS.get(unit, unit)
    parts = [
        f"{label}={fmt_number(value, precision=6)}{unit_text}"
        for label, value in zip(axis_labels, values)
    ]
    return f"欧拉角 {order_text}·{type_text}（{unit}）：" + ", ".join(parts)


def fmt_quaternion(values: Sequence, order: str = "wxyz") -> str:
    """``四元数(wxyz)：w=0.707107, x=0, y=0, z=0.707107``（定点 6 位小数）。"""
    order_text = (order or "wxyz").lower()
    labels = [letter for letter in order_text]
    parts = [
        f"{label}={float(value):.6f}"
        for label, value in zip(labels, values)
    ]
    return f"四元数（{order_text}）：" + ", ".join(parts)


def fmt_matrix(matrix, precision: int = 6, indent: str = "  ") -> str:
    """4×4 / 3×3 齐次矩阵的等宽多行文本。"""
    rows = []
    for row in matrix:
        cells = [f"{float(value): .{precision}f}" for value in row]
        rows.append(indent + " ".join(cells))
    return "\n".join(rows)


def fmt_rotation_spec(rotation: dict) -> str:
    """三种姿态输入形式的可读展示（不倾倒 dict）。"""
    kind = str(rotation.get("type", "")).lower()
    value = rotation.get("value", [])
    if kind in ("rpy", "euler"):
        return fmt_euler(
            value,
            order=rotation.get("order", "ZYX"),
            rotation_type=rotation.get("rotation_type", rotation.get("euler_rotation", "intrinsic")),
            unit=rotation.get("unit", "deg"),
        )
    if kind == "quaternion":
        return fmt_quaternion(value, order=rotation.get("order", "wxyz"))
    if kind == "matrix":
        values = list(value)
        if len(values) == 9:
            return "旋转矩阵（行优先 3×3）：\n" + fmt_matrix(
                [values[0:3], values[3:6], values[6:9]]
            )
        return "旋转矩阵：\n" + fmt_matrix(values)
    return f"旋转（{kind or '未知形式'}）"


def fmt_translation(translation: Sequence, unit: str = "m") -> str:
    """平移统一以 mm 展示（若原始单位为 mm 则原样）。"""
    scale = 1000.0 if unit == "m" else 1.0
    values = [float(item) * scale for item in translation]
    return fmt_vec3(values, unit="mm", precision=3)


def fmt_sigma(sigma_t: float, sigma_r_arcsec: float, unit: str = "m") -> str:
    """``平移 σ=0.400 mm，旋转 σ=1.80″``。CL-29: 单位跟随 to 系。"""
    # 内部统一存 m，按 unit 换算显示
    unit_factors = {"m": 1.0, "mm": 1000.0, "cm": 100.0}
    factor = unit_factors.get(unit, 1.0)
    display_val = float(sigma_t) * factor
    return (
        f"平移 σ={display_val:.3f} {unit}，"
        f"旋转 σ={float(sigma_r_arcsec):.2f}″"
    )


def fmt_status(status: str) -> str:
    """``标定值 · calibrated``（中英并列，不嵌套括号）。"""
    label = STATUS_LABELS.get(status, status)
    return f"{label} · {status}" if label != status else status


def fmt_frame_pair(pair: Sequence[str]) -> str:
    """``camera_panchro ↔ sar_antenna``。"""
    items = list(pair)
    return " ↔ ".join(str(item) for item in items)


def fmt_path(frames: Iterable[str]) -> str:
    return " → ".join(str(frame) for frame in frames)


def _display_width(text: str) -> int:
    """终端/等宽显示宽度：东亚宽字符按 2 计。"""
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)


def text_table(headers: Sequence[str], rows: Sequence[Sequence],
               aligns: Sequence[str] = (), indent: str = "") -> str:
    """中英混排对齐的等宽文本表格（属性/结果栏与 CLI 通用）。

    ``aligns`` 每列 'l' / 'r'，缺省首列左对齐、其余右对齐。
    """
    header_texts = [str(header) for header in headers]
    body = [[("" if cell is None else str(cell)) for cell in row] for row in rows]
    columns = len(header_texts)
    widths = [0] * columns
    for row in [header_texts] + body:
        for index in range(columns):
            widths[index] = max(widths[index], _display_width(row[index]))

    def render(row: Sequence[str]) -> str:
        cells = []
        for index, text in enumerate(row):
            pad = widths[index] - _display_width(text)
            mode = aligns[index] if index < len(aligns) else ("l" if index == 0 else "r")
            cells.append((" " * pad + text) if mode == "r" else (text + " " * pad))
        return indent + "  ".join(cells).rstrip()

    separator = indent + "  ".join("─" * width for width in widths)
    return "\n".join([render(header_texts), separator] + [render(row) for row in body])


def fmt_arcsec(value) -> str:
    return f"{float(value):.3f}″"


def fmt_mm(value) -> str:
    return f"{float(value):.4f} mm"


def fmt_deg(value) -> str:
    return f"{float(value):.6g}°"


# ---------------------------------------------------------------------------
# 条目详情文本（属性面板 / CLI 通用）
# ---------------------------------------------------------------------------


def frame_detail(frame) -> str:
    lines = [
        f"坐标系  {frame.id}",
        f"名称   {frame.name or '—'}",
        f"轴向   {frame.axis}",
        f"单位   {frame.unit}",
        f"各轴定义  {frame.definition or '—'}",
        f"备注   {frame.note or '—'}",
    ]
    return "\n".join(lines)


def ledger_detail(meta, frame_count: int, transform_count: int,
                  limit_count: int) -> str:
    judge = getattr(meta, "judge", None)
    lines = [
        f"账本   {meta.name}",
        f"版本   {meta.version}",
        f"单位   {meta.unit_default} / {meta.angle_default}",
        f"四元数顺序 {meta.quaternion_order}",
        f"欧拉角   默认{meta.euler_rotation}",
    ]
    if judge is not None:
        lines.append(f"判定阈值  关注 {fmt_number(judge.warn_sigma, 4)}σ ／ 超差 {fmt_number(judge.fail_sigma, 4)}σ")
    lines.append(f"规模   {frame_count} 个坐标系 ／ {transform_count} 条变换 ／ {limit_count} 条限值")
    lines.append(f"备注   {meta.note or '—'}")
    return "\n".join(lines)


def transform_detail(record, meta=None, unit=None) -> str:
    """CL-04: unit 参数控制显示单位（跟随 to 系）。"""
    if unit is None:
        if meta is not None:
            unit = getattr(meta, "unit_default", "m")
        else:
            unit = "m"
    lines = [
        f"变换   {record.id}",
        f"关系   {record.matrix_label()}",
        f"状态   {fmt_status(record.status)}",
        f"来源   {record.source or '—'}",
        f"生效   {record.effective or '—'}",
        f"平移   {fmt_translation(record.translation, unit=unit)}",
        f"旋转   {fmt_rotation_spec(record.rotation)}",
        f"误差   {fmt_sigma(record.sigma.t, record.sigma.r_arcsec, unit=unit)}",  # CL-29
        f"备注   {record.note or '—'}",
    ]
    return "\n".join(lines)


def limit_detail(limit) -> str:
    kind_labels = {
        "angle_between": "两轴夹角",
        "rotation_delta": "旋转差异",
        "translation_delta": "平移差异",
    }
    lines = [
        f"限值   {limit.id}",
        f"类型   {kind_labels.get(limit.kind, limit.kind)}（{limit.kind}）",
        f"对象   {fmt_frame_pair(limit.frames)}",
        f"期望   {fmt_number(limit.expected, 6)}±{fmt_number(limit.tolerance, 6)} {limit.unit}",
        f"备注   {limit.note or '—'}",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 结果块（属性/结果栏与 CLI 共用）
# ---------------------------------------------------------------------------

VERDICT_TEXTS = {"ok": "正常", "warn": "关注", "fail": "超差"}


def query_result_text(result) -> str:
    """D1 查询结果卡：关系 / 路径 / 来源 / 矩阵 / 姿态 / 误差。"""
    lines = [
        f"【查询结果】T_{result.target}_{result.source}"
        f"（{result.source} → {result.target}）",
        f"路径       {fmt_path(result.path)}",
        f"当前值来源 {result.source_line()}",
        f"误差       {fmt_sigma(result.sigma_t_m, result.sigma_r_arcsec)}",
        f"姿态       {fmt_euler(result.rpy_deg, order='ZYX', rotation_type='intrinsic', unit='deg')}",
        f"           {fmt_quaternion(result.quaternion, order='wxyz')}",
        "齐次矩阵",
        fmt_matrix(result.matrix),
    ]
    return "\n".join(lines)


def comparison_result_text(result) -> str:
    """D7 对比结果块：分量对比表 + 自动结论句 + 处置建议（6.6.2/6.6.5）。"""
    rows = []
    for row in result.rows:
        unit = "″" if row.name.startswith("rot_") else "mm"
        rows.append([
            f"{row.label} ({unit})",
            f"{row.delta:+.4g}",
            f"{row.sigma:.4g}",
            f"{row.z:+.3f}",
            VERDICT_TEXTS.get(row.verdict, row.verdict),
            "← 最大偏差项" if row.name == result.worst_item else "",
        ])
    table = text_table(
        ["分量", "偏差 δ", "σ", "z=δ/σ", "判定", "备注"],
        rows,
        aligns=["l", "r", "r", "r", "l", "l"],
    )
    lines = [
        f"【变换对比】{result.baseline_id}（{fmt_status(result.baseline_status)}）"
        f"  vs  {result.candidate_id}（{fmt_status(result.candidate_status)}）",
        f"关系  T_{result.from_frame}_{result.to_frame}"
        f"（{result.to_frame} → {result.from_frame}）",
        f"判定  {VERDICT_TEXTS.get(result.overall, result.overall)}",
        "",
        table,
        "",
        f"结论  {result.conclusion}",
    ]
    if result.suggestions:
        lines.append("")
        lines.append("处置建议")
        for suggestion in result.suggestions:
            lines.append(f"  · {suggestion}")
    return "\n".join(lines)


def error_budget_result_text(budget) -> str:
    """D6 误差预算分解表 + 主导段提示（含页脚假设声明）。"""
    rows = []
    for segment in budget.segments:
        rows.append([
            segment.label + (" ← 主导段" if segment.dominant else ""),
            f"{segment.sigma_t_m * 1000:.4g}",
            f"{segment.sigma_r_arcsec:.4g}",
            f"{segment.variance_share:.0%}",
            f"{segment.contribution_arcsec:.4g}",
        ])
    rows.append([
        "合成（RSS）",
        f"{budget.sigma_t_total_m * 1000:.4g}",
        f"{budget.sigma_r_total_arcsec:.4g}",
        "100%",
        f"{budget.sigma_r_total_arcsec:.4g}",
    ])
    table = text_table(
        ["路径段", "平移σ(mm)", "旋转σ(″)", "方差占比", "贡献(″)"],
        rows,
        aligns=["l", "r", "r", "r", "r"],
    )
    lines = [
        f"【误差预算】{budget.source} → {budget.target}",
        table,
    ]
    if budget.dominant_highlight:
        lines.append("")
        lines.append(
            f"★ {budget.dominant_label} 主导合成误差（占比 {budget.dominant_share:.0%}），"
            "优先收紧该段的安装/标定精度。"
        )
    return "\n".join(lines)


def loop_report_text(report) -> str:
    """D8 环路闭合自检表。"""
    rows = []
    for item in report.items:
        rows.append([
            f"回路{item.index}",
            fmt_path(item.frames),
            f"{item.e_rot_arcsec:.3f}″",
            f"{item.threshold_rot_arcsec:.3f}″",
            f"{item.e_trans_mm:.4f} mm",
            f"{item.threshold_trans_mm:.4f} mm",
            "闭合 ✓" if item.closed else "不闭合 ✗",
        ])
    table = text_table(
        ["", "回路", "e_rot", "限值", "e_trans", "限值", "判定"],
        rows,
        aligns=["l", "l", "r", "r", "r", "r", "l"],
    )
    lines = [f"【环路闭合自检】{report.summary()}"
             f"（阈值 = 回路各边 σ RSS × {report.sigma_multiplier:g}）", "", table]
    failing = report.failing()
    if failing:
        lines.append("")
        lines.append("超差回路")
        for item in failing:
            lines.append(f"  · {item.describe()}")
            lines.append(f"    边: {'、'.join(item.edges)}")
    return "\n".join(lines)


def limit_report_text(report) -> str:
    """D9 限值符合性表。"""
    rows = []
    for item in report.items:
        rows.append([
            item.limit_id,
            item.description,
            f"{item.computed:.6g} {item.unit}",
            f"{item.deviation:+.6g} {item.unit}",
            f"{item.expected:.6g}±{item.tolerance:.6g} {item.unit}",
            "通过 ✓" if item.passed else "不通过 ✗",
        ])
    table = text_table(
        ["限值", "对象", "计算值", "偏差", "期望", "判定"],
        rows,
        aligns=["l", "l", "r", "r", "r", "l"],
    )
    return "\n".join([f"【限值符合性】{report.summary()}", "", table])
