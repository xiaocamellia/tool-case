"""
Application-level configuration and constants for the radar tool.
"""

from cycler import cycler

# ---------------------------------------------------------------------------
# 图表色板（UI 视觉规范 V2 §3.4）
# 与 ``ui_theme.CHART_COLORS`` 同源同值。此处保留一份自包含定义，避免
# 纯计算 / CLI 模块为了拿颜色而反向依赖 PyQt5（ui_theme 会 import QtWidgets）。
# 修改时必须两处同步。
# ---------------------------------------------------------------------------
CHART_PALETTE = [
    '#2F6A8C',  # 1 主序列 / 参考真值
    '#C4661F',  # 2 实测 / 测量值
    '#2E8A6E',  # 3 拟合 / 理论值
    '#A34A50',  # 4 超差 / 异常点
    '#6A5AA8',  # 5 仿真 / 第三组
    '#7A6B3F',  # 6 参考线 / 包络
    '#3E8BA6',  # 7 辅助 / 背景系列
    '#6E6259',  # 8 基准 / 网格标注
]

# 历史导出名：``plotting.py`` 仍按 COLORS / LINESTYLES 导入。
COLORS = CHART_PALETTE
LINESTYLES = ['-', '--', '-.', ':']

# ---------------------------------------------------------------------------
# 出图字体（UI 视觉规范 V2 §4.14）
#
# 旧配置把 'Times New Roman' / 'SimSun' / 'STSong' 放在回退链前面，而这两款
# 中文衬线字体在目标机器上并不存在；matplotlib 逐级回退后落到 DejaVu Sans，
# 该字体无 CJK 字形，于是所有中文标题 / 轴标签渲染成方框 □□□□。
# 修复要点不是"再补一个字体名"，而是把**确定可用**的中文字体放到链首，
# 并让 font.family / font.sans-serif / font.serif 三者一致。
#
# 2026-11-14 回归修正：font.family 是**有序列表**，findfont 会遍历整条链。
# 链里只要有一个本机不存在的字体名，每渲染一段文字就会打一条
# "findfont: Font family 'X' not found"。单张三段文字的图实测 147 条，
# 多子图 / 重绘时直接刷屏。因此字体链不能写死，必须在运行时按本机
# 已安装字体裁剪，保证每个进入 rcParams 的名字都能被 findfont 命中。
# ---------------------------------------------------------------------------

# 候选按优先级排列。这里只登记"名字"，是否可用由 resolve_cjk_font_stack()
# 探测决定；未安装的项会被剔除，不会进入 rcParams。
_CJK_FONT_CANDIDATES = [
    'Microsoft YaHei',        # Windows 中文黑体（本机首选）
    'Microsoft YaHei UI',
    'SimHei',
    'Microsoft JhengHei',
    'DengXian',
    'PingFang SC',            # macOS
    'Heiti SC',
    'Noto Sans CJK SC',       # Linux / 思源黑体
    'Source Han Sans SC',
    'WenQuanYi Micro Hei',
    'WenQuanYi Zen Hei',
    'Arial Unicode MS',
    'SimSun',                 # 衬线兜底，仍含 CJK 字形
    'STSong',
    'DejaVu Sans',            # matplotlib 自带，最终兜底（无 CJK）
]

# 候选名全部落空时，从系统字体列表里捞任意中文字族用的关键字。
_CJK_NAME_HINTS = (
    'yahei', 'simhei', 'jhenghei', 'dengxian', 'pingfang', 'heiti',
    'noto sans cjk', 'source han', 'wenquanyi', 'cjk', 'simsun',
    'stsong', 'fangsong', 'kaiti', 'kai', 'song', 'hei', 'ming',
)


def _installed_font_families():
    """返回 matplotlib 可见的字体族名集合；探测失败时返回空集合。"""
    try:
        from matplotlib import font_manager
        return {font.name for font in font_manager.fontManager.ttflist}
    except Exception:
        return set()


def resolve_cjk_font_stack():
    """按本机实际安装的字体裁剪回退链。

    同时满足两个约束：链首是可用的中文字体（不出现 □□□□），且链里没有
    不存在的名字（不刷 findfont 告警）。工具箱会在不同机器上运行，所以
    候选名全部落空时会退而求其次，从系统字体里找含 CJK 关键字的族名。
    """
    installed = _installed_font_families()
    if not installed:
        # fontManager 不可用（极少数精简环境）：只留 matplotlib 自带字体，
        # 宁可中文缺字形，也不要制造上百条 warning。
        return ['DejaVu Sans']

    stack = [name for name in _CJK_FONT_CANDIDATES if name in installed]
    if not any(name != 'DejaVu Sans' for name in stack):
        extras = sorted(
            name for name in installed
            if any(hint in name.lower() for hint in _CJK_NAME_HINTS)
        )
        stack = extras + stack
    return stack or ['DejaVu Sans']


_CJK_FONT_STACK = resolve_cjk_font_stack()
# 公开只读别名，便于测试与截图脚本查询实际生效的字体链。
CJK_FONT_STACK = _CJK_FONT_STACK

MATPLOTLIB_RC_PARAMS = {
    # 字体
    'font.family': _CJK_FONT_STACK,
    'font.sans-serif': _CJK_FONT_STACK,
    'font.serif': _CJK_FONT_STACK,
    'font.size': 9,
    'axes.titlesize': 10,
    'axes.labelsize': 9,
    'xtick.labelsize': 8.5,
    'ytick.labelsize': 8.5,
    'legend.fontsize': 8,
    'axes.unicode_minus': False,  # 负号用半角 U+002D，避免与中文族冲突
    # 色板与线条
    'axes.prop_cycle': cycler(color=CHART_PALETTE),
    'lines.linewidth': 1.4,
    'lines.antialiased': True,
    # 画布与坐标轴
    'figure.dpi': 160,
    'savefig.dpi': 600,
    'figure.facecolor': 'white',
    'axes.facecolor': 'white',
    'axes.edgecolor': '#D2DAE3',
    'axes.labelcolor': '#47525F',
    'axes.linewidth': 1.0,
    'text.color': '#2C353F',
    'xtick.color': '#64717F',
    'ytick.color': '#64717F',
    'axes.spines.top': False,
    'axes.spines.right': False,
    # 网格与图例
    'axes.grid': True,
    'grid.linestyle': '--',
    'grid.alpha': 0.28,
    'grid.color': '#E7ECF2',
    'legend.frameon': False,
    # 导出
    'pdf.fonttype': 42,
    'ps.fonttype': 42,
}
