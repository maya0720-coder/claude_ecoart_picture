"""설정 창 API 키 저장(모듈 08·10): 실제 Windows 자격 증명 관리자 대신 메모리 저장소로 검증."""
import keyring
import pytest
from PySide6.QtWidgets import QMessageBox

from app.security import secrets as sk
from app.ui import settings_dialog as sd
from test_secrets import MemoryKeyring

NEW_KEY = "AQ.FakeKeyForTests_abcdefghijklmnop0123"
OLD_KEY = "AQ.FakeKeyForTests_zzzzzzzzzzzzzzzzOLD9"


class SilentKeyring(MemoryKeyring):
    """저장이 조용히 무시되는 저장소(저장 확인 실패 재현)."""
    def set_password(self, service, username, password):
        pass


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    old = keyring.get_keyring()
    kr = MemoryKeyring()
    keyring.set_keyring(kr)
    shown = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: shown.append(a[2]))
    yield kr, shown
    keyring.set_keyring(old)


def test_save_new_key_replaces_old_and_confirms(qapp, env):
    kr, shown = env
    sk.set_key(sk.GEMINI_KEY, OLD_KEY)
    dlg = sd.SettingsDialog()
    assert dlg.key_state.text() == "AQ.F…OLD9"
    dlg.key_edit.setText("  " + NEW_KEY + "  ")          # 앞뒤 공백은 제거해 저장
    dlg._save()
    assert sk.get_key(sk.GEMINI_KEY) == NEW_KEY
    assert dlg.result() == dlg.DialogCode.Accepted
    assert shown and "AQ.F…0123" in shown[0] and NEW_KEY not in shown[0]   # 확인 창: 마스킹된 값만
    assert sd.SettingsDialog().key_state.text() == "AQ.F…0123"             # 다시 열면 새 키로 보임


def test_save_without_key_keeps_existing(qapp, env):
    kr, shown = env
    sk.set_key(sk.GEMINI_KEY, OLD_KEY)
    dlg = sd.SettingsDialog()
    dlg._save()
    assert sk.get_key(sk.GEMINI_KEY) == OLD_KEY and shown == []


def test_invalid_key_shows_error_and_stays_open(qapp, env):
    dlg = sd.SettingsDialog()
    dlg.key_edit.setText("AQ.abc def")
    dlg._save()
    assert "공백" in dlg.error.text() and sk.get_key(sk.GEMINI_KEY) is None
    assert dlg.result() != dlg.DialogCode.Accepted


def test_store_failure_detected_by_read_back(qapp, env):
    keyring.set_keyring(SilentKeyring())
    dlg = sd.SettingsDialog()
    dlg.key_edit.setText(NEW_KEY)
    dlg._save()
    assert "확인하지 못했습니다" in dlg.error.text()
    assert dlg.result() != dlg.DialogCode.Accepted


@pytest.mark.parametrize("answer, saved, closed", [
    (QMessageBox.StandardButton.Save, True, True),
    (QMessageBox.StandardButton.Discard, False, True),
    (QMessageBox.StandardButton.Cancel, False, False),
])
def test_cancel_with_unsaved_key_asks(qapp, env, monkeypatch, answer, saved, closed):
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: answer)
    dlg = sd.SettingsDialog()
    dlg.show()
    dlg.key_edit.setText(NEW_KEY)
    dlg.reject()
    assert (sk.get_key(sk.GEMINI_KEY) == NEW_KEY) is saved
    assert (not dlg.isVisible()) is closed
    dlg.close() if dlg.isVisible() else None


def test_cancel_without_input_closes_silently(qapp, env, monkeypatch):
    asked = []
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: asked.append(1))
    dlg = sd.SettingsDialog()
    dlg.show()
    dlg.reject()
    assert asked == [] and not dlg.isVisible()
