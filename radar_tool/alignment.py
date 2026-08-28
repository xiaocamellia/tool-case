import numpy as np


ALIGNMENT_METHOD_NAMES = {
    'single_point': '单点/手动偏移',
    'resample': '基线重采样',
    'xcorr': '互相关平移对齐',
    'least_squares_time': '最小二乘时间对齐',
    'robust_xcorr': '稳健互相关对齐',
}


def clean_series(arr):
    arr = np.asarray(arr, dtype=float)
    return arr[np.isfinite(arr)]


def prepare_timed_series(time, values):
    """Return finite, sorted samples and merge duplicate timestamps."""
    time = np.asarray(time, dtype=float)
    values = np.asarray(values, dtype=float)
    if time.shape != values.shape:
        raise ValueError('时间轴与数据列长度不一致')
    valid = np.isfinite(time) & np.isfinite(values)
    time = time[valid]
    values = values[valid]
    if len(time) == 0:
        return time, values
    order = np.argsort(time, kind='stable')
    time = time[order]
    values = values[order]
    unique_time, inverse = np.unique(time, return_inverse=True)
    if len(unique_time) == len(time):
        return time, values
    sums = np.bincount(inverse, weights=values)
    counts = np.bincount(inverse)
    return unique_time, sums / counts


def interpolate_at(time, values, query_time, method='linear'):
    """Interpolate a timed series, leaving out-of-range samples as NaN."""
    time, values = prepare_timed_series(time, values)
    query_time = np.asarray(query_time, dtype=float)
    result = np.full(query_time.shape, np.nan, dtype=float)
    if len(time) == 0:
        return result
    if len(time) == 1:
        result[np.isclose(query_time, time[0])] = values[0]
        return result

    valid = np.isfinite(query_time) & (query_time >= time[0]) & (query_time <= time[-1])
    if not np.any(valid):
        return result
    query = query_time[valid]
    if method == 'nearest':
        right = np.searchsorted(time, query, side='left')
        right = np.clip(right, 0, len(time) - 1)
        left = np.clip(right - 1, 0, len(time) - 1)
        choose_right = np.abs(time[right] - query) < np.abs(query - time[left])
        indices = np.where(choose_right, right, left)
        result[valid] = values[indices]
    elif method == 'cubic' and len(time) >= 4:
        try:
            from scipy.interpolate import CubicSpline
            result[valid] = CubicSpline(time, values)(query)
        except (ImportError, ValueError):
            result[valid] = np.interp(query, time, values)
    else:
        result[valid] = np.interp(query, time, values)
    return result


def apply_time_mapping(reference_time, truth_time, truth_values, mapping, interpolation='linear'):
    """Apply an estimated reference-to-truth time mapping to one truth column."""
    reference_time = np.asarray(reference_time, dtype=float)
    query = (
        float(mapping.get('query_scale', 1.0)) * reference_time
        + float(mapping.get('query_offset_s', 0.0))
    )
    return interpolate_at(truth_time, truth_values, query, interpolation)


def _standardized_mse(reference, candidate):
    valid = np.isfinite(reference) & np.isfinite(candidate)
    minimum = max(8, int(0.45 * len(reference)))
    if np.count_nonzero(valid) < minimum:
        return np.inf
    a = reference[valid]
    b = candidate[valid]
    a_std = np.std(a)
    b_std = np.std(b)
    if a_std <= 1e-12 or b_std <= 1e-12:
        return float(np.mean((a - b) ** 2))
    return float(np.mean(((a - np.mean(a)) / a_std - (b - np.mean(b)) / b_std) ** 2))


def estimate_time_mapping(
    reference_time,
    reference_values,
    truth_time,
    truth_values,
    method='xcorr',
    max_shift_ratio=0.25,
    scale_span=0.30,
    manual_offset_s=0.0,
    interpolation='linear',
    fixed_scale=None,
):
    """Estimate q_truth = query_scale * t_reference + query_offset_s."""
    rt, rv = prepare_timed_series(reference_time, reference_values)
    tt, tv = prepare_timed_series(truth_time, truth_values)
    if len(rt) < 3 or len(tt) < 3:
        raise ValueError('参考维度的有效样点不足（至少需要 3 个）')

    ref_duration = rt[-1] - rt[0]
    truth_duration = tt[-1] - tt[0]
    if ref_duration <= 0 or truth_duration <= 0:
        raise ValueError('时间列必须包含至少两个不同的时间值')

    duration_scale = truth_duration / ref_duration
    base_scale = duration_scale if fixed_scale is None else float(fixed_scale)
    if method == 'single_point':
        scale = 1.0 if fixed_scale is None else base_scale
        offset = tt[0] - scale * rt[0] - manual_offset_s
    else:
        scale = base_scale
        offset = tt[0] - scale * rt[0] - manual_offset_s

    info = {
        'method': ALIGNMENT_METHOD_NAMES.get(method, method),
        'query_scale': float(scale),
        'query_offset_s': float(offset),
        'manual_offset_s': float(manual_offset_s),
    }
    if method in ('single_point', 'resample'):
        return info

    if method in ('xcorr', 'robust_xcorr'):
        if len(rt) > 4096:
            search_indices = np.linspace(0, len(rt) - 1, 4096).astype(int)
            search_time = rt[search_indices]
            search_values = rv[search_indices]
        else:
            search_time = rt
            search_values = rv
        baseline = interpolate_at(
            tt, tv, scale * search_time + offset, interpolation
        )
        finite = np.isfinite(baseline) & np.isfinite(search_values)
        if np.count_nonzero(finite) < 3:
            return info
        # Fill only for correlation; the final interpolation still preserves NaN edges.
        sample_axis = np.arange(len(search_time))
        ref_fill = np.interp(sample_axis, sample_axis[finite], search_values[finite])
        truth_fill = np.interp(sample_axis, sample_axis[finite], baseline[finite])
        if method == 'robust_xcorr':
            ref_fill = np.gradient(ref_fill)
            truth_fill = np.gradient(truth_fill)
            ref_limits = np.percentile(ref_fill, [5, 95])
            truth_limits = np.percentile(truth_fill, [5, 95])
            ref_fill = np.clip(ref_fill, ref_limits[0], ref_limits[1])
            truth_fill = np.clip(truth_fill, truth_limits[0], truth_limits[1])
        max_lag = max(1, int(max_shift_ratio * len(search_time)))
        lag = best_lag_by_xcorr(ref_fill, truth_fill, max_lag)
        search_dt = float(np.median(np.diff(search_time)))
        time_shift = lag * search_dt
        original_dt = float(np.median(np.diff(rt)))
        lag_samples = int(round(time_shift / original_dt))
        offset -= scale * time_shift
        info.update({
            'query_offset_s': float(offset),
            'lag_samples': lag_samples,
            'time_shift_s': float(time_shift),
        })
        return info

    if method == 'least_squares_time':
        if len(rt) > 1200:
            search_indices = np.linspace(0, len(rt) - 1, 1200).astype(int)
            search_time = rt[search_indices]
            search_values = rv[search_indices]
        else:
            search_time = rt
            search_values = rv
        if fixed_scale is None:
            scale_low = max(1e-9, duration_scale * (1.0 - scale_span))
            scale_high = duration_scale * (1.0 + scale_span)
            candidate_scales = np.linspace(scale_low, scale_high, 41)
        else:
            candidate_scales = (base_scale,)
        shifts = np.linspace(-max_shift_ratio * truth_duration, max_shift_ratio * truth_duration, 61)
        best = (np.inf, base_scale, 0.0)
        for candidate_scale in candidate_scales:
            base_offset = tt[0] - candidate_scale * rt[0] - manual_offset_s
            for shift in shifts:
                query = candidate_scale * search_time + base_offset + shift
                candidate = np.interp(
                    query, tt, tv, left=np.nan, right=np.nan
                )
                score = _standardized_mse(search_values, candidate)
                if score < best[0]:
                    best = (score, float(candidate_scale), float(shift))
        _, scale, shift = best
        offset = tt[0] - scale * rt[0] - manual_offset_s + shift
        info.update({
            'query_scale': float(scale),
            'query_offset_s': float(offset),
            'time_shift_s': float(-shift / max(scale, 1e-12)),
            'fit_score': float(best[0]),
        })
        return info

    raise ValueError(f'不支持的对齐方法: {method}')


def calculate_error_metrics(measured, truth, angular=False):
    """Calculate engineering error metrics for a pair of aligned columns."""
    measured = np.asarray(measured, dtype=float)
    truth = np.asarray(truth, dtype=float)
    valid = np.isfinite(measured) & np.isfinite(truth)
    if np.count_nonzero(valid) < 2:
        raise ValueError('有效重叠样点少于 2 个')
    error = measured[valid] - truth[valid]
    if angular:
        error = (error + 180.0) % 360.0 - 180.0
    abs_error = np.abs(error)
    corr = np.nan
    if np.std(measured[valid]) > 1e-12 and np.std(truth[valid]) > 1e-12:
        corr = float(np.corrcoef(measured[valid], truth[valid])[0, 1])
    ss_res = float(np.sum(error ** 2))
    centered = measured[valid] - np.mean(measured[valid])
    ss_tot = float(np.sum(centered ** 2))
    return {
        'count': int(np.count_nonzero(valid)),
        'mean_error': float(np.mean(error)),
        'std_error': float(np.std(error)),
        'mae': float(np.mean(abs_error)),
        'rmse': float(np.sqrt(np.mean(error ** 2))),
        'max_abs': float(np.max(abs_error)),
        'p95_abs': float(np.percentile(abs_error, 95)),
        'corr': corr,
        'r2': float(1.0 - ss_res / ss_tot) if ss_tot > 1e-12 else np.nan,
    }


def resample_series(arr, target_len):
    if target_len <= 0:
        return np.array([], dtype=float)
    if len(arr) == 0:
        return np.zeros(target_len, dtype=float)
    if len(arr) == 1:
        return np.full(target_len, float(arr[0]), dtype=float)
    x_old = np.linspace(0.0, 1.0, len(arr))
    x_new = np.linspace(0.0, 1.0, target_len)
    return np.interp(x_new, x_old, arr)


def shift_series_with_nan(arr, lag):
    n = len(arr)
    out = np.full(n, np.nan, dtype=float)
    if lag >= 0:
        if lag < n:
            out[lag:] = arr[:n - lag]
    else:
        s = -lag
        if s < n:
            out[:n - s] = arr[s:]
    return out


def best_lag_by_xcorr(a, b, max_lag):
    if len(a) == 0 or len(b) == 0:
        return 0
    a0 = a - np.nanmean(a)
    b0 = b - np.nanmean(b)
    if np.nanstd(a0) <= 1e-12 or np.nanstd(b0) <= 1e-12:
        return 0
    result_len = len(a0) + len(b0) - 1
    fft_len = 1 << max(1, result_len - 1).bit_length()
    corr = np.fft.irfft(
        np.fft.rfft(a0, fft_len) * np.fft.rfft(b0[::-1], fft_len),
        fft_len,
    )[:result_len]
    lags = np.arange(-len(b0) + 1, len(a0))
    if max_lag > 0:
        mask = (lags >= -max_lag) & (lags <= max_lag)
        corr = corr[mask]
        lags = lags[mask]
    if len(corr) == 0:
        return 0
    return int(lags[int(np.nanargmax(corr))])


def downsample_for_search(arr, max_len=2000):
    if len(arr) <= max_len:
        return arr
    idx = np.linspace(0, len(arr) - 1, max_len)
    return np.interp(idx, np.arange(len(arr)), arr)


def align_by_least_squares_time(test, truth, max_shift_ratio, scale_span):
    test_s = downsample_for_search(test, max_len=1600)
    truth_s = downsample_for_search(truth, max_len=1600)

    n_t = len(test_s)
    n_r = len(truth_s)
    if n_t < 3 or n_r < 3:
        return resample_series(truth, len(test)), {'scale': 1.0, 'shift': 0.0}

    ratio = (n_r - 1) / max(1, (n_t - 1))
    low = max(0.2, ratio * (1.0 - scale_span))
    high = max(low + 1e-6, ratio * (1.0 + scale_span))
    scales = np.linspace(low, high, 41)
    shift_bound = max(1, int(max_shift_ratio * n_r))
    shifts = np.linspace(-shift_bound, shift_bound, 61)

    best_score = np.inf
    best_scale = ratio
    best_shift = 0.0

    for scale in scales:
        base_idx = scale * np.arange(n_t)
        for shift in shifts:
            idx = base_idx + shift
            valid = (idx >= 0) & (idx <= (n_r - 1))
            if np.count_nonzero(valid) < max(10, int(0.55 * n_t)):
                continue
            y = np.full(n_t, np.nan)
            y[valid] = np.interp(idx[valid], np.arange(n_r), truth_s)
            err = test_s[valid] - y[valid]
            score = float(np.nanmean(err * err))
            if score < best_score:
                best_score = score
                best_scale = float(scale)
                best_shift = float(shift)

    scale_full = best_scale * (max(1, len(truth) - 1) / max(1, n_r - 1)) * (max(1, n_t - 1) / max(1, len(test) - 1))
    shift_full = best_shift * (max(1, len(truth) - 1) / max(1, n_r - 1))
    idx_full = scale_full * np.arange(len(test)) + shift_full
    valid_full = (idx_full >= 0) & (idx_full <= (len(truth) - 1))
    aligned = np.full(len(test), np.nan)
    aligned[valid_full] = np.interp(idx_full[valid_full], np.arange(len(truth)), truth)
    return aligned, {'scale': scale_full, 'shift': shift_full}


def run_alignment(test, truth, method, max_shift_ratio=0.25, scale_span=0.30):
    extra_info = {}

    if method == 'resample':
        aligned_truth = resample_series(truth, len(test))
        extra_info['method'] = '基线重采样'
    elif method == 'xcorr':
        truth_rs = resample_series(truth, len(test))
        max_lag = int(max_shift_ratio * len(test))
        lag = best_lag_by_xcorr(test, truth_rs, max_lag=max_lag)
        aligned_truth = shift_series_with_nan(truth_rs, lag)
        extra_info['method'] = '互相关平移对齐'
        extra_info['lag'] = lag
    elif method == 'least_squares_time':
        aligned_truth, info = align_by_least_squares_time(
            test, truth, max_shift_ratio=max_shift_ratio, scale_span=scale_span
        )
        extra_info['method'] = '最小二乘(时间缩放+平移)'
        extra_info.update(info)
    else:
        truth_rs = resample_series(truth, len(test))
        max_lag = int(max_shift_ratio * len(test))
        lag = best_lag_by_xcorr(test, truth_rs, max_lag=max_lag)
        shifted = shift_series_with_nan(truth_rs, lag)
        valid = np.isfinite(shifted) & np.isfinite(test)
        aligned_truth = shifted.copy()
        gain = 1.0
        bias = 0.0
        if np.count_nonzero(valid) >= 2:
            A = np.column_stack([shifted[valid], np.ones(np.count_nonzero(valid))])
            params, *_ = np.linalg.lstsq(A, test[valid], rcond=None)
            gain = float(params[0])
            bias = float(params[1])
            aligned_truth[valid] = gain * shifted[valid] + bias
        extra_info['method'] = '稳健互相关+幅值校正'
        extra_info['lag'] = lag
        extra_info['gain'] = gain
        extra_info['bias'] = bias

    return aligned_truth, extra_info
