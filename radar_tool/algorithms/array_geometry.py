"""阵列几何生成与输入校验。"""

from __future__ import annotations

import math

import numpy as np


def _positive_integer(value, name, minimum=1):
    if isinstance(value, (bool, np.bool_)):
        raise ValueError(f"{name}必须是不小于 {minimum} 的整数")
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name}必须是不小于 {minimum} 的整数") from exc
    if not math.isfinite(numeric) or not numeric.is_integer():
        raise ValueError(f"{name}必须是不小于 {minimum} 的整数")
    result = int(numeric)
    if result < minimum:
        raise ValueError(f"{name}必须是不小于 {minimum} 的整数")
    return result


def _positive_length(value, name):
    if isinstance(value, (bool, np.bool_)):
        raise ValueError(f"{name}必须大于 0 且为有限数值")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name}必须大于 0 且为有限数值") from exc
    if not math.isfinite(result) or result <= 0:
        raise ValueError(f"{name}必须大于 0 且为有限数值")
    return result


def _validated_positions(positions, name):
    try:
        result = np.asarray(positions, dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name}必须是数值坐标数组") from exc
    if result.ndim != 2 or result.shape[1] != 2 or result.shape[0] < 2:
        raise ValueError(f"{name}必须是至少包含两个阵元的 N×2 数组")
    if not np.all(np.isfinite(result)):
        raise ValueError(f"{name}坐标必须全部为有限数值")
    if np.unique(result, axis=0).shape[0] != result.shape[0]:
        raise ValueError(f"{name}不得包含重复阵元坐标")
    return result


def create_ula(N, d):
    """创建均匀线阵；N 为阵元数，d 为阵元间距（米）。"""
    count = _positive_integer(N, "ULA阵元数", minimum=2)
    spacing = _positive_length(d, "ULA阵元间距")
    positions = np.zeros((count, 2), dtype=float)
    positions[:, 0] = np.arange(count, dtype=float) * spacing
    return _validated_positions(positions, "ULA阵列")


def create_uca(N, radius):
    """创建均匀圆阵；radius 为半径（米）。"""
    count = _positive_integer(N, "UCA阵元数", minimum=2)
    array_radius = _positive_length(radius, "UCA半径")
    angles = np.linspace(0.0, 2.0 * np.pi, count, endpoint=False)
    x = array_radius * np.cos(angles)
    y = array_radius * np.sin(angles)
    positions = np.column_stack([x, y])
    return _validated_positions(positions, "UCA阵列")


def create_l_array(N_x, N_y, d):
    """创建 L 型阵列；两个方向的阵元数均不得小于 2。"""
    count_x = _positive_integer(N_x, "L型阵列X轴阵元数", minimum=2)
    count_y = _positive_integer(N_y, "L型阵列Y轴阵元数", minimum=2)
    spacing = _positive_length(d, "L型阵列阵元间距")
    x_positions = np.zeros((count_x, 2), dtype=float)
    x_positions[:, 0] = np.arange(count_x, dtype=float) * spacing
    y_positions = np.zeros((count_y - 1, 2), dtype=float)
    y_positions[:, 1] = np.arange(1, count_y, dtype=float) * spacing
    positions = np.vstack([x_positions, y_positions])
    return _validated_positions(positions, "L型阵列")


def create_rect_array(N_rows, N_cols, dx, dy):
    """创建矩形面阵；dx、dy 分别为列、行方向间距（米）。"""
    rows = _positive_integer(N_rows, "矩形面阵行数")
    cols = _positive_integer(N_cols, "矩形面阵列数")
    if rows * cols < 2:
        raise ValueError("矩形面阵至少需要两个阵元")
    spacing_x = _positive_length(dx, "矩形面阵X方向间距")
    spacing_y = _positive_length(dy, "矩形面阵Y方向间距")
    column_indices, row_indices = np.meshgrid(
        np.arange(cols, dtype=float),
        np.arange(rows, dtype=float),
    )
    positions = np.column_stack([
        column_indices.ravel() * spacing_x,
        row_indices.ravel() * spacing_y,
    ])
    return _validated_positions(positions, "矩形面阵")
