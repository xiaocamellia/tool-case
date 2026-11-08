"""Numerical optimizer for direction-finding calibration."""

from __future__ import annotations

import threading

import numpy as np
from scipy.optimize import minimize

from .calibration_metrics import calculate_comparison_metrics
from .calibration_model import azimuth_difference, simulate_angles


class CalibrationCancelled(RuntimeError):
    """用户或关闭流程请求停止校正优化。"""


def _validated_data(data: dict) -> dict[str, np.ndarray]:
    required = ('az_true', 'el_true', 'az_meas', 'el_meas')
    result: dict[str, np.ndarray] = {}
    for name in required:
        if name not in data:
            raise ValueError(f'缺少校正数据字段: {name}')
        values: np.ndarray = np.asarray(
            data[name], dtype=float
        ).reshape(-1)
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
    cancel_event=None,
    progress_callback=None,
) -> dict:
    """Optimize yy_r4/zz_r4 and return complete before/after results."""
    values: dict[str, np.ndarray] = _validated_data(data)
    initial = np.array([
        float(init_params['yy_r4_ZT']),
        float(init_params['zz_r4_ZT']),
    ])
    if not np.all(np.isfinite(initial)):
        raise ValueError('优化初值包含无效数值')

    def ensure_not_cancelled():
        if cancel_event is not None and cancel_event.is_set():
            raise CalibrationCancelled('测向校正已取消')

    def report(percent, message):
        if progress_callback is not None:
            progress_callback(percent, message)

    def evaluate(params):
        ensure_not_cancelled()
        az_sim, el_sim = simulate_angles(
            params[0], params[1], values['az_true'], values['el_true'], fixed_params)
        err_az = azimuth_difference(values['az_meas'], az_sim)
        err_el = values['el_meas'] - el_sim
        return float(np.sum(err_az ** 2 + err_el ** 2))

    report(5, '校验初始参数')
    initial_cost = evaluate(initial)
    iteration = {'count': 0}

    def optimizer_callback(_params):
        ensure_not_cancelled()
        iteration['count'] += 1
        percent = min(95, 10 + int(
            85 * iteration['count'] / max(1, max_iterations)
        ))
        report(percent, f'优化迭代 {iteration["count"]}')

    optimized = minimize(
        evaluate,
        initial,
        method='Nelder-Mead',
        callback=optimizer_callback,
        options={
            'maxiter': max(1, int(max_iterations)),
            'xatol': float(tolerance),
            'fatol': float(tolerance),
        },
    )
    ensure_not_cancelled()
    report(96, '整理优化结果')
    final_params: np.ndarray = np.asarray(optimized.x, dtype=float)
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
