"""Signal processing algorithms package."""

from .doa_estimation import (
    C,
    SPEED_OF_LIGHT_M_PER_S,
    DoaValidationError,
    compute_array_manifold_2d,
    generate_received_signal,
    bartlett_doa_1d,
    music_doa_1d,
    bartlett_doa_2d,
    music_doa_2d,
    esprit_doa,
    monte_carlo_evaluation,
)
from .array_geometry import (
    create_ula,
    create_uca,
    create_l_array,
    create_rect_array,
)

__all__ = [
    "C",
    "SPEED_OF_LIGHT_M_PER_S",
    "DoaValidationError",
    "compute_array_manifold_2d",
    "generate_received_signal",
    "bartlett_doa_1d",
    "music_doa_1d",
    "bartlett_doa_2d",
    "music_doa_2d",
    "esprit_doa",
    "monte_carlo_evaluation",
    "create_ula",
    "create_uca",
    "create_l_array",
    "create_rect_array",
]
