"""坐标系账本 SDK 入口（设计文档 8.1）。

    from radar_tool.coord_core import Ledger

    led = Ledger.load("ledger.json")
    led.validate()
    led.build_graph()
    tf = led.query("camera_panchro", "sar_antenna")   # T_camera_sar
    ...

约定：``query(A, B)`` 返回 ``T_A_B``，即 ``p_A = T · p_B``
（"把 B 系下的量变换到 A 系"，设计文档 2.1）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from ..errors import ValidationError
from . import codegen as codegen_module
from . import report as report_module
from .compare import (
    ComparisonResult,
    LimitCheckReport,
    LoopClosureReport,
    check_limits as check_limits_impl,
    compare_transform_records,
    loop_closure as loop_closure_impl,
)
from .conventions import (
    angle_from_radians,
    normalize_status,
)
from .error_budget import ErrorBudget, compute_error_budget
from .graph import PathSegment, TransformGraph, TransformPath
from .schema import (
    Frame,
    LedgerDocument,
    LedgerMeta,
    Limit,
    TransformRecord,
    ValidationResult,
    make_blank_document,
    make_sample_document,
)
from .storage import load_document, merge_documents, save_document, write_template
from .transforms import (
    normalize_vector,
    split_transform,
    transform_points,
    transform_vector,
)


@dataclass
class QueryResult:
    """两系变换查询结果（D1）。"""

    target: str
    source: str
    matrix: np.ndarray
    rpy_deg: Tuple[float, float, float]
    quaternion: Tuple[float, float, float, float]     # wxyz
    sigma_t_m: float
    sigma_r_arcsec: float
    path: List[str]                                   # [source, ..., target]
    segments: List[PathSegment] = field(default_factory=list)
    transform_id: str = ""                            # 直接边时为该记录 id
    status: str = ""                                  # 当前有效值状态（多跳为组合描述）
    source_note: str = ""                             # 当前有效值来源
    strategy: str = "min_error"

    @property
    def sigma(self) -> Tuple[float, float]:
        return (self.sigma_t_m, self.sigma_r_arcsec)

    def source_line(self) -> str:
        """当前值出处（强制显示，闭环痛点 1）。"""
        from .formatting import fmt_status

        if self.transform_id:
            return f"{self.transform_id}（{fmt_status(self.status)}｜{self.source_note or '无来源标注'}）"
        if not self.segments:
            return "恒等变换"
        parts = [
            f"{segment.record_id}（{fmt_status(segment.status)}｜{segment.source or '无来源标注'}）"
            for segment in self.segments
        ]
        return " ⊕ ".join(parts)


@dataclass
class VectorExpression:
    frame: str
    vector: Tuple[float, float, float]


@dataclass
class PointingResult:
    load_frame: str
    ref_frame: str
    azimuth_deg: float
    elevation_deg: float
    deviation_deg: float
    target_in_load: Tuple[float, float, float]


@dataclass
class TransformPointResult:
    source: str
    target: str
    points: np.ndarray


class Ledger:
    """坐标系账本：读写、求解、复核、导出的统一入口。"""

    def __init__(self, document: LedgerDocument, path: str = "", read_only: bool = False):
        self.document = document
        self.path = path
        self.read_only = read_only  # CL-01: 只读标志
        self._graphs: Dict[Optional[str], TransformGraph] = {}
        self._validation: Optional[ValidationResult] = None

    def _ensure_writable(self):
        """CL-01: 只读账本拒绝写入。"""
        if self.read_only:
            raise ReadOnlyLedgerError('示例账本为只读，请先「清空并开始」或另存为新账本')

    # --- 装载 ---

    @classmethod
    def load(cls, filepath: str) -> "Ledger":
        return cls(load_document(filepath), path=filepath)

    @classmethod
    def from_dict(cls, payload: dict) -> "Ledger":
        return cls(LedgerDocument.from_dict(payload))

    @classmethod
    def sample(cls) -> "Ledger":
        return cls(make_sample_document(), read_only=True)  # CL-01

    @classmethod
    def blank(cls, name: str = "新建坐标系账本") -> "Ledger":
        return cls(make_blank_document(name))

    @classmethod
    def merge(cls, ledgers: Sequence["Ledger"], name: str = "合并账本") -> "Ledger":
        return cls(merge_documents([ledger.document for ledger in ledgers], name=name))

    def save(self, filepath: Optional[str] = None) -> str:
        self._ensure_writable()  # CL-01
        target = filepath or self.path
        if not target:
            raise ValidationError("未指定账本保存路径")
        save_document(self.document, target)
        self.path = target
        self._graphs.clear()
        return target

    def export_template(self, filepath: str, sample: bool = True) -> str:
        return write_template(filepath, sample=sample)

    # --- 校验与图 ---

    def validate(self) -> ValidationResult:
        self._validation = self.document.validate()
        return self._validation

    def invalidate(self) -> None:
        """账本内容变更后使图/校验缓存失效（下次查询时重建）。"""
        self._graphs.clear()
        self._validation = None

    def build_graph(self, status: Optional[str] = None) -> TransformGraph:
        if status is not None:
            status = normalize_status(status)
        graph = self._graphs.get(status)
        if graph is None:
            graph = TransformGraph(self.document, status=status)
            self._graphs[status] = graph
        return graph

    @property
    def meta(self) -> LedgerMeta:
        return self.document.meta

    def frames(self) -> List[Frame]:
        return list(self.document.frames)

    def transforms(self) -> List[TransformRecord]:
        return list(self.document.transforms)

    def limits(self) -> List[Limit]:
        return list(self.document.limits)

    def transform_records_between(self, from_frame: str, to_frame: str) -> List[TransformRecord]:
        """同一 ``(from, to)`` 的全部状态记录（多值共存视图）。"""
        return [
            record for record in self.document.transforms
            if record.from_frame == from_frame and record.to_frame == to_frame
        ]

    def current_record(self, from_frame: str, to_frame: str,
                       status: Optional[str] = None) -> Optional[TransformRecord]:
        """当前有效值：状态优先级最高者（obsolete 永不自动选中）。"""
        candidates = self.transform_records_between(from_frame, to_frame)
        if status is not None:
            status = normalize_status(status)
            candidates = [record for record in candidates if record.status == status]
        else:
            candidates = [record for record in candidates if record.status != "obsolete"]
        if not candidates:
            return None
        from .conventions import STATUS_PRIORITY

        candidates.sort(key=lambda record: (-STATUS_PRIORITY[record.status], record.id))
        return candidates[0]

    # --- D1 变换查询 ---

    def query(self, target: str, source: str,
              status: Optional[str] = None,
              strategy: str = "min_error") -> QueryResult:
        """返回 ``T_target_source``：``p_target = T · p_source``。"""
        graph = self.build_graph(status)
        path = graph.resolve(source, target, strategy)
        return self._query_result(path, strategy)

    def _query_result(self, path: TransformPath, strategy: str) -> QueryResult:
        attitude, _trans = split_transform(path.matrix)
        sigma_t, sigma_r = path.sigma_total()
        direct = None
        if len(path.segments) == 1:
            segment = path.segments[0]
            direct = self.document.transform_map().get(segment.record_id)
        if direct is not None:
            transform_id = direct.id
            status_text = direct.status
            source_note = direct.source
        else:
            transform_id = ""
            status_text = "/".join(sorted({segment.status for segment in path.segments})) or "identity"
            source_note = "；".join(
                f"{segment.record_id}:{segment.source or '无'}" for segment in path.segments
            )
        rpy = self._euler_deg(attitude)
        quaternion = attitude.quaternion_wxyz()
        return QueryResult(
            target=path.target,
            source=path.source,
            matrix=np.asarray(path.matrix, dtype=float),
            rpy_deg=(float(rpy[0]), float(rpy[1]), float(rpy[2])),
            quaternion=(float(quaternion[0]), float(quaternion[1]), float(quaternion[2]), float(quaternion[3])),
            sigma_t_m=sigma_t,
            sigma_r_arcsec=sigma_r,
            path=list(path.frames),
            segments=list(path.segments),
            transform_id=transform_id,
            status=status_text,
            source_note=source_note,
            strategy=strategy,
        )

    @staticmethod
    def _euler_deg(attitude) -> Tuple[float, float, float]:
        """ZYX intrinsic 角度回显；万向锁时 scipy 告警降噪，第三角按 0 处理。"""
        import warnings

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            return attitude.euler("ZYX", "intrinsic", "deg")

    # --- D2 矢量跨系 ---

    def transform_point(self, point, source: str, target: str,
                        status: Optional[str] = None):
        result = self.query(target, source, status=status)
        return transform_points(result.matrix, point)

    def transform_points(self, points, source: str, target: str,
                         status: Optional[str] = None) -> TransformPointResult:
        result = self.query(target, source, status=status)
        converted = transform_points(result.matrix, points)
        return TransformPointResult(source=source, target=target, points=converted)

    def transform_vector(self, vector, source: str, target: str,
                         status: Optional[str] = None):
        result = self.query(target, source, status=status)
        attitude, _ = split_transform(result.matrix)
        return transform_vector(attitude, vector)

    def express_vector(self, vector, source: str,
                       targets: Optional[Sequence[str]] = None,
                       to_all: bool = False,
                       status: Optional[str] = None) -> List[VectorExpression]:
        if to_all:
            targets = [frame.id for frame in self.document.frames]
        if not targets:
            raise ValidationError("请指定目标坐标系集合或使用 to_all=True")
        expressions = []
        for target in targets:
            try:
                converted = self.transform_vector(vector, source, target, status=status)
            except ValidationError:
                if to_all:
                    # 与源系不连通的系无法表达，跳过（如变换被删后的孤立系）
                    continue
                raise
            expressions.append(VectorExpression(
                frame=target,
                vector=(float(converted[0]), float(converted[1]), float(converted[2])),
            ))
        return expressions

    # --- D4 指向计算 ---

    def pointing(self, load_frame: str, axis, target_dir, ref: str,
                 status: Optional[str] = None) -> PointingResult:
        """``v_t' = T_load_ref · v_target``；Az/El 为 load 系下球坐标，θ 为偏离角。"""
        load_axis = normalize_vector(axis, "视轴")
        target = normalize_vector(target_dir, "目标方向")
        result = self.query(load_frame, ref, status=status)
        attitude, _ = split_transform(result.matrix)
        target_in_load = attitude.apply(target)
        target_in_load = normalize_vector(target_in_load)

        azimuth = math.atan2(float(target_in_load[1]), float(target_in_load[0]))
        elevation = math.asin(float(np.clip(target_in_load[2], -1.0, 1.0)))
        cosine = float(np.clip(np.dot(load_axis, target_in_load), -1.0, 1.0))
        deviation = math.acos(cosine)
        return PointingResult(
            load_frame=load_frame,
            ref_frame=ref,
            azimuth_deg=float(angle_from_radians(azimuth, "deg")),
            elevation_deg=float(angle_from_radians(elevation, "deg")),
            deviation_deg=float(angle_from_radians(deviation, "deg")),
            target_in_load=(float(target_in_load[0]), float(target_in_load[1]), float(target_in_load[2])),
        )

    # --- D5 姿态需求反算 ---

    def required_body_attitude(self, load_frame: str, axis, target_dir, ref: str,
                               status: Optional[str] = None):
        """D5：目标指向 → 所需本体姿态四元数（wxyz）。

        求 ``R_body_ref`` 使载荷视轴 ``axis``（load 系）指向 ``ref`` 系下的
        ``target_dir``；自由度（绕视轴滚转）取最小转角解。
        """
        from scipy.spatial.transform import Rotation

        load_axis = normalize_vector(axis, "视轴")
        target = normalize_vector(target_dir, "目标方向")
        # 视轴在本体系下的方向
        load_from_body = self.query(load_frame, "body", status=status)
        attitude_load_body, _ = split_transform(load_from_body.matrix)
        boresight_in_body = normalize_vector(attitude_load_body.matrix().T @ load_axis)
        # R_body_ref · target = boresight_in_body（最小转角）
        rotation, _rssd = Rotation.align_vectors(
            boresight_in_body.reshape(1, 3), target.reshape(1, 3)
        )
        x, y, z, w = rotation.as_quat()
        return (float(w), float(x), float(y), float(z))

    # --- D3 批量转换 ---

    def transform_points_table(self, points, source: str, target: str,
                               status: Optional[str] = None) -> List[dict]:
        """D3：N×3 点集批量转换（逐点结果与向量化一致）。"""
        import numpy as np

        array = np.asarray(points, dtype=float)
        if array.ndim != 2 or array.shape[1] != 3:
            raise ValidationError("点集必须是 (N,3)")
        converted = self.transform_points(array, source, target, status=status).points
        return [
            {"x_in": float(row[0]), "y_in": float(row[1]), "z_in": float(row[2]),
             "x_out": float(out[0]), "y_out": float(out[1]), "z_out": float(out[2])}
            for row, out in zip(array, converted)
        ]

    def transform_csv_file(self, input_path: str, output_path: str,
                           source: str, target: str,
                           status: Optional[str] = None) -> str:
        """CSV（表头含 x,y,z）批量转换并写出（F2 家族）。"""
        import pandas as pd

        from ..export_safety import write_dataframe_csv

        dataframe = pd.read_csv(input_path)
        columns = {name.strip().lower(): name for name in dataframe.columns}
        if not all(key in columns for key in ("x", "y", "z")):
            raise ValidationError("CSV 需要 x,y,z 三列")
        points = dataframe[[columns["x"], columns["y"], columns["z"]]].to_numpy(dtype=float)
        rows = self.transform_points_table(points, source, target, status=status)
        write_dataframe_csv(pd.DataFrame(rows), output_path, index=False, encoding="utf-8-sig")
        return output_path

    # --- A6 批量导入 ---

    def import_transforms_csv(self, input_path: str) -> List[str]:
        """A6：CSV 批量导入变换记录（CAD 导出的安装矩阵批量入账）。

        支持两种旋转列：四元数 ``qw,qx,qy,qz`` 或矩阵 ``r00..r22``；
        平移列 ``tx,ty,tz``（m）；可选 ``sigma_t,sigma_r_arcsec,status,source,effective,note``。
        返回新增记录 id 列表。
        """
        import pandas as pd

        dataframe = pd.read_csv(input_path)
        columns = {name.strip().lower(): name for name in dataframe.columns}
        required = {"id", "from", "to", "tx", "ty", "tz"}
        missing = sorted(required - set(columns))
        if missing:
            raise ValidationError(f"CSV 缺少列: {', '.join(missing)}")
        has_quat = all(key in columns for key in ("qw", "qx", "qy", "qz"))
        has_matrix = all(f"r{i}{j}" in columns for i in range(3) for j in range(3))
        if not has_quat and not has_matrix:
            raise ValidationError("CSV 需要四元数列 (qw,qx,qy,qz) 或矩阵列 (r00..r22)")

        added: List[str] = []
        existing = set(self.document.transform_map())
        for index, row in dataframe.iterrows():
            if has_matrix:
                rotation = {
                    "type": "matrix",
                    "value": [float(row[columns[f"r{i}{j}"]]) for i in range(3) for j in range(3)],
                }
            else:
                rotation = {
                    "type": "quaternion", "order": "wxyz",
                    "value": [float(row[columns[key]]) for key in ("qw", "qx", "qy", "qz")],
                }
            payload = {
                "id": str(row[columns["id"]]),
                "from": str(row[columns["from"]]),
                "to": str(row[columns["to"]]),
                "rotation": rotation,
                "translation": [float(row[columns[key]]) for key in ("tx", "ty", "tz")],
                "sigma": {
                    "t": float(row[columns["sigma_t"]]) if "sigma_t" in columns else 0.0,
                    "r_arcsec": float(row[columns["sigma_r_arcsec"]])
                    if "sigma_r_arcsec" in columns else 0.0,
                },
                "status": str(row[columns["status"]]) if "status" in columns else "design",
            }
            for key in ("source", "effective", "note"):
                if key in columns and str(row[columns[key]]).strip() not in ("", "nan"):
                    payload[key] = str(row[columns[key]])
            record = TransformRecord.from_dict(payload, name=f"transforms[{index}]")
            if record.id in existing:
                raise ValidationError(f"导入冲突：变换 id 已存在 {record.id}")
            existing.add(record.id)
            self.document.transforms.append(record)
            added.append(record.id)
        self._graphs.clear()
        return added

    # --- D6 误差预算 ---

    def error_budget(self, source: str, target: str,
                     status: Optional[str] = None,
                     strategy: str = "min_error") -> ErrorBudget:
        graph = self.build_graph(status)
        path = graph.resolve(source, target, strategy)
        return compute_error_budget(path)

    # --- D7/D8/D9 复核 ---

    def compare_transforms(self, baseline_id: str, candidate_id: str,
                           sigma_basis: str = "baseline") -> ComparisonResult:
        transforms = self.document.transform_map()
        if baseline_id not in transforms:
            raise ValidationError(f"变换记录不存在: {baseline_id}")
        if candidate_id not in transforms:
            raise ValidationError(f"变换记录不存在: {candidate_id}")
        return compare_transform_records(
            transforms[baseline_id],
            transforms[candidate_id],
            meta=self.meta,
            judge=self.meta.judge,
            sigma_basis=sigma_basis,
        )

    def compare_status_pair(self, from_frame: str, to_frame: str,
                            baseline_status: str = "design",
                            candidate_status: str = "calibrated",
                            sigma_basis: str = "baseline") -> ComparisonResult:
        """同 ``(from,to)`` 两个状态的当前记录对比（流程 B）。"""
        baseline = self.current_record(from_frame, to_frame, status=baseline_status)
        candidate = self.current_record(from_frame, to_frame, status=candidate_status)
        if baseline is None:
            raise ValidationError(f"{from_frame}→{to_frame} 无 {baseline_status} 记录")
        if candidate is None:
            raise ValidationError(f"{from_frame}→{to_frame} 无 {candidate_status} 记录")
        return self.compare_transforms(baseline.id, candidate.id, sigma_basis=sigma_basis)

    def loop_closure(self, sigma_multiplier: float = 3.0) -> LoopClosureReport:
        graph = self.build_graph()
        return loop_closure_impl(self.document, graph, sigma_multiplier=sigma_multiplier)

    def check_limits(self) -> LimitCheckReport:
        graph = self.build_graph()
        return check_limits_impl(self.document, graph, judge=self.meta.judge)

    def health_summary(self) -> str:
        """面板状态栏健康度（6.5）。"""
        validation = self._validation or self.validate()
        loops = self.loop_closure()
        labeled = all(
            record.source for record in self.document.transforms
            if record.status != "obsolete"
        )
        return (
            f"校验 {len(validation.errors)} 错 {len(validation.warnings)} 警 │ "
            f"{loops.summary()} │ "
            f"当前值来源{'已' if labeled else '未'}标注"
        )

    # --- 导出 ---

    def export_matrix_table(self) -> List[dict]:
        return report_module.matrix_table_rows(self)

    def export_frames_table(self) -> List[dict]:
        return report_module.frame_table_rows(self)

    def export_vector_table(self, vector, source: str, targets=None) -> List[dict]:
        expressions = self.express_vector(vector, source, targets=targets, to_all=targets is None)
        return [
            {"frame": item.frame, "x": item.vector[0], "y": item.vector[1], "z": item.vector[2]}
            for item in expressions
        ]

    def export_codegen(self, language: str = "python", status: Optional[str] = None) -> str:
        return codegen_module.generate(self, language=language, status=status)

    def export_report_markdown(self, **options) -> str:
        return report_module.build_transform_report_markdown(self, **options)

    def export_review_markdown(self, **options) -> str:
        return report_module.build_review_report_markdown(self, **options)


class ReadOnlyLedgerError(Exception):
    """CL-01: 只读账本写入被拒绝。"""
