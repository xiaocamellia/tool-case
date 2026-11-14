"""误差传播与预算分解（设计文档 D6 / 2.3）。

误差模型：各段独立、各向同性，``σ_total = √(Σσᵢ²)``；
共因项（热变形等）不在 M1 范围，假设随报告页脚声明。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

import numpy as np

from .graph import PathSegment, TransformPath


@dataclass
class BudgetSegment:
    label: str
    record_id: str
    sigma_t_m: float
    sigma_r_arcsec: float
    variance_share: float          # σᵢ² / σ_total²（旋转口径）
    contribution_arcsec: float     # 对最终指向的贡献（旋转 σᵢ）
    dominant: bool = False


@dataclass
class ErrorBudget:
    source: str
    target: str
    segments: List[BudgetSegment] = field(default_factory=list)
    sigma_t_total_m: float = 0.0
    sigma_r_total_arcsec: float = 0.0
    dominant_label: str = ""
    dominant_share: float = 0.0
    dominant_highlight: bool = False   # 占比 > 50% 时醒目提示

    def to_rows(self) -> List[dict]:
        rows = []
        for segment in self.segments:
            rows.append({
                "路径段": segment.label,
                "平移σ(mm)": segment.sigma_t_m * 1000.0,
                "旋转σ(″)": segment.sigma_r_arcsec,
                "方差占比": segment.variance_share,
                "对最终指向贡献(″)": segment.contribution_arcsec,
                "主导段": "← 主导段" if segment.dominant else "",
            })
        rows.append({
            "路径段": "合成（RSS）",
            "平移σ(mm)": self.sigma_t_total_m * 1000.0,
            "旋转σ(″)": self.sigma_r_total_arcsec,
            "方差占比": 1.0,
            "对最终指向贡献(″)": self.sigma_r_total_arcsec,
            "主导段": "",
        })
        return rows


FOOTER_NOTE = (
    "误差模型假设各段独立、各向同性；旋转 σ 为各向同性标量，三轴分量共用 σ_r，"
    "平移同理共用 σ_t；共因项（热变形等）不在本模块范围。"
)


def compute_error_budget(path: TransformPath) -> ErrorBudget:
    """按路径段分解误差并识别主导段。"""
    segments: List[BudgetSegment] = []
    total_r_var = sum(segment.sigma_r_arcsec ** 2 for segment in path.segments)
    total_t_var = sum(segment.sigma_t_m ** 2 for segment in path.segments)
    sigma_r_total = float(np.sqrt(total_r_var))
    sigma_t_total = float(np.sqrt(total_t_var))

    raw: List[tuple] = []
    for segment in path.segments:
        r_var = segment.sigma_r_arcsec ** 2
        share = (r_var / total_r_var) if total_r_var > 0 else (1.0 / max(len(path.segments), 1))
        raw.append((segment, share))

    # 按方差占比降序（设计文档 D6）
    raw.sort(key=lambda item: item[1], reverse=True)
    dominant_label = ""
    dominant_share = 0.0
    for index, (segment, share) in enumerate(raw):
        is_dominant = index == 0 and bool(path.segments)
        if is_dominant:
            dominant_label = segment.label()
            dominant_share = share
        segments.append(BudgetSegment(
            label=segment.label(),
            record_id=segment.record_id,
            sigma_t_m=segment.sigma_t_m,
            sigma_r_arcsec=segment.sigma_r_arcsec,
            variance_share=share,
            contribution_arcsec=segment.sigma_r_arcsec,
            dominant=is_dominant,
        ))

    return ErrorBudget(
        source=path.source,
        target=path.target,
        segments=segments,
        sigma_t_total_m=sigma_t_total,
        sigma_r_total_arcsec=sigma_r_total,
        dominant_label=dominant_label,
        dominant_share=dominant_share,
        dominant_highlight=dominant_share > 0.5,
    )


def segment_sigmas(segments: List[PathSegment]) -> List[dict]:
    """路径各段 σ 明细（C6）。"""
    return [
        {
            "record_id": segment.record_id,
            "label": segment.label(),
            "sigma_t_m": segment.sigma_t_m,
            "sigma_r_arcsec": segment.sigma_r_arcsec,
            "status": segment.status,
            "source": segment.source,
        }
        for segment in segments
    ]
