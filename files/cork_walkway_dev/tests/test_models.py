import copy

import numpy as np
import pytest

from app.models import RenderParams, WorkSession


def make_session(**kw):
    img = np.zeros((40, 60, 3), np.uint8)
    return WorkSession(original=img, source_name="현장.jpg", **kw)


def test_create_defaults():
    s = make_session()
    assert s.mask is None and s.quad is None
    assert s.mask_feather_px == 3
    assert s.preset_id == "natural_brown"
    assert s.render_params == RenderParams()
    assert s.render_params.shading_strength == 0.8
    assert s.render_params.color_match == 0.3
    assert s.verified is False


def test_render_params_not_shared():
    a, b = make_session(), make_session()
    a.render_params.granule_scale = 2.0
    assert b.render_params.granule_scale == 1.0


def test_deepcopy_independent():
    s = make_session(mask=np.zeros((40, 60), np.uint8),
                     quad=np.zeros((4, 2), np.float32))
    c = copy.deepcopy(s)
    c.original[0, 0] = 255
    c.mask[0, 0] = 255
    c.quad[0, 0] = 1.0
    c.render_params.color_match = 1.0
    assert s.original[0, 0].sum() == 0
    assert s.mask[0, 0] == 0
    assert s.quad[0, 0] == 0
    assert s.render_params.color_match == 0.3


@pytest.mark.parametrize("kw", [
    {"mask": np.zeros((10, 10), np.uint8)},
    {"quad": np.zeros((3, 2), np.float32)},
    {"mask_feather_px": 0},
    {"mask_feather_px": 11},
])
def test_invalid_session_rejected(kw):
    with pytest.raises(ValueError):
        make_session(**kw)


@pytest.mark.parametrize("img", [
    np.zeros((40, 60), np.uint8),
    np.zeros((40, 60, 3), np.float32),
    np.zeros((40, 60, 4), np.uint8),
])
def test_invalid_original_rejected(img):
    with pytest.raises(ValueError):
        WorkSession(original=img, source_name="x.jpg")


@pytest.mark.parametrize("kw", [
    {"shading_strength": 1.5},
    {"color_match": -0.1},
    {"granule_scale": 0},
    {"edge_band_px": -1},
])
def test_invalid_render_params_rejected(kw):
    with pytest.raises(ValueError):
        RenderParams(**kw)
