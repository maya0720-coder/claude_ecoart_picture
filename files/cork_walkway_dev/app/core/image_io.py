"""사진 불러오기·저장 (모듈 01).

한글 경로 대응: 읽기는 파일 바이트를 직접 읽어 디코딩하고, 쓰기는 cv2.imencode + tofile.
"""
from __future__ import annotations

import io
import os
from pathlib import Path

import cv2
import numpy as np
import pillow_heif
from PIL import Image, ImageOps

pillow_heif.register_heif_opener()

# 2억 화소 휴대폰 사진(약 200MP)까지 허용. 이보다 크면 압축 폭탄으로 보고 거부.
Image.MAX_IMAGE_PIXELS = 300_000_000

SUPPORTED_EXTS = {".jpg", ".jpeg", ".png", ".heic", ".heif"}
HUGE_PIXELS = 50_000_000      # 이보다 크면 경고 후 축소 제안
HUGE_LIMIT_PX = 8000          # 축소 시 긴 변


class ImageLoadError(ValueError):
    """사진을 읽을 수 없음(손상, 미지원 형식 등)."""


def load_image(path: str) -> np.ndarray:
    """BGR uint8, EXIF 회전 적용, 한글 경로 지원."""
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"사진 파일이 없습니다: {p}")
    data = p.read_bytes()
    try:
        with Image.open(io.BytesIO(data)) as im:
            im = ImageOps.exif_transpose(im)
            rgb = _to_rgb8(im)
    except Image.DecompressionBombError as e:
        raise ImageLoadError(f"사진이 너무 큽니다(3억 화소 초과): {p.name}") from e
    except (OSError, ValueError, SyntaxError) as e:
        raise ImageLoadError(f"사진을 읽을 수 없습니다(손상되었거나 지원하지 않는 형식): {p.name}") from e
    return np.ascontiguousarray(rgb[:, :, ::-1])


def _to_rgb8(im: Image.Image) -> np.ndarray:
    """모든 모드(16비트, 알파, 팔레트, CMYK, 흑백)를 RGB uint8 배열로."""
    if im.mode.startswith("I;16") or im.mode == "I":
        a = np.asarray(im, dtype=np.float32)
        a = np.clip(a / 257.0, 0, 255).astype(np.uint8)   # 16비트 → 8비트
        return np.dstack([a, a, a])
    if im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info):
        im = im.convert("RGBA")
        bg = Image.new("RGBA", im.size, (255, 255, 255, 255))   # 투명 부분은 흰 배경
        im = Image.alpha_composite(bg, im)
    return np.asarray(im.convert("RGB"), dtype=np.uint8)


def save_image(path: str, img: np.ndarray, quality: int = 92, strip_meta: bool = True) -> None:
    """JPG/PNG 저장. 한글 경로 지원.

    NumPy 배열에는 메타데이터가 없고 cv2.imencode는 EXIF를 쓰지 않으므로
    결과 파일에는 항상 EXIF·GPS가 없다(strip_meta=False여도 붙일 메타데이터가 없음).
    """
    _check_bgr(img)
    p = Path(path)
    ext = p.suffix.lower()
    if ext in (".jpg", ".jpeg"):
        if not 1 <= quality <= 100:
            raise ValueError(f"JPEG 품질은 1~100이어야 합니다: {quality}")
        params = [cv2.IMWRITE_JPEG_QUALITY, int(quality)]
    elif ext == ".png":
        params = [cv2.IMWRITE_PNG_COMPRESSION, 3]
    else:
        raise ValueError(f"저장할 수 없는 형식입니다(.jpg, .png만 가능): {p.name}")
    if not p.parent.is_dir():
        raise FileNotFoundError(f"저장 폴더가 없습니다: {p.parent}")
    ok, buf = cv2.imencode(ext, img, params)
    if not ok:
        raise OSError(f"이미지 인코딩에 실패했습니다: {p.name}")
    buf.tofile(str(p))


def make_preview(img: np.ndarray, max_px: int) -> tuple[np.ndarray, float]:
    """(축소본, 배율). 배율 = 축소본 크기 / 원본 크기. 이미 작으면 원본 그대로, 배율 1.0."""
    if max_px <= 0:
        raise ValueError(f"max_px는 양수여야 합니다: {max_px}")
    h, w = img.shape[:2]
    long_side = max(h, w)
    if long_side <= max_px:
        return img, 1.0
    scale = max_px / long_side
    size = (max(1, round(w * scale)), max(1, round(h * scale)))
    return cv2.resize(img, size, interpolation=cv2.INTER_AREA), scale


def is_huge(img: np.ndarray) -> bool:
    """50MP 초과 여부. UI는 True면 경고 후 make_preview(img, HUGE_LIMIT_PX)로 축소를 제안한다."""
    return img.shape[0] * img.shape[1] > HUGE_PIXELS


def qimage_to_bgr(qimg) -> np.ndarray:
    """QImage → BGR uint8 (복사본)."""
    from PySide6.QtGui import QImage

    if qimg.isNull():
        raise ValueError("빈 QImage입니다")
    q = qimg.convertToFormat(QImage.Format.Format_BGR888)
    h, w, bpl = q.height(), q.width(), q.bytesPerLine()
    buf = np.frombuffer(q.constBits(), np.uint8, count=q.sizeInBytes())
    return buf.reshape(h, bpl)[:, : w * 3].reshape(h, w, 3).copy()


def recent_images(folder: str, n: int = 6) -> list[str]:
    """폴더의 최신 사진 경로 n개(수정 시각 내림차순). 폴더가 없으면 빈 목록."""
    try:
        entries = [e for e in os.scandir(folder)
                   if e.is_file() and Path(e.name).suffix.lower() in SUPPORTED_EXTS]
    except OSError:
        return []
    entries.sort(key=lambda e: e.stat().st_mtime, reverse=True)
    return [e.path for e in entries[:n]]


def _check_bgr(img: np.ndarray) -> None:
    if not (isinstance(img, np.ndarray) and img.dtype == np.uint8 and img.ndim == 3 and img.shape[2] == 3):
        raise ValueError("이미지는 (H, W, 3) uint8 BGR 배열이어야 합니다")
