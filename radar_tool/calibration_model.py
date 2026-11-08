"""Coordinate transform model for direction-finding calibration."""

from __future__ import annotations

import numpy as np


def _as_vector(values, name: str) -> np.ndarray:
    vector: np.ndarray = np.asarray(values, dtype=float).reshape(-1)
    if vector.size == 0 or not np.all(np.isfinite(vector)):
        raise ValueError(f'{name} 为空或包含无效数值')
    return vector


def azimuth_difference(measured, simulated) -> np.ndarray:
    """Return wrapped azimuth error in [-180, 180) degrees."""
    measured = np.asarray(measured, dtype=float)
    simulated = np.asarray(simulated, dtype=float)
    return (measured - simulated + 180.0) % 360.0 - 180.0


def simulate_angles(
    yy_r4: float,
    zz_r4: float,
    az_true,
    el_true,
    fixed_params: dict,
) -> tuple[np.ndarray, np.ndarray]:
    """Simulate azimuth/elevation after translating and rotating coordinates."""
    azimuth = _as_vector(az_true, '方位角真值')
    elevation = _as_vector(el_true, '俯仰角真值')
    if azimuth.size != elevation.size:
        raise ValueError('方位角真值与俯仰角真值长度不一致')

    rho_obj = float(fixed_params['rho_obj'])
    xx_r4 = float(fixed_params['xx_r4'])
    matrix: np.ndarray = np.asarray(
        fixed_params['matrixZT2ANT'], dtype=float
    )
    if rho_obj <= 0:
        raise ValueError('rho_obj 必须大于 0')
    if matrix.shape != (3, 3) or not np.all(np.isfinite(matrix)):
        raise ValueError('matrixZT2ANT 必须是有效的 3x3 数值矩阵')

    az_rad = np.deg2rad(azimuth)
    neg_el_rad = np.deg2rad(-elevation)
    targets = np.column_stack((
        rho_obj * np.cos(neg_el_rad) * np.cos(az_rad),
        rho_obj * np.cos(neg_el_rad) * np.sin(az_rad),
        rho_obj * np.sin(neg_el_rad),
    ))

    translated = targets - np.array([xx_r4, float(yy_r4), float(zz_r4)])
    antenna_coords = translated @ matrix
    xx = antenna_coords[:, 0]
    yy = antenna_coords[:, 1]
    zz = antenna_coords[:, 2]
    radius = np.linalg.norm(antenna_coords, axis=1)
    if np.any(radius <= np.finfo(float).eps):
        raise ValueError('坐标变换后存在位于原点的样本，无法反算角度')

    az_sim = np.rad2deg(np.arctan2(yy, xx))
    el_sim = -np.rad2deg(np.arcsin(np.clip(zz / radius, -1.0, 1.0)))
    return az_sim, el_sim
