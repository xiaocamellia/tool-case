from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas

from .app_config import COLORS, LINESTYLES


class MatplotlibCanvas(FigureCanvas):
    """Embedded matplotlib canvas."""

    def __init__(self, parent=None):
        self.figure = Figure(figsize=(11, 6.8), dpi=160, facecolor='white')
        self.axes = self.figure.add_subplot(111)
        super().__init__(self.figure)
        self.setParent(parent)
        self.figure.tight_layout(pad=1.2)
