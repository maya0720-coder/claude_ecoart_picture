"""길 원근 4점 추정 (모듈 03).

quad 점 순서: 좌하, 우하, 우상, 좌상 (이미지 좌표, y 아래 방향).
평면(텍스처) 좌표: (0,0)=좌상(먼 쪽), (w,h)=우하(가까운 쪽).
"""
from __future__ import annotations

import cv2
import numpy as np

DEFAULT_PATH_WIDTH_M = 2.0     # 길 폭 미입력 시 가정값(화면에 "가정값" 표시)
EDGE_BAND = 0.2                # 상·하단 추정 구간(마스크 높이 비율)
MIN_TOP_RATIO = 0.05           # 윗변이 아랫변의 5% 미만이면(소실점 근처) 이 폭으로 넓힘
MAX_LENGTH_RATIO = 25.0        # 길이 추정 상한: 길 폭의 25배
MIN_QUAD_AREA = 1000.0         # px², 이보다 작으면 넓이 0에 가까움으로 판단


def estimate_quad(mask: np.ndarray) -> np.ndarray:
    """마스크 하단·상단 20% 구간의 좌·우 가장자리 직선 → (4,2) float32."""
    return estimate_quads(mask, 1)[0]


def estimate_quads(mask: np.ndarray, n: int) -> list[np.ndarray]:
    """굽은 길용: 마스크 높이를 n구간으로 나눠 구간별 4점(가까운 쪽부터). 이웃 구간은 경계 변을 공유한다."""
    if not 1 <= n <= 5:
        raise ValueError(f"구간 수는 1~5여야 합니다: {n}")
    ys, left, right = _row_edges(mask)
    y_bot, y_top = float(ys.max()), float(ys.min())
    span = y_bot - y_top
    if span < 2 * n:
        raise ValueError("길 영역이 너무 작아 원근을 추정할 수 없습니다")
    win = max(2.0, EDGE_BAND * span)
    bounds = np.linspace(y_bot, y_top, n + 1)
    edges = []
    for i, y in enumerate(bounds):
        if i == 0:
            lo, hi = y - win, y                     # 하단: 위로 win
        elif i == n:
            lo, hi = y, y + win                     # 상단: 아래로 win
        else:
            lo, hi = y - win / 2, y + win / 2
        sel = (ys >= lo) & (ys <= hi)
        edges.append([_fit_at(ys[sel], left[sel], y), _fit_at(ys[sel], right[sel], y)])
    # 윗변이 점처럼 좁아지면 최소 폭 보장
    xl, xr = edges[-1]
    bottom_w = edges[0][1] - edges[0][0]
    if xr - xl < MIN_TOP_RATIO * bottom_w:
        c, half = (xl + xr) / 2, MIN_TOP_RATIO * bottom_w / 2
        edges[-1] = [c - half, c + half]
    return [np.array([[edges[i][0], bounds[i]], [edges[i][1], bounds[i]],
                      [edges[i + 1][1], bounds[i + 1]], [edges[i + 1][0], bounds[i + 1]]], np.float32)
            for i in range(n)]


def homography_from_quad(quad: np.ndarray, plane_w: int, plane_h: int) -> np.ndarray:
    """평면 좌표 → 이미지 좌표 3x3 (cv2.warpPerspective(texture, H, (W, H_img))용)."""
    if plane_w <= 0 or plane_h <= 0:
        raise ValueError(f"평면 크기는 양수여야 합니다: {plane_w}x{plane_h}")
    src = np.array([[0, plane_h], [plane_w, plane_h], [plane_w, 0], [0, 0]], np.float32)
    return cv2.getPerspectiveTransform(src, np.asarray(quad, np.float32))


def default_focal_px(img_w: int, img_h: int) -> float:
    """휴대폰 기본 카메라(35mm 환산 26mm) 가정 초점거리(px). 대각선 43.3mm 대비 26mm."""
    return 26.0 / 43.27 * float(np.hypot(img_w, img_h))


def plane_size_for(quad: np.ndarray, path_width_m: float, px_per_m: int,
                   focal_px: float | None = None) -> tuple[int, int]:
    """(plane_w, plane_h) 픽셀. 폭 = 길 폭 × px_per_m, 길이는 원근(아랫변·윗변 폭 비)으로 추정.

    지면 위 길(평행한 두 가장자리)에서 길이 L = W·f·(1/w_top − 1/w_bottom).
    정면 위에서 찍어 두 변이 평행하면 화면 비율(높이/폭)로 추정한다. 둘 중 큰 값.
    focal_px가 없으면 quad 외접 사각형 기준 가정값을 쓴다(호출 측에서 default_focal_px 전달 권장).
    """
    if path_width_m <= 0 or px_per_m <= 0:
        raise ValueError("길 폭과 px_per_m은 양수여야 합니다")
    q = np.asarray(quad, np.float64)
    w_bot = np.linalg.norm(q[1] - q[0])
    w_top = np.linalg.norm(q[2] - q[3])
    if min(w_bot, w_top) < 1:
        raise ValueError("4점의 윗변 또는 아랫변 폭이 0입니다")
    if focal_px is None:
        bw, bh = q.max(0) - q.min(0)
        focal_px = default_focal_px(bw, bh)
    height_px = np.linalg.norm((q[0] + q[1]) / 2 - (q[2] + q[3]) / 2)
    length_persp = path_width_m * focal_px * max(0.0, 1 / w_top - 1 / w_bot)
    length_ortho = path_width_m * height_px / ((w_bot + w_top) / 2)
    length_m = min(max(length_persp, length_ortho), MAX_LENGTH_RATIO * path_width_m)
    return max(1, round(path_width_m * px_per_m)), max(1, round(length_m * px_per_m))


def check_quad(quad: np.ndarray, min_area: float = MIN_QUAD_AREA) -> str | None:
    """문제가 있으면 경고 문구, 정상이면 None. 꼬임(자기 교차·좌우 뒤집힘·오목)과 넓이 0 근처를 거른다."""
    q = np.asarray(quad, np.float64)
    if q.shape != (4, 2) or not np.all(np.isfinite(q)):
        return "4점 좌표가 올바르지 않습니다."
    x, y = q[:, 0], q[:, 1]
    area = -0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(np.roll(x, -1), y))  # 좌하→우하→우상→좌상이면 양수
    if abs(area) < min_area:
        return "4점이 너무 가깝거나 한 줄에 있습니다. 점을 길 가장자리로 넓혀 주세요."
    e = np.roll(q, -1, axis=0) - q
    cross = e[:, 0] * np.roll(e, -1, axis=0)[:, 1] - e[:, 1] * np.roll(e, -1, axis=0)[:, 0]
    if area < 0 or not np.all(cross < 0):
        return "4점이 꼬였습니다. 좌하·우하·우상·좌상 순서로 길 가장자리에 맞춰 주세요."
    return None


def update_quad(prev: np.ndarray | None, new: np.ndarray) -> tuple[np.ndarray | None, str | None]:
    """수동 조정 결과 반영. 문제가 있으면 (직전 값, 경고), 정상이면 (새 값, None)."""
    warn = check_quad(new)
    if warn:
        return prev, warn
    return np.asarray(new, np.float32).copy(), None


def project_grid(quad: np.ndarray, nx: int = 4, ny: int = 8) -> list[np.ndarray]:
    """격자 미리보기 선분 목록(각 (2,2) float32, 이미지 좌표)."""
    H = homography_from_quad(quad, 1, 1)
    segs = []
    for i in range(nx + 1):
        segs.append([[i / nx, 0], [i / nx, 1]])
    for j in range(ny + 1):
        segs.append([[0, j / ny], [1, j / ny]])
    pts = cv2.perspectiveTransform(np.array(segs, np.float32).reshape(-1, 1, 2), H)
    return list(pts.reshape(-1, 2, 2))


def _row_edges(mask: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    m = mask > 0
    rows = np.flatnonzero(m.any(axis=1))
    if rows.size == 0:
        raise ValueError("길 마스크가 비어 있습니다")
    sub = m[rows]
    left = sub.argmax(axis=1).astype(np.float64)
    right = (m.shape[1] - 1 - sub[:, ::-1].argmax(axis=1)).astype(np.float64)
    return rows.astype(np.float64), left, right


def _fit_at(ys: np.ndarray, xs: np.ndarray, y: float) -> float:
    """가장자리 x = a·y + b 직선을 맞춰 y에서의 x. 튀는 행(잔여 조각 등)은 한 번 걸러 다시 맞춘다."""
    if ys.size < 2 or np.ptp(ys) == 0:
        return float(np.median(xs))
    a, b = np.polyfit(ys, xs, 1)
    r = np.abs(xs - (a * ys + b))
    keep = r <= 3 * np.median(r) + 1
    if keep.sum() >= 2 and not keep.all():
        a, b = np.polyfit(ys[keep], xs[keep], 1)
    return float(a * y + b)
