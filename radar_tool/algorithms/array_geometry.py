"""Array geometry module"""

import numpy as np

def create_ula(N, d):
    """Create uniform linear array"""
    pos = np.zeros((N, 2))
    pos[:, 0] = np.arange(N) * d
    return pos


def create_uca(N, radius):
    """Create uniform circular array"""
    angles = np.linspace(0, 2*np.pi, N, endpoint=False)
    x = radius * np.cos(angles)
    y = radius * np.sin(angles)
    return np.column_stack([x, y])


def create_l_array(N_x, N_y, d):
    """Create L-shaped array"""
    x_pos = np.zeros((N_x, 2))
    x_pos[:, 0] = np.arange(N_x) * d
    y_pos = np.zeros((N_y - 1, 2))
    y_pos[:, 1] = np.arange(1, N_y) * d
    return np.vstack([x_pos, y_pos])


def create_rect_array(N_rows, N_cols, dx, dy):
    """Create rectangular planar array"""
    positions = []
    for i in range(N_rows):
        for j in range(N_cols):
            positions.append([j * dx, i * dy])
    return np.array(positions)
