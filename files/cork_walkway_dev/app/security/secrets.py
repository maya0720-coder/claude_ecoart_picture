"""API 키 관리 (모듈 10): Windows 자격 증명 관리자(keyring)에만 저장. 코드·설정 파일·로그에 남기지 않는다."""
from __future__ import annotations

import logging

import keyring
from keyring.errors import KeyringError, PasswordDeleteError

SERVICE = "CorkWalkway"
GEMINI_KEY = "gemini_api_key"

log = logging.getLogger("corkwalkway")


def get_key(name: str) -> str | None:
    """없거나 자격 증명 관리자를 쓸 수 없으면 None."""
    try:
        return keyring.get_password(SERVICE, name) or None
    except KeyringError as e:
        log.warning("키 읽기 실패: 오류=%s", type(e).__name__)
        return None


def set_key(name: str, value: str) -> None:
    value = (value or "").strip()
    if not value:
        raise ValueError("빈 키는 저장할 수 없습니다")
    if any(c.isspace() for c in value):
        raise ValueError("키에 공백이 들어 있습니다. 복사한 값을 확인해 주세요")
    keyring.set_password(SERVICE, name, value)


def delete_key(name: str) -> None:
    try:
        keyring.delete_password(SERVICE, name)
    except PasswordDeleteError:
        pass                                    # 이미 없음


def mask_key(value: str) -> str:
    """화면 표시용: 앞 4자리 외 ****. 4자 이하면 전부 ****."""
    if not value:
        return ""
    return (value[:4] if len(value) > 4 else "") + "****"
