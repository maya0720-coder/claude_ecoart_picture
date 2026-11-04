"""합성·무변경 검증 (모듈 06): 길 밖은 단 1픽셀도 바뀌지 않음을 보장."""
from __future__ import annotations

import cv2
import numpy as np

from app.core.segmentation import feather_alpha


class VerificationError(RuntimeError):
    """길 밖 픽셀이 바뀜. 결과를 버려야 한다(저장·프레젠테이션 불가)."""


def composite(original: np.ndarray, layer: np.ndarray, mask: np.ndarray, feather_px: int) -> np.ndarray:
    """out = original × (1 − α) + layer × α (float32 계산 후 반올림). 원본 해상도에서 호출한다."""
    _check(original, layer, mask)
    a = feather_alpha(mask, feather_px)
    out = original.copy()
    ys, xs = np.nonzero(a)
    if ys.size == 0:
        return out
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1   # α > 0 인 영역만 계산
    al = a[y0:y1, x0:x1, None]
    o = original[y0:y1, x0:x1].astype(np.float32)
    l = layer[y0:y1, x0:x1].astype(np.float32)
    blended = np.rint(o * (1 - al) + l * al).astype(np.uint8)
    # α = 0 인 곳은 계산 오차 없이 원본 그대로
    out[y0:y1, x0:x1] = np.where(al > 0, blended, original[y0:y1, x0:x1])
    return out


def outside_region(mask: np.ndarray, feather_px: int) -> np.ndarray:
    """검증 영역: 마스크를 feather_px + 1 반경으로 넓힌 영역의 바깥(bool)."""
    r = feather_px + 1
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))
    return cv2.dilate((mask > 0).astype(np.uint8), k) == 0


def verify_outside_unchanged(original: np.ndarray, result: np.ndarray, mask: np.ndarray,
                             feather_px: int) -> tuple[bool, int]:
    """(통과 여부, 바뀐 픽셀 수). 크기가 다르면 통과하지 못한 것으로 본다."""
    if original.shape != result.shape or mask.shape != original.shape[:2]:
        return False, int(original.shape[0] * original.shape[1])
    outside = outside_region(mask, feather_px)
    changed = np.any(original != result, axis=2) & outside
    n = int(np.count_nonzero(changed))
    return n == 0, n


def composite_verified(original: np.ndarray, layer: np.ndarray, mask: np.ndarray, feather_px: int) -> np.ndarray:
    """합성 + 검증. 검증에 실패하면 VerificationError(결과 폐기)."""
    out = composite(original, layer, mask, feather_px)
    ok, n = verify_outside_unchanged(original, out, mask, feather_px)
    if not ok:
        raise VerificationError(f"길 밖 픽셀 {n}개가 바뀌어 결과를 사용할 수 없습니다. 다시 렌더링해 주세요.")
    return out


def _check(original: np.ndarray, layer: np.ndarray, mask: np.ndarray) -> None:
    if original.dtype != np.uint8 or layer.dtype != np.uint8:
        raise ValueError("원본과 렌더 레이어는 uint8이어야 합니다")
    if original.shape != layer.shape or original.ndim != 3:
        raise ValueError(f"원본 {original.shape}과 렌더 레이어 {layer.shape}의 크기가 다릅니다(원본 해상도에서 합성)")
    if mask.shape != original.shape[:2]:
        raise ValueError(f"마스크 크기 {mask.shape}가 원본 {original.shape[:2]}과 다릅니다")
