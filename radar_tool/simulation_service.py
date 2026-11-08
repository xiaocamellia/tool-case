"""Background simulation services for interferometer DOA analysis."""

import threading

import numpy as np
from PyQt5.QtCore import QObject, pyqtSignal

from .errors import log_exception, safe_exception_message
from .logger import get_logger
from .algorithms import (
    generate_received_signal,
    bartlett_doa_1d,
    music_doa_1d,
    bartlett_doa_2d,
    music_doa_2d,
    esprit_doa,
    monte_carlo_evaluation,
)
from .algorithms.doa_estimation import MonteCarloCancelled

logger = get_logger("interferometer_sim")


class SimulationCancelled(RuntimeError):
    """Raised when cooperative single-simulation cancellation is observed."""

def _pick_top_peaks_1d(P, thetas, count, min_sep_deg=2.0):
    """Pick separated local maxima from a 1D spectrum."""
    if count <= 0 or len(P) == 0:
        return []
    order = np.argsort(P)[::-1]
    peaks = []
    for idx in order:
        theta = float(thetas[idx])
        if all(abs(theta - picked) >= min_sep_deg for picked in peaks):
            peaks.append(theta)
            if len(peaks) >= count:
                break
    return sorted(peaks)

def _pick_top_peaks_2d(P, thetas, phis, count, min_sep_deg=3.0):
    """Pick separated peaks from a 2D spectrum."""
    if count <= 0 or P.size == 0:
        return []
    flat_order = np.argsort(P.ravel())[::-1]
    peaks = []
    for flat_idx in flat_order:
        phi_idx, theta_idx = np.unravel_index(flat_idx, P.shape)
        theta = float(thetas[theta_idx])
        phi = float(phis[phi_idx])
        if all(np.hypot(theta - pt, phi - pp) >= min_sep_deg for pt, pp in peaks):
            peaks.append((theta, phi))
            if len(peaks) >= count:
                break
    return peaks

class SimulationWorker(QObject):
    """Run a single DOA simulation outside the Qt UI thread."""

    finished = pyqtSignal(dict)
    failed = pyqtSignal(str)
    cancelled = pyqtSignal(str)
    progress = pyqtSignal(int, str)

    def __init__(self, params):
        super().__init__()
        self.params = params
        self._cancel_event = threading.Event()

    def cancel(self):
        self._cancel_event.set()

    def run(self):
        try:
            self.progress.emit(5, '准备仿真数据')
            p = self.params
            array_pos = p['array_pos']
            signals = p['signals']
            fc = p['fc']
            fs = p['fs']
            T = p['T']
            SNR = p['SNR']
            N_signals = p['N_signals']
            do_2d = p['do_2d']
            algo_idx = p['algo_idx']
            theta_range = p['theta_range']
            theta_step = p['theta_step']
            theta_true = p['theta_true']
            phi_true = p['phi_true']
            imperfections = p.get('imperfections')

            if self._cancel_event.is_set():
                raise SimulationCancelled('仿真已取消')
            X = generate_received_signal(
                array_pos, signals, fc, fs, T, SNR,
                imperfections=imperfections,
            )
            if self._cancel_event.is_set():
                raise SimulationCancelled('仿真已取消')
            self.progress.emit(35, '开始 DOA 估计')

            if do_2d:
                if algo_idx == 0:
                    theta_est, phi_est, P, thetas, phis = bartlett_doa_2d(
                        X, array_pos, theta_range, theta_step, (-90, 90), theta_step, fc)
                    algo_name = 'Bartlett (2D)'
                elif algo_idx == 1:
                    theta_est, phi_est, P, thetas, phis = music_doa_2d(
                        X, array_pos, theta_range, theta_step, (-90, 90), theta_step, fc, N_signals)
                    algo_name = 'MUSIC (2D)'
                else:
                    raise ValueError('ESPRIT不支持二维估计')
                peak_pairs = _pick_top_peaks_2d(P, thetas, phis, N_signals)
                theta_ests = [theta for theta, _ in peak_pairs]
                phi_ests = [phi for _, phi in peak_pairs]

                self.finished.emit({
                    'do_2d': True,
                    'algo_name': algo_name,
                    'theta_est': theta_est,
                    'phi_est': phi_est,
                    'theta_ests': theta_ests,
                    'phi_ests': phi_ests,
                    'theta_true': theta_true,
                    'phi_true': phi_true,
                    'targets': signals,
                    'P': P,
                    'thetas': thetas,
                    'phis': phis,
                })
            else:
                if algo_idx == 0:
                    theta_est, P, thetas, _ = bartlett_doa_1d(X, array_pos, theta_range, theta_step, fc, phi_true)
                    algo_name = 'Bartlett'
                elif algo_idx == 1:
                    theta_est, P, thetas, _ = music_doa_1d(X, array_pos, theta_range, theta_step, fc, N_signals, phi_true)
                    algo_name = 'MUSIC'
                else:
                    d = p['array_spacing']
                    if d <= 0:
                        raise ValueError('ESPRIT需要设置阵元间距')
                    angles = esprit_doa(X, d, fc, N_signals)
                    theta_est = float(angles[0]) if len(angles) > 0 else 0
                    _, P, thetas, _ = music_doa_1d(X, array_pos, theta_range, theta_step, fc, N_signals, phi_true)
                    algo_name = 'ESPRIT'
                theta_ests = _pick_top_peaks_1d(P, thetas, N_signals)

                self.finished.emit({
                    'do_2d': False,
                    'algo_name': algo_name,
                    'theta_est': theta_est,
                    'theta_ests': theta_ests,
                    'theta_true': theta_true,
                    'targets': signals,
                    'P': P,
                    'thetas': thetas,
                })
        except SimulationCancelled as e:
            self.cancelled.emit(str(e))
        except Exception as e:
            log_exception(logger, '仿真后台任务', e)
            if self._cancel_event.is_set():
                self.cancelled.emit('仿真已取消')
            else:
                self.failed.emit(safe_exception_message(e))

class MonteCarloWorker(QObject):
    """Run Monte Carlo calculations outside the Qt UI thread."""

    finished = pyqtSignal(dict)
    failed = pyqtSignal(str)
    cancelled = pyqtSignal(str)
    progress = pyqtSignal(int, str)

    def __init__(self, params):
        super().__init__()
        self.params = params
        self._cancel_event = threading.Event()

    def cancel(self):
        self._cancel_event.set()

    def run(self):
        try:
            self.progress.emit(5, '准备蒙特卡洛参数')
            p = self.params
            array_pos = p['array_pos']
            signals = p['signals']
            fc = p['fc']
            fs = p['fs']
            T = p['T']
            SNR = p['SNR']
            N_trials = p['N_trials']
            do_2d = p['do_2d']
            algo_idx = p['algo_idx']
            theta_step = p['theta_step']
            phi_true = p['phi_true']
            imperfections = p.get('imperfections')

            if do_2d:
                if algo_idx == 0:
                    algo_func = lambda X, ap, tr, ts, pr, ps, fc, ns: bartlett_doa_2d(X, ap, tr, ts, pr, ps, fc)
                    algo_name = 'Bartlett (2D)'
                else:
                    algo_func = lambda X, ap, tr, ts, pr, ps, fc, ns: music_doa_2d(X, ap, tr, ts, pr, ps, fc, ns)
                    algo_name = 'MUSIC (2D)'

                rmse_t, bias_t, std_t, errors_t, rmse_p, errors_p = monte_carlo_evaluation(
                    array_pos, signals, fc, fs, T, SNR, algo_func, N_trials,
                    do_2d=True, theta_step=theta_step, phi_step=theta_step,
                    imperfections=imperfections,
                    cancel_event=self._cancel_event,
                    progress_callback=self.progress.emit,
                )
                self.finished.emit({
                    'do_2d': True,
                    'algo_name': algo_name,
                    'rmse_t': rmse_t,
                    'bias_t': bias_t,
                    'std_t': std_t,
                    'errors_t': errors_t,
                    'rmse_p': rmse_p,
                    'errors_p': errors_p,
                })
            else:
                if algo_idx == 0:
                    algo_func = lambda X, ap, tr, ts, fc, ns: bartlett_doa_1d(X, ap, tr, ts, fc, phi_true)
                    algo_name = 'Bartlett'
                else:
                    algo_func = lambda X, ap, tr, ts, fc, ns: music_doa_1d(X, ap, tr, ts, fc, ns, phi_true)
                    algo_name = 'MUSIC' if algo_idx == 1 else 'ESPRIT-like'

                rmse, bias, std_dev, errors = monte_carlo_evaluation(
                    array_pos, signals, fc, fs, T, SNR, algo_func, N_trials,
                    theta_step=theta_step, imperfections=imperfections,
                    cancel_event=self._cancel_event,
                    progress_callback=self.progress.emit,
                )
                self.finished.emit({
                    'do_2d': False,
                    'algo_name': algo_name,
                    'rmse': rmse,
                    'bias': bias,
                    'std_dev': std_dev,
                    'errors': errors,
                })
        except MonteCarloCancelled as e:
            self.cancelled.emit(str(e))
        except Exception as e:
            log_exception(logger, '仿真后台任务', e)
            if self._cancel_event.is_set():
                self.cancelled.emit('蒙特卡洛仿真已取消')
            else:
                self.failed.emit(safe_exception_message(e))
