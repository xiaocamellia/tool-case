from dataclasses import dataclass

from .app_config import COLORS, LINESTYLES

import pandas as pd
from PyQt5.QtWidgets import QWidget, QTextEdit
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar


@dataclass
class DatasetRecord:
    """Single dataset and view state."""

    dataset_id: int
    label: str
    data_filepath: str
    col_filepath: str
    df: pd.DataFrame
    original_df: pd.DataFrame
    start: int = 0
    end: int = 0

    @property
    def row_count(self):
        return 0 if self.df is None else len(self.df)

    def set_range(self, start, end):
        self.start = max(0, int(start))
        if end is None or int(end) <= 0:
            self.end = 0
        else:
            self.end = max(self.start + 1, int(end))

    def get_slice_bounds(self):
        if self.df is None or len(self.df) == 0:
            return 0, 0
        start = min(max(0, int(self.start)), len(self.df) - 1)
        if self.end <= 0:
            end = len(self.df)
        else:
            end = min(len(self.df), max(start + 1, int(self.end)))
        return start, end


@dataclass
class PlotDataItem:
    """Metadata of one plotted series.

    Color and linestyle are computed as properties from color_idx,
    using the global COLORS and LINESTYLES from app_config.
    Callers no longer need to pass colors/linestyles in the constructor.
    """

    dataset_id: int = 0
    col_name: str = ''
    start: int = 0
    end: int = 0
    color_idx: int = 0
    label: str = ''
    chart_id: int = 0

    @property
    def color(self) -> str:
        return COLORS[self.color_idx % len(COLORS)]

    @property
    def linestyle(self) -> str:
        return LINESTYLES[(self.color_idx // len(COLORS)) % len(LINESTYLES)]

    def get_data(self, datasets):
        dataset = datasets.get(self.dataset_id)
        if dataset is None or dataset.df is None or self.col_name not in dataset.df.columns:
            return None

        data = pd.to_numeric(dataset.df[self.col_name], errors='coerce').to_numpy()
        s, e = dataset.get_slice_bounds()
        return data[s:e]


@dataclass
class PlotViewRecord:
    """A chart tab and its widgets."""

    view_id: int
    name: str
    tab_widget: QWidget
    canvas: object
    toolbar: NavigationToolbar
    txt_stats: QTextEdit
