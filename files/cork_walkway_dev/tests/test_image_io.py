import os
import time

import cv2
import numpy as np
import pytest
from PIL import Image

from app.core import image_io as io_


def marker_rgb(w=40, h=20):
    """흰 바탕, 좌상단에 빨간 5x5 표식(RGB)."""
    a = np.full((h, w, 3), 255, np.uint8)
    a[:5, :5] = (255, 0, 0)
    return a


def is_red(px_bgr):
    b, g, r = (int(v) for v in px_bgr)
    return r > 200 and g < 80 and b < 80


@pytest.fixture
def kdir(tmp_path):
    d = tmp_path / "현장 사진"
    d.mkdir()
    return d


@pytest.mark.parametrize("ext", [".jpg", ".png"])
def test_korean_path_roundtrip(kdir, ext):
    img = np.zeros((30, 50, 3), np.uint8)
    img[:, :25] = (10, 120, 200)
    p = kdir / f"흙길{ext}"
    io_.save_image(str(p), img)
    back = io_.load_image(str(p))
    assert back.shape == img.shape and back.dtype == np.uint8
    if ext == ".png":
        assert np.array_equal(back, img)
    else:
        assert np.abs(back.astype(int) - img).mean() < 3


@pytest.mark.parametrize("orientation, red_at", [(6, (0, 19)), (8, (39, 0))])
def test_exif_rotation(kdir, orientation, red_at):
    exif = Image.Exif()
    exif[0x0112] = orientation
    p = kdir / f"회전{orientation}.jpg"
    Image.fromarray(marker_rgb()).save(p, exif=exif, quality=95)
    img = io_.load_image(str(p))
    assert img.shape == (40, 20, 3)          # 가로 40 x 세로 20 → 90도 회전
    y, x = red_at
    assert is_red(img[y, x])
    assert not is_red(img[0, 0]) or red_at == (0, 0)


def test_heic(kdir):
    p = kdir / "휴대폰.heic"
    Image.fromarray(marker_rgb(64, 48)).save(p, quality=95)
    img = io_.load_image(str(p))
    assert img.shape == (48, 64, 3)
    assert is_red(img[2, 2])


def test_16bit_and_alpha_converted(kdir):
    g16 = np.full((10, 12), 32768, np.uint16)
    p1 = kdir / "16비트흑백.png"
    cv2.imencode(".png", g16)[1].tofile(str(p1))
    a = io_.load_image(str(p1))
    assert a.dtype == np.uint8 and a.shape == (10, 12, 3)
    assert abs(int(a[0, 0, 0]) - 127) <= 1

    c16 = np.full((10, 12, 3), 65535, np.uint16)
    c16[..., 0] = 0                          # BGR: 파랑 0
    p2 = kdir / "16비트컬러.png"
    cv2.imencode(".png", c16)[1].tofile(str(p2))
    b = io_.load_image(str(p2))
    assert b.dtype == np.uint8 and b.shape == (10, 12, 3)
    assert tuple(b[0, 0]) == (0, 255, 255)

    rgba = np.zeros((10, 12, 4), np.uint8)   # 완전 투명 → 흰 배경
    rgba[:, :6] = (0, 0, 255, 255)           # 왼쪽 절반 불투명 파랑(RGB)
    p3 = kdir / "투명.png"
    Image.fromarray(rgba, "RGBA").save(p3)
    c = io_.load_image(str(p3))
    assert tuple(c[0, 0]) == (255, 0, 0)     # BGR 파랑
    assert tuple(c[0, 11]) == (255, 255, 255)


def test_strip_meta(kdir):
    exif = Image.Exif()
    exif[0x010F] = "PhoneMaker"               # 제조사
    exif[0x0132] = "2026:11:04 10:00:00"      # 촬영 시각
    gps = exif.get_ifd(0x8825)
    gps[1] = "N"
    gps[2] = (37.0, 30.0, 0.0)
    src = kdir / "원본.jpg"
    Image.fromarray(marker_rgb()).save(src, exif=exif)
    assert len(Image.open(src).getexif()) > 0

    out = kdir / "저장.jpg"
    io_.save_image(str(out), io_.load_image(str(src)), strip_meta=True)
    with Image.open(out) as im:
        assert len(im.getexif()) == 0
        assert "exif" not in im.info
    assert b"Exif" not in out.read_bytes()[:4096]


def test_load_errors(kdir):
    with pytest.raises(FileNotFoundError):
        io_.load_image(str(kdir / "없음.jpg"))
    bad = kdir / "손상.jpg"
    bad.write_bytes(b"not an image")
    with pytest.raises(io_.ImageLoadError):
        io_.load_image(str(bad))


def test_save_errors(kdir):
    img = np.zeros((4, 4, 3), np.uint8)
    with pytest.raises(ValueError):
        io_.save_image(str(kdir / "a.bmp"), img)
    with pytest.raises(ValueError):
        io_.save_image(str(kdir / "a.jpg"), img, quality=0)
    with pytest.raises(ValueError):
        io_.save_image(str(kdir / "a.png"), np.zeros((4, 4), np.uint8))
    with pytest.raises(FileNotFoundError):
        io_.save_image(str(kdir / "없는폴더" / "a.png"), img)


def test_make_preview():
    big = np.zeros((3000, 4000, 3), np.uint8)
    prev, s = io_.make_preview(big, 1600)
    assert prev.shape == (1200, 1600, 3) and s == pytest.approx(0.4)
    small = np.zeros((100, 200, 3), np.uint8)
    prev, s = io_.make_preview(small, 1600)
    assert prev is small and s == 1.0
    with pytest.raises(ValueError):
        io_.make_preview(small, 0)


def test_is_huge():
    assert not io_.is_huge(np.zeros((1, 1, 3), np.uint8))
    assert io_.is_huge(np.broadcast_to(np.zeros(3, np.uint8), (7072, 7072, 3)))


def test_qimage_to_bgr(qapp):
    from PySide6.QtGui import QColor, QImage
    q = QImage(5, 3, QImage.Format.Format_RGB32)  # 폭 5 → 줄 패딩 있는 경우 포함
    q.fill(QColor(0, 0, 0))
    q.setPixelColor(4, 2, QColor(10, 20, 30))
    a = io_.qimage_to_bgr(q)
    assert a.shape == (3, 5, 3) and a.dtype == np.uint8
    assert tuple(a[2, 4]) == (30, 20, 10)
    assert a[:2].sum() == 0
    with pytest.raises(ValueError):
        io_.qimage_to_bgr(QImage())


def test_recent_images(kdir):
    now = time.time()
    names = ["a.jpg", "b.PNG", "c.heic", "d.txt", "e.jpeg", "f.jpg", "g.jpg", "h.png"]
    for i, n in enumerate(names):
        p = kdir / n
        p.write_bytes(b"x")
        os.utime(p, (now - i, now - i))
    got = [os.path.basename(p) for p in io_.recent_images(str(kdir))]
    assert got == ["a.jpg", "b.PNG", "c.heic", "e.jpeg", "f.jpg", "g.jpg"]
    assert io_.recent_images(str(kdir / "없는폴더")) == []
