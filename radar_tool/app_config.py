"""
Application-level configuration and constants for the radar tool.
"""

# matplotlib color cycle
COLORS = ['b', 'g', 'r', 'c', 'm', 'y', 'k', 'orange', 'purple', 'brown', 'pink', 'olive']

# line style cycle
LINESTYLES = ['-', '--', '-.', ':']

# matplotlib global rcParams configuration
MATPLOTLIB_RC_PARAMS = {
    'font.sans-serif': ['SimHei', 'Microsoft YaHei', 'WenQuanYi Micro Hei', 'Arial Unicode MS', 'DejaVu Sans'],
    'axes.unicode_minus': False,
    'figure.dpi': 160,
    'savefig.dpi': 600,
    'figure.facecolor': 'white',
    'axes.facecolor': 'white',
    'axes.edgecolor': '#334155',
    'axes.linewidth': 1.0,
    'axes.grid': True,
    'grid.linestyle': '--',
    'grid.alpha': 0.28,
    'lines.linewidth': 2.0,
    'lines.antialiased': True,
    'legend.frameon': True,
    'legend.framealpha': 0.95,
    'pdf.fonttype': 42,
    'ps.fonttype': 42,
    'font.size': 10,
    'axes.titlesize': 13,
    'axes.labelsize': 11,
    'xtick.labelsize': 10,
    'ytick.labelsize': 10,
}