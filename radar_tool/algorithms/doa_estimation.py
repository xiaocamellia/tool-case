"""DOA估计算法模块 - DOA Estimation Algorithms
包含阵列流形计算、信号生成、Bartlett/MUSIC/ESPRIT等经典DOA估计算法
"""

import numpy as np

C = 3e8  # 光速


def _scalar(value):
    """Return a Python float from a numpy scalar or a 1x1 matrix."""
    return float(np.asarray(value).item())


def _normalize_signal(signal, index=0):
    if isinstance(signal, dict):
        return {
            'theta': float(signal.get('theta', 0)),
            'phi': float(signal.get('phi', 0)),
            'amp': float(signal.get('amp', 1.0)),
            'freq': float(signal.get('freq', 100e3 * (index + 1))),
            'snr': signal.get('snr'),
        }
    theta, phi, amp = signal[:3]
    freq = signal[3] if len(signal) > 3 else 100e3 * (index + 1)
    snr = signal[4] if len(signal) > 4 else None
    return {'theta': float(theta), 'phi': float(phi), 'amp': float(amp), 'freq': float(freq), 'snr': snr}


def _apply_array_imperfections(array_pos, fc, imperfections):
    if not imperfections:
        return array_pos, None

    actual_pos = np.array(array_pos, dtype=float, copy=True)
    if imperfections.get('pos_enabled'):
        pos_std = float(imperfections.get('pos_std', 0.0))
        if pos_std > 0:
            actual_pos += np.random.normal(0.0, pos_std, size=actual_pos.shape)

    sensor_gain = None
    N_ant = len(actual_pos)
    if imperfections.get('amp_enabled') or imperfections.get('phase_enabled'):
        gain = np.ones(N_ant, dtype=complex)
        if imperfections.get('amp_enabled'):
            amp_std_db = float(imperfections.get('amp_std_db', 0.0))
            if amp_std_db > 0:
                gain *= 10 ** (np.random.normal(0.0, amp_std_db, N_ant) / 20.0)
        if imperfections.get('phase_enabled'):
            phase_std_deg = float(imperfections.get('phase_std_deg', 0.0))
            if phase_std_deg > 0:
                gain *= np.exp(1j * np.deg2rad(np.random.normal(0.0, phase_std_deg, N_ant)))
        sensor_gain = gain.reshape(-1, 1)

    return actual_pos, sensor_gain


def compute_array_manifold_2d(array_pos, theta_deg, phi_deg, fc):
    """计算阵列流形向量（阵列位于Y-Z平面，X轴为法线方向）
    
    坐标系约定（右手系）：X为阵面法线方向，Y向右，Z向上
    阵元坐标 array_pos[:, 0] = Y, array_pos[:, 1] = Z
    """
    lambda_ = C / fc
    theta = np.deg2rad(theta_deg)
    phi = np.deg2rad(phi_deg)
    dir_y = np.cos(phi) * np.sin(theta)
    dir_z = np.sin(phi)
    phase = -2 * np.pi / lambda_ * (array_pos[:, 0] * dir_y + array_pos[:, 1] * dir_z)
    a = np.exp(1j * phase).reshape(-1, 1)
    return a


def generate_received_signal(array_pos, signals, fc, fs, T, SNR=20, imperfections=None):
    """生成接收信号"""
    N_ant = len(array_pos)
    N_samples = int(T * fs)
    t = np.arange(N_samples) / fs
    N_signals = len(signals)
    actual_pos, sensor_gain = _apply_array_imperfections(array_pos, fc, imperfections)
    freq_offset_std = float((imperfections or {}).get('freq_offset_std', 0.0)) if (imperfections or {}).get('freq_enabled') else 0.0
    
    s = np.zeros((N_samples, N_signals), dtype=complex)
    normalized_signals = [_normalize_signal(sig, k) for k, sig in enumerate(signals)]
    for k, sig in enumerate(normalized_signals):
        freq = sig['freq']
        if freq_offset_std > 0:
            freq += np.random.normal(0.0, freq_offset_std)
        phase0 = np.random.uniform(0, 2 * np.pi)
        s[:, k] = sig['amp'] * np.exp(1j * (2 * np.pi * freq * t + phase0))
    
    A = np.zeros((N_ant, N_signals), dtype=complex)
    for k, sig in enumerate(normalized_signals):
        a = compute_array_manifold_2d(actual_pos, sig['theta'], sig['phi'], fc)
        if sensor_gain is not None:
            a = sensor_gain * a
        A[:, k:k+1] = a
    
    X = A @ s.T
    noise_power = 0.0
    for k, sig in enumerate(normalized_signals):
        xk = A[:, k:k+1] @ s[:, k:k+1].T
        snr = SNR if sig['snr'] is None else float(sig['snr'])
        noise_power += np.mean(np.abs(xk)**2) / (10 ** (snr / 10))
    if noise_power <= 0:
        signal_power = np.mean(np.abs(X)**2)
        noise_power = signal_power / (10 ** (SNR / 10))
    X += np.sqrt(noise_power / 2) * (np.random.randn(*X.shape) + 1j * np.random.randn(*X.shape))
    return X


def bartlett_doa_1d(X, array_pos, theta_range, theta_step, fc, phi=0):
    """Bartlett波束形成法一维DOA估计"""
    N_ant = X.shape[0]
    R = X @ X.conj().T / X.shape[1]
    thetas = np.arange(theta_range[0], theta_range[1] + theta_step, theta_step)
    P = np.zeros_like(thetas, dtype=float)
    for i, theta in enumerate(thetas):
        a = compute_array_manifold_2d(array_pos, theta, phi, fc)
        P[i] = _scalar(np.abs(a.conj().T @ R @ a) / (N_ant ** 2))
    peak_idx = np.argmax(P)
    theta_est = thetas[peak_idx]
    return theta_est, P, thetas, phi


def music_doa_1d(X, array_pos, theta_range, theta_step, fc, N_signals, phi=0):
    """MUSIC算法一维DOA估计"""
    R = X @ X.conj().T / X.shape[1]
    eigenvalues, eigenvectors = np.linalg.eig(R)
    idx = np.argsort(eigenvalues)[::-1]
    eigenvectors = eigenvectors[:, idx]
    noise_space = eigenvectors[:, N_signals:]
    thetas = np.arange(theta_range[0], theta_range[1] + theta_step, theta_step)
    P = np.zeros_like(thetas, dtype=float)
    for i, theta in enumerate(thetas):
        a = compute_array_manifold_2d(array_pos, theta, phi, fc)
        P[i] = _scalar(1.0 / np.abs(a.conj().T @ noise_space @ noise_space.conj().T @ a))
    peak_idx = np.argmax(P)
    theta_est = thetas[peak_idx]
    return theta_est, P, thetas, phi


def bartlett_doa_2d(X, array_pos, theta_range, theta_step, phi_range, phi_step, fc):
    """Bartlett波束形成法二维DOA估计"""
    N_ant = X.shape[0]
    R = X @ X.conj().T / X.shape[1]
    thetas = np.arange(theta_range[0], theta_range[1] + theta_step, theta_step)
    phis = np.arange(phi_range[0], phi_range[1] + phi_step, phi_step)
    P = np.zeros((len(phis), len(thetas)), dtype=float)
    for ti, theta in enumerate(thetas):
        for pi, phi in enumerate(phis):
            a = compute_array_manifold_2d(array_pos, theta, phi, fc)
            P[pi, ti] = _scalar(np.abs(a.conj().T @ R @ a) / (N_ant ** 2))
    peak_idx = np.unravel_index(np.argmax(P), P.shape)
    theta_est = thetas[peak_idx[1]]
    phi_est = phis[peak_idx[0]]
    return theta_est, phi_est, P, thetas, phis


def music_doa_2d(X, array_pos, theta_range, theta_step, phi_range, phi_step, fc, N_signals):
    """MUSIC算法二维DOA估计"""
    R = X @ X.conj().T / X.shape[1]
    eigenvalues, eigenvectors = np.linalg.eig(R)
    idx = np.argsort(eigenvalues)[::-1]
    eigenvectors = eigenvectors[:, idx]
    noise_space = eigenvectors[:, N_signals:]
    thetas = np.arange(theta_range[0], theta_range[1] + theta_step, theta_step)
    phis = np.arange(phi_range[0], phi_range[1] + phi_step, phi_step)
    P = np.zeros((len(phis), len(thetas)), dtype=float)
    for ti, theta in enumerate(thetas):
        for pi, phi in enumerate(phis):
            a = compute_array_manifold_2d(array_pos, theta, phi, fc)
            P[pi, ti] = _scalar(1.0 / np.abs(a.conj().T @ noise_space @ noise_space.conj().T @ a))
    peak_idx = np.unravel_index(np.argmax(P), P.shape)
    theta_est = thetas[peak_idx[1]]
    phi_est = phis[peak_idx[0]]
    return theta_est, phi_est, P, thetas, phis


def esprit_doa(X, d, fc, N_signals):
    """ESPRIT算法（适用于均匀线阵）"""
    R = X @ X.conj().T / X.shape[1]
    eigenvalues, eigenvectors = np.linalg.eig(R)
    idx = np.argsort(eigenvalues)[::-1]
    signal_space = eigenvectors[:, idx[:N_signals]]
    U1 = signal_space[:-1, :]
    U2 = signal_space[1:, :]
    Phi = np.linalg.pinv(U1) @ U2
    eigenvalues_phi, _ = np.linalg.eig(Phi)
    lambda_ = C / fc
    angles = np.arcsin(np.angle(eigenvalues_phi) * lambda_ / (2 * np.pi * d))
    return np.rad2deg(np.sort(angles))


def monte_carlo_evaluation(
    array_pos, signals, fc, fs, T, SNR, algorithm_func,
    N_trials=100, do_2d=False, theta_step=0.5, phi_step=0.5, imperfections=None
):
    """蒙特卡洛仿真评估"""
    errors_theta = []
    errors_phi = []
    for _ in range(N_trials):
        X = generate_received_signal(array_pos, signals, fc, fs, T, SNR, imperfections=imperfections)
        if do_2d:
            theta_est, phi_est, P, thetas, phis = algorithm_func(
                X, array_pos, (-90, 90), theta_step, (-90, 90), phi_step, fc, len(signals))
            ref = _normalize_signal(signals[0])
            errors_theta.append(theta_est - ref['theta'])
            errors_phi.append(phi_est - ref['phi'])
        else:
            theta_est, _, _, _ = algorithm_func(X, array_pos, (-90, 90), theta_step, fc, len(signals))
            ref = _normalize_signal(signals[0])
            errors_theta.append(theta_est - ref['theta'])
    errors_theta = np.array(errors_theta)
    for e in np.nditer(errors_theta, op_flags=['readwrite']):
        if e > 180: e[...] -= 360
        elif e < -180: e[...] += 360
    rmse = float(np.sqrt(np.mean(errors_theta**2)))
    bias = float(np.mean(errors_theta))
    std_dev = float(np.std(errors_theta, ddof=1))
    if do_2d:
        errors_phi = np.array(errors_phi)
        for e in np.nditer(errors_phi, op_flags=['readwrite']):
            if e > 180: e[...] -= 360
            elif e < -180: e[...] += 360
        rmse_phi = float(np.sqrt(np.mean(errors_phi**2)))
        return rmse, bias, std_dev, errors_theta, rmse_phi, errors_phi
    return rmse, bias, std_dev, errors_theta
