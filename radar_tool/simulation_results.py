"""Result formatting mixins for the interferometer simulation panel."""

import numpy as np


class SimulationResultMixin:

    def _signal_quality_text(self, P, SNR):
        """Build compact quality metrics that make SNR changes visible."""
        P_db = 10 * np.log10(np.maximum(P, 1e-30))
        peak_db = float(np.nanmax(P_db))
        median_db = float(np.nanmedian(P_db))
        noise_rms = np.sqrt(1.0 / (10 ** (SNR / 10)))
        return (
            f"谱峰-中位噪底: {peak_db - median_db:.2f} dB\n"
            f"相对噪声RMS: {noise_rms:.4f}\n"
            f"说明: 高SNR或快拍数较大时，角度估计会稳定在同一网格点"
        )

    def _format_targets_text(self, targets):
        lines = []
        for idx, target in enumerate(targets):
            lines.append(
                f"真实目标{idx + 1}: θ={target['theta']}°, φ={target['phi']}°, "
                f"f={target['freq'] / 1000:.1f}kHz, SNR={target['snr']}dB"
            )
        return '\n'.join(lines)

    def _format_estimates_1d_text(self, theta_ests):
        return '\n'.join(f"估计峰{idx + 1}: θ={theta:.4f}°" for idx, theta in enumerate(theta_ests))

    def _format_estimates_2d_text(self, theta_ests, phi_ests):
        return '\n'.join(
            f"估计峰{idx + 1}: θ={theta:.4f}°, φ={phi:.4f}°"
            for idx, (theta, phi) in enumerate(zip(theta_ests, phi_ests))
        )

    def _format_matched_errors_1d_text(self, targets, theta_ests):
        unused = set(range(len(theta_ests)))
        lines = []
        for target_idx, target in enumerate(targets):
            if not unused:
                lines.append(f"目标{target_idx + 1}: 未匹配到估计峰")
                continue
            best_idx = min(unused, key=lambda idx: abs(theta_ests[idx] - target['theta']))
            unused.remove(best_idx)
            error_t = theta_ests[best_idx] - target['theta']
            lines.append(
                f"目标{target_idx + 1}匹配估计峰{best_idx + 1}: Δθ={error_t:.4f}°"
            )
        return '\n'.join(lines)

    def _format_matched_errors_2d_text(self, targets, theta_ests, phi_ests):
        estimate_count = min(len(theta_ests), len(phi_ests))
        unused = set(range(estimate_count))
        lines = []
        for target_idx, target in enumerate(targets):
            if not unused:
                lines.append(f"目标{target_idx + 1}: 未匹配到估计峰")
                continue
            best_idx = min(
                unused,
                key=lambda idx: np.hypot(theta_ests[idx] - target['theta'], phi_ests[idx] - target['phi'])
            )
            unused.remove(best_idx)
            error_t = theta_ests[best_idx] - target['theta']
            error_p = phi_ests[best_idx] - target['phi']
            lines.append(
                f"目标{target_idx + 1}匹配估计峰{best_idx + 1}: Δθ={error_t:.4f}°, Δφ={error_p:.4f}°"
            )
        return '\n'.join(lines)
