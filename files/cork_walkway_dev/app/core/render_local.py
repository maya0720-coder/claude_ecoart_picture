"""로컬 렌더링 (모듈 05): 원근 투영 + 명암·그림자 유지 + 색 맞춤.

구조
- 기하 캐시: 이미지 좌표 → 평면 좌표(u, v), 밉맵 단계, 명암 비율, 장면 색 편차, 경계 거리.
  사진·마스크·4점·길 폭·입자 배율이 같으면 재사용(프리셋 변경 시 다시 계산하지 않음).
- 텍스처 캐시: 프리셋별 주기 텍스처의 밉맵 피라미드. 좌표 나머지(BORDER_WRAP)로 무한 반복.
"""
from __future__ import annotations

import hashlib
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from app.core.cork_material import CorkPreset, make_periodic_texture, make_tile
from app.core.image_io import make_preview
from app.core.perspective import (DEFAULT_PATH_WIDTH_M, check_quad, default_focal_px,
                                  estimate_quad, homography_from_quad, plane_size_for)
from app.models import WorkSession

PREVIEW_MAX_PX = 1600
TILE_PX = 1024
PX_PER_M_RANGE = (100, 2500)
MAX_LEVEL = 7
SHADING_CLIP = (0.2, 2.0)
NEUTRAL_CHROMA = 15.0          # LAB 채도 이 값 미만 = 무채색(조명 색 추정용)
CAST_RING = 0.08               # 조명 색 추정 범위: 길 주변으로 이미지 긴 변의 8%
EDGE_BAND_DARKEN = 0.8
CONTACT_DARKEN = 0.15
CONTACT_PX = 4

_geo_cache: OrderedDict = OrderedDict()   # 미리보기 + 원본 해상도
_tex_cache: OrderedDict = OrderedDict()   # 프리셋 몇 개
_GEO_MAX, _TEX_MAX = 2, 4
_cache_lock = threading.Lock()            # 미리 만들기(작업 스레드)와 화면 렌더가 동시에 캐시를 쓴다


@dataclass
class _Geometry:
    roi: tuple[int, int, int, int]          # x0, y0, x1, y1
    out_shape: tuple[int, int]
    u: np.ndarray                           # 평면 좌표(텍스처 px, 입자 배율 반영 전)
    v: np.ndarray
    level: np.ndarray                       # 밉맵 단계(연속값)
    shade: np.ndarray                       # 명암 비율(길 평균 = 1)
    cast_ab: np.ndarray                     # 장면 조명 색 편차 (a, b)
    d_in: np.ndarray                        # 길 안쪽 경계까지 거리(px), 바깥 0
    region: np.ndarray                      # 렌더 영역(마스크 + 페더 여유) bool
    px_per_m: int


def render_local(session: WorkSession, preset: CorkPreset, preview: bool = False,
                 max_preview_px: int = PREVIEW_MAX_PX) -> np.ndarray:
    """길 영역(페더 폭 포함)만 채운 렌더 레이어(BGR uint8). 크기 = 원본, preview면 축소본."""
    if session.mask is None or not session.mask.any():
        raise ValueError("길 영역이 지정되지 않았습니다")
    geo = _geometry(session, preview, max_preview_px)
    p = session.render_params
    levels = _texture_levels(preset, geo.px_per_m)

    # 1. 원근 투영(밉맵 3선형 샘플링)
    g = max(p.granule_scale, 1e-3)
    tex = _sample(levels, geo.u / g, geo.v / g, geo.level - np.log2(g))
    # 4. 원근 흐림: 먼 쪽(밉맵 단계 높음)을 약하게 흐림
    far = np.clip((geo.level - 1.0) / 3.0, 0, 1)[..., None] * 0.6
    if far.max() > 0:
        tex = tex * (1 - far) + cv2.GaussianBlur(tex, (0, 0), 0.8) * far

    lab = cv2.cvtColor(np.clip(tex / 255.0, 0, 1).astype(np.float32), cv2.COLOR_BGR2LAB)
    L = lab[..., 0]
    # 2. 명암·그림자 유지
    L *= 1 + p.shading_strength * (geo.shade - 1)
    # 3. 색 맞춤(장면 조명 색 쪽으로 약하게)
    lab[..., 1:] += p.color_match * geo.cast_ab
    # 5. 가장자리 마감선 / 6. 접촉 음영
    if p.edge_band and p.edge_band_px > 0:
        L[geo.d_in <= p.edge_band_px] *= EDGE_BAND_DARKEN
    if p.contact_shadow:
        t = np.clip(geo.d_in / CONTACT_PX, 0, 1)
        L *= 1 - CONTACT_DARKEN * (1 - t)
    np.clip(L, 0, 100, out=L)
    bgr = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)

    out = np.zeros((*geo.out_shape, 3), np.uint8)
    x0, y0, x1, y1 = geo.roi
    out[y0:y1, x0:x1] = np.clip(bgr * 255 + 0.5, 0, 255).astype(np.uint8) * geo.region[..., None]
    return out


def clear_cache() -> None:
    with _cache_lock:
        _geo_cache.clear()
        _tex_cache.clear()


def _cache_get(cache: OrderedDict, key):
    with _cache_lock:
        if key in cache:
            cache.move_to_end(key)
            return cache[key]
    return None


def _cache_put(cache: OrderedDict, key, value, limit: int) -> None:
    with _cache_lock:
        cache[key] = value
        while len(cache) > limit:
            cache.popitem(last=False)


# ---- 기하 ----
def _geometry(s: WorkSession, preview: bool, max_preview_px: int) -> _Geometry:
    H, W = s.original.shape[:2]
    quads = s.quad_segments or [s.quad if s.quad is not None else estimate_quad(s.mask)]
    for q in quads:
        warn = check_quad(q)
        if warn:
            raise ValueError(warn)
    width_m = s.path_width_m or DEFAULT_PATH_WIDTH_M
    key = (_digest(s.original, s.mask, *quads), preview, max_preview_px, width_m, s.mask_feather_px)
    hit = _cache_get(_geo_cache, key)
    if hit is not None:
        return hit

    # 텍스처 축척: 가장 가까운 아랫변에서 텍스처 1px ≈ 사진 1px
    w_bot = float(np.linalg.norm(quads[0][1] - quads[0][0]))
    px_per_m = int(np.clip(round(w_bot / width_m / 50) * 50, *PX_PER_M_RANGE))
    focal = default_focal_px(W, H)
    mats, spans = _segment_mats(quads, width_m, px_per_m, focal)

    if preview:
        img, sc = make_preview(s.original, max_preview_px)
    else:
        img, sc = s.original, 1.0
    mask = s.mask if sc == 1.0 else cv2.resize(s.mask, (img.shape[1], img.shape[0]), interpolation=cv2.INTER_NEAREST)
    mask = (mask > 0).astype(np.uint8)
    S_inv = np.diag([1 / sc, 1 / sc, 1.0])                     # 작업 좌표 → 원본 좌표

    pad = s.mask_feather_px + 2
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * pad + 1, 2 * pad + 1))
    region = cv2.dilate(mask, k)
    ys, xs = np.nonzero(region)
    x0, y0, x1, y1 = int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1
    region = region[y0:y1, x0:x1]
    m_roi = mask[y0:y1, x0:x1]

    gy, gx = np.mgrid[y0:y1, x0:x1].astype(np.float32)
    u, v, level = _plane_coords(gx, gy, [M @ S_inv for M in mats], spans, sc)
    del gx, gy

    lab = cv2.cvtColor(img[y0:y1, x0:x1].astype(np.float32) / 255.0, cv2.COLOR_BGR2LAB)
    shade = _shading(lab[..., 0], m_roi, img.shape)
    cast = _scene_cast(s.original, s.mask)
    d_in = cv2.distanceTransform(m_roi, cv2.DIST_L2, 5)

    outside = region == 0                                         # 렌더 영역 밖은 계산 불필요
    for a in (u, v, level, shade):
        a[outside] = 0
    geo = _Geometry((x0, y0, x1, y1), img.shape[:2], u, v, level, shade, cast, d_in, ~outside, px_per_m)
    _cache_put(_geo_cache, key, geo, _GEO_MAX)
    return geo


def _segment_mats(quads, width_m, px_per_m, focal):
    """구간별 (이미지 → 평면) 행렬과 행 범위. 평면 v는 먼 구간부터 이어지게 오프셋."""
    pw = round(width_m * px_per_m)
    phs = [plane_size_for(q, width_m, px_per_m, focal)[1] for q in quads]
    offs, acc = [0] * len(quads), 0
    for i in range(len(quads) - 1, -1, -1):                       # 먼 구간(마지막)부터 v 누적
        offs[i] = acc
        acc += phs[i]
    mats, spans = [], []
    for q, ph, off in zip(quads, phs, offs):
        Hm = homography_from_quad(q, pw, ph)
        mats.append(np.array([[1, 0, 0], [0, 1, off], [0, 0, 1]], np.float64) @ np.linalg.inv(Hm))
        spans.append((float(q[2:, 1].mean()), float(q[:2, 1].mean())))   # (윗변 y, 아랫변 y), 원본 좌표
    return mats, spans


def _plane_coords(gx, gy, mats, spans, sc):
    """작업 좌표 격자 → (u, v, 밉맵 단계). 구간이 여럿이면 경계 띠에서 좌표를 섞는다."""
    n = len(mats)
    if n == 1:
        weights = [None]
    else:
        y = gy[:, :1] / sc                                         # 원본 좌표 행(열마다 같음)
        bw = 0.25 * min(b - t for t, b in spans)
        s_prev, weights = np.ones_like(y), []
        for i in range(n):
            if i < n - 1:
                yb = spans[i][0]                                   # i 구간 윗변 = 다음 구간 아랫변
                r = np.clip((yb + bw - y) / (2 * bw), 0, 1)
                s_i = r * r * (3 - 2 * r)
            else:
                s_i = np.zeros_like(y)
            weights.append(s_prev - s_i)
            s_prev = s_i
    u = np.zeros(gx.shape, np.float32)
    v = np.zeros(gx.shape, np.float32)
    lv = np.zeros(gx.shape, np.float32)
    for M, wgt in zip(mats, weights):
        den = M[2, 0] * gx + M[2, 1] * gy + M[2, 2]
        ok = den > 1e-9
        den = np.where(ok, den, 1.0)
        uu = (M[0, 0] * gx + M[0, 1] * gy + M[0, 2]) / den
        vv = (M[1, 0] * gx + M[1, 1] * gy + M[1, 2]) / den
        # 밉맵 단계: 야코비안 두 열벡터 길이 중 큰 값(GPU 표준). 먼 쪽 세로 압축에서 앨리어싱 방지
        ex = np.hypot(M[0, 0] - uu * M[2, 0], M[1, 0] - vv * M[2, 0])
        ey = np.hypot(M[0, 1] - uu * M[2, 1], M[1, 1] - vv * M[2, 1])
        scale = np.maximum(ex, ey) / np.abs(den)
        ll = np.where(ok, np.log2(np.maximum(scale, 1.0)), MAX_LEVEL)
        if wgt is None:
            u[:], v[:], lv[:] = uu, vv, ll
        else:
            u += wgt * uu
            v += wgt * vv
            lv += wgt * ll
    return u, v, np.clip(lv, 0, MAX_LEVEL).astype(np.float32)


def _box(x: np.ndarray, r: int) -> np.ndarray:
    return cv2.blur(x, (2 * r + 1, 2 * r + 1), borderType=cv2.BORDER_REFLECT)


def _shading(L: np.ndarray, m: np.ndarray, full_shape) -> np.ndarray:
    """길 영역 L에서 빛·그림자(저주파)만 추출한 명암 비율. 길 밖 픽셀은 계산에 넣지 않는다.

    마스크 가중 자기 유도 필터(guided filter): 흙 얼룩처럼 대비가 작은 무늬는 지우고,
    그림자 경계처럼 대비가 큰 변화는 유지. 반경은 이미지 크기에 비례.
    """
    diag = float(np.hypot(*full_shape[:2]))
    r = max(3, int(0.006 * diag))
    eps = 10.0 ** 2
    mf = m.astype(np.float32)
    den = np.maximum(_box(mf, r), 1e-4)
    mean_I = _box(L * mf, r) / den
    var = np.maximum(_box(L * L * mf, r) / den - mean_I ** 2, 0)
    a = var / (var + eps)
    b = (1 - a) * mean_I
    q = (_box(a * mf, r) / den) * L + _box(b * mf, r) / den
    # 페더 띠(길 바로 밖)에서는 원본 L 대신 이웃 길 값으로
    q = np.where(m > 0, q, mean_I)
    # 남은 잔무늬 제거용 약한 블러(유효 영역만)
    rs = max(1, r // 3)
    q = _box(q * mf, rs) / np.maximum(_box(mf, rs), 1e-4) * (m > 0) + q * (m == 0)
    avg = float(q[m > 0].mean())
    return np.clip(q / max(avg, 1e-3), *SHADING_CLIP).astype(np.float32)


def _scene_cast(img: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """길과 주변(긴 변의 8%)의 무채색 픽셀 평균 a, b = 조명 색 편차. 무채색이 거의 없으면 (0, 0).

    길 주변 평균 색을 그대로 쓰면 잔디·흙 색이 코르크에 묻으므로, 조명 색을 반영하는 무채색(회색 벽·연석·포장면)만 쓴다.
    """
    small, _ = make_preview(img, 512)
    m = cv2.resize(mask, (small.shape[1], small.shape[0]), interpolation=cv2.INTER_NEAREST)
    r = max(1, int(CAST_RING * max(small.shape[:2])))
    ring = cv2.dilate((m > 0).astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))) > 0
    lab = cv2.cvtColor(small.astype(np.float32) / 255.0, cv2.COLOR_BGR2LAB)
    a, b, L = lab[..., 1], lab[..., 2], lab[..., 0]
    neutral = ring & (np.hypot(a, b) < NEUTRAL_CHROMA) & (L > 20) & (L < 95)
    if neutral.sum() < 0.01 * ring.sum():
        return np.zeros(2, np.float32)
    return np.array([a[neutral].mean(), b[neutral].mean()], np.float32)


# ---- 텍스처 ----
def _texture_levels(preset: CorkPreset, px_per_m: int) -> list[np.ndarray]:
    mtime = Path(preset.sample).stat().st_mtime if preset.sample else None
    key = (preset.id, preset.sample, mtime, tuple(preset.base_colors), preset.granule_mm,
           preset.sample_width_m, px_per_m)
    hit = _cache_get(_tex_cache, key)
    if hit is not None:
        return hit
    per = make_periodic_texture(make_tile(preset, px_per_m, TILE_PX, seed=0), seed=0).astype(np.float32)
    levels = [per]
    while len(levels) <= MAX_LEVEL and levels[-1].shape[0] % 2 == 0 and levels[-1].shape[0] >= 64:
        n = levels[-1].shape[0] // 2
        levels.append(cv2.resize(levels[-1], (n, n), interpolation=cv2.INTER_AREA))   # 정확히 1/2 = 상자 필터(주기 유지)
    _cache_put(_tex_cache, key, levels, _TEX_MAX)
    return levels


def _sample(levels: list[np.ndarray], u: np.ndarray, v: np.ndarray, level: np.ndarray) -> np.ndarray:
    """밉맵 3선형 샘플링. 단계별로 필요한 행 범위만 remap."""
    level = np.clip(level, 0, len(levels) - 1)
    k0 = np.floor(level).astype(np.int32)
    f = (level - k0)[..., None]
    out = np.zeros((*u.shape, 3), np.float32)
    for k, tex in enumerate(levels):
        w = np.where(k0 == k, 1 - f[..., 0], 0) + np.where(k0 == k - 1, f[..., 0], 0)
        rows = np.flatnonzero(w.any(axis=1))
        if rows.size == 0:
            continue
        r0, r1 = rows[0], rows[-1] + 1
        p = tex.shape[0]
        scale = 1.0 / (2 ** k)
        mx = np.mod(u[r0:r1] * scale, p).astype(np.float32)
        my = np.mod(v[r0:r1] * scale, p).astype(np.float32)
        smp = cv2.remap(tex, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_WRAP)
        out[r0:r1] += smp * w[r0:r1, :, None]
    return out


def _digest(*arrays) -> str:
    h = hashlib.blake2b(digest_size=16)
    for a in arrays:
        a = np.ascontiguousarray(a)
        h.update(str((a.shape, a.dtype)).encode())
        h.update(a.data)
    return h.hexdigest()
