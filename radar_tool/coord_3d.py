"""3D 视口（PyVista，懒加载 + matplotlib 静态降级）。

设计文档 6.7：用户首次切到"3D"子页时才 import pyvista；
PyVista 不可用时降级为 matplotlib 静态 3D 图，功能降级但不崩溃。
"""

from __future__ import annotations

import os
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from .logger import get_logger

logger = get_logger("coord_3d")

# 场景配色：深色底 + 高对比轴色
SCENE_BG = "#1d2530"
PANE_BG = "#28323f"
AXIS_COLORS = {"x": "#e5484d", "y": "#46a758", "z": "#4d8fe0"}
LABEL_COLOR = "#eef2f7"
LINK_COLOR = "#5c6b7d"
HIGHLIGHT_COLOR = "#f5a524"
VECTOR_COLOR = "#f5a524"


def pyvista_available() -> bool:
    try:
        import pyvista  # noqa: F401
        import pyvistaqt  # noqa: F401
        return True
    except Exception:
        return False


_CJK_FONT_CANDIDATES = (
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\simsun.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
)
_font_cache: dict = {}


def cjk_font_file() -> Optional[str]:
    """系统 CJK 字体文件（VTK 标签用）；找不到时返回 None（标签退回纯 ASCII id）。"""
    if "path" in _font_cache:
        return _font_cache["path"]
    found = next((path for path in _CJK_FONT_CANDIDATES if os.path.isfile(path)), None)
    _font_cache["path"] = found
    return found


def matplotlib_cjk_fontproperties():
    """matplotlib 中文标签字体：解析首个可用族，避免回退链告警。"""
    from matplotlib import font_manager

    if "fp" not in _font_cache:
        family = "DejaVu Sans"
        for candidate in (
            "Microsoft YaHei", "SimHei", "PingFang SC", "Noto Sans CJK SC",
            "WenQuanYi Zen Hei", "Source Han Sans SC",
        ):
            try:
                font_manager.findfont(candidate, fallback_to_default=False)
            except Exception:
                continue
            family = candidate
            break
        _font_cache["fp"] = font_manager.FontProperties(family=[family])
    return _font_cache["fp"]


class Coord3DView:
    """3D 场景数据准备与两种后端的渲染适配。"""

    def __init__(self):
        self.frames: Dict[str, np.ndarray] = {}     # frame_id → 4×4 pose
        self.labels: Dict[str, str] = {}
        self.highlight_path: List[str] = []
        self.links: List[Tuple[str, str]] = []      # 安装关系连线（from, to）
        self.vectors: List[tuple] = []              # (origin, direction, color)
        self.cones: List[tuple] = []                # (origin, direction, half_angle_deg)

    def set_frames(self, poses: Dict[str, np.ndarray], labels: Optional[Dict[str, str]] = None) -> None:
        self.frames = {key: np.asarray(value, dtype=float) for key, value in poses.items()}
        self.labels = dict(labels or {key: key for key in self.frames})

    def set_links(self, links: Sequence[Tuple[str, str]]) -> None:
        self.links = [(a, b) for a, b in links if a in self.frames and b in self.frames]

    def set_highlight_path(self, path: Sequence[str]) -> None:
        self.highlight_path = list(path)

    def add_vector(self, origin, direction, color=VECTOR_COLOR) -> None:
        self.vectors.append((
            np.asarray(origin, dtype=float),
            np.asarray(direction, dtype=float),
            color,
        ))

    def clear_vectors(self) -> None:
        self.vectors.clear()
        self.cones.clear()

    def _axis_length(self) -> float:
        if not self.frames:
            return 1.0
        origins = np.array([pose[:3, 3] for pose in self.frames.values()])
        span = float(np.max(origins.max(axis=0) - origins.min(axis=0)))
        return max(span * 0.22, 0.3)

    def _is_highlighted(self, frame_id: str) -> bool:
        return frame_id in self.highlight_path

    def _label_of(self, frame_id: str, allow_cjk: bool = True) -> str:
        """系名标签：id · 中文名（与账本结构树一致，便于对号入座）。

        无 CJK 字体时只显示 ASCII id，避免乱码方块。
        """
        name = self.labels.get(frame_id, "")
        if allow_cjk and name and name != frame_id:
            return f"{frame_id} · {name}"
        return frame_id

    def _link_highlighted(self, a: str, b: str) -> bool:
        path = self.highlight_path
        for first, second in zip(path, path[1:]):
            if {first, second} == {a, b}:
                return True
        return False

    # ------------------------------------------------------------------
    # matplotlib 降级（静态图）
    # ------------------------------------------------------------------

    def render_matplotlib(self, figure=None):
        import matplotlib.pyplot as plt
        from mpl_toolkits.mplot3d import Axes3D  # noqa: F401

        font = matplotlib_cjk_fontproperties()

        if figure is None:
            figure = plt.figure(figsize=(8, 7))
        figure.patch.set_facecolor(SCENE_BG)
        axes = figure.add_subplot(111, projection="3d", facecolor=PANE_BG)
        axis_length = self._axis_length()

        # 安装关系连线
        for a, b in self.links:
            if a in self.frames and b in self.frames:
                start = self.frames[a][:3, 3]
                end = self.frames[b][:3, 3]
                highlighted = self._link_highlighted(a, b)
                axes.plot(
                    [start[0], end[0]], [start[1], end[1]], [start[2], end[2]],
                    color=HIGHLIGHT_COLOR if highlighted else LINK_COLOR,
                    linewidth=2.2 if highlighted else 1.1,
                    alpha=0.95 if highlighted else 0.7,
                )

        for frame_id, pose in self.frames.items():
            origin = pose[:3, 3]
            highlighted = self._is_highlighted(frame_id)
            width = 3.2 if highlighted else 1.8
            for index, (name, color) in enumerate(AXIS_COLORS.items()):
                direction = pose[:3, index] * axis_length
                axes.quiver(
                    *origin, *direction, color=color,
                    linewidth=width, arrow_length_ratio=0.22,
                )
                tip = origin + direction * 1.12
                axes.text(
                    *tip, name.upper(), color=color,
                    fontsize=11 if highlighted else 9,
                    fontweight="bold", ha="center", va="center",
                    fontproperties=font,
                )
            label_pos = origin + np.array([0.0, 0.0, axis_length * 0.32])
            axes.text(
                *label_pos, self._label_of(frame_id, allow_cjk=True),
                color="#ffffff" if highlighted else LABEL_COLOR,
                fontsize=10.5 if highlighted else 9,
                fontweight="bold" if highlighted else "normal",
                ha="center", va="bottom",
                fontproperties=font,
                bbox=dict(
                    boxstyle="round,pad=0.28",
                    facecolor=HIGHLIGHT_COLOR if highlighted else "#33414f",
                    edgecolor="none", alpha=0.88,
                ),
            )

        for start, direction, color in self.vectors:
            axes.quiver(*start, *direction, color=color, linewidth=2.4,
                        arrow_length_ratio=0.2)

        self._set_matplotlib_limits(axes, axis_length)
        axes.set_xlabel("X", color=AXIS_COLORS["x"], labelpad=6)
        axes.set_ylabel("Y", color=AXIS_COLORS["y"], labelpad=6)
        axes.set_zlabel("Z", color=AXIS_COLORS["z"], labelpad=6)
        axes.tick_params(colors="#9fb0c0", labelsize=7)
        try:
            axes.set_box_aspect((1, 1, 1))
        except Exception:
            pass
        axes.view_init(elev=18, azim=-58)
        axes.grid(False)
        figure.tight_layout()
        return figure

    def _set_matplotlib_limits(self, axes, axis_length: float) -> None:
        if not self.frames:
            axes.set_xlim(-1, 1)
            axes.set_ylim(-1, 1)
            axes.set_zlim(-1, 1)
            return
        origins = np.array([pose[:3, 3] for pose in self.frames.values()])
        low = origins.min(axis=0) - axis_length * 1.2
        high = origins.max(axis=0) + axis_length * 1.2
        axes.set_xlim(low[0], high[0])
        axes.set_ylim(low[1], high[1])
        axes.set_zlim(low[2], high[2])

    # ------------------------------------------------------------------
    # PyVista 后端
    # ------------------------------------------------------------------

    def render_pyvista(self, plotter, first_frame: bool = False) -> None:
        import pyvista as pv

        camera = None
        if not first_frame:
            try:
                camera = plotter.camera_position
            except Exception:
                camera = None

        plotter.clear()
        plotter.set_background(SCENE_BG)
        axis_length = self._axis_length()
        font = cjk_font_file()

        # 安装关系连线
        for a, b in self.links:
            start = self.frames[a][:3, 3]
            end = self.frames[b][:3, 3]
            highlighted = self._link_highlighted(a, b)
            plotter.add_mesh(
                pv.Line(start, end),
                color=HIGHLIGHT_COLOR if highlighted else LINK_COLOR,
                line_width=3 if highlighted else 1,
                opacity=0.95 if highlighted else 0.55,
            )

        for frame_id, pose in self.frames.items():
            origin = pose[:3, 3]
            highlighted = self._is_highlighted(frame_id)
            for index, (name, color) in enumerate(AXIS_COLORS.items()):
                direction = pose[:3, index]
                arrow = pv.Arrow(
                    start=origin, direction=direction,
                    scale=axis_length,
                    tip_length=0.28, tip_radius=0.10, shaft_radius=0.035,
                )
                plotter.add_mesh(arrow, color=color)
                tip = origin + direction * axis_length * 1.12
                plotter.add_point_labels(
                    [tip], [name.upper()],
                    font_size=22 if highlighted else 17,
                    text_color=color,
                    shape_opacity=0,
                    show_points=False,
                    always_visible=True,
                    font_file=font,
                )
            label_pos = origin + np.array([0.0, 0.0, axis_length * 0.35])
            plotter.add_point_labels(
                [label_pos],
                [self._label_of(frame_id, allow_cjk=font is not None)],
                font_size=20 if highlighted else 15,
                text_color="#ffffff",
                shape_color=HIGHLIGHT_COLOR if highlighted else "#33414f",
                shape_opacity=0.8,
                always_visible=True,
                show_points=False,
                font_file=font,
            )

        for start, direction, color in self.vectors:
            magnitude = float(np.linalg.norm(direction))
            if magnitude < 1e-12:
                continue
            arrow = pv.Arrow(
                start=start, direction=direction / magnitude,
                scale=magnitude,
                tip_length=0.3, tip_radius=0.12, shaft_radius=0.05,
            )
            plotter.add_mesh(arrow, color=color)

        if camera is not None and not first_frame:
            try:
                plotter.camera_position = camera
            except Exception:
                plotter.view_isometric()
                plotter.reset_camera()
        else:
            plotter.view_isometric()
            plotter.reset_camera()

    def screenshot(self, filepath: str) -> str:
        """当前视角截图；优先 PyVista，降级为 matplotlib 落盘。"""
        if pyvista_available():
            import pyvista as pv

            plotter = pv.Plotter(off_screen=True)
            try:
                self.render_pyvista(plotter, first_frame=True)
                plotter.screenshot(filepath, transparent_background=False)
            finally:
                plotter.close()
            return filepath
        figure = self.render_matplotlib()
        figure.savefig(filepath, dpi=150, bbox_inches="tight", facecolor=SCENE_BG)
        return filepath


class Matplotlib3DCanvas:
    """matplotlib 降级画布（嵌入 Qt）。"""

    def __init__(self, parent=None):
        from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
        from matplotlib.figure import Figure

        self.figure = Figure(figsize=(7, 6))
        self.figure.patch.set_facecolor(SCENE_BG)
        self.canvas = FigureCanvasQTAgg(self.figure)
        if parent is not None:
            self.canvas.setParent(parent)

    def widget(self):
        return self.canvas

    def draw_view(self, view: Coord3DView) -> None:
        self.figure.clear()
        view.render_matplotlib(self.figure)
        self.canvas.draw_idle()


def create_pyvista_interactor(parent):
    """懒加载创建 QtInteractor；失败时抛出异常由调用方降级。"""
    from pyvistaqt import QtInteractor

    return QtInteractor(parent)
