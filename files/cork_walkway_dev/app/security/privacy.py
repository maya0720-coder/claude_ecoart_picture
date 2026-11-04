"""사진 유출 방지 (모듈 10).

원칙: 현장 사진은 PC 안에서만 보관·처리한다. 외부 전송은 사용자가 켠 Gemini 고품질 모드에서,
길 주변만 잘라 메타데이터를 지운 축소본만 보낸다.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from app.config import APP_NAME, user_data_dir

ALLOWED_HOST = "generativelanguage.googleapis.com"
SEND_TARGET = "Google Gemini API"

NOTICE_CONSENT = "고객 현장 사진을 외부 AI로 보내기 전에 회사 정보보호 규정과 고객 동의 여부를 확인하십시오."
NOTICE_RETENTION = ("유료 등급에서도 Google은 정책 위반 감지를 위해 요청·응답을 일정 기간 기록할 수 있습니다. "
                    "완전한 무보관이 필요하면 Vertex AI 무보관(ZDR) 구성을 사용해야 합니다.")

log = logging.getLogger("corkwalkway")


def prepare_for_send(img: np.ndarray, mask: np.ndarray, max_px: int,
                     margin_ratio: float = 0.1) -> tuple[bytes, tuple[int, int, int, int]]:
    """(JPEG 바이트, 자른 영역 x, y, w, h). 길 주변만 잘라 긴 변 max_px 이하로 줄이고 메타데이터 없이 재인코딩.

    cv2.imencode는 EXIF·GPS·기기 정보를 쓰지 않는다(픽셀만 인코딩).
    """
    if max_px <= 0:
        raise ValueError(f"max_px는 양수여야 합니다: {max_px}")
    if mask.shape != img.shape[:2]:
        raise ValueError("마스크 크기가 사진과 다릅니다")
    x, y, w, h = crop_box(mask, margin_ratio)
    crop = img[y:y + h, x:x + w]
    s = min(1.0, max_px / max(w, h))
    if s < 1.0:
        crop = cv2.resize(crop, (max(1, round(w * s)), max(1, round(h * s))), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 92])
    if not ok:
        raise OSError("전송용 이미지 인코딩 실패")
    return buf.tobytes(), (x, y, w, h)


def crop_box(mask: np.ndarray, margin_ratio: float = 0.1) -> tuple[int, int, int, int]:
    """마스크 외접 사각형을 margin_ratio만큼 넓힌 (x, y, w, h). 사진 경계에서 자른다."""
    ys, xs = np.nonzero(mask)
    if ys.size == 0:
        raise ValueError("길 영역이 비어 있어 보낼 영역이 없습니다")
    H, W = mask.shape
    x0, x1, y0, y1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    mx, my = int((x1 - x0) * margin_ratio), int((y1 - y0) * margin_ratio)
    x0, y0 = max(0, x0 - mx), max(0, y0 - my)
    x1, y1 = min(W, x1 + mx), min(H, y1 + my)
    return int(x0), int(y0), int(x1 - x0), int(y1 - y0)


@dataclass(frozen=True)
class TransferRecord:
    time: str                   # 로컬 시각 "YYYY-MM-DD HH:MM:SS"
    target: str
    sent_size: tuple[int, int]  # 보낸 이미지 (w, h)
    region: tuple[int, int]     # 원본에서 잘라낸 영역 (w, h)
    images: int                 # 한 요청에 보낸 이미지 수


class TransferLog:
    """이번 실행의 전송 내역(메모리에만, 이미지 자체는 기록하지 않음)."""

    def __init__(self) -> None:
        self._items: list[TransferRecord] = []

    def add(self, sent_size: tuple[int, int], region: tuple[int, int], images: int = 1) -> TransferRecord:
        r = TransferRecord(time.strftime("%Y-%m-%d %H:%M:%S"), SEND_TARGET, tuple(sent_size), tuple(region), images)
        self._items.append(r)
        log.info("전송 기록: 대상=%s 보낸크기=%dx%d 영역=%dx%d 이미지=%d",
                 r.target, *r.sent_size, *r.region, r.images)
        return r

    def entries(self) -> list[TransferRecord]:
        return list(self._items)


class SendConsent:
    """전송 전 확인. "이번 실행 동안 묻지 않기"만 허용(저장하지 않으므로 다음 실행에 다시 묻는다)."""

    def __init__(self) -> None:
        self._skip = False

    def needs_confirmation(self) -> bool:
        return not self._skip

    def skip_for_this_run(self) -> None:
        self._skip = True


# ---- 임시 파일 ----
def temp_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home())
    d = Path(base) / APP_NAME / "temp"
    d.mkdir(parents=True, exist_ok=True)
    return d


def cleanup_temp() -> None:
    """임시 폴더 안의 파일·폴더를 모두 삭제(종료 시, 그리고 비정상 종료 대비 시작 시)."""
    d = temp_dir()
    for p in d.iterdir():
        try:
            if p.is_dir() and not p.is_symlink():
                shutil.rmtree(p)
            else:
                p.unlink()
        except OSError as e:
            log.warning("임시 파일 삭제 실패: 오류=%s", type(e).__name__)


# ---- 로그 ----
_B64 = re.compile(r"[A-Za-z0-9+/_-]{64,}={0,2}")
_GOOGLE_KEY = re.compile(r"AIza[0-9A-Za-z_-]{20,}")


class RedactFilter(logging.Filter):
    """로그에 base64(이미지·응답 원문)나 API 키가 섞이면 지운다. 마지막 방어선."""

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        clean = _GOOGLE_KEY.sub("[키 삭제]", _B64.sub("[데이터 생략]", msg))
        if clean != msg or record.args:
            record.msg, record.args = clean, None
        if record.exc_info:                       # 예외 메시지에 응답 원문이 섞일 수 있음 → 형식만 남김
            et = record.exc_info[0]
            record.msg = f"{record.msg} (예외: {et.__name__ if et else '알 수 없음'})"
            record.exc_info, record.exc_text = None, None
        return True


def setup_logging(level: int = logging.INFO) -> Path:
    """%APPDATA%\\CorkWalkway\\logs\\app.log. 시각·단계·소요 시간·오류 코드만 기록."""
    d = user_data_dir() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    path = d / "app.log"
    h = logging.FileHandler(path, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    h.addFilter(RedactFilter())
    log.handlers[:] = [h]
    log.setLevel(level)
    log.propagate = False
    return path
