"""DOA estimation algorithms with explicit numerical input validation."""

from __future__ import annotations

import math
from typing import Iterable, Optional

import numpy as np

from ..errors import ValidationError


SPEED_OF_LIGHT_M_PER_S = 3.0e8
C = SPEED_OF_LIGHT_M_PER_S


class DoaValidationError(ValidationError):
    """Raised when DOA inputs or numerical subspaces are invalid."""


class MonteCarloCancelled(RuntimeError):
    """Raised when cooperative Monte Carlo cancellation is observed."""


def _scalar(value):
    """Return a finite real scalar from a scalar or a 1x1 matrix."""
    try:
        array = np.asarray(value)
    except (TypeError, ValueError) as exc:
        raise DoaValidationError("标量结果必须是数值") from exc
    if array.size != 1:
        raise DoaValidationError("标量结果必须只包含一个数值")
    item = array.item()
    if isinstance(item, complex):
        if not math.isfinite(item.real) or not math.isfinite(item.imag):
            raise DoaValidationError("标量结果必须是有限数值")
        tolerance = 1e-10 * max(1.0, abs(item.real))
        if abs(item.imag) > tolerance:
            raise DoaValidationError("Hermitian 二次型必须为实数")
        return float(item.real)
    try:
        result = float(item)
    except (TypeError, ValueError) as exc:
        raise DoaValidationError("标量结果必须是有限数值") from exc
    if not math.isfinite(result):
        raise DoaValidationError("标量结果必须是有限数值")
    return result


def _finite(value, name):
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise DoaValidationError(f'{name}必须是有限数值') from exc
    if not math.isfinite(result):
        raise DoaValidationError(f'{name}必须是有限数值')
    return result


def _positive(value, name):
    result = _finite(value, name)
    if result <= 0:
        raise DoaValidationError(f'{name}必须大于 0')
    return result


def _validate_array(array_pos, min_elements=1):
    try:
        positions = np.asarray(array_pos, dtype=float)
    except (TypeError, ValueError) as exc:
        raise DoaValidationError('阵元坐标必须是数值数组') from exc
    if positions.ndim != 2 or positions.shape[1] != 2:
        raise DoaValidationError('阵元坐标必须是 N×2 数组，列为 Y、Z 坐标')
    if positions.shape[0] < min_elements:
        raise DoaValidationError(f'阵元数必须至少为 {min_elements}')
    if not np.all(np.isfinite(positions)):
        raise DoaValidationError('阵元坐标必须全部为有限数值')
    if np.unique(positions, axis=0).shape[0] != positions.shape[0]:
        raise DoaValidationError('阵元坐标不得包含重复阵元，奇异阵列不可用于 DOA 估计')
    return positions


def _validate_matrix(X, min_antennas=2):
    try:
        matrix = np.asarray(X, dtype=complex)
    except (TypeError, ValueError) as exc:
        raise DoaValidationError('快拍矩阵必须是数值矩阵') from exc
    if matrix.ndim != 2:
        raise DoaValidationError('快拍矩阵必须是二维矩阵')
    if matrix.shape[0] < min_antennas or matrix.shape[1] < 1:
        raise DoaValidationError(
            f'快拍矩阵形状无效：至少 {min_antennas} 个阵元且至少 1 个快拍'
        )
    if not np.all(np.isfinite(matrix)):
        raise DoaValidationError('快拍矩阵必须全部为有限数值')
    return matrix


def _validate_signal_count(N_signals, N_ant):
    if isinstance(N_signals, bool):
        raise DoaValidationError('信号数必须是整数')
    signal_count = _finite(N_signals, '信号数')
    if not signal_count.is_integer():
        raise DoaValidationError('信号数必须是整数')
    count = int(signal_count)
    if not 0 < count < N_ant:
        raise DoaValidationError(
            f'信号数必须满足 0 < N_signals < N_ant（N_ant={N_ant}）'
        )
    return count


def _validate_scan(scan_range, step, name):
    try:
        start_value, end_value = scan_range
    except (TypeError, ValueError) as exc:
        raise DoaValidationError(f'{name}扫描范围必须包含起点和终点') from exc
    start = _finite(start_value, f'{name}范围起点')
    end = _finite(end_value, f'{name}范围终点')
    step = _positive(step, f'{name}扫描步长')
    if start > end:
        raise DoaValidationError(f'{name}范围起点不得大于终点')
    return start, end, step


def _scan_axis(scan_range, step, name):
    start, end, step = _validate_scan(scan_range, step, name)
    return np.arange(start, end + step, step, dtype=float)


def _normalize_signal(signal, index=0):
    if isinstance(signal, dict):
        normalized = {
            'theta': signal.get('theta', 0),
            'phi': signal.get('phi', 0),
            'amp': signal.get('amp', 1.0),
            'freq': signal.get('freq', 100e3 * (index + 1)),
            'snr': signal.get('snr'),
        }
    else:
        try:
            values = list(signal)
            theta, phi, amp = values[:3]
        except (TypeError, ValueError, IndexError) as exc:
            raise DoaValidationError('每个信号至少包含 theta、phi、amp') from exc
        freq = values[3] if len(values) > 3 else 100e3 * (index + 1)
        snr = values[4] if len(values) > 4 else None
        normalized = {
            'theta': theta, 'phi': phi, 'amp': amp,
            'freq': freq, 'snr': snr,
        }

    result = {
        'theta': _finite(normalized['theta'], '信号方位角'),
        'phi': _finite(normalized['phi'], '信号俯仰角'),
        'amp': _finite(normalized['amp'], '信号幅度'),
        'freq': _finite(normalized['freq'], '信号频率'),
        'snr': normalized['snr'],
    }
    if result['snr'] is not None:
        result['snr'] = _finite(result['snr'], '信号SNR')
    return result


def _make_rng(seed=None, rng=None):
    if rng is not None:
        if not isinstance(rng, np.random.Generator):
            raise DoaValidationError('rng 必须是 numpy Generator')
        return rng
    try:
        return np.random.default_rng(seed)
    except (TypeError, ValueError) as exc:
        raise DoaValidationError('随机种子无效') from exc


def _apply_array_imperfections(array_pos, fc, imperfections, rng=None):
    positions = _validate_array(array_pos, min_elements=1)
    _positive(fc, '载频')
    if not imperfections:
        return positions, None
    if not isinstance(imperfections, dict):
        raise DoaValidationError('阵列误差配置必须是字典')
    rng = _make_rng(rng=rng)

    actual_pos = positions.copy()
    if imperfections.get('pos_enabled'):
        pos_std = _finite(imperfections.get('pos_std', 0.0), '位置误差标准差')
        if pos_std < 0:
            raise DoaValidationError('位置误差标准差不得小于 0')
        if pos_std > 0:
            actual_pos += rng.normal(0.0, pos_std, size=actual_pos.shape)

    sensor_gain = None
    N_ant = len(actual_pos)
    if imperfections.get('amp_enabled') or imperfections.get('phase_enabled'):
        gain = np.ones(N_ant, dtype=complex)
        if imperfections.get('amp_enabled'):
            amp_std_db = _finite(
                imperfections.get('amp_std_db', 0.0), '幅度误差标准差')
            if amp_std_db < 0:
                raise DoaValidationError('幅度误差标准差不得小于 0')
            if amp_std_db > 0:
                gain *= 10 ** (
                    rng.normal(0.0, amp_std_db, N_ant) / 20.0)
        if imperfections.get('phase_enabled'):
            phase_std_deg = _finite(
                imperfections.get('phase_std_deg', 0.0), '相位误差标准差')
            if phase_std_deg < 0:
                raise DoaValidationError('相位误差标准差不得小于 0')
            if phase_std_deg > 0:
                gain *= np.exp(
                    1j * np.deg2rad(
                        rng.normal(0.0, phase_std_deg, N_ant)))
        sensor_gain = gain.reshape(-1, 1)

    return actual_pos, sensor_gain


def compute_array_manifold_2d(array_pos, theta_deg, phi_deg, fc):
    """Compute the array manifold for Y-Z planar coordinates, in metres."""

    positions = _validate_array(array_pos, min_elements=1)
    theta = math.radians(_finite(theta_deg, '方位角'))
    phi = math.radians(_finite(phi_deg, '俯仰角'))
    frequency = _positive(fc, '载频')
    wavelength = SPEED_OF_LIGHT_M_PER_S / frequency
    dir_y = math.cos(phi) * math.sin(theta)
    dir_z = math.sin(phi)
    phase = -2 * np.pi / wavelength * (
        positions[:, 0] * dir_y + positions[:, 1] * dir_z)
    return np.exp(1j * phase).reshape(-1, 1)


def generate_received_signal(
    array_pos,
    signals,
    fc,
    fs,
    T,
    SNR=20,
    imperfections=None,
    seed=None,
    rng=None,
):
    """Generate noisy snapshots with optional reproducible imperfections."""

    positions = _validate_array(array_pos, min_elements=2)
    if signals is None or len(signals) < 1:
        raise DoaValidationError('至少需要一个信号')
    frequency = _positive(fc, '载频')
    sample_rate = _positive(fs, '采样率')
    duration = _positive(T, '快拍时长')
    snr_db = _finite(SNR, 'SNR')
    N_samples = int(duration * sample_rate)
    if N_samples < 1:
        raise DoaValidationError('快拍时长与采样率至少产生 1 个快拍')

    rng = _make_rng(seed=seed, rng=rng)
    normalized_signals = [
        _normalize_signal(signal, index)
        for index, signal in enumerate(signals)
    ]
    actual_pos, sensor_gain = _apply_array_imperfections(
        positions, frequency, imperfections, rng=rng)

    t = np.arange(N_samples) / sample_rate
    s = np.zeros((N_samples, len(normalized_signals)), dtype=complex)
    freq_offset_std = 0.0
    if imperfections:
        if not isinstance(imperfections, dict):
            raise DoaValidationError('阵列误差配置必须是字典')
        if imperfections.get('freq_enabled'):
            freq_offset_std = _finite(
                imperfections.get('freq_offset_std', 0.0),
                '频率误差标准差')
            if freq_offset_std < 0:
                raise DoaValidationError('频率误差标准差不得小于 0')

    for k, signal in enumerate(normalized_signals):
        freq = signal['freq']
        if freq_offset_std > 0:
            freq += rng.normal(0.0, freq_offset_std)
        phase0 = rng.uniform(0, 2 * np.pi)
        s[:, k] = signal['amp'] * np.exp(
            1j * (2 * np.pi * freq * t + phase0))

    A = np.zeros((len(actual_pos), len(normalized_signals)), dtype=complex)
    for k, signal in enumerate(normalized_signals):
        a = compute_array_manifold_2d(
            actual_pos, signal['theta'], signal['phi'], frequency)
        if sensor_gain is not None:
            a = sensor_gain * a
        A[:, k:k + 1] = a

    X = A @ s.T
    noise_power = 0.0
    for k, signal in enumerate(normalized_signals):
        xk = A[:, k:k + 1] @ s[:, k:k + 1].T
        snr = snr_db if signal['snr'] is None else signal['snr']
        try:
            snr_linear = 10.0 ** (snr / 10.0)
        except OverflowError as exc:
            raise DoaValidationError('SNR超出可表示范围') from exc
        if snr_linear <= 0:
            raise DoaValidationError('SNR过低，无法生成有限噪声功率')
        noise_power += np.mean(np.abs(xk) ** 2) / snr_linear
    if noise_power <= 0:
        signal_power = np.mean(np.abs(X) ** 2)
        try:
            snr_linear = 10.0 ** (snr_db / 10.0)
        except OverflowError as exc:
            raise DoaValidationError('SNR超出可表示范围') from exc
        if snr_linear <= 0 or signal_power <= 0:
            raise DoaValidationError('信号功率或SNR过低，无法生成噪声')
        noise_power = signal_power / snr_linear

    X = X + np.sqrt(noise_power / 2) * (
        rng.standard_normal(X.shape) + 1j * rng.standard_normal(X.shape))
    if not np.all(np.isfinite(X)):
        raise DoaValidationError('生成的快拍矩阵包含非有限数值')
    return X


def _covariance(X):
    matrix = _validate_matrix(X, min_antennas=2)
    covariance = matrix @ matrix.conj().T / matrix.shape[1]
    covariance = (covariance + covariance.conj().T) / 2
    if not np.all(np.isfinite(covariance)):
        raise DoaValidationError('协方差矩阵包含非有限数值')
    return covariance


def _hermitian_subspaces(X, N_signals):
    covariance = _covariance(X)
    N_ant = covariance.shape[0]
    count = _validate_signal_count(N_signals, N_ant)
    eigenvalues, eigenvectors = np.linalg.eigh(covariance)
    order = np.argsort(eigenvalues.real)[::-1]
    eigenvalues = eigenvalues.real[order]
    eigenvectors = eigenvectors[:, order]
    noise_values = eigenvalues[count:]
    scale = max(float(np.max(np.abs(eigenvalues))), 1.0)
    if noise_values.size == 0 or float(np.max(noise_values)) <= 1e-12 * scale:
        raise DoaValidationError(
            '噪声子空间为零或数值上不可分辨，无法执行 MUSIC'
        )
    return eigenvalues, eigenvectors, count


def bartlett_doa_1d(X, array_pos, theta_range, theta_step, fc, phi=0):
    """Bartlett beamformer for one-dimensional scans."""

    positions = _validate_array(array_pos, min_elements=2)
    matrix = _validate_matrix(X, min_antennas=2)
    if matrix.shape[0] != len(positions):
        raise DoaValidationError('快拍矩阵阵元数与阵列坐标不一致')
    frequency = _positive(fc, '载频')
    phi_value = _finite(phi, '俯仰角')
    thetas = _scan_axis(theta_range, theta_step, '方位角')
    covariance = _covariance(matrix)
    P = np.zeros(len(thetas), dtype=float)
    for i, theta in enumerate(thetas):
        a = compute_array_manifold_2d(positions, theta, phi_value, frequency)
        P[i] = _scalar(
            np.abs(a.conj().T @ covariance @ a) / (len(positions) ** 2))
    peak_idx = int(np.argmax(P))
    return float(thetas[peak_idx]), P, thetas, phi_value


def music_doa_1d(X, array_pos, theta_range, theta_step, fc, N_signals, phi=0):
    """MUSIC estimator for one-dimensional scans."""

    positions = _validate_array(array_pos, min_elements=2)
    matrix = _validate_matrix(X, min_antennas=2)
    if matrix.shape[0] != len(positions):
        raise DoaValidationError('快拍矩阵阵元数与阵列坐标不一致')
    frequency = _positive(fc, '载频')
    phi_value = _finite(phi, '俯仰角')
    _eigenvalues, eigenvectors, count = _hermitian_subspaces(
        matrix, N_signals)
    noise_space = eigenvectors[:, count:]
    thetas = _scan_axis(theta_range, theta_step, '方位角')
    P = np.zeros(len(thetas), dtype=float)
    epsilon = np.finfo(float).eps
    for i, theta in enumerate(thetas):
        a = compute_array_manifold_2d(positions, theta, phi_value, frequency)
        denominator = abs(
            _scalar(a.conj().T @ noise_space @ noise_space.conj().T @ a))
        P[i] = 1.0 / max(denominator, epsilon)
    peak_idx = int(np.argmax(P))
    return float(thetas[peak_idx]), P, thetas, phi_value


def bartlett_doa_2d(X, array_pos, theta_range, theta_step, phi_range, phi_step, fc):
    """Bartlett beamformer for two-dimensional scans."""

    positions = _validate_array(array_pos, min_elements=2)
    matrix = _validate_matrix(X, min_antennas=2)
    if matrix.shape[0] != len(positions):
        raise DoaValidationError('快拍矩阵阵元数与阵列坐标不一致')
    frequency = _positive(fc, '载频')
    thetas = _scan_axis(theta_range, theta_step, '方位角')
    phis = _scan_axis(phi_range, phi_step, '俯仰角')
    covariance = _covariance(matrix)
    P = np.zeros((len(phis), len(thetas)), dtype=float)
    for ti, theta in enumerate(thetas):
        for pi, phi in enumerate(phis):
            a = compute_array_manifold_2d(positions, theta, phi, frequency)
            P[pi, ti] = _scalar(
                np.abs(a.conj().T @ covariance @ a)
                / (len(positions) ** 2))
    peak_idx = np.unravel_index(np.argmax(P), P.shape)
    return (
        float(thetas[peak_idx[1]]), float(phis[peak_idx[0]]),
        P, thetas, phis,
    )


def music_doa_2d(
    X, array_pos, theta_range, theta_step, phi_range, phi_step, fc, N_signals
):
    """MUSIC estimator for two-dimensional scans."""

    positions = _validate_array(array_pos, min_elements=2)
    matrix = _validate_matrix(X, min_antennas=2)
    if matrix.shape[0] != len(positions):
        raise DoaValidationError('快拍矩阵阵元数与阵列坐标不一致')
    frequency = _positive(fc, '载频')
    _eigenvalues, eigenvectors, count = _hermitian_subspaces(
        matrix, N_signals)
    noise_space = eigenvectors[:, count:]
    thetas = _scan_axis(theta_range, theta_step, '方位角')
    phis = _scan_axis(phi_range, phi_step, '俯仰角')
    P = np.zeros((len(phis), len(thetas)), dtype=float)
    epsilon = np.finfo(float).eps
    for ti, theta in enumerate(thetas):
        for pi, phi in enumerate(phis):
            a = compute_array_manifold_2d(positions, theta, phi, frequency)
            denominator = abs(
                _scalar(a.conj().T @ noise_space @ noise_space.conj().T @ a))
            P[pi, ti] = 1.0 / max(denominator, epsilon)
    peak_idx = np.unravel_index(np.argmax(P), P.shape)
    return (
        float(thetas[peak_idx[1]]), float(phis[peak_idx[0]]),
        P, thetas, phis,
    )


def esprit_doa(X, d, fc, N_signals):
    """ESPRIT for a uniform linear array; unobservable angles are clipped."""

    matrix = _validate_matrix(X, min_antennas=2)
    spacing = _positive(d, '阵元间距')
    frequency = _positive(fc, '载频')
    _eigenvalues, eigenvectors, count = _hermitian_subspaces(
        matrix, N_signals)
    signal_space = eigenvectors[:, :count]
    U1 = signal_space[:-1, :]
    U2 = signal_space[1:, :]
    if U1.shape[0] < 1 or np.linalg.matrix_rank(U1) < count:
        raise DoaValidationError('ESPRIT 信号子空间不可解')
    Phi = np.linalg.pinv(U1) @ U2
    eigenvalues_phi = np.linalg.eigvals(Phi)
    wavelength = SPEED_OF_LIGHT_M_PER_S / frequency
    argument = (
        np.angle(eigenvalues_phi) * wavelength / (2 * np.pi * spacing)
    )
    if not np.all(np.isfinite(argument)):
        raise DoaValidationError('ESPRIT 相位参数不可解')
    clipped = np.clip(np.real(argument), -1.0, 1.0)
    return np.rad2deg(np.sort(np.arcsin(clipped)))


def _wrap_angle(errors):
    wrapped = np.asarray(errors, dtype=float)
    return (wrapped + 180.0) % 360.0 - 180.0


def monte_carlo_evaluation(
    array_pos,
    signals,
    fc,
    fs,
    T,
    SNR,
    algorithm_func,
    N_trials=100,
    do_2d=False,
    theta_step=0.5,
    phi_step=0.5,
    imperfections=None,
    seed=None,
    cancel_event=None,
    progress_callback=None,
):
    """Run reproducible Monte Carlo DOA evaluation."""

    if not callable(algorithm_func):
        raise DoaValidationError('algorithm_func 必须是可调用对象')
    if isinstance(N_trials, bool):
        raise DoaValidationError('试验次数必须是整数')
    try:
        trials = int(N_trials)
    except (TypeError, ValueError) as exc:
        raise DoaValidationError('试验次数必须是整数') from exc
    if trials != N_trials or trials < 1:
        raise DoaValidationError('试验次数必须至少为 1')
    _validate_scan((-90, 90), theta_step, '方位角')
    if do_2d:
        _validate_scan((-90, 90), phi_step, '俯仰角')
    if signals is None or len(signals) < 1:
        raise DoaValidationError('至少需要一个信号')

    rng = _make_rng(seed=seed)
    errors_theta = []
    errors_phi = []
    last_bucket = -1
    for index in range(trials):
        if cancel_event is not None and cancel_event.is_set():
            raise MonteCarloCancelled('蒙特卡洛仿真已取消')
        X = generate_received_signal(
            array_pos, signals, fc, fs, T, SNR,
            imperfections=imperfections, rng=rng)
        if do_2d:
            theta_est, phi_est, _P, _thetas, _phis = algorithm_func(
                X, array_pos, (-90, 90), theta_step,
                (-90, 90), phi_step, fc, len(signals))
            ref = _normalize_signal(signals[0])
            errors_theta.append(theta_est - ref['theta'])
            errors_phi.append(phi_est - ref['phi'])
        else:
            theta_est, _P, _thetas, _phi = algorithm_func(
                X, array_pos, (-90, 90), theta_step, fc, len(signals))
            ref = _normalize_signal(signals[0])
            errors_theta.append(theta_est - ref['theta'])

        bucket = int((index + 1) * 20 / trials)
        if progress_callback is not None and (
            bucket != last_bucket or index + 1 == trials
        ):
            progress_callback(
                int((index + 1) * 100 / trials),
                f'蒙特卡洛试验 {index + 1}/{trials}',
            )
            last_bucket = bucket

    if cancel_event is not None and cancel_event.is_set():
        raise MonteCarloCancelled('蒙特卡洛仿真已取消')

    errors_theta = _wrap_angle(errors_theta)
    rmse = float(np.sqrt(np.mean(errors_theta ** 2)))
    bias = float(np.mean(errors_theta))
    std_dev = float(np.std(errors_theta, ddof=1 if trials > 1 else 0))
    if do_2d:
        errors_phi = _wrap_angle(errors_phi)
        rmse_phi = float(np.sqrt(np.mean(errors_phi ** 2)))
        return rmse, bias, std_dev, errors_theta, rmse_phi, errors_phi
    return rmse, bias, std_dev, errors_theta
