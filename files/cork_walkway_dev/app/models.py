"""모듈 간 공통 데이터 구조."""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class RenderParams:
    shading_strength: float = 0.8   # 0~1, 원본 명암 유지 정도
    color_match: float = 0.3        # 0~1, 장면 색 맞춤 정도
    granule_scale: float = 1.0
    edge_band: bool = False
    edge_band_px: int = 0
    contact_shadow: bool = False    # 경계 안쪽 몇 px를 약하게 어둡게(접촉 음영)

    def __post_init__(self) -> None:
        for name in ("shading_strength", "color_match"):
            v = getattr(self, name)
            if not 0.0 <= v <= 1.0:
                raise ValueError(f"{name}는 0~1이어야 합니다: {v}")
        if self.granule_scale <= 0:
            raise ValueError(f"granule_scale은 0보다 커야 합니다: {self.granule_scale}")
        if self.edge_band_px < 0:
            raise ValueError(f"edge_band_px는 0 이상이어야 합니다: {self.edge_band_px}")


@dataclass
class WorkSession:
    original: np.ndarray                 # BGR uint8, EXIF 회전 보정 완료, 원본 해상도
    source_name: str                     # 표시용 파일명(전송 금지)
    mask: np.ndarray | None = None       # uint8 0/255, 원본과 같은 크기
    mask_feather_px: int = 3
    quad: np.ndarray | None = None       # (4,2) float32: 좌하, 우하, 우상, 좌상
    preset_id: str = "natural_brown"
    path_width_m: float | None = None    # 실제 길 폭(m). None이면 가정값 2.0m
    quad_segments: list[np.ndarray] | None = None   # 굽은 길: 구간별 4점(가까운 쪽부터). None이면 quad 하나
    render_params: RenderParams = field(default_factory=RenderParams)
    result_local: np.ndarray | None = None
    result_hq: np.ndarray | None = None
    verified: bool = False

    def __post_init__(self) -> None:
        o = self.original
        if not (isinstance(o, np.ndarray) and o.dtype == np.uint8 and o.ndim == 3 and o.shape[2] == 3):
            raise ValueError("original은 (H, W, 3) uint8 BGR 배열이어야 합니다")
        if self.mask is not None and self.mask.shape != o.shape[:2]:
            raise ValueError(f"mask 크기 {self.mask.shape}가 원본 {o.shape[:2]}과 다릅니다")
        if self.quad is not None and self.quad.shape != (4, 2):
            raise ValueError(f"quad는 (4, 2)여야 합니다: {self.quad.shape}")
        if self.path_width_m is not None and self.path_width_m <= 0:
            raise ValueError(f"길 폭은 0보다 커야 합니다: {self.path_width_m}")
        if self.quad_segments is not None and not (
                1 <= len(self.quad_segments) <= 5 and all(q.shape == (4, 2) for q in self.quad_segments)):
            raise ValueError("quad_segments는 (4, 2) 배열 1~5개여야 합니다")
        if not 1 <= self.mask_feather_px <= 10:
            raise ValueError(f"mask_feather_px는 1~10이어야 합니다: {self.mask_feather_px}")
