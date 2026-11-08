"""步骤 8：DOA 算法数值稳定性与可复现性测试。"""

from __future__ import annotations

import numpy as np
import pytest

from radar_tool.algorithms import (
    C,
    SPEED_OF_LIGHT_M_PER_S,
    DoaValidationError,
    bartlett_doa_1d,
    bartlett_doa_2d,
    create_l_array,
    create_rect_array,
    create_ula,
    create_uca,
    esprit_doa,
    generate_received_signal,
    monte_carlo_evaluation,
    music_doa_1d,
)


FC = 3.0e8
WAVELENGTH = SPEED_OF_LIGHT_M_PER_S / FC
ARRAY = create_ula(8, WAVELENGTH / 2)


def _generate(signals, snr=20.0, seed=1234):
    return generate_received_signal(
        ARRAY, signals, FC, 1.0e6, 1.0e-3, snr, seed=seed)


def _separated_peaks(power, thetas, count, separation=5.0):
    local_indices = [
        index
        for index in range(1, len(power) - 1)
        if power[index] >= power[index - 1]
        and power[index] > power[index + 1]
    ]
    local_indices.sort(key=lambda index: power[index], reverse=True)
    selected = []
    for index in local_indices:
        if all(
            abs(float(thetas[index]) - float(thetas[chosen])) >= separation
            for chosen in selected
        ):
            selected.append(index)
            if len(selected) == count:
                break
    return sorted(float(thetas[index]) for index in selected)


def test_single_source_music_baseline():
    signals = [{"theta": -15.0, "phi": 0.0, "amp": 1.0, "freq": 100e3}]
    matrix = _generate(signals)
    theta, power, thetas, phi = music_doa_1d(
        matrix, ARRAY, (-90, 90), 0.5, FC, 1, phi=0.0)

    assert theta == pytest.approx(-15.0, abs=0.5)
    assert phi == 0.0
    assert np.all(np.isfinite(power))
    assert power.shape == thetas.shape


def test_two_source_music_baseline_resolves_both_directions():
    signals = [
        {"theta": -20.0, "phi": 0.0, "amp": 1.0, "freq": 100e3},
        {"theta": 20.0, "phi": 0.0, "amp": 1.0, "freq": 200e3},
    ]
    matrix = _generate(signals)
    _theta, power, thetas, _phi = music_doa_1d(
        matrix, ARRAY, (-90, 90), 0.5, FC, 2, phi=0.0)
    peaks = _separated_peaks(power, thetas, 2)

    assert peaks[0] == pytest.approx(-20.0, abs=1.0)
    assert peaks[1] == pytest.approx(20.0, abs=1.0)


def test_low_snr_music_baseline_remains_finite():
    signals = [{"theta": 10.0, "phi": 0.0, "amp": 1.0, "freq": 100e3}]
    matrix = _generate(signals, snr=-10.0, seed=2026)
    theta, power, _thetas, _phi = music_doa_1d(
        matrix, ARRAY, (-90, 90), 0.5, FC, 1, phi=0.0)

    assert np.isfinite(theta)
    assert np.all(np.isfinite(power))
    assert np.max(power) > 0.0


def test_correlated_sources_music_baseline_does_not_return_nan():
    signals = [
        {"theta": -20.0, "phi": 0.0, "amp": 1.0, "freq": 100e3},
        {"theta": 20.0, "phi": 0.0, "amp": 1.0, "freq": 100e3},
    ]
    matrix = _generate(signals, seed=31415)
    theta, power, thetas, _phi = music_doa_1d(
        matrix, ARRAY, (-90, 90), 0.5, FC, 2, phi=0.0)
    peaks = _separated_peaks(power, thetas, 2)

    assert np.isfinite(theta)
    assert np.all(np.isfinite(power))
    assert peaks[0] == pytest.approx(-20.0, abs=2.5)
    assert peaks[1] == pytest.approx(20.0, abs=2.5)


def test_singular_array_with_duplicate_coordinates_is_rejected():
    singular_array = np.array([[0.0, 0.0], [0.0, 0.0], [1.0, 0.0]])
    matrix = np.ones((3, 8), dtype=complex)

    with pytest.raises(DoaValidationError, match="重复阵元"):
        music_doa_1d(
            matrix, singular_array, (-90, 90), 1.0, FC, 1, phi=0.0)


def test_array_geometry_rejects_invalid_or_singular_parameters():
    invalid_calls = [
        lambda: create_ula(1, 0.5),
        lambda: create_ula(4, 0.0),
        lambda: create_uca(4, np.nan),
        lambda: create_l_array(1, 3, 0.5),
        lambda: create_rect_array(1, 1, 0.5, 0.5),
        lambda: create_rect_array(2, 2, 0.0, 0.5),
    ]
    for call in invalid_calls:
        with pytest.raises(ValueError):
            call()

    geometries = [
        create_ula(4, 0.5),
        create_uca(4, 1.0),
        create_l_array(3, 3, 0.5),
        create_rect_array(2, 3, 0.5, 0.75),
    ]
    for positions in geometries:
        assert positions.ndim == 2
        assert positions.shape[1] == 2
        assert positions.shape[0] >= 2
        assert np.all(np.isfinite(positions))
        assert np.unique(positions, axis=0).shape[0] == positions.shape[0]


def test_music_uses_eigh_for_hermitian_covariance(monkeypatch):
    matrix = _generate(
        [{"theta": 5.0, "phi": 0.0, "amp": 1.0, "freq": 100e3}])

    def fail_if_general_eig_is_used(*_args, **_kwargs):
        raise AssertionError("MUSIC 不得调用 np.linalg.eig")

    monkeypatch.setattr(np.linalg, "eig", fail_if_general_eig_is_used)
    theta, _power, _thetas, _phi = music_doa_1d(
        matrix, ARRAY, (-90, 90), 1.0, FC, 1, phi=0.0)

    assert np.isfinite(theta)


@pytest.mark.parametrize("signal_count", [0, -1, 8, 8.5, np.nan])
def test_music_rejects_invalid_signal_count(signal_count):
    matrix = _generate(
        [{"theta": 0.0, "phi": 0.0, "amp": 1.0, "freq": 100e3}])

    with pytest.raises(DoaValidationError):
        music_doa_1d(
            matrix, ARRAY, (-90, 90), 1.0, FC, signal_count, phi=0.0)


def test_music_rejects_zero_noise_subspace():
    matrix = np.zeros((len(ARRAY), 16), dtype=complex)

    with pytest.raises(DoaValidationError, match="噪声子空间"):
        music_doa_1d(
            matrix, ARRAY, (-90, 90), 1.0, FC, 1, phi=0.0)


def test_scan_range_and_step_validation():
    matrix = _generate(
        [{"theta": 0.0, "phi": 0.0, "amp": 1.0, "freq": 100e3}])

    with pytest.raises(DoaValidationError, match="步长必须大于 0"):
        bartlett_doa_1d(matrix, ARRAY, (-90, 90), 0.0, FC, phi=0.0)
    with pytest.raises(DoaValidationError, match="起点不得大于终点"):
        music_doa_1d(matrix, ARRAY, (10, -10), 1.0, FC, 1, phi=0.0)
    with pytest.raises(DoaValidationError, match="起点不得大于终点"):
        bartlett_doa_2d(
            matrix, ARRAY, (-90, 90), 1.0, (10, -10), 1.0, FC)


def test_esprit_clips_out_of_visible_range_without_nan():
    antenna_count = 4
    snapshot_count = 64
    alternating_mode = np.exp(
        1j * np.pi * np.arange(antenna_count))
    matrix = np.repeat(alternating_mode[:, None], snapshot_count, axis=1)
    rng = np.random.default_rng(77)
    matrix = matrix + 1e-4 * (
        rng.standard_normal(matrix.shape)
        + 1j * rng.standard_normal(matrix.shape)
    )

    angles = esprit_doa(matrix, WAVELENGTH / 4.0, FC, 1)

    assert angles.shape == (1,)
    assert np.all(np.isfinite(angles))
    assert np.all(np.abs(angles) <= 90.0)
    assert angles[0] == pytest.approx(90.0, abs=1e-6)


def test_same_seed_reproduces_imperfections_phase_and_noise():
    signals = [
        {"theta": -10.0, "phi": 0.0, "amp": 1.0, "freq": 100e3},
        {"theta": 15.0, "phi": 0.0, "amp": 0.8, "freq": 180e3},
    ]
    imperfections = {
        "pos_enabled": True,
        "pos_std": 0.01,
        "amp_enabled": True,
        "amp_std_db": 0.5,
        "phase_enabled": True,
        "phase_std_deg": 5.0,
        "freq_enabled": True,
        "freq_offset_std": 100.0,
    }

    first = generate_received_signal(
        ARRAY, signals, FC, 1.0e6, 1.0e-3, 12.0,
        imperfections=imperfections, seed=20260405)
    second = generate_received_signal(
        ARRAY, signals, FC, 1.0e6, 1.0e-3, 12.0,
        imperfections=imperfections, seed=20260405)

    assert np.array_equal(first, second)


def test_same_seed_reproduces_monte_carlo_results():
    signals = [{"theta": -8.0, "phi": 0.0, "amp": 1.0, "freq": 100e3}]
    imperfections = {
        "pos_enabled": True,
        "pos_std": 0.005,
        "phase_enabled": True,
        "phase_std_deg": 3.0,
    }

    def algorithm(matrix, positions, _theta_range, theta_step, fc, count):
        return bartlett_doa_1d(
            matrix, positions, (-90, 90), theta_step, fc, phi=0.0)

    first = monte_carlo_evaluation(
        ARRAY, signals, FC, 1.0e6, 5.0e-4, 15.0, algorithm,
        N_trials=3, theta_step=2.0, imperfections=imperfections, seed=99)
    second = monte_carlo_evaluation(
        ARRAY, signals, FC, 1.0e6, 5.0e-4, 15.0, algorithm,
        N_trials=3, theta_step=2.0, imperfections=imperfections, seed=99)

    assert np.array_equal(first[3], second[3])
    assert np.array_equal(np.asarray(first[:3]), np.asarray(second[:3]))


def test_single_trial_monte_carlo_uses_population_standard_deviation():
    signals = [{"theta": 0.0, "phi": 0.0, "amp": 1.0, "freq": 100e3}]

    def algorithm(matrix, positions, _theta_range, theta_step, fc, count):
        return bartlett_doa_1d(
            matrix, positions, (-90, 90), theta_step, fc, phi=0.0)

    rmse, bias, std_dev, errors = monte_carlo_evaluation(
        ARRAY, signals, FC, 1.0e6, 5.0e-4, 20.0, algorithm,
        N_trials=1, theta_step=2.0, seed=1)

    assert np.isfinite(rmse)
    assert np.isfinite(bias)
    assert np.isfinite(std_dev)
    assert std_dev == 0.0
    assert errors.shape == (1,)


def test_speed_of_light_constant_has_explicit_si_unit():
    assert SPEED_OF_LIGHT_M_PER_S == 3.0e8
    assert SPEED_OF_LIGHT_M_PER_S == C
