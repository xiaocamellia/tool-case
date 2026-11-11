"""Shared Matplotlib canvas and figure-format helpers (legend, font, size, naming)."""
import os

from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas

from .app_config import COLORS, LINESTYLES

# 图片尺寸预设（宽、高，单位英寸）
FIG_SIZE_PRESETS = {
    '默认': (11.0, 6.8),
    '窄幅': (8.0, 5.0),
    '宽幅': (14.0, 8.5),
    '方形': (9.0, 9.0),
}

# 纵横比预设：None 表示沿用预设尺寸自带比例
ASPECT_PRESETS = {
    '自动': None,
    '4:3': 4 / 3,
    '16:9': 16 / 9,
    '1:1': 1.0,
}

# 导出宽度预设（厘米）：None 表示跟随绘图尺寸
EXPORT_WIDTH_PRESETS_CM = {
    '跟随绘图尺寸': None,
    '12 cm': 12.0,
    '16 cm': 16.0,
    '20 cm': 20.0,
    '24 cm': 24.0,
}

LEGEND_FONT_SIZE = 8.0
_SERIES_LABEL_STEM_LIMIT = 16


def compact_series_label(file_label, col_name):
    """紧凑图例标签：文件主名 | 字段名（不带采样区间，避免图例过大遮挡）。"""
    stem = os.path.splitext(os.path.basename(str(file_label)))[0] or str(file_label)
    if len(stem) > _SERIES_LABEL_STEM_LIMIT:
        stem = stem[:_SERIES_LABEL_STEM_LIMIT - 1] + '…'
    return f'{stem} | {col_name}'


def default_export_basename(file_label, col_names):
    """导出图默认文件名：数据文件名 + 字段名。"""
    stem = os.path.splitext(os.path.basename(str(file_label)))[0] or 'plot'
    cols = [str(c) for c in col_names if str(c).strip()]
    name = '_'.join([stem] + cols) if cols else stem
    for ch in '\\/:*?"<>|':
        name = name.replace(ch, '_')
    name = name.strip(' .')
    if len(name) > 120:
        name = name[:120]
    return name or 'plot'


def style_axes_legend(ax, fontsize=LEGEND_FONT_SIZE, loc='upper right'):
    """统一图例样式：小字号、半透明边框，默认置于图内右上角。"""
    handles, labels = ax.get_legend_handles_labels()
    if not handles:
        return None
    legend = ax.get_legend()
    if legend is not None:
        legend.remove()
    legend = ax.legend(
        handles,
        labels,
        loc=loc,
        fontsize=fontsize,
        frameon=True,
        framealpha=0.9,
        edgecolor='#cbd5e1',
    )
    legend.get_frame().set_linewidth(0.8)
    return legend


def resolve_figure_size(preset_name='默认', aspect_name='自动'):
    """返回 (宽, 高) 英寸；纵横比预设优先于预设尺寸自带比例。"""
    width, height = FIG_SIZE_PRESETS.get(preset_name, FIG_SIZE_PRESETS['默认'])
    aspect = ASPECT_PRESETS.get(aspect_name, None)
    if aspect:
        height = width / aspect
    return width, height


def apply_figure_size(figure, preset_name='默认', aspect_name='自动'):
    width, height = resolve_figure_size(preset_name, aspect_name)
    figure.set_size_inches(width, height, forward=True)
    return width, height


def scaled_size_for_width(figure, width_cm):
    """按目标宽度（厘米）缩放当前图形，保持纵横比。"""
    width_in = width_cm / 2.54
    current_w, current_h = figure.get_size_inches()
    if current_w <= 0:
        return width_in, width_in
    scale = width_in / current_w
    return width_in, current_h * scale


class MatplotlibCanvas(FigureCanvas):
    """Embedded matplotlib canvas."""

    def __init__(self, parent=None):
        self.figure = Figure(figsize=FIG_SIZE_PRESETS['默认'], dpi=160, facecolor='white')
        self.axes = self.figure.add_subplot(111)
        super().__init__(self.figure)
        self.setParent(parent)
        self.figure.tight_layout(pad=1.2)
