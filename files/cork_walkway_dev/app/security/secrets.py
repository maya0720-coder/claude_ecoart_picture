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


MASK_EDGE = 4               # 앞·뒤로 보여 줄 글자 수(키를 바꿨는지 구분하는 용도, 가운데는 가림)
MASK_MIN_LEN_FOR_TAIL = 16  # 이보다 짧으면 뒤 글자는 보이지 않음(가려진 부분이 너무 짧아지지 않게)


def mask_key(value: str) -> str:
    """화면 표시용: 앞 4자리…뒤 4자리. 새 형식 키(AQ.…)는 앞부분이 모두 같아 뒤 4자리로 구분한다.

    16자 미만이면 앞 4자리 + ****, 4자 이하면 전부 ****.
    """
    if not value:
        return ""
    if len(value) >= MASK_MIN_LEN_FOR_TAIL:
        return f"{value[:MASK_EDGE]}…{value[-MASK_EDGE:]}"
    return (value[:MASK_EDGE] if len(value) > MASK_EDGE else "") + "****"
