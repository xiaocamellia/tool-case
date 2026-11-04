"""Shared pytest cleanup for GUI and Matplotlib tests."""

from __future__ import annotations

import matplotlib.pyplot as plt
import pytest


@pytest.fixture(autouse=True)
def close_figures_after_test():
    yield
    plt.close("all")
