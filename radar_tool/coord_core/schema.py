"""坐标系账本数据模型与校验（对齐 schemas.py 风格）。

字段语义（设计文档 5.x）：

- ``T_from_to``：``p_from = T · p_to``，``from`` 为父系/结果系，``to`` 为子系/被变换系；
- ``translation``：子系（``to``）原点在父系（``from``）中的坐标，单位取 ``to`` 系 unit；
- 同一 ``(from, to)`` 允许多条记录（design / calibrated / …），查询缺省取
  状态优先级最高者（``as_built > calibrated > design > obsolete``）。
"""

from __future__ import annotations

import copy
import math
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from ..errors import ValidationError
from . import conventions as conv
from .transforms import Attitude, orthonormal_deviation, parse_rotation_spec

SCHEMA_NAME = "coordinate_ledger"
SCHEMA_VERSION = 1
_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,128}")


# ---------------------------------------------------------------------------
# 基础校验小工具（与 schemas.py 同风格）
# ---------------------------------------------------------------------------


def _require_mapping(value, name):
    if not isinstance(value, dict):
        raise ValidationError(f"{name} 必须是 JSON 对象")
    return value


def _require_text(value, name, allow_empty=True):
    if not isinstance(value, str):
        raise ValidationError(f"{name} 必须是字符串")
    normalized = value.strip()
    if not allow_empty and not normalized:
        raise ValidationError(f"{name} 不能为空")
    return normalized


def _optional_text(value, name):
    if value is None:
        return ""
    return _require_text(value, name)


def _require_id(value, name):
    normalized = _require_text(value, name, allow_empty=False)
    if not _ID_PATTERN.fullmatch(normalized):
        raise ValidationError(f"{name} 只能包含字母、数字、下划线或连字符")
    return normalized


def _finite_number(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(f"{name} 必须是有限数值")
    number = float(value)
    if not math.isfinite(number):
        raise ValidationError(f"{name} 必须是有限数值")
    return number


def _ensure_json_value(value, name, depth=0):
    if depth > 64:
        raise ValidationError(f"{name} 嵌套深度超过上限")
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        _finite_number(value, name)
        return
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str):
                raise ValidationError(f"{name} 的键必须是字符串")
            _ensure_json_value(child, f"{name}.{key}", depth + 1)
        return
    if isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _ensure_json_value(child, f"{name}[{index}]", depth + 1)
        return
    raise ValidationError(f"{name} 包含不能序列化的原始数据")


# ---------------------------------------------------------------------------
# 账本级配置
# ---------------------------------------------------------------------------


@dataclass
class JudgeThresholds:
    """对比判定阈值（σ 倍数），供 D7/D8/D9 共用（设计文档 5.1）。"""

    warn_sigma: float = 1.0
    fail_sigma: float = 3.0

    @classmethod
    def from_dict(cls, payload, name: str = "judge") -> "JudgeThresholds":
        if payload is None:
            return cls()
        data = _require_mapping(payload, name)
        warn = _finite_number(data.get("warn_sigma", 1.0), f"{name}.warn_sigma")
        fail = _finite_number(data.get("fail_sigma", 3.0), f"{name}.fail_sigma")
        if warn <= 0 or fail <= 0:
            raise ValidationError(f"{name} 阈值必须大于 0")
        if warn >= fail:
            raise ValidationError(f"{name}.warn_sigma 必须小于 fail_sigma")
        return cls(warn_sigma=warn, fail_sigma=fail)

    def to_dict(self) -> dict:
        return {"warn_sigma": self.warn_sigma, "fail_sigma": self.fail_sigma}

    def verdict(self, z_score: float) -> str:
        """|z| → ok / warn / fail。"""
        magnitude = abs(z_score)
        if magnitude < self.warn_sigma:
            return "ok"
        if magnitude < self.fail_sigma:
            return "warn"
        return "fail"


@dataclass
class LedgerMeta:
    name: str = "未命名账本"
    version: str = "1.0"
    unit_default: str = "m"
    angle_default: str = "deg"
    quaternion_order: str = "wxyz"
    euler_rotation: str = "intrinsic"
    judge: JudgeThresholds = field(default_factory=JudgeThresholds)
    note: str = ""

    @classmethod
    def from_dict(cls, payload, name: str = "ledger") -> "LedgerMeta":
        data = _require_mapping(payload if payload is not None else {}, name)
        unit = conv.normalize_length_unit(data.get("unit_default", "m"))
        angle = conv.normalize_angle_unit(data.get("angle_default", "deg"))
        quat_order = conv.normalize_quaternion_order(data.get("quaternion_order"))
        euler_rotation = data.get("euler_rotation", "intrinsic")
        if euler_rotation is not None:
            euler_rotation = conv.normalize_rotation_type(euler_rotation)
        else:
            euler_rotation = "intrinsic"
        return cls(
            name=_require_text(data.get("name", "未命名账本"), f"{name}.name") or "未命名账本",
            version=_require_text(data.get("version", "1.0"), f"{name}.version") or "1.0",
            unit_default=unit,
            angle_default=angle,
            quaternion_order=quat_order,
            euler_rotation=euler_rotation,
            judge=JudgeThresholds.from_dict(data.get("judge")),
            note=_optional_text(data.get("note"), f"{name}.note"),
        )

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "unit_default": self.unit_default,
            "angle_default": self.angle_default,
            "quaternion_order": self.quaternion_order,
            "euler_rotation": self.euler_rotation,
            "judge": self.judge.to_dict(),
            "note": self.note,
        }


# ---------------------------------------------------------------------------
# 坐标系
# ---------------------------------------------------------------------------


@dataclass
class Frame:
    id: str
    name: str = ""
    axis: str = "Z_UP"
    unit: str = "m"
    definition: str = ""
    note: str = ""

    @classmethod
    def from_dict(cls, payload, name: str = "frame") -> "Frame":
        data = _require_mapping(payload, name)
        frame_id = _require_id(data.get("id"), f"{name}.id")
        return cls(
            id=frame_id,
            name=_optional_text(data.get("name"), f"{name}.name"),
            axis=conv.normalize_axis_convention(data.get("axis")),
            unit=conv.normalize_length_unit(data.get("unit", "m")),
            definition=_optional_text(data.get("definition"), f"{name}.definition"),
            note=_optional_text(data.get("note"), f"{name}.note"),
        )

    def to_dict(self) -> dict:
        payload = {
            "id": self.id,
            "axis": self.axis,
            "unit": self.unit,
        }
        if self.name:
            payload["name"] = self.name
        if self.definition:
            payload["definition"] = self.definition
        if self.note:
            payload["note"] = self.note
        return payload


# ---------------------------------------------------------------------------
# 变换记录
# ---------------------------------------------------------------------------


@dataclass
class Sigma:
    t: float = 0.0          # 平移误差 1σ，内部单位 m
    r_arcsec: float = 0.0   # 旋转误差 1σ，角秒

    @classmethod
    def from_dict(cls, payload, name: str = "sigma") -> "Sigma":
        if payload is None:
            return cls()
        data = _require_mapping(payload, name)
        t_value = _finite_number(data.get("t", 0.0), f"{name}.t")
        r_value = _finite_number(data.get("r_arcsec", 0.0), f"{name}.r_arcsec")
        if t_value < 0 or r_value < 0:
            raise ValidationError(f"{name} 必须非负")
        return cls(t=t_value, r_arcsec=r_value)

    def to_dict(self) -> dict:
        return {"t": self.t, "r_arcsec": self.r_arcsec}


@dataclass
class TransformRecord:
    """一条变换记录：``p_from = T · p_to``。"""

    id: str
    from_frame: str
    to_frame: str
    rotation: Dict[str, Any]
    translation: Tuple[float, float, float]      # 内部单位 m（子系原点在父系坐标）
    sigma: Sigma = field(default_factory=Sigma)
    status: str = "design"
    source: str = ""
    effective: str = ""
    note: str = ""

    @classmethod
    def from_dict(cls, payload, name: str = "transform") -> "TransformRecord":
        data = _require_mapping(payload, name)
        record_id = _require_id(data.get("id"), f"{name}.id")
        from_frame = _require_id(data.get("from"), f"{name}.from")
        to_frame = _require_id(data.get("to"), f"{name}.to")
        if from_frame == to_frame:
            raise ValidationError(f"{name}.from 与 to 不能相同")
        rotation = _require_mapping(data.get("rotation"), f"{name}.rotation")
        _ensure_json_value(rotation, f"{name}.rotation")
        translation = conv.finite_tuple(data.get("translation", (0.0, 0.0, 0.0)), 3, f"{name}.translation")
        return cls(
            id=record_id,
            from_frame=from_frame,
            to_frame=to_frame,
            rotation=copy.deepcopy(rotation),
            translation=translation,
            sigma=Sigma.from_dict(data.get("sigma")),
            status=conv.normalize_status(data.get("status")),
            source=_optional_text(data.get("source"), f"{name}.source"),
            effective=_optional_text(data.get("effective"), f"{name}.effective"),
            note=_optional_text(data.get("note"), f"{name}.note"),
        )

    def to_dict(self) -> dict:
        payload = {
            "id": self.id,
            "from": self.from_frame,
            "to": self.to_frame,
            "rotation": copy.deepcopy(self.rotation),
            "translation": list(self.translation),
            "sigma": self.sigma.to_dict(),
            "status": self.status,
        }
        if self.source:
            payload["source"] = self.source
        if self.effective:
            payload["effective"] = self.effective
        if self.note:
            payload["note"] = self.note
        return payload

    def attitude(self, meta: Optional[LedgerMeta] = None) -> Attitude:
        meta = meta or LedgerMeta()
        return parse_rotation_spec(
            self.rotation,
            default_quat_order=meta.quaternion_order,
            default_euler_rotation=meta.euler_rotation,
            default_angle_unit=meta.angle_default,
        )

    def homogeneous(self, meta: Optional[LedgerMeta] = None):
        """返回 ``T_from_to``（4×4）。"""
        from .transforms import make_transform

        return make_transform(self.attitude(meta), self.translation)

    def matrix_label(self) -> str:
        """双写法显示：``T_body_cam（camera_panchro → body）``（设计文档 2.1）。"""
        return f"T_{self.from_frame}_{self.to_frame}（{self.to_frame} → {self.from_frame}）"


# ---------------------------------------------------------------------------
# 限值
# ---------------------------------------------------------------------------


@dataclass
class Limit:
    id: str
    kind: str
    frames: Tuple[str, str]
    expected: float
    tolerance: float
    unit: str
    note: str = ""

    @classmethod
    def from_dict(cls, payload, name: str = "limit") -> "Limit":
        data = _require_mapping(payload, name)
        limit_id = _require_id(data.get("id"), f"{name}.id")
        kind = conv.normalize_limit_kind(data.get("kind"))
        frames = data.get("frames")
        if not isinstance(frames, (list, tuple)) or len(frames) != 2:
            raise ValidationError(f"{name}.frames 必须是 2 元数组")
        pair = (
            _require_id(frames[0], f"{name}.frames[0]"),
            _require_id(frames[1], f"{name}.frames[1]"),
        )
        unit = data.get("unit")
        if unit not in ("deg", "arcsec", "m", "mm"):
            raise ValidationError(f"{name}.unit 非法，可选 deg / arcsec / m / mm")
        return cls(
            id=limit_id,
            kind=kind,
            frames=pair,
            expected=_finite_number(data.get("expected"), f"{name}.expected"),
            tolerance=_finite_number(data.get("tolerance"), f"{name}.tolerance"),
            unit=unit,
            note=_optional_text(data.get("note"), f"{name}.note"),
        )

    def to_dict(self) -> dict:
        payload = {
            "id": self.id,
            "kind": self.kind,
            "frames": list(self.frames),
            "expected": self.expected,
            "tolerance": self.tolerance,
            "unit": self.unit,
        }
        if self.note:
            payload["note"] = self.note
        return payload


# ---------------------------------------------------------------------------
# 文档级结构
# ---------------------------------------------------------------------------


@dataclass
class ValidationResult:
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def raise_if_failed(self) -> None:
        if self.errors:
            joined = "；".join(self.errors[:20])
            more = f"（共 {len(self.errors)} 项）" if len(self.errors) > 20 else ""
            raise ValidationError(f"账本校验失败：{joined}{more}")


@dataclass
class LedgerDocument:
    meta: LedgerMeta
    frames: List[Frame] = field(default_factory=list)
    transforms: List[TransformRecord] = field(default_factory=list)
    limits: List[Limit] = field(default_factory=list)

    # --- 索引 ---

    def frame_map(self) -> Dict[str, Frame]:
        return {frame.id: frame for frame in self.frames}

    def transform_map(self) -> Dict[str, TransformRecord]:
        return {record.id: record for record in self.transforms}

    def get_frame(self, frame_id: str) -> Frame:
        frames = self.frame_map()
        if frame_id not in frames:
            raise ValidationError(f"坐标系不存在: {frame_id}")
        return frames[frame_id]

    def get_transform(self, transform_id: str) -> TransformRecord:
        records = self.transform_map()
        if transform_id not in records:
            raise ValidationError(f"变换记录不存在: {transform_id}")
        return records[transform_id]

    # --- 序列化 ---

    @classmethod
    def from_dict(cls, payload) -> "LedgerDocument":
        data = _require_mapping(payload, "账本")
        schema_name = data.get("schema")
        if schema_name is not None and schema_name != SCHEMA_NAME:
            raise ValidationError(f"schema 必须是 {SCHEMA_NAME!r}，实际 {schema_name!r}")
        version = data.get("schema_version", SCHEMA_VERSION)
        if isinstance(version, bool) or not isinstance(version, int):
            raise ValidationError("schema_version 必须是整数")
        if version > SCHEMA_VERSION:
            raise ValidationError(
                f"不支持的 schema_version: {version}（最高支持 {SCHEMA_VERSION}），请升级工具"
            )
        if version < SCHEMA_VERSION:
            # 当前仅有 v1；预留迁移入口
            raise ValidationError(f"缺少从 schema_version {version} 的迁移函数")

        meta = LedgerMeta.from_dict(data.get("ledger", {}))
        raw_frames = data.get("frames", [])
        raw_transforms = data.get("transforms", [])
        raw_limits = data.get("limits", [])
        for container, kind in (
            (raw_frames, "frames"),
            (raw_transforms, "transforms"),
            (raw_limits, "limits"),
        ):
            if not isinstance(container, list):
                raise ValidationError(f"{kind} 必须是数组")

        frames = [Frame.from_dict(item, f"frames[{index}]")
                  for index, item in enumerate(raw_frames)]
        transforms = [TransformRecord.from_dict(item, f"transforms[{index}]")
                      for index, item in enumerate(raw_transforms)]
        limits = [Limit.from_dict(item, f"limits[{index}]")
                  for index, item in enumerate(raw_limits)]
        document = cls(meta=meta, frames=frames, transforms=transforms, limits=limits)
        return document

    def to_dict(self) -> dict:
        return {
            "schema": SCHEMA_NAME,
            "schema_version": SCHEMA_VERSION,
            "ledger": self.meta.to_dict(),
            "frames": [frame.to_dict() for frame in self.frames],
            "transforms": [record.to_dict() for record in self.transforms],
            "limits": [limit.to_dict() for limit in self.limits],
        }

    # --- A5 校验 ---

    def validate(self) -> ValidationResult:
        result = ValidationResult()
        self._validate_unique_ids(result)
        self._validate_references(result)
        self._validate_rotations(result)
        self._validate_duplicate_status(result)
        self._validate_connectivity(result)
        return result

    def _validate_unique_ids(self, result: ValidationResult) -> None:
        for label, items in (
            ("坐标系", self.frames),
            ("变换", self.transforms),
            ("限值", self.limits),
        ):
            seen: Dict[str, int] = {}
            for item in items:
                seen[item.id] = seen.get(item.id, 0) + 1
            duplicates = sorted(key for key, count in seen.items() if count > 1)
            if duplicates:
                result.errors.append(
                    f"{label} id 重复：{', '.join(duplicates)}"
                )

    def _validate_references(self, result: ValidationResult) -> None:
        frame_ids = {frame.id for frame in self.frames}
        missing = []
        for record in self.transforms:
            for frame_id in (record.from_frame, record.to_frame):
                if frame_id not in frame_ids:
                    missing.append(f"{record.id}→{frame_id}")
        if missing:
            result.errors.append(
                f"变换引用了不存在的坐标系：{', '.join(sorted(set(missing)))}"
            )
        transform_ids = {record.id for record in self.transforms}
        missing_limits = []
        for limit in self.limits:
            if limit.kind == "angle_between":
                for frame_id in limit.frames:
                    if frame_id not in frame_ids:
                        missing_limits.append(f"{limit.id}→{frame_id}")
            else:
                for transform_id in limit.frames:
                    if transform_id not in transform_ids:
                        missing_limits.append(f"{limit.id}→{transform_id}")
        if missing_limits:
            result.errors.append(
                f"限值引用了不存在的对象：{', '.join(sorted(set(missing_limits)))}"
            )

    def _validate_rotations(self, result: ValidationResult) -> None:
        for record in self.transforms:
            try:
                attitude = record.attitude(self.meta)
            except ValidationError as exc:
                message = getattr(exc, "user_message", None) or str(exc)
                result.errors.append(f"{record.id} 姿态非法：{message}")
                continue
            matrix = record.rotation.get("value") if record.rotation.get("type") == "matrix" else None
            if matrix is not None:
                import numpy as np

                array = np.asarray(matrix, dtype=float).reshape(3, 3)
                ortho_err, det_err = orthonormal_deviation(array)
                if ortho_err > 1e-6 or det_err > 1e-6:
                    result.errors.append(
                        f"{record.id} 旋转矩阵未正交归一："
                        f"‖RᵀR−I‖∞={ortho_err:.3e}，|det−1|={det_err:.3e}"
                    )
            # 确认可构造
            _ = attitude.matrix()

    def _validate_duplicate_status(self, result: ValidationResult) -> None:
        buckets: Dict[Tuple[str, str], Dict[str, List[str]]] = {}
        for record in self.transforms:
            key = (record.from_frame, record.to_frame)
            buckets.setdefault(key, {}).setdefault(record.status, []).append(record.id)
        for (from_frame, to_frame), statuses in buckets.items():
            for status, ids in statuses.items():
                if len(ids) > 1:
                    result.warnings.append(
                        f"{from_frame}→{to_frame} 存在 {len(ids)} 条同状态({status})记录，"
                        f"缺省选取不确定：{', '.join(sorted(ids))}"
                    )

    def _validate_connectivity(self, result: ValidationResult) -> None:
        if not self.frames:
            return
        adjacency: Dict[str, set] = {frame.id: set() for frame in self.frames}
        for record in self.transforms:
            if record.from_frame in adjacency and record.to_frame in adjacency:
                adjacency[record.from_frame].add(record.to_frame)
                adjacency[record.to_frame].add(record.from_frame)
        start = self.frames[0].id
        visited = {start}
        stack = [start]
        while stack:
            current = stack.pop()
            for neighbor in adjacency[current]:
                if neighbor not in visited:
                    visited.add(neighbor)
                    stack.append(neighbor)
        isolated = sorted(set(adjacency) - visited)
        if isolated:
            result.warnings.append(
                f"图连通性：{len(isolated)} 个坐标系与主图不连通：{', '.join(isolated)}"
            )


# ---------------------------------------------------------------------------
# 模板生成（A3）
# ---------------------------------------------------------------------------


def make_sample_document() -> LedgerDocument:
    """示例账本（含 design/calibrated 双状态），几何自洽：
    相机视轴沿 body −Z（对地），星敏光轴沿 body +X，SAR 波束偏离对地方向 30°；
    T_st1_cam 由 design 值导出，design 回路精确闭合。
    """
    payload = {
        "schema": SCHEMA_NAME,
        "schema_version": SCHEMA_VERSION,
        "ledger": {
            "name": "ST-2026 载荷坐标系账本",
            "version": "1.0",
            "unit_default": "m",
            "angle_default": "deg",
            "quaternion_order": "wxyz",
            "euler_rotation": "intrinsic",
            "judge": {"warn_sigma": 1.0, "fail_sigma": 3.0},
            "note": "示例账本",
        },
        "frames": [
            {"id": "body", "name": "本体坐标系", "axis": "Z_UP",
             "definition": "X 沿飞行方向，Z 指向地心，Y 右手法则"},
            {"id": "star_tracker_1", "name": "星敏1光轴系", "axis": "Z_FORWARD",
             "definition": "Z 沿光轴，指向 +X 方向"},
            {"id": "camera_panchro", "name": "全色相机视轴系", "axis": "Z_FORWARD",
             "definition": "Z 沿视轴，对地指向"},
            {"id": "sar_antenna", "name": "SAR波束中心系", "type": "payload", "axis": "Z_UP",
             "definition": "Z 沿波束中心，偏离对地方向 30°"},
        ],
        "transforms": [
            {
                "id": "T_body_cam_design",
                "from": "body", "to": "camera_panchro",
                "rotation": {"type": "quaternion", "value": [0.7071068, 0.0, 0.0, 0.7071068]},
                "translation": [0.000, 0.000, 1.200],
                "sigma": {"t": 0.0008, "r_arcsec": 3.2},
                "status": "design",
                "source": "ST-2026-JG-021 表3",
                "effective": "图纸设计值",
                "note": "结构图安装矩阵",
            },
            {
                "id": "T_body_cam_cal_202605",
                "from": "body", "to": "camera_panchro",
                "rotation": {"type": "rpy", "value": [0.001, -0.001, 89.998], "order": "ZYX",
                             "rotation_type": "intrinsic", "unit": "deg"},
                "translation": [0.000, 0.002, 1.201],
                "sigma": {"t": 0.0004, "r_arcsec": 1.8},
                "status": "calibrated",
                "source": "ST-2026-BD-005 表2",
                "effective": "2026-05 批次，常温",
            },
            {
                "id": "T_body_st1_design",
                "from": "body", "to": "star_tracker_1",
                "rotation": {"type": "rpy", "value": [0, 90, 0], "order": "ZYX",
                             "rotation_type": "intrinsic", "unit": "deg"},
                "translation": [0.300, 0.100, 0.900],
                "sigma": {"t": 0.0005, "r_arcsec": 2.1},
                "status": "design",
                "source": "ST-2026-JG-018 表2",
                "effective": "图纸设计值",
            },
            {
                "id": "T_st1_cam_design",
                "from": "star_tracker_1", "to": "camera_panchro",
                "rotation": {"type": "matrix", "value": [0, 0, -1, 1, 0, 0, 0, -1, 0]},
                "translation": [-0.300, -0.100, -0.300],
                "sigma": {"t": 0.0006, "r_arcsec": 1.4},
                "status": "design",
                "source": "ST-2026-JG-021 表4",
                "effective": "图纸设计值",
                "note": "由 body→st1 与 body→cam 设计值导出",
            },
            {
                "id": "T_body_sar_design",
                "from": "body", "to": "sar_antenna",
                "rotation": {"type": "rpy", "value": [30, 0, 0], "order": "ZYX",
                             "rotation_type": "intrinsic", "unit": "deg"},
                "translation": [0.000, 0.500, 0.800],
                "sigma": {"t": 0.0010, "r_arcsec": 4.0},
                "status": "design",
                "source": "ST-2026-JG-030 表1",
                "effective": "图纸设计值",
            },
        ],
        "limits": [
            {"id": "LIM_cam_sar_angle", "kind": "angle_between",
             "frames": ["camera_panchro", "sar_antenna"],
             "expected": 30.0, "tolerance": 0.1, "unit": "deg",
             "note": "SYS-REQ-0213 载荷间光轴夹角要求"},
        ],
    }
    return LedgerDocument.from_dict(payload)


def make_blank_document(name: str = "新建坐标系账本") -> LedgerDocument:
    payload = {
        "schema": SCHEMA_NAME,
        "schema_version": SCHEMA_VERSION,
        "ledger": {
            "name": name,
            "version": "1.0",
            "unit_default": "m",
            "angle_default": "deg",
            "quaternion_order": "wxyz",
            "euler_rotation": "intrinsic",
            "judge": {"warn_sigma": 1.0, "fail_sigma": 3.0},
            "note": "",
        },
        "frames": [],
        "transforms": [],
        "limits": [],
    }
    return LedgerDocument.from_dict(payload)
