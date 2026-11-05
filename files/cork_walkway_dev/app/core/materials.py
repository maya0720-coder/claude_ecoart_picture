"""사용자 추가 소재(모듈 04 확장): 다른 바닥재 샘플 사진을 등록해 Gemini 변환에 쓴다.

기본 소재는 코르크 프리셋(materials/cork/presets.yaml)이고, 여기서는 사용자가 추가한 소재만 다룬다.
저장 위치: %APPDATA%\\CorkWalkway\\materials\\<id>\\(reference.jpg, meta.json)
- 샘플 사진은 원본을 복사하지 않고 긴 변 SAMPLE_MAX_PX로 줄여 메타데이터(EXIF·GPS) 없이 다시 저장한다.
- id는 프로그램이 만든 것(custom_ + 16진 8자리)만 인정한다. 폴더 이름·삭제 대상은 이 형식으로만 정해진다.
"""
from __future__ import annotations

import json
import logging
import re
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from app.config import user_data_dir
from app.core.image_io import load_image

log = logging.getLogger("corkwalkway")

SAMPLE_NAME = "reference.jpg"
META_NAME = "meta.json"
SAMPLE_MAX_PX = 1024               # 저장·전송하는 샘플 사진 긴 변 상한
SAMPLE_MIN_PX = 64                 # 이보다 작은 사진은 질감을 알 수 없어 거부
MAX_FILE_MB = 50                   # 고를 수 있는 샘플 사진 파일 크기 상한
NAME_MAX = 30                      # 소재 이름 최대 글자 수
MAX_CUSTOM = 30                    # 등록할 수 있는 사용자 소재 수
_ID_RE = re.compile(r"^custom_[0-9a-f]{8}$")


@dataclass(frozen=True)
class CustomMaterial:
    id: str
    name: str
    reference: Path                # 샘플 사진(정리된 사본)


def materials_root() -> Path:
    return user_data_dir() / "materials"


def clean_name(name: str) -> str:
    """소재 이름: 제어문자 제거, 공백 정리, NAME_MAX자까지. 비면 ValueError."""
    t = re.sub(r"\s+", " ", re.sub(r"[\x00-\x1f\x7f]", " ", name or "")).strip()[:NAME_MAX]
    if not t:
        raise ValueError("소재 이름을 입력하세요")
    return t


def list_custom(root: Path | None = None) -> list[CustomMaterial]:
    """등록된 사용자 소재(이름순). 형식이 맞지 않는 폴더는 건너뛴다."""
    root = Path(root) if root else materials_root()
    if not root.is_dir():
        return []
    out = []
    for d in root.iterdir():
        if not (d.is_dir() and _ID_RE.match(d.name) and (d / SAMPLE_NAME).is_file()):
            continue
        try:
            meta = json.loads((d / META_NAME).read_text(encoding="utf-8"))
            out.append(CustomMaterial(d.name, clean_name(str(meta.get("name", ""))), d / SAMPLE_NAME))
        except (OSError, ValueError, AttributeError):
            log.warning("사용자 소재 정보를 읽지 못해 건너뜀: %s", d.name)
    return sorted(out, key=lambda m: m.name)


def add_custom(src: str | Path, name: str, root: Path | None = None) -> CustomMaterial:
    """샘플 사진을 검사·축소·재인코딩해 등록한다. 잘못된 입력이면 ValueError(사용자에게 보일 사유)."""
    root = Path(root) if root else materials_root()
    name = clean_name(name)
    if len(list_custom(root)) >= MAX_CUSTOM:
        raise ValueError(f"소재는 {MAX_CUSTOM}개까지 등록할 수 있습니다. 쓰지 않는 소재를 삭제하세요")
    src = Path(src)
    try:
        size = src.stat().st_size
    except OSError:
        raise ValueError("샘플 사진 파일을 찾을 수 없습니다") from None
    if size > MAX_FILE_MB * 1024 * 1024:
        raise ValueError(f"샘플 사진이 너무 큽니다({MAX_FILE_MB}MB 이하)")
    try:
        img = load_image(str(src))
    except (OSError, ValueError):
        raise ValueError("사진으로 읽을 수 없는 파일입니다(jpg·png·heic)") from None
    if min(img.shape[:2]) < SAMPLE_MIN_PX:
        raise ValueError(f"샘플 사진이 너무 작습니다(짧은 변 {SAMPLE_MIN_PX}px 이상)")
    s = min(1.0, SAMPLE_MAX_PX / max(img.shape[:2]))
    if s < 1.0:
        img = cv2.resize(img, (round(img.shape[1] * s), round(img.shape[0] * s)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 92])     # 메타데이터 없이 다시 저장
    if not ok:
        raise ValueError("샘플 사진을 저장하지 못했습니다")
    mid = "custom_" + uuid.uuid4().hex[:8]
    tmp = root / (mid + ".tmp")
    tmp.mkdir(parents=True, exist_ok=False)
    try:
        np.asarray(buf).tofile(str(tmp / SAMPLE_NAME))
        (tmp / META_NAME).write_text(json.dumps({"name": name}, ensure_ascii=False), encoding="utf-8")
        tmp.replace(root / mid)
    except OSError:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    log.info("사용자 소재 등록: %s", mid)
    return CustomMaterial(mid, name, root / mid / SAMPLE_NAME)


def remove_custom(material_id: str, root: Path | None = None) -> None:
    """사용자 소재 삭제. 프로그램이 만든 id 형식만 받는다(경로 조작 차단)."""
    if not _ID_RE.match(material_id or ""):
        raise ValueError("잘못된 소재 id")
    root = Path(root) if root else materials_root()
    d = root / material_id
    if d.is_dir():
        shutil.rmtree(d)
        log.info("사용자 소재 삭제: %s", material_id)
