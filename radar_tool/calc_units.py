"""Pure unit conversion and numeric validation helpers."""
import math

C = 3e8
K_BOLTZ = 1.38e-23

def _finite_value(value, name):
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f'{name}必须是有限数值') from exc
    if not math.isfinite(result):
        raise ValueError(f'{name}必须是有限数值')
    return result
def _positive_value(value, name):
    result = _finite_value(value, name)
    if result <= 0:
        raise ValueError(f'{name}必须大于 0')
    return result
def convert_temperature(value, source_unit, target_unit):
    """Convert Celsius/Fahrenheit/Kelvin with absolute-temperature checks."""

    value = _finite_value(value, '温度')
    if source_unit not in ('℃', '℉', 'K'):
        raise ValueError(f'不支持的温度单位: {source_unit}')
    if target_unit not in ('℃', '℉', 'K'):
        raise ValueError(f'不支持的温度单位: {target_unit}')

    if source_unit == 'K':
        kelvin = _positive_value(value, '开尔文温度')
    elif source_unit == '℃':
        kelvin = value + 273.15
    else:
        kelvin = (value - 32) * 5 / 9 + 273.15
    if kelvin <= 0:
        raise ValueError('温度换算结果必须大于 0 K')

    if target_unit == 'K':
        return kelvin
    if target_unit == '℃':
        return kelvin - 273.15
    return (kelvin - 273.15) * 9 / 5 + 32
def convert_angle(value, source_unit, target_unit):
    """Convert degrees, radians, and milliradians."""

    value = _finite_value(value, '角度')
    to_radians = {'°': math.radians, 'rad': lambda x: x,
                  'mrad': lambda x: x / 1000}
    from_radians = {'°': math.degrees, 'rad': lambda x: x,
                    'mrad': lambda x: x * 1000}
    if source_unit not in to_radians or target_unit not in from_radians:
        raise ValueError(f'不支持的角度单位: {source_unit} -> {target_unit}')
    return from_radians[target_unit](to_radians[source_unit](value))
def convert_power(value, source_unit, target_unit):
    """Convert linear watts/milliwatts and dBm/dBW power levels."""

    value = _finite_value(value, '功率')
    linear_units = {'W', 'mW'}
    dbm_units = {'dBm', 'dBW'}
    if source_unit not in linear_units | dbm_units:
        raise ValueError(f'不支持的功率单位: {source_unit}')
    if target_unit not in linear_units | dbm_units:
        raise ValueError(f'不支持的功率单位: {target_unit}')

    if source_unit == 'W':
        watts = _positive_value(value, '功率')
    elif source_unit == 'mW':
        watts = _positive_value(value, '功率') / 1000
    elif source_unit == 'dBm':
        watts = 10 ** ((value - 30) / 10)
    else:
        watts = 10 ** (value / 10)

    if target_unit == 'W':
        return watts
    if target_unit == 'mW':
        return watts * 1000
    if target_unit == 'dBm':
        return 10 * math.log10(watts * 1000)
    return 10 * math.log10(watts)
def convert_gain_ratio(value, source_unit, target_unit):
    """Convert a positive power/amplitude ratio to decibels and back."""

    value = _finite_value(value, '增益')
    if source_unit == 'dB':
        ratio = 10 ** (value / 10)
    elif source_unit == '倍数':
        ratio = _positive_value(value, '倍数')
    else:
        raise ValueError(f'不支持的增益单位: {source_unit}')

    if target_unit == 'dB':
        return 10 * math.log10(ratio)
    if target_unit == '倍数':
        return ratio
    raise ValueError(f'不支持的增益单位: {target_unit}')
def convert_frequency_wavelength(value, source_unit, target_unit):
    """Convert positive frequencies and wavelengths, including cross-domain."""

    value = _positive_value(value, '频率/波长')
    frequency_factors = {'Hz': 1.0, 'kHz': 1e3, 'MHz': 1e6, 'GHz': 1e9}
    length_factors = {'m': 1.0, 'cm': 100.0, 'mm': 1000.0}
    if source_unit in frequency_factors:
        base = value * frequency_factors[source_unit]
        if target_unit in frequency_factors:
            return base / frequency_factors[target_unit]
        if target_unit in length_factors:
            return (C / base) * length_factors[target_unit]
    elif source_unit in length_factors:
        base = value / length_factors[source_unit]
        if target_unit in length_factors:
            return base * length_factors[target_unit]
        if target_unit in frequency_factors:
            return (C / base) / frequency_factors[target_unit]
    raise ValueError(
        f'不支持的频率/波长转换组合: {source_unit} -> {target_unit}')
def convert_length(value, source_unit, target_unit):
    """Convert positive physical lengths."""

    value = _positive_value(value, '长度')
    factors = {
        'm': 1.0, 'cm': 100.0, 'mm': 1000.0, 'km': 0.001,
        '英寸': 39.3701, '英尺': 3.28084,
    }
    if source_unit not in factors or target_unit not in factors:
        raise ValueError(f'不支持的长度单位: {source_unit} -> {target_unit}')
    return value / factors[source_unit] * factors[target_unit]
def convert_unit(category, value, source_unit, target_unit):
    """Dispatch unit conversion to an independent pure calculator."""

    try:
        if category == 0:
            result = convert_frequency_wavelength(
                value, source_unit, target_unit)
        elif category == 1:
            result = convert_power(value, source_unit, target_unit)
        elif category == 2:
            result = convert_angle(value, source_unit, target_unit)
        elif category == 3:
            result = convert_gain_ratio(value, source_unit, target_unit)
        elif category == 4:
            result = convert_temperature(value, source_unit, target_unit)
        elif category == 5:
            result = convert_length(value, source_unit, target_unit)
        else:
            raise ValueError(f'不支持的转换类型: {category}')
    except OverflowError as exc:
        raise ValueError('换算结果超出可表示范围') from exc
    return _finite_value(result, '换算结果')
