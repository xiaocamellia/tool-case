"""Metrics used by the direction-finding calibration workflow."""

from __future__ import annotations

import numpy as np


def calculate_error_metrics(errors) -> dict[str, float]:
    """Return the core error statistics required by the calibration report."""
    values = np.asarray(errors, dtype=float).reshape(-1)
    if values.size == 0 or not np.all(np.isfinite(values)):
        raise ValueError('误差序列为空或包含无效数值')
    return {
        'mean': float(np.mean(values)),
        'std': float(np.std(values)),
        'rmse': float(np.sqrt(np.mean(values ** 2))),
        'max_abs': float(np.max(np.abs(values))),
    }


def calculate_comparison_metrics(
    err_az_orig,
    err_el_orig,
    err_az_opt,
    err_el_opt,
) -> dict[str, dict[str, dict[str, float]]]:
    """Build before/after metrics for azimuth and elevation."""
    return {
        'azimuth': {
            'before': calculate_error_metrics(err_az_orig),
            'after': calculate_error_metrics(err_az_opt),
        },
        'elevation': {
            'before': calculate_error_metrics(err_el_orig),
            'after': calculate_error_metrics(err_el_opt),
        },
    }
