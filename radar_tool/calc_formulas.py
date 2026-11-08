"""Pure engineering calculator formulas."""
import math

from .calc_units import C

def calculate_link_budget(
    pt_dbm,
    gt_dbi,
    lt_db,
    freq_ghz,
    distance_km,
    gr_dbi,
    lr_db,
    nf_db,
    bandwidth_mhz,
    ebn0_req_db,
    rate_bps,
):
    """Calculate a link budget using explicit physical units."""

    values = {
        '发射功率': pt_dbm,
        '发射增益': gt_dbi,
        '发射损耗': lt_db,
        '频率': freq_ghz,
        '距离': distance_km,
        '接收增益': gr_dbi,
        '接收损耗': lr_db,
        '噪声系数': nf_db,
        '带宽': bandwidth_mhz,
        '所需Eb/N0': ebn0_req_db,
        '码率': rate_bps,
    }
    for name, value in values.items():
        if not math.isfinite(float(value)):
            raise ValueError(f'{name}必须是有限数值')

    if freq_ghz <= 0:
        raise ValueError('频率必须大于 0 GHz')
    if distance_km <= 0:
        raise ValueError('距离必须大于 0 km')
    if bandwidth_mhz <= 0:
        raise ValueError('带宽必须大于 0 MHz')
    if rate_bps <= 0:
        raise ValueError('码率必须大于 0 bps')

    frequency_hz = float(freq_ghz) * 1e9
    distance_m = float(distance_km) * 1e3
    bandwidth_hz = float(bandwidth_mhz) * 1e6
    rate_bps = float(rate_bps)

    wavelength_m = C / frequency_hz
    free_space_loss_db = 20 * math.log10(
        4 * math.pi * distance_m / wavelength_m)
    receive_power_dbm = (
        float(pt_dbm) + float(gt_dbi) - float(lt_db)
        - free_space_loss_db + float(gr_dbi) - float(lr_db)
    )
    noise_power_dbm = (
        -174 + 10 * math.log10(bandwidth_hz) + float(nf_db)
    )
    carrier_to_noise_db = receive_power_dbm - noise_power_dbm
    eb_to_n0_db = carrier_to_noise_db - 10 * math.log10(
        bandwidth_hz / rate_bps)
    margin_db = eb_to_n0_db - float(ebn0_req_db)

    return {
        'frequency_hz': frequency_hz,
        'distance_m': distance_m,
        'bandwidth_hz': bandwidth_hz,
        'rate_bps': rate_bps,
        'wavelength_m': wavelength_m,
        'free_space_loss_db': free_space_loss_db,
        'receive_power_dbm': receive_power_dbm,
        'receive_power_dbw': receive_power_dbm - 30,
        'noise_power_dbm': noise_power_dbm,
        'noise_power_dbw': noise_power_dbm - 30,
        'carrier_to_noise_db': carrier_to_noise_db,
        'eb_to_n0_db': eb_to_n0_db,
        'ebn0_req_db': float(ebn0_req_db),
        'margin_db': margin_db,
    }
def calculate_df_accuracy(
    baseline_lam,
    element_count,
    snr_db,
    snapshots,
    theta_deg,
    algorithm,
):
    """Calculate interferometer/MUSIC accuracy with explicit validity checks."""

    values = {
        '基线长度': baseline_lam,
        '阵元数': element_count,
        '信噪比': snr_db,
        '快拍数': snapshots,
        '来波方向': theta_deg,
    }
    for name, value in values.items():
        if not math.isfinite(float(value)):
            raise ValueError(f'{name}必须是有限数值')

    baseline_lam = float(baseline_lam)
    element_count = int(element_count)
    snr_db = float(snr_db)
    snapshots = int(snapshots)
    theta_deg = float(theta_deg)

    if baseline_lam <= 0:
        raise ValueError('基线长度必须大于 0 λ')
    if element_count < 2:
        raise ValueError('阵元数必须至少为 2')
    if snapshots < 1:
        raise ValueError('快拍数必须至少为 1')
    if not -90 < theta_deg < 90:
        raise ValueError('来波方向必须满足 -90° < theta < 90°')

    theta_rad = math.radians(theta_deg)
    cos_theta = math.cos(theta_rad)
    snr_linear = 10 ** (snr_db / 10)
    singular = abs(cos_theta) < 1e-12

    if singular:
        sigma_interfer_rad = float('inf')
        crb_rad2 = float('inf')
    else:
        sigma_interfer_rad = (
            1 / (2 * math.pi * baseline_lam * cos_theta
                 * math.sqrt(2 * snr_linear))
        )
        crb_rad2 = (
            1 / (snapshots * snr_linear)
            / (8 * math.pi ** 2 * baseline_lam ** 2 * cos_theta ** 2)
        )

    sigma_interfer_deg = math.degrees(sigma_interfer_rad)
    crb_deg = math.degrees(math.sqrt(crb_rad2)) if math.isfinite(crb_rad2) else float('inf')

    is_music = 'MUSIC' in str(algorithm)
    music_reasons = []
    if element_count < 2:
        music_reasons.append('阵元数至少为 2')
    if snapshots < 2 * element_count:
        music_reasons.append('快拍数至少为 2N')
    if snr_db < 0:
        music_reasons.append('SNR 至少为 0 dB')
    music_applicable = is_music and not music_reasons
    if is_music and music_applicable:
        estimated_rmse_deg = sigma_interfer_deg / math.sqrt(element_count)
        music_gain = math.sqrt(element_count)
    else:
        estimated_rmse_deg = sigma_interfer_deg
        music_gain = 1.0

    if music_reasons:
        music_status = '不适用（' + '、'.join(music_reasons) + '）'
    elif is_music:
        music_status = '适用（窄带、非相关信源、阵列已校准）'
    else:
        music_status = '未选择'

    side_fire_warning = abs(theta_deg) >= 89
    ambiguity_range = (
        math.degrees(math.asin(1 / (2 * baseline_lam)))
        if baseline_lam > 0.5 else 90.0
    )

    return {
        'baseline_lam': baseline_lam,
        'element_count': element_count,
        'snr_db': snr_db,
        'snr_linear': snr_linear,
        'snapshots': snapshots,
        'theta_deg': theta_deg,
        'theta_rad': theta_rad,
        'cos_theta': cos_theta,
        'singular': singular,
        'sigma_interfer_rad': sigma_interfer_rad,
        'sigma_interfer_deg': sigma_interfer_deg,
        'crb_rad2': crb_rad2,
        'crb_deg': crb_deg,
        'algorithm': str(algorithm),
        'is_music': is_music,
        'music_applicable': music_applicable,
        'music_gain': music_gain,
        'music_status': music_status,
        'estimated_rmse_deg': estimated_rmse_deg,
        'ambiguity_range_deg': ambiguity_range,
        'side_fire_warning': side_fire_warning,
    }
def calculate_array_parameters(
    config,
    element_count,
    spacing_lam,
    frequency_hz,
    element_gain,
    radius_lam=None,
    rows=None,
    cols=None,
    dx_lam=None,
    dy_lam=None,
):
    """Calculate configuration-specific array aperture and beam metrics."""

    if not math.isfinite(float(frequency_hz)) or frequency_hz <= 0:
        raise ValueError('工作频率必须大于 0')
    if not math.isfinite(float(element_gain)):
        raise ValueError('阵元增益必须是有限数值')
    element_count = int(element_count)
    if element_count < 2:
        raise ValueError('阵元数必须至少为 2')

    config = str(config)
    if config.startswith('均匀线阵'):
        spacing_lam = float(spacing_lam)
        if not math.isfinite(spacing_lam) or spacing_lam <= 0:
            raise ValueError('阵元间距必须大于 0')
        aperture = (element_count - 1) * spacing_lam
        beamwidth = 50.8 / (element_count * spacing_lam)
        if spacing_lam > 1:
            grating = math.degrees(math.asin(min(1.0 / spacing_lam, 1.0)))
            warning = f'间距 {spacing_lam:.2f}λ > 1λ，存在栅瓣'
        else:
            grating = None
            warning = (
                f'间距 {spacing_lam:.2f}λ > 0.5λ，无模糊范围收窄'
                if spacing_lam > 0.5 else '间距 ≤0.5λ，无栅瓣风险'
            )
        unambig = (
            math.degrees(math.asin(min(1.0 / (2 * spacing_lam), 1.0)))
            if spacing_lam > 0.5 else 180.0
        )
        return {
            'array_type': 'ULA',
            'element_count': element_count,
            'gain_db': float(element_gain) + 10 * math.log10(element_count),
            'beamwidth_deg': beamwidth,
            'beamwidth_az_deg': beamwidth,
            'beamwidth_el_deg': None,
            'aperture': aperture,
            'aperture_x': aperture,
            'aperture_y': 0.0,
            'grating_angle_deg': grating,
            'unambig_deg': unambig,
            'warning': warning,
            'formula': f'θ3dB=50.8/(N·d)={beamwidth:.2f}°',
        }

    if config.startswith('矩形面阵'):
        rows = int(rows)
        cols = int(cols)
        dx_lam = float(dx_lam)
        dy_lam = float(dy_lam)
        if rows < 1 or cols < 1 or rows * cols < 2:
            raise ValueError('矩形面阵行数×列数必须至少为 2')
        if not all(math.isfinite(value) and value > 0
                   for value in (dx_lam, dy_lam)):
            raise ValueError('X/Y 阵元间距必须大于 0')
        aperture_x = (cols - 1) * dx_lam
        aperture_y = (rows - 1) * dy_lam
        beamwidth_az = 50.8 / (cols * dx_lam)
        beamwidth_el = 50.8 / (rows * dy_lam)
        if dx_lam > 1 or dy_lam > 1:
            spacing = max(dx_lam, dy_lam)
            grating = math.degrees(math.asin(min(1.0 / spacing, 1.0)))
            warning = f'存在大于 1λ 的方向间距，可能产生栅瓣'
        else:
            grating = None
            warning = 'X/Y 间距均不超过 1λ，无一维栅瓣风险'
        unambig = min(
            math.degrees(math.asin(min(1.0 / (2 * dx_lam), 1.0)))
            if dx_lam > 0.5 else 180.0,
            math.degrees(math.asin(min(1.0 / (2 * dy_lam), 1.0)))
            if dy_lam > 0.5 else 180.0,
        )
        return {
            'array_type': 'RECT',
            'element_count': rows * cols,
            'gain_db': float(element_gain) + 10 * math.log10(rows * cols),
            'beamwidth_deg': min(beamwidth_az, beamwidth_el),
            'beamwidth_az_deg': beamwidth_az,
            'beamwidth_el_deg': beamwidth_el,
            'aperture': math.hypot(aperture_x, aperture_y),
            'aperture_x': aperture_x,
            'aperture_y': aperture_y,
            'grating_angle_deg': grating,
            'unambig_deg': unambig,
            'warning': warning,
            'formula': (
                f'方位θ3dB=50.8/(M·dx)={beamwidth_az:.2f}°，'
                f'俯仰θ3dB=50.8/(N·dy)={beamwidth_el:.2f}°'
            ),
        }

    if config.startswith('均匀圆阵'):
        radius_lam = float(radius_lam)
        if not math.isfinite(radius_lam) or radius_lam <= 0:
            raise ValueError('UCA 半径必须大于 0')
        beamwidth = 50.8 / (2 * radius_lam)
        return {
            'array_type': 'UCA',
            'element_count': element_count,
            'gain_db': float(element_gain) + 10 * math.log10(element_count),
            'beamwidth_deg': beamwidth,
            'beamwidth_az_deg': beamwidth,
            'beamwidth_el_deg': None,
            'aperture': 2 * radius_lam,
            'aperture_x': 2 * radius_lam,
            'aperture_y': 2 * radius_lam,
            'grating_angle_deg': None,
            'unambig_deg': None,
            'warning': '圆阵按半径和角间距评估，不套用线阵栅瓣公式',
            'formula': f'θ3dB≈50.8/(2R)={beamwidth:.2f}°',
        }

    raise ValueError('未知阵列构型')
