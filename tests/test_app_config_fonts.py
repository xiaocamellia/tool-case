"""matplotlib 出图字体链回归测试（UI 视觉规范 V2 §4.14）。

历史问题：
1. 回退链里放本机缺失的中文字体，逐级回退到 DejaVu Sans，中文变方框。
2. 链里只要有一个不存在的名字，findfont 每渲染一段文字就打一条
   "Font family 'X' not found"，单张三段文字的图实测 147 条，多子图刷屏。

因此字体链必须运行时按本机已安装字体裁剪，三处 font 族保持一致。
"""

from __future__ import annotations

import logging

import matplotlib
from matplotlib import font_manager
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from radar_tool.app_config import CJK_FONT_STACK, MATPLOTLIB_RC_PARAMS


def test_font_stack_only_contains_installed_families():
    """链里每个名字都必须能被 findfont 命中，否则会刷告警。"""
    installed = {font.name for font in font_manager.fontManager.ttflist}
    assert CJK_FONT_STACK, '字体链不能为空'
    missing = [name for name in CJK_FONT_STACK if name not in installed]
    assert not missing, f'字体链含本机不存在的名字，会刷 findfont 告警: {missing}'


def test_three_font_families_stay_identical():
    """family / sans-serif / serif 不一致会让中文各自回退，重新出现方框。"""
    assert MATPLOTLIB_RC_PARAMS['font.family'] == CJK_FONT_STACK
    assert MATPLOTLIB_RC_PARAMS['font.sans-serif'] == CJK_FONT_STACK
    assert MATPLOTLIB_RC_PARAMS['font.serif'] == CJK_FONT_STACK


def test_drawing_cjk_emits_no_findfont_warning():
    """用独立 rc_context 画一张含中文标题/轴标签/图例的图，捕获全部日志。"""
    messages = []

    class _Collector(logging.Handler):
        def emit(self, record):
            messages.append(record.getMessage())

    handler = _Collector()
    root = logging.getLogger()
    fm_logger = logging.getLogger('matplotlib.font_manager')
    old_level = fm_logger.level
    root.addHandler(handler)
    fm_logger.setLevel(logging.WARNING)
    try:
        # rc_context 避免污染全局 rcParams，也不触碰 pyplot 的 backend。
        with matplotlib.rc_context(rc=MATPLOTLIB_RC_PARAMS):
            fig = Figure(figsize=(6, 4))
            FigureCanvasAgg(fig)
            ax = fig.subplots()
            ax.set_title('中文测试 幅度响应')
            ax.set_xlabel('频率 (MHz)')
            ax.set_ylabel('增益 (dB)')
            ax.plot([1, 2, 3], [1, 4, 2], label='实测曲线')
            ax.legend()
            fig.canvas.draw()
    finally:
        root.removeHandler(handler)
        fm_logger.setLevel(old_level)

    findfont_warnings = [msg for msg in messages if 'findfont' in msg]
    assert not findfont_warnings, findfont_warnings
