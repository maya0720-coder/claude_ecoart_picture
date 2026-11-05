"""전·후 비교 화면(모듈 08): 결과가 없을 때 원본에 '시공 후' 표시를 하지 않는다."""
import numpy as np

from app.ui.compare_view import CompareView


def center_rgb(view):
    img = view.grab().toImage()
    c = img.pixelColor(img.width() // 2, img.height() // 2)
    return c.red(), c.green(), c.blue()


def test_before_only_has_no_slider(qapp):
    v = CompareView()
    v.resize(400, 300)
    red = np.zeros((300, 400, 3), np.uint8)
    red[..., 2] = 200                                   # BGR 빨강
    v.set_images(red, None)
    r, g, b = center_rgb(v)
    assert r > 150 and g < 60 and b < 60                # 가운데에 흰 슬라이더 선·손잡이 없음 = 원본만 표시


def test_with_result_shows_slider(qapp):
    v = CompareView()
    v.resize(400, 300)
    red = np.zeros((300, 400, 3), np.uint8)
    red[..., 2] = 200
    v.set_images(red, red.copy())
    r, g, b = center_rgb(v)
    assert min(r, g, b) > 200                           # 가운데 흰 손잡이


def test_keyboard_moves_slider_only_with_result(qapp):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    v = CompareView()
    v.resize(400, 300)
    img = np.zeros((300, 400, 3), np.uint8)
    v.set_images(img, None)
    QTest.keyClick(v, Qt.Key.Key_Right)
    assert v.split == 0.5                               # 결과 없으면 움직이지 않음
    v.set_images(img, img.copy())
    QTest.keyClick(v, Qt.Key.Key_Right)
    assert abs(v.split - 0.55) < 1e-9
    for _ in range(30):
        QTest.keyClick(v, Qt.Key.Key_Left)
    assert v.split == 0.0
    v.set_mode("toggle")
    QTest.keyClick(v, Qt.Key.Key_Space)
    assert v.show_after is False
