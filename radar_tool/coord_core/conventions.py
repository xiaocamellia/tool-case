"""坐标约定解析、scipy 序列映射与单位换算。

约定映射集中在本模块（设计文档 2.2 / R3 对策），业务代码不得直接把
欧拉角序列字符串传给 scipy。
"""

from __future__ import annotations

import math
from typing import Iterable, Sequence, Tuple

from ..errors import ValidationError
from .. import calc_units

# ---------------------------------------------------------------------------
# 枚举取值
# ---------------------------------------------------------------------------

EULER_ORDERS = (
    "XYZ", "XZY", "YXZ", "YZX", "ZXY", "ZYX",
    "XYX", "XZX", "YXY", "YZY", "ZXZ", "ZYZ",
)
ROTATION_TYPES = ("intrinsic", "extrinsic")
QUATERNION_ORDERS = ("wxyz", "xyzw")
ANGLE_UNITS = ("deg", "rad", "arcsec")
LENGTH_UNITS = ("m", "mm")
AXIS_CONVENTIONS = ("Z_UP", "Z_FORWARD", "Y_UP", "NED", "ENU")
TRANSFORM_STATUS = ("design", "calibrated", "as_built", "obsolete")
LIMIT_KINDS = ("angle_between", "rotation_delta", "translation_delta")

#: 状态优先级：数值越大越优先作为"当前有效值"；obsolete 永不自动选中。
STATUS_PRIORITY = {
    "as_built": 3,
    "calibrated": 2,
    "design": 1,
    "obsolete": 0,
}

# ---------------------------------------------------------------------------
# scipy 映射（唯一出口）
# ---------------------------------------------------------------------------


def to_scipy_seq(order: str, rotation_type: str) -> str:
    """把账本的欧拉角约定映射为 ``scipy.spatial.transform.Rotation`` 序列。

    scipy 约定：小写序列 = 内旋（intrinsic），大写序列 = 外旋（extrinsic）。

    **value 顺序**：账本 ``value = [α, β, γ]`` 与 ``order`` 字母**逆序**对应
    （设计文档 16.1：``intrinsic ZYX → R = Rz(γ)·Ry(β)·Rx(α)``，即
    ``value[0]=α`` 对应 order 末字母、``value[2]=γ`` 对应首字母）。
    因此传给 scipy 时须 ``angles = value[::-1]``（见 ``attitude_angle_order``）。
    ZYX 场景下 ``value = [绕X, 绕Y, 绕Z] = [roll, pitch, yaw]``。
    """
    normalized_order = normalize_euler_order(order)
    normalized_type = normalize_rotation_type(rotation_type)
    return normalized_order.lower() if normalized_type == "intrinsic" else normalized_order.upper()


def attitude_angle_order(values):
    """账本 value → scipy from_euler 角度顺序（逆序）。"""
    return tuple(values)[::-1]


def attitude_angle_order_inverse(values):
    """scipy as_euler 输出 → 账本 value 顺序（逆序还原）。"""
    return tuple(values)[::-1]


def from_scipy_seq(seq: str) -> Tuple[str, str]:
    """``to_scipy_seq`` 的逆映射，用于调试与报告回显。"""
    if not isinstance(seq, str) or not seq or len(seq) != 3:
        raise ValidationError(f"scipy 欧拉角序列非法: {seq!r}")
    if seq.islower():
        return seq.upper(), "intrinsic"
    if seq.isupper():
        return seq, "extrinsic"
    raise ValidationError(f"scipy 欧拉角序列非法: {seq!r}")


def normalize_euler_order(order) -> str:
    if not isinstance(order, str):
        raise ValidationError("欧拉角顺序 order 必填（如 ZYX）")
    text = order.strip()
    if len(text) == 3 and text.isalpha() and text.islower():
        text = text.upper()
    if text not in EULER_ORDERS:
        raise ValidationError(
            f"欧拉角顺序非法: {order!r}，可选 {', '.join(EULER_ORDERS)}"
        )
    return text


def normalize_rotation_type(rotation_type) -> str:
    if not isinstance(rotation_type, str):
        raise ValidationError(
            "欧拉角旋转类型 rotation_type 必填（intrinsic / extrinsic）"
        )
    text = rotation_type.strip().lower()
    if text not in ROTATION_TYPES:
        raise ValidationError(
            f"欧拉角旋转类型非法: {rotation_type!r}，可选 intrinsic / extrinsic"
        )
    return text


def normalize_quaternion_order(order, default: str = "wxyz") -> str:
    if order is None:
        order = default
    if not isinstance(order, str):
        raise ValidationError("四元数顺序必须是字符串")
    text = order.strip().lower()
    if text not in QUATERNION_ORDERS:
        raise ValidationError(
            f"四元数顺序非法: {order!r}，可选 wxyz / xyzw"
        )
    return text


# ---------------------------------------------------------------------------
# 四元数顺序处理（账本边界 wxyz，scipy 原生 xyzw）
# ---------------------------------------------------------------------------


def quaternion_to_wxyz(quat: Sequence[float], order: str = "wxyz") -> Tuple[float, float, float, float]:
    """任意顺序四元数 → wxyz。"""
    values = _as_quat(quat, "四元数")
    normalized = normalize_quaternion_order(order)
    if normalized == "wxyz":
        return values
    x, y, z, w = values
    return (w, x, y, z)


def quaternion_wxyz_to(wxyz: Sequence[float], order: str = "wxyz") -> Tuple[float, float, float, float]:
    """wxyz 四元数 → 指定顺序。"""
    values = _as_quat(wxyz, "四元数")
    normalized = normalize_quaternion_order(order)
    if normalized == "wxyz":
        return values
    w, x, y, z = values
    return (x, y, z, w)


def _as_quat(quat: Sequence[float], name: str) -> Tuple[float, float, float, float]:
    if not isinstance(quat, (list, tuple)) or len(quat) != 4:
        raise ValidationError(f"{name} 必须是 4 元数组")
    out = []
    for index, item in enumerate(quat):
        out.append(_finite(item, f"{name}[{index}]"))
    return (out[0], out[1], out[2], out[3])


# ---------------------------------------------------------------------------
# 单位换算（复用 calc_units，补 arcsec 与带符号长度）
# ---------------------------------------------------------------------------

_LENGTH_TO_M = {"m": 1.0, "mm": 1e-3}
_ANGLE_TO_RAD = {"deg": math.pi / 180.0, "rad": 1.0, "arcsec": math.pi / 180.0 / 3600.0}


def angle_to_radians(value, unit: str) -> float:
    """角度 → rad（支持负值）。"""
    number = _finite(value, "角度")
    unit_text = normalize_angle_unit(unit)
    if unit_text == "deg":
        return calc_units.convert_angle(number, "°", "rad")
    if unit_text == "rad":
        return calc_units.convert_angle(number, "rad", "rad")
    return number * _ANGLE_TO_RAD["arcsec"]


def angle_from_radians(value, unit: str) -> float:
    """rad → 目标角度单位。"""
    number = _finite(value, "角度")
    unit_text = normalize_angle_unit(unit)
    if unit_text == "deg":
        return calc_units.convert_angle(number, "rad", "°")
    if unit_text == "rad":
        return calc_units.convert_angle(number, "rad", "rad")
    return number / _ANGLE_TO_RAD["arcsec"]


def angle_to_arcsec(value, unit: str) -> float:
    """任意角度单位 → 角秒。"""
    return angle_from_radians(angle_to_radians(value, unit), "arcsec")


def angle_from_arcsec(value, unit: str) -> float:
    number = _finite(value, "角秒")
    return angle_from_radians(number * _ANGLE_TO_RAD["arcsec"], unit)


def length_to_meters(value, unit: str) -> float:
    """长度 → m（允许负值与零）。"""
    number = _finite(value, "长度")
    unit_text = normalize_length_unit(unit)
    return number * _LENGTH_TO_M[unit_text]


def length_from_meters(value, unit: str) -> float:
    number = _finite(value, "长度")
    unit_text = normalize_length_unit(unit)
    return number / _LENGTH_TO_M[unit_text]


def length_to_mm(value, unit: str) -> float:
    return length_from_meters(length_to_meters(value, unit), "mm")


def length_from_mm(value, unit: str) -> float:
    return length_from_meters(length_to_meters(value, "mm"), unit)


def normalize_angle_unit(unit) -> str:
    if not isinstance(unit, str):
        raise ValidationError("角度单位必填（deg / rad / arcsec）")
    text = unit.strip()
    aliases = {"°": "deg", "degree": "deg", "degrees": "deg", "deg": "deg",
               "rad": "rad", "radian": "rad", "radians": "rad",
               "arcsec": "arcsec", "″": "arcsec", '"': "arcsec",
               "as": "arcsec", "秒": "arcsec"}
    key = text.lower()
    if key not in aliases:
        raise ValidationError(f"不支持的角度单位: {unit!r}，可选 deg / rad / arcsec")
    return aliases[key]


def normalize_length_unit(unit) -> str:
    if not isinstance(unit, str):
        raise ValidationError("长度单位必填（m / mm）")
    text = unit.strip().lower()
    if text not in _LENGTH_TO_M:
        raise ValidationError(f"不支持的长度单位: {unit!r}，可选 m / mm")
    return text


def _finite(value, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(f"{name} 必须是有限数值")
    number = float(value)
    if not math.isfinite(number):
        raise ValidationError(f"{name} 必须是有限数值")
    return number


# ---------------------------------------------------------------------------
# 轴向约定
# ---------------------------------------------------------------------------


def normalize_axis_convention(axis) -> str:
    if not isinstance(axis, str):
        raise ValidationError("轴向约定 axis 必填（Z_UP / Z_FORWARD / Y_UP / NED / ENU）")
    text = axis.strip()
    for candidate in AXIS_CONVENTIONS:
        if text.upper() == candidate:
            return candidate
    raise ValidationError(
        f"轴向约定非法: {axis!r}，可选 {' / '.join(AXIS_CONVENTIONS)}"
    )


def principal_axis_index(axis: str) -> int:
    """轴向约定的主轴（指向/测量基准轴）在基坐标中的下标。

    Z_UP / Z_FORWARD / NED / ENU 主轴取 Z；Y_UP 主轴取 Y。
    """
    convention = normalize_axis_convention(axis)
    return 1 if convention == "Y_UP" else 2


def principal_axis_vector(axis: str):
    import numpy as np

    vec = np.zeros(3, dtype=float)
    vec[principal_axis_index(axis)] = 1.0
    return vec


def normalize_status(status) -> str:
    if not isinstance(status, str):
        raise ValidationError(f"变换 status 必填，可选 {' / '.join(TRANSFORM_STATUS)}")
    text = status.strip().lower()
    if text not in TRANSFORM_STATUS:
        raise ValidationError(
            f"变换 status 非法: {status!r}，可选 {' / '.join(TRANSFORM_STATUS)}"
        )
    return text


def normalize_limit_kind(kind) -> str:
    if not isinstance(kind, str):
        raise ValidationError(f"限值 kind 必填，可选 {' / '.join(LIMIT_KINDS)}")
    text = kind.strip().lower()
    if text not in LIMIT_KINDS:
        raise ValidationError(f"限值 kind 非法: {kind!r}，可选 {' / '.join(LIMIT_KINDS)}")
    return text


def finite_tuple(values: Iterable, length: int, name: str):
    items = list(values)
    if len(items) != length:
        raise ValidationError(f"{name} 必须是 {length} 元数组")
    return tuple(_finite(item, f"{name}[{index}]") for index, item in enumerate(items))
