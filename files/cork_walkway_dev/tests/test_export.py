import json
import re
from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import Image

from app.core import export as ex
from app.core.compositor import composite_verified
from app.core.image_io import load_image, save_image
from app.models import WorkSession
from synth import make_scene


@pytest.fixture
def session():
    sc = make_scene(600, 800)
    layer = np.zeros_like(sc.img)
    layer[:] = (40, 80, 140)
    result = composite_verified(sc.img, layer, sc.path_wo_obj, 3)
    return WorkSession(sc.img, "흙길.jpg", mask=sc.path_wo_obj, quad=sc.quad, result_local=result, verified=True)


@pytest.fixture
def kdir(tmp_path):
    d = tmp_path / "저장 폴더"
    d.mkdir()
    return d


def test_export_all_korean(qapp, session, kdir):
    paths = ex.export_result(session, str(kdir), "서울숲 산책로", preset_name="내추럴 브라운")
    names = [Path(p).name for p in paths]
    assert len(paths) == 5 and all(Path(p).is_file() for p in paths)
    assert all(n.startswith("서울숲 산책로_") for n in names)
    assert any(re.search(r"_\d{8}_\d{4}_전후비교\.jpg$", n) for n in names)
    for suffix in ("_시공후.jpg", "_예상도.pdf", "_작업설정.json", "_마스크.png"):
        assert any(n.endswith(suffix) for n in names), suffix


def test_default_site_name(qapp, session, kdir):
    p = ex.export_result(session, str(kdir), "", {"compare"})[0]
    assert Path(p).name.startswith("현장_") and Path(p).name.endswith("_전후비교.jpg")


def test_no_exif(qapp, session, kdir):
    for p in ex.export_result(session, str(kdir), "현장", {"after", "compare", "settings"}):
        if p.endswith((".jpg", ".png")):
            with Image.open(p) as im:
                assert len(im.getexif()) == 0
            assert b"Exif" not in Path(p).read_bytes()[:4096]


def test_pdf_one_page_a4_landscape(qapp, session, kdir):
    p = ex.export_result(session, str(kdir), "현장", {"pdf"}, preset_name="다크 브라운")[0]
    data = Path(p).read_bytes()
    assert data[:5] == b"%PDF-"
    pages = re.findall(rb"/Type\s*/Page(?!s)", data)
    assert len(pages) == 1
    box = re.search(rb"/MediaBox\s*\[\s*0\s+0\s+([\d.]+)\s+([\d.]+)\s*\]", data)
    w, h = float(box.group(1)), float(box.group(2))
    assert w == pytest.approx(841.9, abs=2) and h == pytest.approx(595.3, abs=2)   # A4 가로(pt)
    assert len(data) < 3_000_000                                                    # 이미지 축소 후 삽입
    assert b"/FontFile" not in data                                               # 글꼴 파일 미포함(글자는 윤곽선)


def test_never_overwrites(qapp, session, kdir):
    a = ex.export_result(session, str(kdir), "현장", {"after"})[0]
    first = Path(a).read_bytes()
    b = ex.export_result(session, str(kdir), "현장", {"after"})[0]
    assert a != b and Path(b).stem.endswith("_2")
    assert Path(a).read_bytes() == first


def test_png_without_watermark_keeps_outside_identical(qapp, session, kdir):
    p = ex.export_result(session, str(kdir), "현장", {"after"}, watermark=False, image_format="png")[0]
    saved = load_image(p)
    outside = cv2.dilate(session.mask, np.ones((9, 9), np.uint8)) == 0
    assert np.array_equal(saved[outside], session.original[outside])   # 파일 단위로도 길 밖 무변경
    assert np.array_equal(saved, session.result_local)


def test_watermark_and_logo(qapp, session, kdir, tmp_path):
    plain = ex.export_result(session, str(kdir), "현장", {"after"}, watermark=False, image_format="png")[0]
    marked = ex.export_result(session, str(kdir), "현장", {"after"}, watermark=True, image_format="png")[0]
    a, b = load_image(plain), load_image(marked)
    diff = np.any(a != b, axis=2)
    ys, xs = np.nonzero(diff)
    assert ys.size > 0 and ys.min() > a.shape[0] * 0.8                 # 고지 문구는 아래쪽에만
    logo = np.zeros((40, 80, 3), np.uint8)
    logo[:] = (0, 0, 255)
    lp = tmp_path / "로고.png"
    save_image(str(lp), logo)
    with_logo = load_image(ex.export_result(session, str(kdir), "현장", {"after"}, watermark=False,
                                            image_format="png", logo_path=str(lp))[0])
    corner = with_logo[-40:, -70:]
    assert (corner[..., 2] > 200).mean() > 0.2                         # 우측 하단 빨간 로고
    assert np.array_equal(with_logo[:300], a[:300])


def test_compare_orientation(qapp):
    land = np.zeros((300, 400, 3), np.uint8)
    out = ex.make_compare(land, land)
    assert out.shape[1] > 2 * 400 * 0.99 and out.shape[0] == 300
    port = np.zeros((400, 300, 3), np.uint8)
    out = ex.make_compare(port, port)
    assert out.shape[0] > 2 * 400 * 0.99 and out.shape[1] == 300


def test_settings_json_reproducible(qapp, session, kdir):
    session.path_width_m = 2.5
    paths = ex.export_result(session, str(kdir), "현장", {"settings"}, preset_name="컬러")
    js = json.loads(Path(next(p for p in paths if p.endswith(".json"))).read_text(encoding="utf-8"))
    assert js["preset_id"] == session.preset_id and js["preset_name"] == "컬러"
    assert js["path_width_m"] == 2.5 and js["path_width_assumed"] is False
    assert np.allclose(js["quad"], session.quad, atol=0.01)
    assert js["render_params"]["shading_strength"] == 0.8
    mask = load_image(str(kdir / js["mask_file"]))[..., 0]
    assert np.array_equal(mask > 0, session.mask > 0)


def test_errors(qapp, session, kdir):
    with pytest.raises(FileNotFoundError):
        ex.export_result(session, str(kdir / "없음"), "현장")
    with pytest.raises(ValueError):
        ex.export_result(session, str(kdir), "현장", {"gif"})
    session.verified = False
    with pytest.raises(ValueError):
        ex.export_result(session, str(kdir), "현장")


@pytest.mark.parametrize("name, safe", [
    ("", "현장"), ("   ", "현장"), ("서울:숲<1>", "서울_숲_1_"), ("CON", "현장"), ("a" * 60, "a" * 40),
    ("끝에 점.", "끝에 점"), ("탭\t문자", "탭_문자"),
])
def test_safe_site_name(name, safe):
    assert ex.safe_site_name(name) == safe
