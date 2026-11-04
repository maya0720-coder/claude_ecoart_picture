import keyring
import pytest
from keyring.backend import KeyringBackend
from keyring.errors import KeyringError, PasswordDeleteError

from app.security import secrets as sk


class MemoryKeyring(KeyringBackend):
    """테스트용: 실제 Windows 자격 증명 관리자를 건드리지 않음."""
    priority = 1

    def __init__(self):
        self.store = {}

    def get_password(self, service, username):
        return self.store.get((service, username))

    def set_password(self, service, username, password):
        self.store[(service, username)] = password

    def delete_password(self, service, username):
        if (service, username) not in self.store:
            raise PasswordDeleteError()
        del self.store[(service, username)]


class BrokenKeyring(MemoryKeyring):
    def get_password(self, service, username):
        raise KeyringError("locked")


@pytest.fixture
def mem():
    old = keyring.get_keyring()
    kr = MemoryKeyring()
    keyring.set_keyring(kr)
    yield kr
    keyring.set_keyring(old)


def test_roundtrip(mem):
    assert sk.get_key(sk.GEMINI_KEY) is None
    sk.set_key(sk.GEMINI_KEY, "  AIzaTESTKEY123456  ")
    assert sk.get_key(sk.GEMINI_KEY) == "AIzaTESTKEY123456"
    assert mem.store == {(sk.SERVICE, sk.GEMINI_KEY): "AIzaTESTKEY123456"}
    sk.delete_key(sk.GEMINI_KEY)
    assert sk.get_key(sk.GEMINI_KEY) is None
    sk.delete_key(sk.GEMINI_KEY)                    # 없어도 오류 없음


def test_set_key_validation(mem):
    for bad in ("", "   ", "abc def"):
        with pytest.raises(ValueError):
            sk.set_key(sk.GEMINI_KEY, bad)


def test_keyring_error_returns_none():
    old = keyring.get_keyring()
    keyring.set_keyring(BrokenKeyring())
    try:
        assert sk.get_key(sk.GEMINI_KEY) is None
    finally:
        keyring.set_keyring(old)


def test_windows_credential_manager_available():
    # 이 파일의 가짜 백엔드 클래스도 keyring 후보로 자동 등록되므로, 기본 백엔드 대신 후보 목록을 확인한다.
    import sys
    from keyring.backend import get_all_keyring
    if sys.platform == "win32":
        assert "WinVaultKeyring" in [type(k).__name__ for k in get_all_keyring()]


@pytest.mark.parametrize("value, shown", [
    ("AIzaSyD-abcdefghijk", "AIza****"),
    ("abcde", "abcd****"),
    ("abcd", "****"),
    ("a", "****"),
    ("", ""),
])
def test_mask_key(value, shown):
    assert sk.mask_key(value) == shown
