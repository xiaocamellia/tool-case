"""4×4 齐次变换与姿态互转（scipy 封装）。

语义（设计文档 2.1，全局唯一约定）::

    T_A_B  表示"把 B 系下的量变换到 A 系"
    p_A = T_A_B · p_B

拼接 ``T_A_C = T_A_B · T_B_C``；求逆 ``T_B_A = inv(T_A_B)``。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence, Tuple

import numpy as np
from scipy.spatial.transform import Rotation

from ..errors import ValidationError
from . import conventions as conv

# 数值容差：正交归一校验（设计文档 A5 / R5）
_ORTHO_TOL = 1e-6
# 姿态互转回归阈值（设计文档 10：1e-10）
_ROUNDTRIP_TOL = 1e-10


@dataclass(frozen=True)
class Attitude:
    """姿态的统一内部表示（scipy Rotation，原生 xyzw 四元数）。"""

    rotation: Rotation

    @classmethod
    def identity(cls) -> "Attitude":
        return cls(Rotation.identity())

    @classmethod
    def from_matrix(cls, matrix, *, validate: bool = True, name: str = "旋转矩阵") -> "Attitude":
        array = np.asarray(matrix, dtype=float)
        if array.shape != (3, 3):
            raise ValidationError(f"{name} 必须是 3×3")
        if not np.all(np.isfinite(array)):
            raise ValidationError(f"{name} 含非有限数值")
        if validate:
            check_orthonormal(array, name=name)
        return cls(Rotation.from_matrix(array))

    @classmethod
    def from_quaternion(cls, quat, order: str = "wxyz") -> "Attitude":
        wxyz = conv.quaternion_to_wxyz(quat, order)
        norm = math.sqrt(sum(component * component for component in wxyz))
        if norm < 1e-15:
            raise ValidationError("四元数模长为 0")
        xyzw = (wxyz[1], wxyz[2], wxyz[3], wxyz[0])
        return cls(Rotation.from_quat(xyzw))

    @classmethod
    def from_euler(cls, angles, order: str, rotation_type: str, unit: str = "deg") -> "Attitude":
        seq = conv.to_scipy_seq(order, rotation_type)
        values = conv.finite_tuple(angles, 3, "欧拉角")
        radians = [conv.angle_to_radians(value, unit) for value in values]
        # 账本 value = [α, β, γ] 与 order 字母逆序对应；scipy 取 value[::-1]
        scipy_angles = conv.attitude_angle_order(radians)
        return cls(Rotation.from_euler(seq, scipy_angles, degrees=False))

    @classmethod
    def from_rotvec(cls, rotvec, unit: str = "rad") -> "Attitude":
        values = conv.finite_tuple(rotvec, 3, "旋转向量")
        radians = [conv.angle_to_radians(value, unit) for value in values]
        return cls(Rotation.from_rotvec(np.asarray(radians, dtype=float)))

    @classmethod
    def from_any(cls, spec, *, default_quat_order: str = "wxyz",
                 default_euler_rotation: str = "intrinsic",
                 default_angle_unit: str = "deg") -> "Attitude":
        """解析 5.4 节的三种姿态输入形式。"""
        if not isinstance(spec, dict):
            raise ValidationError("rotation 必须是对象")
        kind = spec.get("type")
        if not isinstance(kind, str):
            raise ValidationError("rotation.type 必填（rpy / quaternion / matrix）")
        kind = kind.strip().lower()
        value = spec.get("value")
        if value is None:
            raise ValidationError("rotation.value 必填")
        if kind in ("rpy", "euler"):
            order = spec.get("order")
            rotation_type = spec.get("rotation_type", spec.get("euler_rotation"))
            if rotation_type is None:
                rotation_type = default_euler_rotation
            unit = spec.get("unit", default_angle_unit)
            return cls.from_euler(value, order, rotation_type, unit)
        if kind == "quaternion":
            order = spec.get("order", default_quat_order)
            return cls.from_quaternion(value, order)
        if kind == "matrix":
            array = np.asarray(value, dtype=float).reshape(-1)
            if array.size != 9:
                raise ValidationError("rotation.value 矩阵必须是行优先 9 元")
            return cls.from_matrix(array.reshape(3, 3))
        raise ValidationError(f"未知 rotation.type: {kind!r}")

    # --- 输出 ---

    def matrix(self) -> np.ndarray:
        return self.rotation.as_matrix()

    def quaternion_wxyz(self) -> Tuple[float, float, float, float]:
        x, y, z, w = self.rotation.as_quat()
        return (float(w), float(x), float(y), float(z))

    def euler(self, order: str, rotation_type: str, unit: str = "deg") -> Tuple[float, float, float]:
        seq = conv.to_scipy_seq(order, rotation_type)
        radians = self.rotation.as_euler(seq, degrees=False)
        ledger_angles = conv.attitude_angle_order_inverse(radians)
        return tuple(conv.angle_from_radians(float(v), unit) for v in ledger_angles)

    def rotvec(self, unit: str = "rad") -> Tuple[float, float, float]:
        vec = self.rotation.as_rotvec()
        return tuple(conv.angle_from_radians(float(v), unit) for v in vec)

    def magnitude(self, unit: str = "rad") -> float:
        """等效转角（旋转模长）。"""
        return conv.angle_from_radians(float(self.rotation.magnitude()), unit)

    def inverse(self) -> "Attitude":
        return Attitude(self.rotation.inv())

    def apply(self, vectors) -> np.ndarray:
        return self.rotation.apply(np.asarray(vectors, dtype=float))


def check_orthonormal(matrix, name: str = "旋转矩阵", tol: float = _ORTHO_TOL) -> None:
    """校验 RᵀR ≈ I 且 det ≈ 1，超差报错并给出偏差量（A5 / R5）。"""
    array = np.asarray(matrix, dtype=float)
    if array.shape != (3, 3):
        raise ValidationError(f"{name} 必须是 3×3")
    gram = array.T @ array
    ortho_err = float(np.max(np.abs(gram - np.eye(3))))
    det = float(np.linalg.det(array))
    det_err = abs(det - 1.0)
    if ortho_err > tol or det_err > tol:
        raise ValidationError(
            f"{name} 未正交归一：‖RᵀR-I‖∞={ortho_err:.3e}，|det-1|={det_err:.3e}（容差 {tol:.0e}）"
        )


def make_transform(attitude: Attitude, translation: Sequence[float]) -> np.ndarray:
    """构造 4×4 齐次矩阵 ``[R t; 0 1]``。"""
    t = np.asarray(conv.finite_tuple(translation, 3, "平移"), dtype=float)
    transform = np.eye(4, dtype=float)
    transform[:3, :3] = attitude.matrix()
    transform[:3, 3] = t
    return transform


def split_transform(transform) -> Tuple[Attitude, np.ndarray]:
    array = np.asarray(transform, dtype=float)
    if array.shape != (4, 4):
        raise ValidationError("齐次变换必须是 4×4")
    return Attitude.from_matrix(array[:3, :3], validate=False), array[:3, 3].copy()


def invert_transform(transform) -> np.ndarray:
    """``T⁻¹ = [Rᵀ -Rᵀt; 0 1]``。"""
    array = np.asarray(transform, dtype=float)
    if array.shape != (4, 4):
        raise ValidationError("齐次变换必须是 4×4")
    r = array[:3, :3]
    t = array[:3, 3]
    inverse = np.eye(4, dtype=float)
    inverse[:3, :3] = r.T
    inverse[:3, 3] = -r.T @ t
    return inverse


def compose_transforms(*transforms) -> np.ndarray:
    """按传入顺序左乘拼接：``compose(T_A_B, T_B_C) = T_A_C``。"""
    result = np.eye(4, dtype=float)
    for transform in transforms:
        array = np.asarray(transform, dtype=float)
        if array.shape != (4, 4):
            raise ValidationError("齐次变换必须是 4×4")
        result = result @ array
    return result


def transform_points(transform, points) -> np.ndarray:
    """变换点（含平移）。``points`` 为 (3,) 或 (N,3)。"""
    array = np.asarray(points, dtype=float)
    if array.ndim == 1:
        if array.shape != (3,):
            raise ValidationError("点必须是 3 元数组")
        homogeneous = np.append(array, 1.0)
        result = np.asarray(transform, dtype=float) @ homogeneous
        return result[:3]
    if array.ndim != 2 or array.shape[1] != 3:
        raise ValidationError("点集必须是 (N,3) 数组")
    ones = np.ones((array.shape[0], 1), dtype=float)
    homogeneous = np.hstack([array, ones])
    result = homogeneous @ np.asarray(transform, dtype=float).T
    return result[:, :3]


def transform_vector(attitude: Attitude, vector) -> np.ndarray:
    """方向矢量只取旋转（不含平移）。"""
    array = np.asarray(vector, dtype=float)
    if array.shape != (3,):
        raise ValidationError("矢量必须是 3 元数组")
    return attitude.apply(array)


def rotation_between(attitude_a: Attitude, attitude_b: Attitude) -> Attitude:
    """``ΔR = R_a · R_b⁻¹``。"""
    return Attitude(attitude_a.rotation * attitude_b.rotation.inv())


def delta_transform(transform_a, transform_b) -> np.ndarray:
    """``ΔT = T_a · inv(T_b)``（设计文档 D7）。"""
    return compose_transforms(transform_a, invert_transform(transform_b))


def rotvec_components_arcsec(attitude: Attitude) -> Tuple[float, float, float]:
    """微小转角分解到 X/Y/Z 轴，单位角秒。"""
    return tuple(float(v) for v in attitude.rotvec("arcsec"))


def angle_between_vectors(vector_a, vector_b) -> float:
    """两方向矢量夹角（rad），对模长不敏感。"""
    a = np.asarray(vector_a, dtype=float)
    b = np.asarray(vector_b, dtype=float)
    if a.shape != (3,) or b.shape != (3,):
        raise ValidationError("矢量必须是 3 元数组")
    na = float(np.linalg.norm(a))
    nb = float(np.linalg.norm(b))
    if na < 1e-15 or nb < 1e-15:
        raise ValidationError("零矢量无夹角定义")
    cosine = float(np.clip(np.dot(a, b) / (na * nb), -1.0, 1.0))
    return math.acos(cosine)


def normalize_vector(vector, name: str = "矢量") -> np.ndarray:
    array = np.asarray(vector, dtype=float)
    if array.shape != (3,):
        raise ValidationError(f"{name} 必须是 3 元数组")
    norm = float(np.linalg.norm(array))
    if norm < 1e-15:
        raise ValidationError(f"{name} 模长为 0")
    return array / norm


def parse_rotation_spec(spec, *, default_quat_order: str = "wxyz",
                        default_euler_rotation: str = "intrinsic",
                        default_angle_unit: str = "deg") -> Attitude:
    return Attitude.from_any(
        spec,
        default_quat_order=default_quat_order,
        default_euler_rotation=default_euler_rotation,
        default_angle_unit=default_angle_unit,
    )


def orthonormal_deviation(matrix) -> Tuple[float, float]:
    """返回 (‖RᵀR-I‖∞, |det-1|)，用于校验报错信息。"""
    array = np.asarray(matrix, dtype=float)
    gram = array.T @ array
    ortho_err = float(np.max(np.abs(gram - np.eye(3))))
    det_err = abs(float(np.linalg.det(array)) - 1.0)
    return ortho_err, det_err
