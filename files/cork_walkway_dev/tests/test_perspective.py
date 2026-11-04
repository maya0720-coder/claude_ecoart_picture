import numpy as np
import pytest

from app.core import perspective as pv
from app.models import WorkSession
from synth import make_scene

import cv2


def corner_err(a, b):
    return float(np.abs(np.asarray(a) - np.asarray(b)).max())


@pytest.mark.parametrize("h, w", [(900, 1200), (3000, 4000)])
def test_estimate_quad_synthetic(h, w):
    sc = make_scene(h, w)
    q = pv.estimate_quad(sc.path)
    assert q.shape == (4, 2) and q.dtype == np.float32
    assert corner_err(q, sc.quad) <= 5.0
    assert pv.check_quad(q) is None


def test_estimate_quad_ignores_hole_and_stray_rows():
    sc = make_scene()
    m = sc.path_wo_obj.copy()                # 가운데 물체 구멍은 가장자리에 영향 없음
    m[850, 100:110] = 255                    # 하단 구간의 튀는 조각
    q = pv.estimate_quad(m)
    assert corner_err(q, sc.quad) <= 5.0


def test_estimate_quad_converging_top_gets_min_width():
    m = np.zeros((400, 400), np.uint8)
    cv2.fillPoly(m, [np.array([[50, 399], [350, 399], [200, 50]], np.int32)], 255)   # 삼각형(소실점)
    q = pv.estimate_quad(m)
    top_w = q[2, 0] - q[3, 0]
    assert top_w >= pv.MIN_TOP_RATIO * (q[1, 0] - q[0, 0]) - 1e-3
    assert pv.check_quad(q) is None


def test_estimate_errors():
    with pytest.raises(ValueError):
        pv.estimate_quad(np.zeros((50, 50), np.uint8))
    with pytest.raises(ValueError):
        pv.estimate_quads(make_scene().path, 6)


def test_estimate_quads_segments_share_edges():
    sc = make_scene()
    qs = pv.estimate_quads(sc.path, 3)
    assert len(qs) == 3
    for a, b in zip(qs, qs[1:]):
        assert np.allclose(a[3], b[0]) and np.allclose(a[2], b[1])   # 윗변 = 다음 구간 아랫변
    assert np.allclose(qs[0][:2], pv.estimate_quad(sc.path)[:2], atol=1e-3)
    assert all(pv.check_quad(q) is None for q in qs)


def test_estimate_quads_curved_path_follows_center():
    h, w = 600, 800
    m = np.zeros((h, w), np.uint8)
    for y in range(100, h):                  # 위로 갈수록 오른쪽으로 휘는 길
        t = (h - y) / (h - 100)
        c = 300 + 250 * t ** 2
        half = 150 * (1 - 0.7 * t)
        m[y, int(c - half):int(c + half)] = 255
    single = pv.estimate_quad(m)
    seg = pv.estimate_quads(m, 4)
    mid_y = 300
    true_c = 300 + 250 * ((h - mid_y) / (h - 100)) ** 2
    k = next(i for i, q in enumerate(seg) if q[2, 1] <= mid_y <= q[0, 1])
    def center_at(q, y):
        t = (q[0, 1] - y) / (q[0, 1] - q[3, 1])
        l = q[0, 0] + t * (q[3, 0] - q[0, 0])
        r = q[1, 0] + t * (q[2, 0] - q[1, 0])
        return (l + r) / 2
    assert abs(center_at(seg[k], mid_y) - true_c) < abs(center_at(single, mid_y) - true_c)
    assert abs(center_at(seg[k], mid_y) - true_c) < 15


def test_homography_maps_plane_corners():
    sc = make_scene()
    H = pv.homography_from_quad(sc.quad, 400, 1500)
    plane = np.array([[[0, 1500]], [[400, 1500]], [[400, 0]], [[0, 0]]], np.float32)
    out = cv2.perspectiveTransform(plane, H).reshape(4, 2)
    assert np.allclose(out, sc.quad, atol=1e-2)
    with pytest.raises(ValueError):
        pv.homography_from_quad(sc.quad, 0, 10)


def test_plane_size():
    sc = make_scene()
    f = pv.default_focal_px(1200, 900)
    pw, ph = pv.plane_size_for(sc.quad, 2.0, 200, focal_px=f)
    assert pw == 400
    # 아랫변 720px, 윗변 180px, f≈901 → L = 2·901·(1/180 − 1/720) ≈ 7.5m
    assert ph == pytest.approx(7.5 * 200, rel=0.02)
    pw2, ph2 = pv.plane_size_for(sc.quad, 3.0, 200, focal_px=f)      # 폭을 키우면 길이도 비례
    assert pw2 == 600 and ph2 == pytest.approx(ph * 1.5, rel=0.01)
    rect = np.array([[100, 500], [300, 500], [300, 100], [100, 100]], np.float32)   # 위에서 본 길(평행)
    pw3, ph3 = pv.plane_size_for(rect, 2.0, 100, focal_px=f)
    assert (pw3, ph3) == (200, 400)
    far = np.array([[0, 500], [1000, 500], [500.5, 0], [499.5, 0]], np.float32)     # 거의 점인 윗변
    assert pv.plane_size_for(far, 2.0, 100, focal_px=f)[1] == round(pv.MAX_LENGTH_RATIO * 2.0 * 100)
    assert pv.plane_size_for(sc.quad, 2.0, 200)[1] > 0                              # focal 없이도 동작
    with pytest.raises(ValueError):
        pv.plane_size_for(sc.quad, 0, 200)


def test_check_and_update_quad():
    good = np.array([[0, 100], [100, 100], [70, 0], [30, 0]], np.float32)
    assert pv.check_quad(good) is None
    twisted = good[[0, 1, 3, 2]]                       # 윗변 두 점 뒤바뀜(자기 교차)
    mirrored = good[[1, 0, 3, 2]]                      # 좌우 뒤집힘
    tiny = np.array([[0, 10], [10, 10], [10, 9], [0, 9]], np.float32)
    line = np.array([[0, 0], [50, 50], [100, 100], [25, 25]], np.float32)
    concave = np.array([[0, 100], [100, 100], [50, 80], [0, 0]], np.float32)
    for bad in (twisted, mirrored, tiny, line, concave, np.full((4, 2), np.nan, np.float32)):
        assert pv.check_quad(bad) is not None
        q, warn = pv.update_quad(good, bad)
        assert warn and q is good                       # 경고 + 직전 값 유지
    q, warn = pv.update_quad(good, good + 5)
    assert warn is None and np.allclose(q, good + 5)


def test_project_grid():
    sc = make_scene()
    segs = pv.project_grid(sc.quad, 4, 8)
    assert len(segs) == 5 + 9
    assert np.allclose(segs[0][0], sc.quad[3], atol=1e-2)   # 첫 세로선 위끝 = 좌상
    assert np.allclose(segs[0][1], sc.quad[0], atol=1e-2)   # 아래끝 = 좌하


def test_session_new_fields():
    img = np.zeros((10, 10, 3), np.uint8)
    s = WorkSession(img, "a.jpg")
    assert s.path_width_m is None and s.quad_segments is None
    with pytest.raises(ValueError):
        WorkSession(img, "a.jpg", path_width_m=0)
    with pytest.raises(ValueError):
        WorkSession(img, "a.jpg", quad_segments=[np.zeros((3, 2))])
