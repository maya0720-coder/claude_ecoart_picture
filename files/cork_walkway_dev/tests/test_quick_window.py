"""간편 모드 화면(모듈 08): 사진만 올리면 자동 변환 → 비교 → 저장. 가짜 Gemini 서버로 오프라인 검증."""
import time
from pathlib import Path

import pytest

from app.config import load_config
from app.ui.quick_window import QuickWindow
from synth import make_scene
from test_gemini_convert import FakeGemini, converter


def wait_until(app, cond, timeout=30.0):
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


def test_auto_flow_compare_and_save(qapp, env):
    sc = make_scene(900, 1200)
    fake = FakeGemini(sc.path)
    win = QuickWindow(load_config(), converter=converter(fake))
    assert win.view_stack.currentWidget() is win.home and not win.bottom.isVisibleTo(win)
    win.set_session(sc.img, "현장.jpg")                       # 사진만 올리면 바로 변환(사용자 조작 없음)
    wait_until(qapp, lambda: win.session.verified)
    assert len(fake.requests) == 1
    assert win.view_stack.currentWidget() is win.compare
    assert win.bottom.isVisibleTo(win) and win.btn_save.isEnabled()
    assert len(win.transfer_log.entries()) == 1               # 화면의 전송 내역 = 실제 전송 기록
    win._set_mode("side")
    assert win.compare.mode == "side" and win.mode_btns["side"].isChecked()

    out = env / "저장 폴더"
    out.mkdir()
    win.settings["output_folder"] = str(out)
    win.site_name.setText("테스트 현장")
    win.save()
    wait_until(qapp, lambda: bool(win.last_saved))
    names = [Path(p).name for p in win.last_saved]
    assert any("시공후" in n for n in names) and any("전후비교" in n for n in names)
    win.close()


def test_failure_shows_reason_and_retry(qapp, env):
    sc = make_scene(600, 800)
    fake = FakeGemini(sc.path, "free")
    win = QuickWindow(load_config(), converter=converter(fake))
    win.set_session(sc.img, "a.jpg")
    wait_until(qapp, lambda: win._busy_kind is None and len(fake.requests) == 1)
    assert "무료 등급" in win.banner.text() and not win.btn_save.isEnabled()
    fake.mode = "ok"                                          # 결제 연결 후 [다시 만들기]
    win.start_convert()
    wait_until(qapp, lambda: win.session.verified)
    assert len(fake.requests) == 2
    win.close()


def test_unavailable_sends_nothing(qapp, env):
    sc = make_scene(600, 800)
    fake = FakeGemini(sc.path)
    win = QuickWindow(load_config(), converter=converter(fake, settings={}))
    win.set_session(sc.img, "a.jpg")
    assert "할 수 없습니다" in win.banner.text() and "[설정]" in win.banner.text()
    assert fake.requests == [] and not win.btn_save.isEnabled()
    win.close()


def test_consent_cancel_sends_nothing(qapp, env, monkeypatch):
    from app.ui import quick_window as qw
    monkeypatch.setattr(qw.SendConfirmDialog, "exec", lambda self: 0)   # [취소]
    sc = make_scene(600, 800)
    fake = FakeGemini(sc.path)
    win = QuickWindow(load_config(), converter=converter(fake, confirmed=False))
    win.set_session(sc.img, "a.jpg")
    assert fake.requests == [] and "취소" in win.banner.text()
    win.close()


def test_note_and_custom_material_flow(qapp, env, monkeypatch):
    import json

    import cv2
    import numpy as np

    from app.core.materials import list_custom
    from app.ui import quick_window as qw
    sc = make_scene(600, 800)
    fake = FakeGemini(sc.path)
    win = QuickWindow(load_config(), converter=converter(fake))
    assert win.material_panel.current_id() == win.presets[0].id          # 기본 = 코르크
    assert not win.material_panel.btn_remove.isEnabled()                  # 기본 소재는 삭제 불가

    src = env / "샘플.png"
    cv2.imencode(".png", np.full((200, 300, 3), 90, np.uint8))[1].tofile(str(src))

    class FakeDialog:
        def __init__(self, *a, **k):
            self.path = str(src)
            self.name = type("N", (), {"text": lambda _s: "화강석"})()

        def exec(self):
            return qw.QDialog.DialogCode.Accepted
    monkeypatch.setattr(qw, "AddMaterialDialog", FakeDialog)
    win.add_material()
    wait_until(qapp, lambda: win._busy_kind is None and len(list_custom()) == 1)
    mat = list_custom()[0]
    assert win.material_panel.current_id() == mat.id and win.material_panel.btn_remove.isEnabled()

    win.note_panel.edit.setPlainText("경계석은 유지" + "가" * 500)
    assert len(win.note_panel.text()) == 300                             # 입력 칸에서 글자 수 제한
    win.set_session(sc.img, "a.jpg")
    wait_until(qapp, lambda: win.session.verified)
    parts = json.loads(fake.requests[0].content)["contents"][0]["parts"]
    assert len(parts) == 3 and "경계석은 유지" in parts[0]["text"] and "Image 2" in parts[0]["text"]
    assert win.btn_convert.text() == "다시 만들기"

    monkeypatch.setattr(qw.QMessageBox, "question", lambda *a, **k: qw.QMessageBox.StandardButton.Yes)
    win.remove_material(mat.id)
    assert list_custom() == [] and win.material_panel.current_id() == win.presets[0].id
    win.remove_material(win.presets[0].id)                                # 기본 소재는 무시
    assert win.presets[0].id in win.material_by_id
    win.close()


def test_add_material_rejects_bad_file(qapp, env, monkeypatch):
    from app.ui import quick_window as qw
    bad = env / "bad.jpg"
    bad.write_bytes(b"nope")

    class FakeDialog:
        def __init__(self, *a, **k):
            self.path = str(bad)
            self.name = type("N", (), {"text": lambda _s: "x"})()

        def exec(self):
            return qw.QDialog.DialogCode.Accepted
    monkeypatch.setattr(qw, "AddMaterialDialog", FakeDialog)
    win = QuickWindow(load_config(), converter=converter(FakeGemini(make_scene(300, 400).path)))
    win.add_material()
    wait_until(qapp, lambda: win._busy_kind is None)
    assert "추가하지 못했습니다" in win.banner.text() and "읽을 수 없는" in win.banner.text()
    win.close()


def test_title_icon_and_min_size(qapp, env):
    from PIL import Image

    from app.config import resolve_resource
    win = QuickWindow(load_config(), converter=converter(FakeGemini(make_scene(300, 400).path)))
    assert win.windowTitle() == "시공 시뮬레이터"
    assert win.minimumWidth() >= 800 and win.minimumHeight() >= 600
    with Image.open(resolve_resource("assets/app.ico")) as ico:
        assert {(16, 16), (32, 32), (256, 256)} <= set(ico.info["sizes"])
    assert resolve_resource("assets/app.png").is_file()
    win.close()


def test_sidebar_resizable_and_remembered(qapp, env):
    from app.config import load_user_settings
    from app.ui import quick_window as qw
    win = QuickWindow(load_config(), converter=converter(FakeGemini(make_scene(300, 400).path)))
    win.resize(1300, 800)
    win.show()
    qapp.processEvents()
    win.splitter.moveSplitter(450, 1)
    qapp.processEvents()
    assert abs(win.sidebar_width() - 450) <= 2
    win.splitter.moveSplitter(5000, 1)                                 # 범위를 넘겨도 오른쪽 화면이 사라지지 않음
    qapp.processEvents()
    assert win.sidebar_width() <= qw.SIDEBAR_MAX
    win.splitter.moveSplitter(450, 1)
    qapp.processEvents()
    win.close()
    assert abs(load_user_settings()["sidebar_width"] - 450) <= 2       # 다음 실행에도 유지
    win2 = QuickWindow(load_config(), converter=converter(FakeGemini(make_scene(300, 400).path)))
    win2.resize(1300, 800)
    win2.show()
    qapp.processEvents()
    assert abs(win2.sidebar_width() - 450) <= 2
    win2.close()


def test_long_file_name_does_not_push_sidebar(qapp, env):
    """띄어쓰기 없는 긴 파일 이름이 왼쪽 메뉴를 밀어내 화면이 잘리던 문제."""
    from app.ui import quick_window as qw
    sc = make_scene(300, 400)
    win = QuickWindow(load_config(), converter=converter(FakeGemini(sc.path), settings={}))
    win.resize(*qw.WINDOW_MIN)
    win.show()
    long = "코코넛매트_시공_야자매트_설치_산책로_흙길_표면_정리_" * 4 + "(151).jpg"
    win.set_session(sc.img, long)
    qapp.processEvents()
    scroll = win.splitter.widget(0).findChild(qw.QScrollArea)
    panel = scroll.widget()
    assert panel.width() <= scroll.viewport().width()                  # 가로로 넘치지 않음(잘림 없음)
    assert scroll.horizontalScrollBar().maximum() == 0
    assert win.file_label.full_text().startswith(long) and "…" in win.file_label.text()
    assert win.file_label.toolTip().startswith(long)
    for b in (win.btn_open, win.material_panel.btn_add, win.material_panel.btn_remove, win.btn_convert):
        assert b.geometry().right() <= b.parentWidget().width()       # 버튼이 오른쪽으로 잘리지 않음
    win.close()


def test_debris_checkbox_saved_and_sent(qapp, env):
    import json

    from app.config import load_user_settings
    sc = make_scene(600, 800)
    fake = FakeGemini(sc.path)
    win = QuickWindow(load_config(), converter=converter(fake))
    assert win.chk_debris.isChecked()                                   # 기본: 정리
    win.chk_debris.setChecked(False)
    assert load_user_settings()["clear_debris"] is False
    win.set_session(sc.img, "a.jpg")
    wait_until(qapp, lambda: win.session.verified)
    assert "branches" not in json.loads(fake.requests[0].content)["contents"][0]["parts"][0]["text"]
    win.close()


def test_bottom_bar_fits_at_min_size(qapp, env):
    from app.ui import quick_window as qw
    sc = make_scene(300, 400)
    win = QuickWindow(load_config(), converter=converter(FakeGemini(sc.path)))
    win.resize(*qw.WINDOW_MIN)
    win.show()
    win.set_session(sc.img, "a.jpg")
    wait_until(qapp, lambda: win.session.verified)
    qapp.processEvents()
    for b in win.mode_btns.values():
        assert b.width() >= b.sizeHint().width()                      # 비교 방식 글자 잘림 없음
    assert win.btn_save.geometry().right() <= win.bottom.width()
    assert win.site_name.width() >= 120
    win.close()


def test_edge_checkbox_default_saved_and_sent(qapp, env):
    import json

    from app.config import load_user_settings
    sc = make_scene(600, 800)
    fake = FakeGemini(sc.path)
    win = QuickWindow(load_config(), converter=converter(fake))
    assert win.chk_edge.isChecked()                                     # 기본: 마감재 시공
    win.set_session(sc.img, "a.jpg")
    wait_until(qapp, lambda: win.session.verified)
    assert "edging" in json.loads(fake.requests[0].content)["contents"][0]["parts"][0]["text"]
    win.chk_edge.setChecked(False)
    assert load_user_settings()["edge_finish"] is False and "[다시 만들기]" in win.banner.text()
    win.close()
    win2 = QuickWindow(load_config(), converter=converter(fake))
    assert not win2.chk_edge.isChecked()                                # 선택 유지
    win2.close()


def test_file_name_and_size_shown_separately(qapp, env):
    sc = make_scene(300, 400)
    win = QuickWindow(load_config(), converter=converter(FakeGemini(sc.path), settings={}))
    win.resize(1200, 800)
    win.show()
    name = "청주 코코넛매트 시공 야자매트 설치 산책로 흙길 표면 정리_(151).jpg"
    win.set_session(sc.img, name)
    qapp.processEvents()
    assert win.size_label.text() == "400 × 300 px" and win.size_label.isVisible()
    shown = win.file_label.text()
    assert "px" not in shown and (shown == name or (shown.endswith(".jpg") and "…" in shown))
    win.close()


@pytest.mark.parametrize("avail, small", [((1280, 752), True), ((800, 1232), True), ((2560, 1400), False)])
def test_fits_tablet_screens(qapp, env, avail, small):
    win = QuickWindow(load_config(), converter=converter(FakeGemini(make_scene(300, 400).path)))
    assert win.fit_to_screen(avail) is small
    assert win.minimumWidth() <= avail[0] and win.minimumHeight() <= avail[1]
    win.close()
