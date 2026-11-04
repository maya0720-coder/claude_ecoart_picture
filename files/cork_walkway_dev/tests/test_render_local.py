import time

import cv2
import numpy as np
import pytest

from app.core import render_local as rl
from app.core.cork_material import CorkPreset
from app.core.perspective import estimate_quads
from app.models import RenderParams, WorkSession
from synth import make_scene


def preset(pid="natural_brown", colors=("#8B5A2B", "#A0522D", "#6B4423")):
    return CorkPreset(pid, pid, None, list(colors), 3.0)


@pytest.fixture(autouse=True)
def fresh_cache():
    rl.clear_cache()
    yield
    rl.clear_cache()


def session(sc, **kw):
    return WorkSession(sc.img, "a.jpg", mask=sc.path_wo_obj, quad=sc.quad, **kw)


def L_of(img):
    return cv2.cvtColor(img, cv2.COLOR_BGR2LAB)[..., 0].astype(np.float32)


def test_layer_basic():
    sc = make_scene()
    out = rl.render_local(session(sc), preset())
    assert out.shape == sc.img.shape and out.dtype == np.uint8
    far_out = cv2.dilate(sc.path_wo_obj, np.ones((15, 15), np.uint8)) == 0
    assert out[far_out].max() == 0                       # 길(+페더 폭) 밖은 비어 있음
    inside = sc.path_wo_obj > 0
    assert out[inside].min(axis=1).max() > 0
    assert out[inside].mean() > 10


def test_shadow_band_preserved():
    sc = make_scene()
    out = rl.render_local(session(sc), preset())
    L = L_of(out)
    inside = sc.path_wo_obj > 0
    band = sc.shadow & inside
    rows = np.zeros_like(inside)
    rows[int(0.55 * 900):int(0.6 * 900)] = True           # 그림자 띠 바로 위(그늘 아님)
    rows &= inside
    ratio = L[band].mean() / L[rows].mean()
    assert ratio < 0.8                                    # 원본 그림자(밝기 0.55배)가 결과에서도 어둡게 유지

    rl.clear_cache()
    flat = rl.render_local(session(sc, render_params=RenderParams(shading_strength=0.0)), preset())
    Lf = L_of(flat)
    assert Lf[band].mean() / Lf[rows].mean() > 0.9        # 명암 유지를 끄면 그림자 없음


def test_dirt_stains_not_copied():
    """흙의 작은 얼룩(돌·바퀴 자국)은 명암에 남기지 않는다."""
    sc = make_scene()
    img = sc.img.copy()
    rng = np.random.default_rng(5)
    for _ in range(60):                                   # 길 위 작은 어두운 돌
        x, y = int(rng.integers(400, 800)), int(rng.integers(780, 880))
        cv2.circle(img, (x, y), 3, (30, 50, 70), -1)
    s = WorkSession(img, "a.jpg", mask=sc.path_wo_obj, quad=sc.quad)
    geo = rl._geometry(s, False, rl.PREVIEW_MAX_PX)
    x0, y0, x1, y1 = geo.roi
    sh = geo.shade[780 - y0:880 - y0, 400 - x0:800 - x0]
    assert sh.std() < 0.08


def test_preview_size_and_consistency():
    sc = make_scene(1200, 1600)
    s = session(sc)
    prev = rl.render_local(s, preset(), preview=True, max_preview_px=800)
    assert prev.shape == (600, 800, 3)
    full = rl.render_local(s, preset())
    small = cv2.resize(full, (800, 600), interpolation=cv2.INTER_AREA)
    inside = cv2.resize(sc.path_wo_obj, (800, 600), interpolation=cv2.INTER_NEAREST) > 0
    inside = cv2.erode(inside.astype(np.uint8), np.ones((9, 9), np.uint8)) > 0
    diff = np.abs(prev[inside].astype(np.float32).mean(0) - small[inside].astype(np.float32).mean(0))
    assert diff.max() < 6                                 # 미리보기와 최종의 평균 색이 같음


def test_cache_makes_preset_switch_faster():
    sc = make_scene(1500, 2000)
    s = session(sc)
    t = time.perf_counter(); rl.render_local(s, preset("a")); first = time.perf_counter() - t
    t = time.perf_counter(); rl.render_local(s, preset("b", ["#4A2C17", "#5C3A1E"])); second = time.perf_counter() - t
    t = time.perf_counter(); rl.render_local(s, preset("a")); third = time.perf_counter() - t
    assert second < first
    assert third < second                                 # 기하·텍스처 모두 캐시


def test_color_match_follows_scene_cast():
    sc = make_scene()
    img = sc.img.copy()
    img[int(0.2 * 900): int(0.28 * 900)] = (160, 140, 135)   # 길 바로 위쪽 회색 벽(파란 기운 조명)
    s = WorkSession(img, "a.jpg", mask=sc.path_wo_obj, quad=sc.quad)
    geo = rl._geometry(s, False, rl.PREVIEW_MAX_PX)
    assert geo.cast_ab[1] < -3                            # b < 0 = 파란 기운
    base = rl.render_local(WorkSession(img, "a.jpg", mask=sc.path_wo_obj, quad=sc.quad,
                                       render_params=RenderParams(color_match=0.0)), preset())
    tinted = rl.render_local(WorkSession(img, "a.jpg", mask=sc.path_wo_obj, quad=sc.quad,
                                         render_params=RenderParams(color_match=1.0)), preset())
    inside = sc.path_wo_obj > 0
    b0 = cv2.cvtColor(base, cv2.COLOR_BGR2LAB)[..., 2][inside].mean()
    b1 = cv2.cvtColor(tinted, cv2.COLOR_BGR2LAB)[..., 2][inside].mean()
    assert b1 < b0 - 2


def test_edge_band_and_contact_shadow():
    sc = make_scene()
    plain = rl.render_local(session(sc), preset())
    banded = rl.render_local(session(sc, render_params=RenderParams(edge_band=True, edge_band_px=6)), preset())
    contact = rl.render_local(session(sc, render_params=RenderParams(contact_shadow=True)), preset())
    m = (sc.path_wo_obj > 0).astype(np.uint8)
    d = cv2.distanceTransform(m, cv2.DIST_L2, 5)
    edge, core = (d > 0) & (d <= 3), d > 20
    Lp, Lb, Lc = L_of(plain), L_of(banded), L_of(contact)
    assert Lb[edge].mean() < 0.9 * Lp[edge].mean()
    assert abs(Lb[core].mean() - Lp[core].mean()) < 0.5
    assert Lc[edge].mean() < Lp[edge].mean()


def test_granule_scale_changes_texture():
    sc = make_scene()
    a = rl.render_local(session(sc), preset())
    b = rl.render_local(session(sc, render_params=RenderParams(granule_scale=2.0)), preset())
    inside = sc.path_wo_obj > 0
    ga = np.abs(cv2.Laplacian(L_of(a), cv2.CV_32F))[inside].mean()
    gb = np.abs(cv2.Laplacian(L_of(b), cv2.CV_32F))[inside].mean()
    assert gb < ga                                        # 입자가 크면 고주파가 줄어듦


def test_perspective_mapping_and_far_filtering():
    sc = make_scene()
    s = session(sc)
    geo = rl._geometry(s, False, rl.PREVIEW_MAX_PX)
    x0, y0, _, _ = geo.roi
    lb = sc.quad[0].round().astype(int)
    lt = sc.quad[3].round().astype(int)
    assert geo.u[lb[1] - y0, lb[0] - x0] == pytest.approx(0, abs=3)
    assert geo.v[lt[1] - y0, lt[0] - x0] == pytest.approx(0, abs=3)
    assert geo.v[lb[1] - y0, lb[0] - x0] > geo.v[lt[1] - y0, lt[0] - x0]
    near = geo.level[lb[1] - y0 - 5, int(sc.quad[:2, 0].mean()) - x0]
    far = geo.level[lt[1] - y0 + 5, int(sc.quad[2:, 0].mean()) - x0]
    assert near < 1.0 < far                               # 먼 쪽은 밉맵 단계가 높음(축소 필터)


def test_segments_render_continuous():
    sc = make_scene()
    qs = estimate_quads(sc.path, 3)
    out = rl.render_local(WorkSession(sc.img, "a.jpg", mask=sc.path_wo_obj, quad=qs[0], quad_segments=qs), preset())
    inside = (cv2.erode(sc.path_wo_obj, np.ones((7, 7), np.uint8)) > 0) & ~sc.shadow
    L = L_of(out)
    row_mean = np.array([L[y][inside[y]].mean() if inside[y].sum() > 20 else np.nan for y in range(900)])
    jumps = np.abs(np.diff(row_mean))
    jumps = jumps[~np.isnan(jumps)]
    assert jumps.max() < 6 * np.median(jumps) + 3          # 구간 경계에 밝기 계단 없음


def test_errors():
    sc = make_scene()
    with pytest.raises(ValueError):
        rl.render_local(WorkSession(sc.img, "a.jpg"), preset())
    bad = sc.quad[[0, 1, 3, 2]]
    with pytest.raises(ValueError):
        rl.render_local(WorkSession(sc.img, "a.jpg", mask=sc.path, quad=bad), preset())
    auto = rl.render_local(WorkSession(sc.img, "a.jpg", mask=sc.path), preset())   # quad 없으면 자동 추정
    assert auto[sc.path > 0].mean() > 10
