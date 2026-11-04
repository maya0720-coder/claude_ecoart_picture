from pathlib import Path

import cv2
import numpy as np
import pytest

from app.core import cork_material as cm
from app.core.image_io import save_image

ROOT = Path(__file__).resolve().parent.parent


def seam_ratio(tile: np.ndarray) -> float:
    """타일 2×2를 붙였을 때 경계선 그래디언트 / 내부 평균 그래디언트(가로·세로 중 큰 값)."""
    s = tile.shape[0]
    big = np.tile(tile.astype(np.float32), (2, 2, 1))
    gx = np.abs(np.diff(big, axis=1)).mean(axis=(0, 2))   # x-1→x 차이, 길이 2s-1
    gy = np.abs(np.diff(big, axis=0)).mean(axis=(1, 2))
    return max(gx[s - 1] / gx.mean(), gy[s - 1] / gy.mean())


def proc_preset(pid="natural_brown", granule=3.0):
    return cm.CorkPreset(pid, "테스트", None, ["#8B5A2B", "#A0522D", "#6B4423"], granule)


@pytest.fixture
def sample_preset(tmp_path):
    """조명 기울기가 있는 가짜 코르크 제품 사진(한글 경로)."""
    rng = np.random.default_rng(1)
    h, w = 900, 1200
    img = np.full((h, w, 3), (40, 70, 110), np.float32)   # 결합재 바탕 + 촘촘한 입자(실제 제품 사진과 비슷하게)
    for _ in range(25000):
        c = (int(rng.integers(w)), int(rng.integers(h)))
        col = tuple(float(v) for v in rng.uniform([30, 60, 100], [70, 110, 170]))
        cv2.circle(img, c, int(rng.integers(3, 9)), col, -1)
    img *= np.linspace(0.6, 1.3, w, dtype=np.float32)[None, :, None]   # 왼쪽 어둡고 오른쪽 밝음
    d = tmp_path / "자재 사진" / "natural_brown"
    d.mkdir(parents=True)
    save_image(str(d / "sample.jpg"), np.clip(img, 0, 255).astype(np.uint8))
    yml = tmp_path / "자재 사진" / "presets.yaml"
    yml.write_text("- id: natural_brown\n  name: 내추럴\n  sample: natural_brown/sample.jpg\n"
                   "  base_colors: ['#8B5A2B']\n  granule_mm: 3.0\n", encoding="utf-8")
    return cm.load_presets(str(yml))[0]


# ---- 프리셋 ----
def test_load_project_presets():
    ps = cm.load_presets(str(ROOT / "materials" / "cork" / "presets.yaml"))
    assert [p.id for p in ps] == ["natural_brown", "dark_brown", "color"]
    assert ps[0].name == "내추럴 브라운"
    assert all(p.sample is None for p in ps)          # 제품 사진 없음 → 절차적 생성
    assert all(p.granule_mm > 0 and p.base_colors for p in ps)


def test_sample_resolved(sample_preset):
    assert sample_preset.sample and Path(sample_preset.sample).is_file()
    assert sample_preset.sample_width_m == cm.DEFAULT_SAMPLE_WIDTH_M


@pytest.mark.parametrize("text", [
    "[]",
    "- id: a\n  name: A\n  base_colors: ['#zzzzzz']\n  granule_mm: 3\n",
    "- id: a\n  name: A\n  base_colors: ['#112233']\n  granule_mm: 0\n",
    "- id: a\n  name: A\n  base_colors: []\n  granule_mm: 3\n",
    "- name: A\n  base_colors: ['#112233']\n  granule_mm: 3\n",
    "- {id: a, name: A, base_colors: ['#112233'], granule_mm: 3}\n- {id: a, name: B, base_colors: ['#112233'], granule_mm: 3}\n",
])
def test_invalid_presets(tmp_path, text):
    p = tmp_path / "presets.yaml"
    p.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError):
        cm.load_presets(str(p))


# ---- 타일 ----
@pytest.mark.parametrize("px_per_m, granule", [(1000, 3.0), (500, 3.0), (2000, 5.0)])
def test_procedural_tile_seamless(px_per_m, granule):
    t = cm.make_tile(proc_preset(granule=granule), px_per_m, 512, seed=3)
    assert t.shape == (512, 512, 3) and t.dtype == np.uint8
    assert seam_ratio(t) <= 1.5


def test_procedural_color_near_preset():
    t = cm.make_tile(proc_preset(), 1000, 512)
    mean_bgr = t.reshape(-1, 3).mean(0)
    base = np.mean([cm._hex_bgr(c) for c in proc_preset().base_colors], axis=0)
    assert np.abs(mean_bgr - base).max() < 40


@pytest.mark.parametrize("px_per_m", [500, 6000])   # 샘플이 타일보다 작음(반복) / 큼(잘라냄)
def test_sample_tile_seamless_and_flat(sample_preset, px_per_m):
    t = cm.make_tile(sample_preset, px_per_m, 512)
    assert t.shape == (512, 512, 3)
    assert seam_ratio(t) <= 1.5
    left, right = t[:, :128].mean(), t[:, -128:].mean()
    assert abs(left - right) / t.mean() < 0.1          # 조명 기울기 제거


def test_tile_seed_reproducible():
    p = proc_preset()
    a, b = cm.make_tile(p, 1000, 256, seed=7), cm.make_tile(p, 1000, 256, seed=7)
    assert np.array_equal(a, b)
    assert not np.array_equal(a, cm.make_tile(p, 1000, 256, seed=8))
    assert not np.array_equal(a, cm.make_tile(proc_preset("dark_brown"), 1000, 256, seed=7))


def test_tile_errors():
    with pytest.raises(ValueError):
        cm.make_tile(proc_preset(), 0)
    with pytest.raises(ValueError):
        cm.make_tile(proc_preset(), 1000, 8)


# ---- 평면 텍스처 ----
def test_plane_texture():
    tile = cm.make_tile(proc_preset(), 1000, 256, seed=1)
    tex = cm.make_plane_texture(tile, 700, 1500, seed=2)
    assert tex.shape == (1500, 700, 3) and tex.dtype == np.uint8
    assert np.array_equal(tex, cm.make_plane_texture(tile, 700, 1500, seed=2))
    # 대비 유지: 겹침 블렌딩 후에도 표준편차가 타일과 비슷
    assert tex.std() == pytest.approx(tile.std(), rel=0.25)
    # 타일 경계(회전 배치)에 띠가 생기지 않음: 행·열 평균 그래디언트에 튀는 곳 없음
    g = np.abs(np.diff(tex.astype(np.float32), axis=1)).mean(axis=(0, 2))
    assert g.max() <= 1.5 * g.mean()
    with pytest.raises(ValueError):
        cm.make_plane_texture(tile, 0, 10)


def test_plane_texture_small():
    tile = cm.make_tile(proc_preset(), 1000, 64)
    assert cm.make_plane_texture(tile, 10, 5).shape == (5, 10, 3)
