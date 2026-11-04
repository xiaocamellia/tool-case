import numpy as np

from radar_tool.compare_analysis import (
    _compute_truth_review, resample_gps_to_radar_cadence,
)

from radar_tool.alignment import (
    apply_time_mapping,
    best_lag_by_xcorr,
    calculate_error_metrics,
    estimate_time_mapping,
    interpolate_at,
    prepare_timed_series,
)


def test_cross_correlation_does_not_shift_constant_series():
    assert best_lag_by_xcorr(np.ones(30), np.ones(30), max_lag=10) == 0


def test_prepare_timed_series_keeps_pairs_and_merges_duplicate_times():
    time, values = prepare_timed_series(
        [2.0, 1.0, 1.0, np.nan, 3.0],
        [20.0, 8.0, 12.0, 99.0, np.nan],
    )
    np.testing.assert_allclose(time, [1.0, 2.0])
    np.testing.assert_allclose(values, [10.0, 20.0])


def test_interpolation_leaves_extrapolated_samples_invalid():
    actual = interpolate_at([0.0, 1.0, 2.0], [0.0, 10.0, 20.0], [-1.0, 0.5, 3.0])
    assert np.isnan(actual[0])
    assert actual[1] == 5.0
    assert np.isnan(actual[2])


def test_cross_correlation_recovers_truth_clock_delay():
    radar_time = np.arange(240, dtype=float) * 0.128
    truth_time = np.arange(120, dtype=float) * 0.256
    delay_s = 0.768
    radar = np.sin(0.43 * radar_time) + 0.2 * np.sin(1.1 * radar_time)
    truth = np.sin(0.43 * (truth_time - delay_s)) + 0.2 * np.sin(1.1 * (truth_time - delay_s))

    mapping = estimate_time_mapping(
        radar_time, radar, truth_time, truth, method='xcorr', max_shift_ratio=0.2
    )
    aligned = apply_time_mapping(radar_time, truth_time, truth, mapping)
    metrics = calculate_error_metrics(radar, aligned)

    assert abs(mapping['query_offset_s'] - delay_s) < 0.15
    assert metrics['rmse'] < 0.04
    assert metrics['corr'] > 0.999


def test_single_point_manual_offset_uses_documented_sign():
    radar_time = np.arange(20, dtype=float)
    truth_time = np.arange(20, dtype=float)
    radar = radar_time.copy()
    truth = truth_time - 2.0
    mapping = estimate_time_mapping(
        radar_time, radar, truth_time, truth,
        method='single_point', manual_offset_s=-2.0,
    )
    aligned = apply_time_mapping(radar_time, truth_time, truth, mapping)
    np.testing.assert_allclose(aligned[:-2], radar[:-2])


def test_angular_metrics_wrap_across_180_degrees():
    measured = np.array([179.0, -179.0, 178.0])
    truth = np.array([-179.0, 179.0, 179.0])
    metrics = calculate_error_metrics(measured, truth, angular=True)
    assert metrics['max_abs'] == 2.0
    assert metrics['rmse'] < 2.0


def test_gps_dropped_rows_are_interpolated_by_timestamp_without_stretching():
    full_time = np.arange(9, dtype=float) * 0.256
    kept = np.array([0, 1, 2, 4, 5, 7, 8])
    raw_sample, grid_sample, actual = resample_gps_to_radar_cadence(
        full_time[kept], 3.0 * full_time[kept] + 2.0,
        radar_interval_ms=128.0, time_unit='s', method='linear',
    )
    np.testing.assert_allclose(raw_sample, kept * 2.0)
    np.testing.assert_array_equal(grid_sample, np.arange(17))
    np.testing.assert_allclose(actual, 3.0 * (np.arange(17) * 0.128) + 2.0)


def test_two_stage_review_keeps_zero_bias_for_coarse_and_removes_pairs_for_fine():
    radar_sample = np.arange(80, dtype=float)
    radar_time = radar_sample * 0.128
    gps_time = np.delete(np.arange(40, dtype=float) * 0.256, [9, 21])
    truth = 100.0 + np.sin(gps_time)
    radar = 105.0 + np.sin(radar_time)
    config = {
        'key': 'distance', 'label': '距离', 'unit': 'm', 'angular': False,
        'radar_col': '距离', 'truth_col': '距离',
        'radar_bias': 0.0, 'truth_bias': 0.0,
    }
    payload = {
        'stage': 'coarse', 'radar_sample': radar_sample,
        'gps_time': gps_time, 'gps_time_column': '时间', 'gps_time_unit': 's',
        'radar_interval_ms': 128.0,
        'series': {'distance': {
            'config': config, 'radar_source': radar, 'truth_source': truth,
        }},
        'reference_key': 'distance', 'method': 'xcorr',
        'interpolation': 'linear', 'max_shift_ratio': 0.25,
        'scale_span': 0.3, 'manual_offset_s': 0.0,
        'outlier_threshold': 0.0, 'coarse_mapping': None,
        'preprocess_revision': 0,
    }
    coarse = _compute_truth_review(payload)
    assert coarse['mapping']['query_scale'] == 1.0
    assert abs(coarse['metric_results']['distance']['metrics']['mean_error'] - 5.0) < 0.02

    config['radar_bias'] = -5.0
    radar[30] = 999.0
    payload.update(stage='fine', coarse_mapping=coarse['mapping'])
    fine = _compute_truth_review(payload)
    assert not fine['result'].loc[30, 'paired_sample_kept']
    assert np.isnan(fine['result'].loc[30, 'radar_distance'])
    assert np.isnan(fine['result'].loc[30, 'gps_aligned_distance'])
    assert fine['metric_results']['distance']['metrics']['rmse'] < 0.02


def test_multiple_outlier_dimensions_remove_union_but_alignment_uses_reference():
    sample = np.arange(80, dtype=float)
    time_s = sample * 0.128
    distance = 100.0 + np.sin(time_s)
    speed = 5.0 + np.cos(time_s)
    azimuth = 20.0 + np.sin(time_s * 0.5)
    distance_config = {
        'key': 'distance', 'label': '距离', 'unit': 'm', 'angular': False,
        'radar_col': '距离', 'truth_col': '距离',
        'radar_bias': 0.0, 'truth_bias': 0.0,
    }
    speed_config = {
        'key': 'speed', 'label': '速度', 'unit': 'm/s', 'angular': False,
        'radar_col': '速度', 'truth_col': '速度',
        'radar_bias': 0.0, 'truth_bias': 0.0,
    }
    azimuth_config = {
        'key': 'azimuth', 'label': '方位角', 'unit': 'deg', 'angular': True,
        'radar_col': '方位角', 'truth_col': '方位角',
        'radar_bias': 0.0, 'truth_bias': 0.0,
    }
    radar_distance = distance.copy()
    radar_speed = speed.copy()
    radar_distance[20] = 900.0
    radar_speed[50] = -500.0
    radar_azimuth = azimuth.copy()
    radar_azimuth[65] = 150.0
    payload = {
        'stage': 'coarse', 'radar_sample': sample,
        'gps_time': time_s, 'gps_time_column': '时间', 'gps_time_unit': 's',
        'radar_interval_ms': 128.0,
        'series': {
            'distance': {
                'config': distance_config, 'radar_source': radar_distance,
                'truth_source': distance,
            },
            'speed': {
                'config': speed_config, 'radar_source': radar_speed,
                'truth_source': speed,
            },
            'azimuth': {
                'config': azimuth_config, 'radar_source': radar_azimuth,
                'truth_source': azimuth,
            },
        },
        'reference_key': 'distance', 'reference_angular': False,
        'method': 'single_point', 'interpolation': 'linear',
        'max_shift_ratio': 0.25, 'scale_span': 0.3,
        'manual_offset_s': 0.0, 'outlier_threshold': 1.0,
        'additional_outlier_dimensions': [],
        'coarse_mapping': None, 'preprocess_revision': 0,
    }
    coarse = _compute_truth_review(payload)
    payload.update(
        stage='fine', coarse_mapping=coarse['mapping'],
        additional_outlier_dimensions=[
            {'key': 'speed', 'threshold': 1.0},
            {'key': 'azimuth', 'threshold': 5.0},
        ],
    )
    fine = _compute_truth_review(payload)

    kept = fine['result']['paired_sample_kept'].to_numpy()
    assert not kept[20]
    assert not kept[50]
    assert not kept[65]
    assert kept.sum() == 77
    assert fine['mapping']['query_scale'] == 1.0
    assert fine['metrics_summary']['reference_metric'] == 'distance'
    assert [
        item['metric_key']
        for item in fine['metrics_summary']['outlier_removal']['dimensions']
    ] == ['distance', 'speed', 'azimuth']
