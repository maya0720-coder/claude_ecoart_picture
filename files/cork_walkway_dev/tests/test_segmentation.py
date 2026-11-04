import shutil
from pathlib import Path

import numpy as np
import pytest

from app.core import segmentation as seg
from synth import iou, make_scene

MODELS = Path(__file__).resolve().parent.parent / "models"
HAS_MODEL = (MODELS / seg.DEFAULT_ENCODER).is_file() and (MODELS / seg.DEFAULT_DECODER).is_file()
needs_model = pytest.mark.skipif(not HAS_MODEL, reason="models/에 SAM ONNX 모델 없음")


# ---- 모델 없음 ----
def test_no_model(tmp_path):
    s = seg.PathSegmenter(str(tmp_path / "없는폴더"))
    assert not s.available()
    assert "모델이 없습니다" in s.reason
    with pytest.raises(RuntimeError):
        s.set_image(np.zeros((10, 10, 3), np.uint8))


def test_broken_model_in_korean_dir(tmp_path):
    d = tmp_path / "모델 폴더"
    d.mkdir()
    (d / seg.DEFAULT_ENCODER).write_bytes(b"broken")
    (d / seg.DEFAULT_DECODER).write_bytes(b"broken")
    s = seg.PathSegmenter(str(d))
    assert not s.available()
    assert "불러오지 못했습니다" in s.reason


@needs_model
def test_wrong_model_format(tmp_path):
    shutil.copy(MODELS / seg.DEFAULT_DECODER, tmp_path / seg.DEFAULT_ENCODER)  # 인코더 자리에 디코더
    shutil.copy(MODELS / seg.DEFAULT_DECODER, tmp_path / seg.DEFAULT_DECODER)
    s = seg.PathSegmenter(str(tmp_path))
    assert not s.available() and "인코더" in s.reason


# ---- 모델 있음 ----
@pytest.fixture(scope="module")
def ready():
    sc = make_scene()
    s = seg.PathSegmenter(str(MODELS))
    assert s.available(), s.reason
    s.set_image(sc.img)
    return s, sc


@needs_model
def test_one_point_iou(ready):
    s, sc = ready
    m = s.predict([sc.road_pt], [])
    assert m.shape == sc.path.shape and m.dtype == np.uint8
    assert set(np.unique(m)) <= {0, 255}
    assert iou(m, sc.path_wo_obj) >= 0.8


@needs_model
def test_negative_point_excludes_object(ready):
    # 포함 점 1개 + 제외 점 1개만으로는 길 일부가 빠질 수 있어(모델 특성) 포함 점 2개로 지정
    s, sc = ready
    m = s.predict([sc.road_pt, sc.far_pt], [sc.obj_pt])
    covered = (m > 0)[sc.obj > 0].mean()
    assert covered < 0.1
    assert iou(m, sc.path_wo_obj) >= 0.8


@needs_model
def test_predict_input_checks(ready):
    s, sc = ready
    assert s.predict([], [sc.obj_pt]).max() == 0
    with pytest.raises(ValueError):
        s.predict([(-1, 5)], [])
    with pytest.raises(ValueError):
        s.predict([(sc.img.shape[1], 5)], [])
    fresh = seg.PathSegmenter(str(MODELS))
    with pytest.raises(RuntimeError):
        fresh.predict([sc.road_pt], [])


# ---- 후처리 ----
def test_clean_mask():
    m = np.zeros((200, 200), np.uint8)
    m[20:180, 20:180] = 255
    m[50:53, 50:53] = 0          # 작은 구멍 → 채움
    m[100:104, 100:104] = 0      # 제외 점이 있는 작은 구멍 → 유지
    m[30:120, 130:170] = 0       # 큰 구멍 → 유지
    m[190:193, 5:8] = 255        # 작은 조각 → 제거
    m[0:3, 195:200] = 0
    out = seg.clean_mask(m, 0.002, keep_pts=[(101, 101)])
    assert out.dtype == np.uint8 and set(np.unique(out)) <= {0, 255}
    assert out[51, 51] == 255
    assert out[101, 101] == 0
    assert out[60, 150] == 0
    assert out[191, 6] == 0
    assert out[100, 50] == 255


def test_clean_mask_border_hole_not_filled():
    m = np.full((100, 100), 255, np.uint8)
    m[0:2, 40:42] = 0             # 테두리에 닿은 빈 곳은 구멍이 아님
    out = seg.clean_mask(m, 0.01)
    assert out[0, 40] == 0


@pytest.mark.parametrize("px", [1, 3, 10])
def test_feather_alpha(px):
    m = np.zeros((120, 120), np.uint8)
    m[30:90, 30:90] = 255
    a = seg.feather_alpha(m, px)
    assert a.dtype == np.float32 and a.min() >= 0 and a.max() <= 1
    import cv2
    d_out = cv2.distanceTransform((m == 0).astype(np.uint8), cv2.DIST_L2, 5)
    assert np.all(a[d_out >= px] == 0.0)          # 마스크 밖 px 이상: 정확히 0
    assert a[60, 60] == 1.0
    if px == 1:
        assert np.array_equal(a > 0, m > 0)
    with pytest.raises(ValueError):
        seg.feather_alpha(m, 0)


# ---- 수동 보정 ----
def test_editor_brush_erase_polygon_undo_redo():
    e = seg.MaskEditor((100, 100))
    e.brush([(10, 10), (50, 10)], radius=3)
    assert e.mask[10, 30] == 255 and e.mask[10, 54] == 0 and e.mask[20, 30] == 0
    e.brush([(30, 10)], radius=2, add=False)
    assert e.mask[10, 30] == 0 and e.mask[10, 40] == 255
    e.polygon([(60, 60), (90, 60), (90, 90)])
    assert e.mask[70, 85] == 255
    e.polygon([(60, 60), (90, 60), (90, 90)], add=False)
    assert e.mask[70, 85] == 0

    assert e.undo() and e.mask[70, 85] == 255
    assert e.undo() and e.mask[70, 85] == 0
    assert e.undo() and e.mask[10, 30] == 255
    assert e.redo() and e.mask[10, 30] == 0
    e.brush([(5, 90)], radius=2)               # 새 작업 → 다시 실행 기록 삭제
    assert not e.can_redo()


def test_editor_undo_limit_and_set_mask():
    e = seg.MaskEditor((50, 50))
    for i in range(25):
        e.brush([(i * 2, 25)], radius=1)
    n = 0
    while e.undo():
        n += 1
    assert n == seg.UNDO_STEPS
    full = np.full((50, 50), 255, np.uint8)
    e.set_mask(full)
    assert e.mask.min() == 255
    e.undo()
    assert e.mask[0, 0] == 0
    with pytest.raises(ValueError):
        e.set_mask(np.zeros((10, 10), np.uint8))
    with pytest.raises(ValueError):
        e.polygon([(1, 1), (2, 2)])
    with pytest.raises(ValueError):
        e.brush([], radius=3)
