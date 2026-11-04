"""코르크 텍스처·프리셋 (모듈 04)."""
from __future__ import annotations

import re
import zlib
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import yaml

from app.core.image_io import load_image

_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
DEFAULT_SAMPLE_WIDTH_M = 0.3    # 확인 필요: 제품 사진 중앙 정사각 영역이 덮는 실제 폭(m) 가정값
MIN_GRANULE_PX = 2.0            # 입자가 이보다 작게 그려지면 알아볼 수 없어 하한 적용


@dataclass
class CorkPreset:
    id: str
    name: str
    sample: str | None              # 제품 사진 절대 경로. 파일이 없으면 None(절차적 생성)
    base_colors: list[str]          # "#RRGGBB"
    granule_mm: float
    sample_width_m: float = DEFAULT_SAMPLE_WIDTH_M


def load_presets(path: str) -> list[CorkPreset]:
    """presets.yaml 로드·검증. sample은 presets.yaml 폴더 기준 상대 경로."""
    p = Path(path)
    with open(p, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, list) or not data:
        raise ValueError(f"프리셋 파일에 프리셋 목록이 없습니다: {p}")
    out, seen = [], set()
    for i, d in enumerate(data):
        where = f"프리셋 {i + 1}번"
        if not isinstance(d, dict):
            raise ValueError(f"{where} 형식이 잘못되었습니다")
        pid, name = d.get("id"), d.get("name")
        if not isinstance(pid, str) or not pid or not isinstance(name, str) or not name:
            raise ValueError(f"{where}: id와 name이 필요합니다")
        if pid in seen:
            raise ValueError(f"{where}: id가 중복됩니다({pid})")
        seen.add(pid)
        colors = d.get("base_colors")
        if not isinstance(colors, list) or not colors or not all(isinstance(c, str) and _HEX.match(c) for c in colors):
            raise ValueError(f"{where}({pid}): base_colors는 \"#RRGGBB\" 목록이어야 합니다")
        g = d.get("granule_mm")
        sw = d.get("sample_width_m", DEFAULT_SAMPLE_WIDTH_M)
        if not isinstance(g, (int, float)) or g <= 0 or not isinstance(sw, (int, float)) or sw <= 0:
            raise ValueError(f"{where}({pid}): granule_mm, sample_width_m은 양수여야 합니다")
        sample = None
        if d.get("sample"):
            sp = p.parent / str(d["sample"])
            sample = str(sp) if sp.is_file() else None
        out.append(CorkPreset(pid, name, sample, list(colors), float(g), float(sw)))
    return out


def make_tile(preset: CorkPreset, px_per_m: int, size_px: int = 1024, seed: int = 0) -> np.ndarray:
    """이음매 없는(가로·세로 반복 가능) 정사각 타일, BGR uint8. 실제 축척은 px_per_m."""
    if px_per_m <= 0 or size_px < 16:
        raise ValueError("px_per_m은 양수, size_px는 16 이상이어야 합니다")
    rng = np.random.default_rng([seed, zlib.crc32(preset.id.encode("utf-8"))])
    if preset.sample:
        return _tile_from_sample(preset, px_per_m, size_px)
    return _tile_procedural(preset, px_per_m, size_px, rng)


def make_plane_texture(tile: np.ndarray, w: int, h: int, seed: int = 0) -> np.ndarray:
    """평면 텍스처(w×h): make_periodic_texture 결과를 반복해 채운다."""
    if w <= 0 or h <= 0:
        raise ValueError(f"텍스처 크기는 양수여야 합니다: {w}x{h}")
    per = make_periodic_texture(tile, seed=seed)
    p = per.shape[0]
    return np.tile(per, (-(-h // p), -(-w // p), 1))[:h, :w]


def make_periodic_texture(tile: np.ndarray, k: int = 3, seed: int = 0) -> np.ndarray:
    """k×k 타일을 원환(torus) 위에 배치한 주기 텍스처(가로·세로 반복해도 이음매 없음).

    타일마다 무작위 90° 회전·반전, 겹침 구간은 대비 유지 블렌딩, 저주파 밝기 변화(±6%).
    렌더링(05)은 이 텍스처를 좌표 나머지로 무한 반복해 쓴다.
    """
    if k < 2:
        raise ValueError("k는 2 이상이어야 합니다")
    rng = np.random.default_rng(seed)
    t = tile.astype(np.float32)
    s = t.shape[0]
    ov = max(2, s // 8)                         # 겹침 폭
    step = s - ov
    P = k * step
    mean = t.reshape(-1, 3).mean(0)
    ramp = np.ones(s, np.float32)
    ramp[:ov] = np.linspace(0, 1, ov + 2, dtype=np.float32)[1:-1]
    ramp[-ov:] = ramp[:ov][::-1]
    wgt = np.outer(ramp, ramp)[..., None]
    acc = np.zeros((P, P, 3), np.float32)
    q = np.zeros((P, P, 1), np.float32)
    for j in range(k):
        for i in range(k):
            v = np.rot90(t, int(rng.integers(4)))
            if rng.integers(2):
                v = v[:, ::-1]
            idx = np.ix_((j * step + np.arange(s)) % P, (i * step + np.arange(s)) % P)
            acc[idx] += wgt * (v - mean)
            q[idx] += wgt * wgt
    out = mean + acc / np.sqrt(np.maximum(q, 1e-6))
    out *= _periodic_blotches(P, rng)[..., None]
    return np.clip(out, 0, 255).astype(np.uint8)


# ---- 내부 ----
def _periodic_blotches(P: int, rng: np.random.Generator, amp: float = 0.06) -> np.ndarray:
    """주기 P의 얼룩형 저주파 밝기 변화(1 ± amp). 여러 방향 정수 주파수 코사인 합 → 줄무늬 없음.

    저해상도 격자에서 정확히 계산한 뒤 원환 패딩 후 확대(속도).
    """
    n = max(8, P // 16)
    yy, xx = np.mgrid[0:n, 0:n].astype(np.float32) * (2 * np.pi / n)
    lf = np.zeros((n, n), np.float32)
    for fx in range(-3, 4):
        for fy in range(0, 4):
            r = np.hypot(fx, fy)
            if (fy == 0 and fx <= 0) or r > 3.2:
                continue
            lf += rng.normal(0, 1 / r) * np.cos(fx * xx + fy * yy + rng.uniform(0, 2 * np.pi))
    lf = 1 + amp * lf / np.abs(lf).max()
    cell = P / n
    big = cv2.resize(np.pad(lf, 1, mode="wrap"), (round((n + 2) * cell), round((n + 2) * cell)),
                     interpolation=cv2.INTER_LINEAR)
    o = round(cell)
    return big[o:o + P, o:o + P]


def _tile_from_sample(preset: CorkPreset, px_per_m: int, size_px: int) -> np.ndarray:
    img = load_image(preset.sample)
    h, w = img.shape[:2]
    c = min(h, w)
    crop = img[(h - c) // 2:(h - c) // 2 + c, (w - c) // 2:(w - c) // 2 + c]
    target = max(16, round(preset.sample_width_m * px_per_m))   # 이 축척에서 샘플이 차지하는 px
    if target >= size_px:
        crop = cv2.resize(crop, (target, target), interpolation=cv2.INTER_AREA if target < c else cv2.INTER_CUBIC)
        o = (target - size_px) // 2
        return _make_seamless(_flatten_light(crop[o:o + size_px, o:o + size_px]))
    k = -(-size_px // target)                                     # 반복 횟수(이음매 유지 위해 정수)
    unit = size_px // k
    small = cv2.resize(crop, (unit, unit), interpolation=cv2.INTER_AREA if unit < c else cv2.INTER_CUBIC)
    tiled = np.tile(_make_seamless(_flatten_light(small)), (k, k, 1))
    if tiled.shape[0] != size_px:                                 # 나머지 px만큼 늘림(아주 작은 배율 차이)
        tiled = _make_seamless(cv2.resize(tiled, (size_px, size_px), interpolation=cv2.INTER_LINEAR))
    return tiled


def _flatten_light(img: np.ndarray) -> np.ndarray:
    """조명 평탄화: 큰 블러로 나눠 밝기 기울기 제거(평균 밝기 유지)."""
    f = img.astype(np.float32) + 1.0
    sigma = max(4.0, img.shape[0] / 6)
    low = cv2.GaussianBlur(f, (0, 0), sigma, borderType=cv2.BORDER_REFLECT)
    out = f / low * f.reshape(-1, 3).mean(0)
    return np.clip(out - 1.0, 0, 255).astype(np.uint8)


def _make_seamless(img: np.ndarray) -> np.ndarray:
    """가장자리는 반 칸 밀어낸 사본, 가운데는 원본을 쓰는 블렌딩으로 이음매 제거."""
    s = img.shape[0]
    f = img.astype(np.float32)
    rolled = np.roll(f, (s // 2, s // 2), axis=(0, 1))
    d = np.minimum(np.arange(s), np.arange(s)[::-1]).astype(np.float32)
    band = max(2.0, s / 4)
    r = np.clip(d / band, 0, 1)
    r = r * r * (3 - 2 * r)                                       # smoothstep
    wgt = np.minimum.outer(r, r)[..., None]                       # 가장자리 0 → 가운데 1
    mu = f.reshape(-1, 3).mean(0)
    # 대비 유지 블렌딩: 두 사본을 섞은 구간이 흐려지지 않도록 표준편차 보정
    out = mu + (wgt * (f - mu) + (1 - wgt) * (rolled - mu)) / np.sqrt(wgt ** 2 + (1 - wgt) ** 2)
    return np.clip(out, 0, 255).astype(np.uint8)


def _hex_bgr(c: str) -> np.ndarray:
    return np.array([int(c[5:7], 16), int(c[3:5], 16), int(c[1:3], 16)], np.float32)


def _tile_procedural(preset: CorkPreset, px_per_m: int, size_px: int, rng: np.random.Generator) -> np.ndarray:
    """입자(보로노이 셀) 배치로 코르크 칩 질감 생성. 원환(torus) 위에서 계산해 이음매가 없다."""
    s = size_px
    g = max(MIN_GRANULE_PX, preset.granule_mm / 1000.0 * px_per_m)
    # 층화 무작위 배치(Poisson disk 근사): 칸마다 점 하나 → 크기가 고르면서 모양이 불규칙한 입자
    n = max(2, int(round(s / g)))
    cell = s / n
    gy, gx = np.mgrid[0:n, 0:n]
    pts = np.stack([(gx + rng.random((n, n))) * cell,
                    (gy + rng.random((n, n))) * cell], -1).reshape(-1, 2)
    pts = (pts + rng.random(2) * cell) % s                         # 격자선이 타일 경계와 겹치지 않게 전체 이동
    m = int(np.ceil(3 * cell))                                    # 가장자리 너머 이웃 점까지 고려
    canvas = np.full((s + 2 * m, s + 2 * m), 255, np.uint8)
    idx_img = np.full(canvas.shape, -1, np.int64)
    for dy in (-s, 0, s):
        for dx in (-s, 0, s):
            q = np.round(pts + (dx + m, dy + m)).astype(int)
            ok = (q[:, 0] >= 0) & (q[:, 0] < canvas.shape[1]) & (q[:, 1] >= 0) & (q[:, 1] < canvas.shape[0])
            canvas[q[ok, 1], q[ok, 0]] = 0
            idx_img[q[ok, 1], q[ok, 0]] = np.flatnonzero(ok)
    _, lab = cv2.distanceTransformWithLabels(canvas, cv2.DIST_L2, 5, labelType=cv2.DIST_LABEL_PIXEL)
    # 라벨 번호 → 점 번호
    zero_y, zero_x = np.nonzero(canvas == 0)
    lut = np.zeros(lab.max() + 1, np.int64)
    lut[lab[zero_y, zero_x]] = idx_img[zero_y, zero_x]
    cells = lut[lab][m:m + s, m:m + s]

    colors = np.stack([_hex_bgr(c) for c in preset.base_colors])
    pick = colors[rng.integers(len(colors), size=len(pts))]
    bright = rng.normal(1.0, 0.12, (len(pts), 1)).astype(np.float32)
    tint = rng.normal(0, 6, (len(pts), 3)).astype(np.float32)
    img = pick[cells] * bright[cells] + tint[cells]

    # 입자 사이 어두운 틈(결합재): 이웃 픽셀과 입자가 다른 곳(원환 기준)
    if g >= 4:
        edge = (cells != np.roll(cells, 1, 0)) | (cells != np.roll(cells, 1, 1))
        img[edge] *= 0.62
    # 미세 노이즈 + 약한 하이라이트(이음매 없도록 원환 패딩 후 블러)
    pad = 8
    noise = rng.normal(0, 1, (s, s)).astype(np.float32)
    noise = cv2.GaussianBlur(np.pad(noise, pad, mode="wrap"), (0, 0), 0.8)[pad:-pad, pad:-pad]
    img *= (1 + 0.06 * noise)[..., None]
    hl = rng.random((s, s)) > 0.995
    img[hl] = np.minimum(img[hl] * 1.25, 255)
    return np.clip(img, 0, 255).astype(np.uint8)
