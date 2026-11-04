"""화면(모듈 08) 통합 테스트: 실제 MainWindow를 화면 없이(offscreen) 조작."""
import time
from pathlib import Path

import numpy as np
import pytest
from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QAbstractButton, QFileDialog

from app.config import load_config
from app.core.image_io import save_image
from app.core.segmentation import PathSegmenter
from app.ui.main_window import MainWindow
from synth import iou, make_scene

ROOT = Path(__file__).resolve().parent.parent
HAS_MODEL = (ROOT / "models" / "mobile_sam_image_encoder.onnx").is_file()


def wait_until(app, cond, timeout=60.0):
    end = time.perf_counter() + timeout
    while time.perf_counter() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    raise AssertionError("시간 초과")


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    return tmp_path


@pytest.fixture
def win(qapp, env):
    w = MainWindow(load_config())
    w.show()
    wait_until(qapp, lambda: w.segmenter is not None)
    yield w
    w.close()
    w.runner.wait(30000)
    qapp.processEvents()


def click(widget, pos=None):
    QTest.mouseClick(widget, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, pos or widget.rect().center())


def tap_orig(canvas, x, y, button=Qt.MouseButton.LeftButton):
    p = canvas.to_widget(x, y)
    QTest.mouseClick(canvas, button, Qt.KeyboardModifier.NoModifier, QPoint(int(p.x()), int(p.y())))


def load_scene(qapp, w, sc):
    w.set_session(sc.img, "테스트.jpg")
    if w._model_ok():
        wait_until(qapp, lambda: w.enc_ready)


@pytest.mark.skipif(not HAS_MODEL, reason="SAM 모델 없음")
def test_open_to_save_within_7_clicks(qapp, win, env, monkeypatch):
    sc = make_scene(900, 1200)
    photo_dir = env / "현장 사진"
    photo_dir.mkdir()
    photo = photo_dir / "흙길.jpg"
    save_image(str(photo), sc.img)
    out_dir = env / "결과"
    out_dir.mkdir()
    clicks = {"n": 0}

    def pick_file(*a, **k):
        clicks["n"] += 1
        return str(photo), ""

    def pick_dir(*a, **k):
        clicks["n"] += 1
        return str(out_dir)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", pick_file)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", pick_dir)

    def user_click(widget, pos=None):
        clicks["n"] += 1
        click(widget, pos)

    user_click(win.btn_open)                                            # 1 사진 열기 (+1 파일 선택)
    wait_until(qapp, lambda: win.step == 2 and win.enc_ready)
    p = win.canvas.to_widget(*sc.road_pt)
    user_click(win.canvas, QPoint(int(p.x()), int(p.y())))              # 3 길 터치
    wait_until(qapp, lambda: win.session.mask is not None and win.session.mask.any())
    assert iou(win.session.mask, sc.path_wo_obj) > 0.8
    user_click(win.btn_next2)                                           # 4 다음
    assert win.step == 3 and win.session.quad is not None
    user_click(win.btn_next3)                                           # 5 결과 보기
    assert win.step == 4
    wait_until(qapp, lambda: win.session.preset_id in win.previews)
    user_click(win.btn_save)                                            # 6 저장 (+1 폴더 선택)
    wait_until(qapp, lambda: bool(win.last_saved))
    assert clicks["n"] <= 7, clicks
    saved = Path(win.last_saved[0])
    assert saved.is_file() and saved.parent == out_dir
    assert win.session.verified
    assert photo.read_bytes() == (photo_dir / "흙길.jpg").read_bytes()  # 원본 그대로


def _all_buttons_inside(w):
    bad = []
    for b in w.findChildren(QAbstractButton):
        if not b.isVisible():
            continue
        top_left = b.mapTo(w, QPoint(0, 0))
        r = b.rect().translated(top_left)
        if not w.rect().contains(r):
            bad.append((b.text(), r))
    return bad


@pytest.mark.parametrize("size", [(1366, 768), (800, 1280)])
def test_buttons_not_clipped(qapp, win, size):
    sc = make_scene(600, 800)
    load_scene(qapp, win, sc)
    win.session.mask = sc.path_wo_obj.copy()
    win._sync_step_buttons()
    win.adv.setChecked(True)                                             # 고급 설정 펼친 상태도 확인
    for step in (1, 2, 3, 4):
        win.go_step(step)
        win.resize(*size)
        qapp.processEvents()
        win.runner.wait(60000)
        qapp.processEvents()
        assert win.minimumSizeHint().width() <= size[0] and win.minimumSizeHint().height() <= size[1], (step, win.minimumSizeHint())
        assert win.width() <= size[0] and win.height() <= size[1]
        assert _all_buttons_inside(win) == [], (step, _all_buttons_inside(win))
        for b in win.pages[step - 1].findChildren(QAbstractButton):
            if b.isVisible() and b.minimumHeight() > 0:
                assert b.height() >= 48, (step, b.text(), b.height())


def test_ui_responsive_during_heavy_work(qapp, win):
    sc = make_scene(3000, 4000)                                          # 12MP
    load_scene(qapp, win, sc)
    win.session.mask = sc.path_wo_obj.copy()
    win.session.quad = sc.quad
    win.go_step(4)
    ticks, gaps, last = [], [], [time.perf_counter()]

    def tick():
        now = time.perf_counter()
        gaps.append(now - last[0])
        last[0] = now
        ticks.append(now)
    t = QTimer()
    t.timeout.connect(tick)
    t.start(20)
    done = {}
    win._full_result(lambda out: done.update(out=out))
    for i in range(20):                                                  # 작업 중 창 크기 변경
        win.resize(1000 + i * 10, 700)
        qapp.processEvents()
    wait_until(qapp, lambda: "out" in done, timeout=120)
    win.runner.wait(60000)
    t.stop()
    assert done["out"].shape == sc.img.shape
    assert len(ticks) > 20
    assert max(gaps) < 0.5, max(gaps)                                    # 화면이 0.5초 넘게 멈추지 않음


@pytest.mark.skipif(not HAS_MODEL, reason="SAM 모델 없음")
def test_points_brush_undo(qapp, win):
    sc = make_scene(600, 800)
    load_scene(qapp, win, sc)
    tap_orig(win.canvas, *sc.road_pt)
    wait_until(qapp, lambda: win.session.mask is not None and win.session.mask.any())
    base = win.session.mask.copy()
    win.set_tool("brush")
    win.on_stroke([(50, 50), (120, 50)], 10, True)                       # 길 밖에 칠하기
    wait_until(qapp, lambda: win.session.mask[50, 80] > 0)
    win.set_tool("point")                                                # 점을 추가해도 브러시 기록은 유지
    tap_orig(win.canvas, *sc.far_pt)
    wait_until(qapp, lambda: len(win.pos) == 2 and not win.runner.busy("mask"))
    assert win.session.mask[50, 80] > 0
    win.undo()                                                           # 점 취소
    win.undo()                                                           # 브러시 취소
    wait_until(qapp, lambda: not win.runner.busy("mask") and win.session.mask[50, 80] == 0)
    assert np.array_equal(win.session.mask, base)
    tap_orig(win.canvas, *sc.obj_pt, button=Qt.MouseButton.RightButton)  # 오른쪽 클릭 = 제외 점
    wait_until(qapp, lambda: len(win.neg) == 1)


def test_no_model_brush_only(qapp, env):
    w = MainWindow(load_config(), segmenter=PathSegmenter(str(env / "없음")))
    w.show()
    sc = make_scene(600, 800)
    w.set_session(sc.img, "a.jpg")
    assert w.canvas.mode == "brush" and "브러시" in w.guide.text()
    w.on_point(10, 10, True)
    assert w.banner.isVisible() and w.pos == []
    w.on_stroke([(400, 500), (400, 560)], 40, True)
    wait_until(qapp, lambda: w.session.mask is not None and w.session.mask.any())
    w.go_step(3)
    assert w.step == 3 and w.session.quad is not None
    w.close()
    w.runner.wait(30000)


def test_quad_invalid_keeps_previous(qapp, win):
    sc = make_scene(600, 800)
    load_scene(qapp, win, sc)
    win.session.mask = sc.path_wo_obj.copy()
    win.go_step(3)
    before = win.session.quad.copy()
    twisted = before[[0, 1, 3, 2]]
    win.on_quad_changed(twisted)
    assert win.banner.isVisible() and "꼬였" in win.banner.text()
    assert np.array_equal(win.session.quad, before)
    moved = before.copy()
    moved[0, 0] -= 20
    win.on_quad_changed(moved)
    assert np.allclose(win.session.quad, moved)


def test_presentation_and_preset_switch_cached(qapp, win):
    sc = make_scene(900, 1200)
    load_scene(qapp, win, sc)
    win.session.mask = sc.path_wo_obj.copy()
    win.go_step(4)
    assert not win.btn_hq.isEnabled() and win.btn_hq.toolTip()          # 고품질: 꺼짐 사유 표시
    ids = [p.id for p in win.presets]
    wait_until(qapp, lambda: all(i in win.previews for i in ids), timeout=120)   # 뒤에서 미리 만들기
    win.start_presentation()
    pres = win.presentation
    assert pres is not None and pres.isFullScreen()
    t0 = time.perf_counter()
    click(pres.chips.buttons[ids[1]])
    assert win.session.preset_id == ids[1]
    assert time.perf_counter() - t0 < 2.0                                # 캐시로 즉시 전환
    assert pres.view.notice_visible
    QTest.keyClick(pres, Qt.Key.Key_Escape)                              # ESC로 종료
    qapp.processEvents()
    assert win.presentation is None
    win.start_presentation()
    click(win.presentation.btn_close)                                    # 모서리 버튼으로 종료
    qapp.processEvents()
    assert win.presentation is None


def test_polygon_tool_and_redo(qapp, env):
    w = MainWindow(load_config(), segmenter=PathSegmenter(str(env / "없음")))
    w.show()
    sc = make_scene(600, 800)
    w.set_session(sc.img, "a.jpg")
    w.set_tool("polygon")
    assert w.btn_poly_done.isVisible()
    for x, y in sc.quad:                                                 # 길 네 모서리 찍기
        tap_orig(w.canvas, float(x), float(y))
    click(w.btn_poly_done)
    wait_until(qapp, lambda: w.session.mask is not None and w.session.mask.any())
    assert iou(w.session.mask, sc.path) > 0.9
    w.undo()
    wait_until(qapp, lambda: not w.session.mask.any())
    w.redo()
    wait_until(qapp, lambda: w.session.mask.any())
    assert iou(w.session.mask, sc.path) > 0.9
    w.on_stroke([(10, 10)], 5, True)                                     # 새 작업 → 다시 실행 기록 삭제
    assert w.redo_stack == []
    w.close()
    w.runner.wait(30000)
