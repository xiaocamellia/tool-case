"""Numerical optimizer for direction-finding calibration."""

from __future__ import annotations

import numpy as np
from scipy.optimize import minimize

from .calibration_metrics import calculate_comparison_metrics
from .calibration_model import azimuth_difference, simulate_angles


def _validated_data(data: dict) -> dict[str, np.ndarray]:
    required = ('az_true', 'el_true', 'az_meas', 'el_meas')
    result = {}
    for name in required:
        if name not in data:
            raise ValueError(f'缺少校正数据字段: {name}')
        values = np.asarray(data[name], dtype=float).reshape(-1)
        if values.size == 0 or not np.all(np.isfinite(values)):
            raise ValueError(f'{name} 为空或包含无效数值')
        result[name] = values
    lengths = {values.size for values in result.values()}
    if len(lengths) != 1:
        raise ValueError('四列校正数据长度不一致')
    return result


def run_calibration(
    data: dict,
    fixed_params: dict,
    init_params: dict,
    *,
    max_iterations: int = 1000,
    tolerance: float = 1e-8,
) -> dict:
    """Optimize yy_r4/zz_r4 and return complete before/after results."""
    values = _validated_data(data)
    initial = np.array([
        float(init_params['yy_r4_ZT']),
        float(init_params['zz_r4_ZT']),
    ])
    if not np.all(np.isfinite(initial)):
        raise ValueError('优化初值包含无效数值')

    def evaluate(params):
        az_sim, el_sim = simulate_angles(
            params[0], params[1], values['az_true'], values['el_true'], fixed_params)
        err_az = azimuth_difference(values['az_meas'], az_sim)
        err_el = values['el_meas'] - el_sim
        return float(np.sum(err_az ** 2 + err_el ** 2))

    initial_cost = evaluate(initial)
    optimized = minimize(
        evaluate,
        initial,
        method='Nelder-Mead',
        options={
            'maxiter': max(1, int(max_iterations)),
            'xatol': float(tolerance),
            'fatol': float(tolerance),
        },
    )
    final_params = np.asarray(optimized.x, dtype=float)
    final_cost = evaluate(final_params)
    if not np.isfinite(final_cost):
        raise ValueError('优化结果无效，请检查数据和固定参数')

    az_orig, el_orig = simulate_angles(
        initial[0], initial[1], values['az_true'], values['el_true'], fixed_params)
    az_opt, el_opt = simulate_angles(
        final_params[0], final_params[1], values['az_true'], values['el_true'], fixed_params)
    err_az_orig = azimuth_difference(values['az_meas'], az_orig)
    err_el_orig = values['el_meas'] - el_orig
    err_az_opt = azimuth_difference(values['az_meas'], az_opt)
    err_el_opt = values['el_meas'] - el_opt

    return {
        'success': bool(optimized.success),
        'message': str(optimized.message),
        'iterations': int(getattr(optimized, 'nit', 0)),
        'sample_count': int(values['az_true'].size),
        'initial_params': {
            'yy_r4_ZT': float(initial[0]),
            'zz_r4_ZT': float(initial[1]),
        },
        'optimized_params': {
            'yy_r4_ZT': float(final_params[0]),
            'zz_r4_ZT': float(final_params[1]),
        },
        'initial_cost': float(initial_cost),
        'final_cost': float(final_cost),
        'metrics': calculate_comparison_metrics(
            err_az_orig, err_el_orig, err_az_opt, err_el_opt),
        'series': {
            **values,
            'az_sim_orig': az_orig,
            'el_sim_orig': el_orig,
            'az_sim_opt': az_opt,
            'el_sim_opt': el_opt,
            'err_az_orig': err_az_orig,
            'err_el_orig': err_el_orig,
            'err_az_opt': err_az_opt,
            'err_el_opt': err_el_opt,
        },
    }
