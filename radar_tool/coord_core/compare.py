"""复核功能：D7 变换对比 / D8 环路闭合 / D9 限值符合性。

D7 判定依据为**本征差异视图**（与参数化方式无关）::

    ΔT = T_candidate · inv(T_baseline)
    δr = rotvec(ΔR)   分量单位 ″
    δt = Δt           分量单位 mm
    z = δ / σ，σ 缺省取 baseline 记录的 σ（各向同性标量）

判定分级：|z|<1 绿(ok)、1≤|z|<3 黄(warn)、|z|≥3 红(fail)。
结论句由工具自动生成，界面与报告同文，不允许手写覆盖。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from ..errors import ValidationError
from .conventions import (
    angle_from_radians,
    length_from_meters,
    principal_axis_vector,
)
from .graph import TransformGraph
from .schema import JudgeThresholds, LedgerDocument, Limit, TransformRecord
from .transforms import (
    Attitude,
    angle_between_vectors,
    delta_transform,
    normalize_vector,
    rotvec_components_arcsec,
    split_transform,
)

COMPONENT_LABELS = {
    "rot_x": "绕X", "rot_y": "绕Y", "rot_z": "绕Z",
    "trans_x": "X", "trans_y": "Y", "trans_z": "Z",
}
VERDICT_LABELS = {"ok": "正常", "warn": "关注", "fail": "超差"}
COMPONENT_ORDER = ("rot_x", "rot_y", "rot_z", "trans_x", "trans_y", "trans_z")


# ---------------------------------------------------------------------------
# D7 变换对比
# ---------------------------------------------------------------------------


@dataclass
class ComponentRow:
    name: str                 # rot_x / trans_y / …
    label: str                # 绕X / Y / …
    unit: str                 # ″ 或 mm
    design_value: Optional[float]   # 参数视图（可空）
    measured_value: Optional[float]
    delta: float              # 本征差异 δ
    sigma: float
    z: float
    verdict: str              # ok / warn / fail


@dataclass
class ComparisonResult:
    baseline_id: str
    candidate_id: str
    baseline_status: str
    candidate_status: str
    baseline_source: str
    candidate_source: str
    from_frame: str
    to_frame: str
    delta_rot_arcsec: Tuple[float, float, float]
    delta_trans_mm: Tuple[float, float, float]
    sigma_r_arcsec: float
    sigma_t_mm: float
    z_scores: Dict[str, float]
    verdicts: Dict[str, str]
    rows: List[ComponentRow] = field(default_factory=list)
    worst_item: str = ""
    worst_z: float = 0.0
    conclusion: str = ""
    suggestions: List[str] = field(default_factory=list)
    limits_overlay: List[dict] = field(default_factory=list)

    @property
    def overall(self) -> str:
        values = set(self.verdicts.values())
        if "fail" in values:
            return "fail"
        if "warn" in values:
            return "warn"
        return "ok"

    @property
    def overall_label(self) -> str:
        return VERDICT_LABELS[self.overall]

    def has_fail(self) -> bool:
        return self.overall == "fail"


def compare_transform_records(
    baseline: TransformRecord,
    candidate: TransformRecord,
    meta=None,
    judge: Optional[JudgeThresholds] = None,
    sigma_basis: str = "baseline",
) -> ComparisonResult:
    """对比两条变换记录（典型 design vs calibrated）。

    ``sigma_basis``：归一化 σ 取值口径——
    ``baseline``（缺省，与 6.6.2 示例一致）/ ``candidate`` / ``rss``。
    """
    from .schema import LedgerMeta

    meta = meta or LedgerMeta()
    judge = judge or meta.judge
    t_baseline = baseline.homogeneous(meta)
    t_candidate = candidate.homogeneous(meta)
    delta = delta_transform(t_candidate, t_baseline)
    delta_attitude, delta_trans_m = split_transform(delta)

    delta_rot = rotvec_components_arcsec(delta_attitude)
    delta_trans = tuple(float(length_from_meters(value, "mm")) for value in delta_trans_m)

    sigma_r, sigma_t_m = _comparison_sigma(baseline, candidate, sigma_basis)
    sigma_t_mm = sigma_t_m * 1000.0

    values = {
        "rot_x": delta_rot[0], "rot_y": delta_rot[1], "rot_z": delta_rot[2],
        "trans_x": delta_trans[0], "trans_y": delta_trans[1], "trans_z": delta_trans[2],
    }
    sigmas = {
        "rot_x": sigma_r, "rot_y": sigma_r, "rot_z": sigma_r,
        "trans_x": sigma_t_mm, "trans_y": sigma_t_mm, "trans_z": sigma_t_mm,
    }
    units = {
        "rot_x": "″", "rot_y": "″", "rot_z": "″",
        "trans_x": "mm", "trans_y": "mm", "trans_z": "mm",
    }

    z_scores: Dict[str, float] = {}
    verdicts: Dict[str, str] = {}
    rows: List[ComponentRow] = []
    for name in COMPONENT_ORDER:
        delta_value = values[name]
        sigma_value = sigmas[name]
        z = (delta_value / sigma_value) if sigma_value > 0 else (0.0 if abs(delta_value) < 1e-15 else math.copysign(math.inf, delta_value))
        verdict = judge.verdict(z) if math.isfinite(z) else "fail"
        z_scores[name] = float(z)
        verdicts[name] = verdict
        rows.append(ComponentRow(
            name=name,
            label=COMPONENT_LABELS[name],
            unit=units[name],
            design_value=None,
            measured_value=None,
            delta=float(delta_value),
            sigma=float(sigma_value),
            z=float(z),
            verdict=verdict,
        ))

    worst_name = max(COMPONENT_ORDER, key=lambda name: abs(z_scores[name]))
    worst_z = z_scores[worst_name]

    result = ComparisonResult(
        baseline_id=baseline.id,
        candidate_id=candidate.id,
        baseline_status=baseline.status,
        candidate_status=candidate.status,
        baseline_source=baseline.source,
        candidate_source=candidate.source,
        from_frame=baseline.from_frame,
        to_frame=baseline.to_frame,
        delta_rot_arcsec=(delta_rot[0], delta_rot[1], delta_rot[2]),
        delta_trans_mm=(delta_trans[0], delta_trans[1], delta_trans[2]),
        sigma_r_arcsec=float(sigma_r),
        sigma_t_mm=float(sigma_t_mm),
        z_scores=z_scores,
        verdicts=verdicts,
        rows=rows,
        worst_item=worst_name,
        worst_z=float(worst_z),
    )
    result.conclusion = build_conclusion(result)
    result.suggestions = match_disposition_patterns(result)
    return result


def _comparison_sigma(
    baseline: TransformRecord,
    candidate: TransformRecord,
    sigma_basis: str,
) -> Tuple[float, float]:
    if sigma_basis == "candidate":
        return candidate.sigma.r_arcsec, candidate.sigma.t
    if sigma_basis == "rss":
        r = math.hypot(baseline.sigma.r_arcsec, candidate.sigma.r_arcsec)
        t = math.hypot(baseline.sigma.t, candidate.sigma.t)
        return r, t
    if sigma_basis != "baseline":
        raise ValidationError(f"未知 sigma_basis: {sigma_basis}")
    return baseline.sigma.r_arcsec, baseline.sigma.t


def build_conclusion(result: ComparisonResult) -> str:
    """自动生成结论句（6.6.2，界面与报告同文）。"""
    worst = result.worst_item
    worst_row = next(row for row in result.rows if row.name == worst)
    parts = [
        f"最大偏差项：{worst_row.label} 轴 {worst_row.delta:+.3g}{worst_row.unit}"
        if worst.startswith("rot_") else
        f"最大偏差项：{worst_row.label} 向 {worst_row.delta:+.3g}{worst_row.unit}"
    ]
    parts[0] += f"（{abs(worst_row.z):.2f}σ，{VERDICT_LABELS[worst_row.verdict]}）"

    secondary = [
        row for row in result.rows
        if row.name != worst and row.verdict in ("warn", "fail")
    ]
    if secondary:
        bits = []
        for row in secondary:
            direction = "轴" if row.name.startswith("rot_") else "向"
            bits.append(f"{row.label}{direction} {row.delta:+.3g}{row.unit}（{abs(row.z):.2f}σ）")
        parts.append("次要关注：" + "、".join(bits))

    ok_rows = [row for row in result.rows if row.verdict == "ok" and row.name != worst]
    if ok_rows:
        if not secondary and worst_row.verdict == "ok":
            parts.append("全部分量均在 1σ 内")
        else:
            parts.append(f"其余 {len(ok_rows)} 个分量均在 1σ 内")

    if result.overall == "fail":
        axis_hint = "旋转" if result.worst_item.startswith("rot_") else "平移"
        axis_name = COMPONENT_LABELS[result.worst_item]
        parts.append(
            f"建议优先核查 {result.from_frame} → {result.to_frame} "
            f"{axis_name} 向{axis_hint}的安装/标定状态"
        )
    elif result.overall == "warn":
        parts.append("建议复测确认后再更新当前有效值")

    return "；".join(parts) + "。"


def match_disposition_patterns(result: ComparisonResult) -> List[str]:
    """按 6.6.4 判读经验表匹配处置建议（命中才附上）。"""
    suggestions: List[str] = []
    rot_fails = [row for row in result.rows if row.name.startswith("rot_") and row.verdict == "fail"]
    rot_oks = [row for row in result.rows if row.name.startswith("rot_") and row.verdict == "ok"]
    trans_fails = [row for row in result.rows if row.name.startswith("trans_") and row.verdict == "fail"]
    trans_warns = [row for row in result.rows if row.name.startswith("trans_") and row.verdict == "warn"]

    if len(rot_fails) == 1 and len(rot_oks) == 2:
        suggestions.append(
            "偏差模式：单轴旋转超差，其余轴正常——可能原因：该轴向安装错位、标定基准错、"
            "螺钉未按力矩拧紧。建议动作：专项核查该轴安装与标定基准。"
        )
    if len(trans_fails) == 1 and len(trans_warns) == 0 and not rot_fails:
        suggestions.append(
            "偏差模式：平移偏差集中在单一方向——可能原因：安装面变形、垫片/支架误差。"
            "建议动作：查结构件与安装面。"
        )
    if rot_fails and trans_fails:
        suggestions.append(
            "偏差模式：旋转与平移偏差同时超差——可能原因：同一次装调操作引入（如偏心安装）。"
            "建议动作：复装后复测，成对复核。"
        )
    if result.overall == "ok":
        suggestions.append(
            "偏差模式：三轴旋转与平移均在 1σ 内——正常标定残差。建议动作：接受，更新状态。"
        )
    return suggestions


# ---------------------------------------------------------------------------
# D8 环路闭合
# ---------------------------------------------------------------------------


@dataclass
class LoopClosureItem:
    index: int
    edges: List[str]                 # 记录 id（含方向标注）
    frames: List[str]
    e_rot_arcsec: float
    e_trans_mm: float
    threshold_rot_arcsec: float
    threshold_trans_mm: float
    closed: bool

    def describe(self) -> str:
        route = " → ".join(self.frames) if self.frames else ""
        status = "闭合 ✓" if self.closed else "不闭合 ✗"
        return (
            f"回路{self.index}: {route} | "
            f"e_rot={self.e_rot_arcsec:.3f}″ (限 {self.threshold_rot_arcsec:.3f}″) | "
            f"e_trans={self.e_trans_mm:.4f}mm (限 {self.threshold_trans_mm:.4f}mm) | {status}"
        )


@dataclass
class LoopClosureReport:
    items: List[LoopClosureItem] = field(default_factory=list)
    sigma_multiplier: float = 3.0

    @property
    def total(self) -> int:
        return len(self.items)

    @property
    def closed_count(self) -> int:
        return sum(1 for item in self.items if item.closed)

    @property
    def all_closed(self) -> bool:
        return all(item.closed for item in self.items)

    def summary(self) -> str:
        return f"环路 {self.closed_count}/{self.total} 闭合"

    def failing(self) -> List[LoopClosureItem]:
        return [item for item in self.items if not item.closed]


def loop_closure(
    document: LedgerDocument,
    graph: Optional[TransformGraph] = None,
    sigma_multiplier: float = 3.0,
    loops: Optional[Sequence[Sequence[Tuple[str, str]]]] = None,
) -> LoopClosureReport:
    """全账本环路自检（D8）。

    阈值缺省取回路各边 σ 的 RSS 合成 × ``sigma_multiplier``（3σ 原则）。
    ``loops`` 可指定回路（每个回路为 ``(u, v)`` 边序列）；缺省用基本回路。
    """
    graph = graph or TransformGraph(document)
    report = LoopClosureReport(sigma_multiplier=sigma_multiplier)

    if loops is None:
        cycles = graph.fundamental_cycles()
    else:
        cycles = [
            [(u, v, graph._edge_between(u, v)) for (u, v) in loop]
            for loop in loops
        ]

    for index, cycle in enumerate(cycles, start=1):
        if not cycle:
            continue
        # 每条边 (u, v) 把 p_u 变到 v 系；绕回路一圈应得单位阵，
        # 乘积顺序与行走方向相反：M_last · … · M_first。
        matrices = [graph.edge_matrix(u, v) for (u, v, _segment) in cycle]
        loop_matrix = matrices[-1]
        for matrix in reversed(matrices[:-1]):
            loop_matrix = loop_matrix @ matrix
        report.items.append(_build_loop_item(index, cycle, loop_matrix, sigma_multiplier))

    return report


def _build_loop_item(index, cycle, loop_matrix, sigma_multiplier) -> LoopClosureItem:
    loop_array = np.asarray(loop_matrix, dtype=float)
    attitude = Attitude.from_matrix(loop_array[:3, :3], validate=False)
    trans_m = loop_array[:3, 3]
    e_rot = attitude.magnitude("arcsec")
    e_trans_mm = float(np.linalg.norm(trans_m)) * 1000.0

    r_var = sum(segment.sigma_r_arcsec ** 2 for _u, _v, segment in cycle)
    t_var = sum(segment.sigma_t_m ** 2 for _u, _v, segment in cycle)
    threshold_rot = sigma_multiplier * math.sqrt(r_var)
    threshold_trans = sigma_multiplier * math.sqrt(t_var) * 1000.0

    closed = e_rot <= threshold_rot and e_trans_mm <= max(threshold_trans, 1e-12)
    frames = [cycle[0][0]] + [v for (_u, v, _segment) in cycle]
    edges = [
        f"{segment.record_id}{'（取逆）' if segment.reversed else ''}"
        for (_u, _v, segment) in cycle
    ]

    return LoopClosureItem(
        index=index,
        edges=edges,
        frames=frames,
        e_rot_arcsec=float(e_rot),
        e_trans_mm=float(e_trans_mm),
        threshold_rot_arcsec=float(threshold_rot),
        threshold_trans_mm=float(threshold_trans),
        closed=closed,
    )


# ---------------------------------------------------------------------------
# D9 限值符合性
# ---------------------------------------------------------------------------


@dataclass
class LimitCheckItem:
    limit_id: str
    kind: str
    description: str
    computed: float
    expected: float
    tolerance: float
    unit: str
    deviation: float
    passed: bool
    note: str = ""

    def describe(self) -> str:
        verdict = "通过 ✓" if self.passed else "不通过 ✗"
        return (
            f"{self.limit_id}: 计算值 {self.computed:.6g}{self.unit}，"
            f"期望 {self.expected:.6g}±{self.tolerance:.6g}{self.unit}，"
            f"偏差 {self.deviation:+.6g}{self.unit} | {verdict}"
        )


@dataclass
class LimitCheckReport:
    items: List[LimitCheckItem] = field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        return all(item.passed for item in self.items)

    def summary(self) -> str:
        passed = sum(1 for item in self.items if item.passed)
        return f"限值 {passed}/{len(self.items)} 通过"


def check_limits(
    document: LedgerDocument,
    graph: Optional[TransformGraph] = None,
    limits: Optional[Sequence[Limit]] = None,
    judge: Optional[JudgeThresholds] = None,
) -> LimitCheckReport:
    """全部（或指定）限值符合性检查（D9）。"""
    graph = graph or TransformGraph(document)
    meta = document.meta
    judge = judge or meta.judge
    report = LimitCheckReport()
    transform_map = document.transform_map()
    frame_map = document.frame_map()

    for limit in (limits if limits is not None else document.limits):
        if limit.kind == "angle_between":
            item = _check_angle_between(limit, document, graph, frame_map)
        elif limit.kind in ("rotation_delta", "translation_delta"):
            item = _check_transform_delta(limit, meta, judge, transform_map)
        else:
            raise ValidationError(f"未知限值类型: {limit.kind}")
        report.items.append(item)
    return report


def _check_angle_between(limit: Limit, document, graph, frame_map) -> LimitCheckItem:
    frame_a, frame_b = limit.frames
    for frame_id in (frame_a, frame_b):
        if frame_id not in frame_map:
            raise ValidationError(f"限值 {limit.id} 引用不存在的坐标系: {frame_id}")
    axis_a = principal_axis_vector(frame_map[frame_a].axis)
    axis_b = principal_axis_vector(frame_map[frame_b].axis)
    # 把 B 系主轴变换到 A 系下求夹角（与参考系无关）
    path = graph.resolve(frame_b, frame_a)
    from .transforms import split_transform as _split

    attitude, _trans = _split(path.matrix)
    axis_b_in_a = normalize_vector(attitude.apply(axis_b))
    angle_rad = angle_between_vectors(axis_a, axis_b_in_a)
    computed = angle_from_radians(angle_rad, limit.unit)
    deviation = computed - limit.expected
    passed = abs(deviation) <= limit.tolerance + 1e-12
    return LimitCheckItem(
        limit_id=limit.id,
        kind=limit.kind,
        description=f"{frame_a} 与 {frame_b} 主轴夹角",
        computed=float(computed),
        expected=limit.expected,
        tolerance=limit.tolerance,
        unit=limit.unit,
        deviation=float(deviation),
        passed=passed,
        note=limit.note,
    )


def _check_transform_delta(limit: Limit, meta, judge, transform_map) -> LimitCheckItem:
    id_a, id_b = limit.frames
    for transform_id in (id_a, id_b):
        if transform_id not in transform_map:
            raise ValidationError(f"限值 {limit.id} 引用不存在的变换: {transform_id}")
    record_a = transform_map[id_a]
    record_b = transform_map[id_b]
    t_a = record_a.homogeneous(meta)
    t_b = record_b.homogeneous(meta)
    delta = delta_transform(t_a, t_b)
    attitude, trans_m = split_transform(delta)
    if limit.kind == "rotation_delta":
        raw = attitude.magnitude("rad")
        computed = angle_from_radians(raw, limit.unit)
        description = f"{id_a} 与 {id_b} 旋转差异"
    else:
        raw = float(np.linalg.norm(trans_m))
        computed = length_from_meters(raw, limit.unit)
        description = f"{id_a} 与 {id_b} 平移差异"
    deviation = computed - limit.expected
    passed = abs(deviation) <= limit.tolerance + 1e-12
    return LimitCheckItem(
        limit_id=limit.id,
        kind=limit.kind,
        description=description,
        computed=float(computed),
        expected=limit.expected,
        tolerance=limit.tolerance,
        unit=limit.unit,
        deviation=float(deviation),
        passed=passed,
        note=limit.note,
    )
