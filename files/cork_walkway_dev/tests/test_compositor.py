import cv2
import numpy as np
import pytest

from app.core import compositor as cp
from app.core import render_local as rl
from app.core.cork_material import CorkPreset
from app.models import WorkSession
from synth import make_scene


def random_case(rng):
    h, w = int(rng.integers(20, 160)), int(rng.integers(20, 160))
    img = rng.integers(0, 256, (h, w, 3), dtype=np.uint8)
    layer = rng.integers(0, 256, (h, w, 3), dtype=np.uint8)
    mask = np.zeros((h, w), np.uint8)
    for _ in range(int(rng.integers(0, 4))):
        kind = rng.integers(3)
        c = (int(rng.integers(w)), int(rng.integers(h)))
        if kind == 0:
            cv2.circle(mask, c, int(rng.integers(1, max(2, min(h, w) // 2))), 255, -1)
        elif kind == 1:
            pts = rng.integers(0, [w, h], (int(rng.integers(3, 7)), 2)).astype(np.int32)
            cv2.fillPoly(mask, [pts], 255)
        else:
            mask[rng.random((h, w)) < 0.02] = 255          # 흩어진 점
    return img, layer, mask, int(rng.integers(1, 11))


def test_random_100_all_pass():
    rng = np.random.default_rng(2026)
    for i in range(100):
        img, layer, mask, f = random_case(rng)
        out = cp.composite(img, layer, mask, f)
        ok, n = cp.verify_outside_unchanged(img, out, mask, f)
        assert ok and n == 0, f"case {i}: {n} changed"
        assert out.dtype == np.uint8 and out.shape == img.shape


def test_inside_actually_replaced():
    img = np.zeros((60, 60, 3), np.uint8)
    layer = np.full((60, 60, 3), 200, np.uint8)
    mask = np.zeros((60, 60), np.uint8)
    mask[10:50, 10:50] = 255
    out = cp.composite(img, layer, mask, 3)
    assert (out[20:40, 20:40] == 200).all()
    assert out[0, 0].sum() == 0


@pytest.mark.parametrize("n_bad", [1, 37])
def test_violation_detected(n_bad, monkeypatch):
    rng = np.random.default_rng(n_bad)
    img, layer, mask, f = random_case(rng)
    mask[:] = 0
    mask[5:15, 5:15] = 255
    out = cp.composite(img, layer, mask, f)
    outside = np.argwhere(cp.outside_region(mask, f))
    for y, x in outside[rng.choice(len(outside), n_bad, replace=False)]:
        out[y, x, int(rng.integers(3))] ^= 1                 # 한 채널 1만 바꿔도 검출
    ok, n = cp.verify_outside_unchanged(img, out, mask, f)
    assert not ok and n == n_bad
    monkeypatch.setattr(cp, "composite", lambda *a: out)    # 합성 단계가 바깥을 건드렸다고 가정
    with pytest.raises(cp.VerificationError):
        cp.composite_verified(img, layer, mask, f)


def test_empty_mask_and_shape_errors():
    img = np.full((30, 40, 3), 7, np.uint8)
    out = cp.composite(img, np.zeros_like(img), np.zeros((30, 40), np.uint8), 3)
    assert np.array_equal(out, img) and out is not img
    ok, n = cp.verify_outside_unchanged(img, img[:, :39], np.zeros((30, 40), np.uint8), 3)
    assert not ok
    with pytest.raises(ValueError):
        cp.composite(img, np.zeros((30, 39, 3), np.uint8), np.zeros((30, 40), np.uint8), 3)
    with pytest.raises(ValueError):
        cp.composite(img, np.zeros_like(img), np.zeros((10, 10), np.uint8), 3)


def test_with_real_render():
    sc = make_scene()
    s = WorkSession(sc.img, "a.jpg", mask=sc.path_wo_obj, quad=sc.quad)
    layer = rl.render_local(s, CorkPreset("natural_brown", "n", None, ["#8B5A2B"], 3.0))
    out = cp.composite_verified(sc.img, layer, s.mask, s.mask_feather_px)
    inner_obj = cv2.erode(sc.obj, np.ones((2 * s.mask_feather_px + 3,) * 2, np.uint8)) > 0
    assert np.array_equal(out[inner_obj], sc.img[inner_obj])   # 길 위 물체(제외 영역)는 원본 유지
    assert not np.array_equal(out[sc.path_wo_obj > 0], sc.img[sc.path_wo_obj > 0])
