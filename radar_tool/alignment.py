import numpy as np


def clean_series(arr):
    arr = np.asarray(arr, dtype=float)
    return arr[np.isfinite(arr)]


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
    corr = np.correlate(a0, b0, mode='full')
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
