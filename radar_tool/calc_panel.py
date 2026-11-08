"""Compatibility facade for calculator UI, units, and pure formulas."""

from .calc_formulas import (
    calculate_array_parameters, calculate_df_accuracy, calculate_link_budget,
)
from .calc_units import (
    C, K_BOLTZ, _finite_value, _positive_value, convert_angle,
    convert_frequency_wavelength, convert_gain_ratio, convert_length,
    convert_power, convert_temperature, convert_unit,
)
from .calc_ui import (
    CalcPanel, _AntennaGainCalc, _ArrayParamCalc, _BaseCalc,
    _DFAccuracyCalc, _LinkBudgetCalc, _RadarRangeCalc, _SNRCalc,
    _UnitConverter, logger,
)

__all__ = [
    "CalcPanel", "_BaseCalc", "_UnitConverter", "_AntennaGainCalc",
    "_RadarRangeCalc", "_LinkBudgetCalc", "_DFAccuracyCalc",
    "_ArrayParamCalc", "_SNRCalc", "convert_unit", "convert_temperature",
    "convert_angle", "convert_power", "convert_gain_ratio",
    "convert_frequency_wavelength", "convert_length",
    "calculate_link_budget", "calculate_df_accuracy",
    "calculate_array_parameters", "C", "K_BOLTZ",
]
