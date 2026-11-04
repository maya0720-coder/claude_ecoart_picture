"""Gemini 결과 정렬 (모듈 07): 마스크 바깥(바뀌지 않아야 할 곳) 특징점으로 원본에 맞춘다."""
from __future__ import annotations

import cv2
import numpy as np

MAX_MEAN_ERR_PX = 2.0          # 정렬 오차 기준(원본 크롭 해상도 기준 평균 px)
WORK_PX = 1024                 # 특징점 계산용 축소 크기
MIN_INLIERS = 15
MAX_SHIFT_RATIO = 0.05         # 이동이 크롭 크기의 5%를 넘으면 엉뚱한 결과로 본다
SCALE_RANGE = (0.9, 1.1)


def align_to_original(candidate: np.ndarray, original_crop: np.ndarray,
                      mask_crop: np.ndarray) -> tuple[np.ndarray | None, float]:
    """(정렬된 후보 또는 None, 평균 오차 px). 오차가 기준을 넘거나 변환이 비정상이면 None.

    ORB 특징점 + RANSAC 호모그래피(마스크 바깥 영역만). 오차 = 인라이어 재투영 평균 거리.
    바깥에 무늬가 거의 없으면(민무늬 벽·하늘) 특징점이 부족해 실패 → 호출 측은 로컬 결과를 유지한다.
    """
    h, w = original_crop.shape[:2]
    if candidate.shape[:2] != (h, w):
        candidate = cv2.resize(candidate, (w, h), interpolation=cv2.INTER_LINEAR)
    s = min(1.0, WORK_PX / max(h, w))
    small = lambda im, interp=cv2.INTER_AREA: cv2.resize(im, (max(1, round(w * s)), max(1, round(h * s))), interpolation=interp) if s < 1 else im
    g_c = cv2.cvtColor(small(candidate), cv2.COLOR_BGR2GRAY)
    g_o = cv2.cvtColor(small(original_crop), cv2.COLOR_BGR2GRAY)
    m = small(mask_crop, cv2.INTER_NEAREST)
    outside = (cv2.dilate((m > 0).astype(np.uint8), np.ones((9, 9), np.uint8)) == 0).astype(np.uint8) * 255
    if cv2.countNonZero(outside) < 0.05 * outside.size:
        return None, float("inf")                   # 기준으로 쓸 바깥 영역이 거의 없음

    H, err = _orb(g_c, g_o, outside)
    if H is None:
        return None, float("inf")
    err_full = err / s
    S = np.diag([s, s, 1.0])
    H_full = np.linalg.inv(S) @ H @ S              # 축소 좌표 변환 → 원본 크롭 좌표 변환
    if err_full > MAX_MEAN_ERR_PX or not _plausible(H_full, w, h):
        return None, err_full
    aligned = cv2.warpPerspective(candidate, H_full, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    return aligned, err_full


def _orb(g_c, g_o, outside):
    orb = cv2.ORB_create(3000)
    k1, d1 = orb.detectAndCompute(g_c, outside)
    k2, d2 = orb.detectAndCompute(g_o, outside)
    if d1 is None or d2 is None or len(k1) < MIN_INLIERS or len(k2) < MIN_INLIERS:
        return None, float("inf")
    matches = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True).match(d1, d2)
    if len(matches) < MIN_INLIERS:
        return None, float("inf")
    p1 = np.float32([k1[m.queryIdx].pt for m in matches])
    p2 = np.float32([k2[m.trainIdx].pt for m in matches])
    H, inl = cv2.findHomography(p1, p2, cv2.RANSAC, 3.0)
    if H is None or inl is None or int(inl.sum()) < MIN_INLIERS:
        return None, float("inf")
    sel = inl.ravel() > 0
    proj = cv2.perspectiveTransform(p1[sel].reshape(-1, 1, 2), H).reshape(-1, 2)
    return H, float(np.linalg.norm(proj - p2[sel], axis=1).mean())


def _plausible(H: np.ndarray, w: int, h: int) -> bool:
    """거의 항등에 가까운 변환인지(작은 이동·배율·기울기)."""
    if not np.all(np.isfinite(H)):
        return False
    corners = np.float32([[0, 0], [w, 0], [w, h], [0, h]]).reshape(-1, 1, 2)
    moved = cv2.perspectiveTransform(corners, H).reshape(-1, 2)
    shift = np.abs(moved - corners.reshape(-1, 2)).max()
    if shift > MAX_SHIFT_RATIO * max(w, h):
        return False
    area = cv2.contourArea(moved) / float(w * h)
    return SCALE_RANGE[0] ** 2 <= area <= SCALE_RANGE[1] ** 2
