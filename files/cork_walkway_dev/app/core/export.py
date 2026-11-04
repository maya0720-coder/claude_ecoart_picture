"""저장·내보내기 (모듈 09): 시공 후 예상도, 전·후 비교 이미지, 1페이지 PDF, 작업 설정 JSON(+마스크 PNG).

- 저장 위치는 사용자가 고른 로컬 폴더만. 같은 이름이 있으면 _2, _3 …(어떤 파일도 덮어쓰지 않음 → 원본 보호)
- 이미지는 cv2.imencode로 픽셀만 저장(EXIF·GPS 없음)
- 한글 글자는 Qt QPainter로 그린다(cv2.putText는 한글 불가). QGuiApplication이 있어야 한다.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import cv2
import numpy as np

from app.config import resolve_resource
from app.core.image_io import make_preview, save_image
from app.core.perspective import DEFAULT_PATH_WIDTH_M

NOTICE = "가상 시공 예상도 — 실제 시공 결과와 다를 수 있습니다"
TITLE = "코르크 포장 시공 예상도"
DEFAULT_SITE = "현장"
ALL_FORMATS = frozenset({"after", "compare", "pdf", "settings"})
COMPARE_MAX_PX = 2400          # 비교 이미지 한 장의 긴 변 상한
PDF_IMAGE_PX = 1400            # PDF에 넣는 이미지 긴 변(150dpi 기준 충분)
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}

_font_family: str | None = None


def export_result(session, out_dir: str, site_name: str = "", formats: set[str] = ALL_FORMATS, *,
                  result: np.ndarray | None = None, preset_name: str = "", watermark: bool = True,
                  jpeg_quality: int = 92, image_format: str = "jpg", logo_path: str | None = None) -> list[str]:
    """저장한 파일 경로 목록. result를 안 주면 검증된 session.result_hq 또는 result_local."""
    formats = set(formats)
    bad = formats - ALL_FORMATS
    if bad or not formats:
        raise ValueError(f"알 수 없는 저장 형식입니다: {sorted(bad) or '없음'}")
    if image_format not in ("jpg", "png"):
        raise ValueError("이미지 형식은 jpg 또는 png만 가능합니다")
    out = Path(out_dir)
    if not out.is_dir():
        raise FileNotFoundError(f"저장 폴더가 없습니다: {out}. 다른 폴더를 선택하세요.")
    after = result if result is not None else (session.result_hq if session.result_hq is not None else session.result_local)
    if after is None or not session.verified:
        raise ValueError("검증된 결과가 없어 저장할 수 없습니다. 결과를 다시 만들어 주세요.")
    if after.shape != session.original.shape:
        raise ValueError("결과와 원본의 크기가 다릅니다. 결과를 다시 만들어 주세요.")

    site = safe_site_name(site_name)
    stamp = time.strftime("%Y%m%d_%H%M")
    base = f"{site}_{stamp}"
    logo = _load_logo(logo_path)
    ext = "." + image_format
    saved: list[str] = []

    if "after" in formats:
        img = _annotate(after, watermark, logo) if (watermark or logo is not None) else after
        p = _unique(out / f"{base}_시공후{ext}")
        save_image(str(p), img, jpeg_quality)
        saved.append(str(p))
    if "compare" in formats:
        p = _unique(out / f"{base}_전후비교{ext}")
        save_image(str(p), make_compare(session.original, after, watermark, logo), jpeg_quality)
        saved.append(str(p))
    if "pdf" in formats:
        p = _unique(out / f"{base}_예상도.pdf")
        write_pdf(str(p), session.original, after, site_name.strip(), preset_name, logo)
        saved.append(str(p))
    if "settings" in formats:
        pm = _unique(out / f"{base}_마스크.png")
        save_image(str(pm), cv2.cvtColor(session.mask, cv2.COLOR_GRAY2BGR))
        pj = _unique(out / f"{base}_작업설정.json")
        pj.write_text(json.dumps(_settings_dict(session, site_name.strip(), preset_name, pm.name,
                                                after is session.result_hq), ensure_ascii=False, indent=2),
                      encoding="utf-8")
        saved += [str(pj), str(pm)]
    return saved


def safe_site_name(name: str) -> str:
    """Windows 파일명에 쓸 수 있게 정리. 비면 '현장'."""
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", (name or "").strip())
    s = re.sub(r"\s+", " ", s).strip(" .")[:40].strip(" .")
    if not s or s.upper() in _RESERVED:
        return DEFAULT_SITE
    return s


# ---- 이미지 ----
def make_compare(before: np.ndarray, after: np.ndarray, watermark: bool = True, logo=None) -> np.ndarray:
    """가로 사진은 좌우, 세로 사진은 상하로 붙이고 '시공 전', '시공 후(예상)' 라벨."""
    b, _ = make_preview(before, COMPARE_MAX_PX)
    a, _ = make_preview(after, COMPARE_MAX_PX)
    h, w = b.shape[:2]
    gap = max(4, w // 200)
    if w >= h:
        canvas = np.full((h, 2 * w + gap, 3), 255, np.uint8)
        canvas[:, :w], canvas[:, w + gap:] = b, a
        boxes = [(0, 0, w, h), (w + gap, 0, w, h)]
    else:
        canvas = np.full((2 * h + gap, w, 3), 255, np.uint8)
        canvas[:h], canvas[h + gap:] = b, a
        boxes = [(0, 0, w, h), (0, h + gap, w, h)]
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QPainter
    q = _to_qimage(canvas)
    p = QPainter(q)
    fs = max(14, int(min(w, h) * 0.045))
    for (x, y, bw, bh), label in zip(boxes, ("시공 전", "시공 후(예상)")):
        _label(p, QRectF(x, y, bw, bh), label, fs, top=True)
    if watermark:
        _label(p, QRectF(boxes[1][0], boxes[1][1], boxes[1][2], boxes[1][3]), NOTICE, max(12, int(fs * 0.6)), top=False)
    if logo is not None:
        _draw_logo(p, logo, QRectF(0, 0, q.width(), q.height()))
    p.end()
    return _from_qimage(q)


def _annotate(img: np.ndarray, watermark: bool, logo) -> np.ndarray:
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QPainter
    q = _to_qimage(img)
    p = QPainter(q)
    r = QRectF(0, 0, q.width(), q.height())
    if watermark:
        _label(p, r, NOTICE, max(14, int(min(q.width(), q.height()) * 0.028)), top=False)
    if logo is not None:
        _draw_logo(p, logo, r)
    p.end()
    return _from_qimage(q)


def _label(p, r, text: str, size_px: int, top: bool) -> None:
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QColor, QFont
    f = QFont(_font())
    f.setPixelSize(size_px)
    f.setBold(top)
    p.setFont(f)
    fm = p.fontMetrics()
    pad = size_px * 0.4
    w = min(fm.horizontalAdvance(text) + 2 * pad, r.width() - 2 * pad)
    h = fm.height() + pad
    x = r.x() + pad
    y = r.y() + pad if top else r.bottom() - h - pad
    box = QRectF(x, y, w, h)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(0, 0, 0, 150))
    p.drawRoundedRect(box, pad / 2, pad / 2)
    p.setPen(QColor("white"))
    p.drawText(box, Qt.AlignmentFlag.AlignCenter, text)


def _draw_logo(p, logo, r) -> None:
    """우측 하단에 작게(폭의 8%)."""
    from PySide6.QtCore import QRectF
    w = r.width() * 0.08
    h = w * logo.height() / max(1, logo.width())
    m = r.width() * 0.015
    p.drawImage(QRectF(r.right() - w - m, r.bottom() - h - m, w, h), logo)


def _load_logo(path: str | None):
    p = Path(path) if path else resolve_resource("assets/logo.png")
    if not p.is_file():
        return None
    from PySide6.QtGui import QImage
    img = QImage()
    return img if img.loadFromData(p.read_bytes()) else None   # 한글 경로 대응: 바이트로 읽기


# ---- PDF ----
def write_pdf(path: str, before: np.ndarray, after: np.ndarray, site_name: str, preset_name: str, logo=None) -> None:
    """A4 가로 1페이지: 제목, 현장명·날짜·프리셋, 전·후 사진, 고지 문구.

    글자는 글꼴을 PDF에 넣지 않고 윤곽선(벡터 경로)으로 그린다: 일부 PDF 뷰어에서 내장 한글 글꼴이
    네모로 보이는 문제를 확인했다. 어느 뷰어에서나 같게 보이고, 글꼴 파일도 PDF에 들어가지 않는다.
    """
    from PySide6.QtCore import QMarginsF, QPointF, QRectF
    from PySide6.QtGui import (QColor, QFont, QFontMetricsF, QPageLayout, QPageSize, QPainter, QPainterPath,
                               QPdfWriter)
    pdf = QPdfWriter(path)
    pdf.setTitle(TITLE)
    pdf.setCreator("CorkWalkway")
    pdf.setResolution(150)
    pdf.setPageLayout(QPageLayout(QPageSize(QPageSize.PageSizeId.A4), QPageLayout.Orientation.Landscape,
                                  QMarginsF(12, 12, 12, 12), QPageLayout.Unit.Millimeter))
    p = QPainter(pdf)
    if not p.isActive():
        raise OSError(f"PDF를 만들 수 없습니다: {Path(path).name}. 폴더 쓰기 권한을 확인하세요.")
    W, H = pdf.width(), pdf.height()
    unit = H / 100.0

    def font(size, bold=False):
        f = QFont(_font())
        f.setPixelSize(int(size * unit))
        f.setBold(bold)
        return f

    def text(r: QRectF, s: str, f: QFont, color: QColor) -> None:
        """왼쪽·세로 가운데 정렬, 윤곽선으로 채우기. 폭을 넘으면 글자 크기를 줄여 맞춘다."""
        fm = QFontMetricsF(f, pdf)
        tw = fm.horizontalAdvance(s)
        if tw > r.width():
            f = QFont(f)
            f.setPixelSize(max(1, int(f.pixelSize() * r.width() / tw * 0.98)))
            fm = QFontMetricsF(f, pdf)
        path = QPainterPath()
        path.addText(QPointF(r.x(), r.center().y() + (fm.ascent() - fm.descent()) / 2), f, s)
        p.fillPath(path, color)

    p.fillRect(QRectF(0, 0, W, H), QColor("white"))
    dark, grey = QColor(30, 30, 30), QColor(90, 90, 90)
    text(QRectF(0, 0, W, 9 * unit), TITLE, font(6, True), dark)
    info = f"현장: {site_name or DEFAULT_SITE}     날짜: {time.strftime('%Y-%m-%d')}     코르크: {preset_name or '-'}"
    text(QRectF(0, 10 * unit, W, 5 * unit), info, font(3), dark)
    if logo is not None:
        lw = W * 0.12
        lh = lw * logo.height() / max(1, logo.width())
        p.drawImage(QRectF(W - lw, 0, lw, min(lh, 14 * unit)), logo)

    gap = 2 * unit
    top, bottom = 18 * unit, H - 12 * unit
    box_w = (W - gap) / 2
    for i, (img, label) in enumerate(((before, "시공 전"), (after, "시공 후(예상)"))):
        small, _ = make_preview(img, PDF_IMAGE_PX)
        q = _to_qimage(small)
        area = QRectF(i * (box_w + gap), top + 5 * unit, box_w, bottom - top - 5 * unit)
        s = min(area.width() / q.width(), area.height() / q.height())
        r = QRectF(area.x() + (area.width() - q.width() * s) / 2, area.y(), q.width() * s, q.height() * s)
        text(QRectF(r.x(), top, r.width(), 5 * unit), label, font(3.2, True), dark)
        p.drawImage(r, q)
    text(QRectF(0, H - 9 * unit, W, 9 * unit), NOTICE + ". 실제 색상·질감·입자 크기는 제품과 현장 조건에 따라 달라집니다.",
         font(3), grey)
    p.end()


# ---- 작업 설정 ----
def _settings_dict(s, site: str, preset_name: str, mask_file: str, is_hq: bool) -> dict:
    rp = s.render_params
    return {
        "app": "CorkWalkway", "version": 1, "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        "site_name": site, "source_name": s.source_name,
        "image_size": [int(s.original.shape[1]), int(s.original.shape[0])],
        "preset_id": s.preset_id, "preset_name": preset_name,
        "path_width_m": s.path_width_m if s.path_width_m is not None else DEFAULT_PATH_WIDTH_M,
        "path_width_assumed": s.path_width_m is None,
        "mask_file": mask_file, "mask_feather_px": s.mask_feather_px,
        "quad": None if s.quad is None else np.asarray(s.quad, float).round(2).tolist(),
        "quad_segments": None if not s.quad_segments else [np.asarray(q, float).round(2).tolist() for q in s.quad_segments],
        "render_params": {"shading_strength": rp.shading_strength, "color_match": rp.color_match,
                          "granule_scale": rp.granule_scale, "edge_band": rp.edge_band,
                          "edge_band_px": rp.edge_band_px, "contact_shadow": rp.contact_shadow},
        "result": "gemini_hq" if is_hq else "local",
    }


# ---- 공통 ----
def _unique(p: Path) -> Path:
    if not p.exists():
        return p
    i = 2
    while p.with_name(f"{p.stem}_{i}{p.suffix}").exists():
        i += 1
    return p.with_name(f"{p.stem}_{i}{p.suffix}")


def _font() -> str:
    """한글 글꼴: assets/fonts의 글꼴 → Windows 맑은 고딕 순. 둘 다 없으면 Qt 기본 글꼴."""
    global _font_family
    if _font_family is not None:
        return _font_family
    from PySide6.QtGui import QFontDatabase
    candidates = sorted(resolve_resource("assets/fonts").glob("*.[ot]tf")) + [Path(r"C:\Windows\Fonts\malgun.ttf")]
    for c in candidates:
        if c.is_file():
            fid = QFontDatabase.addApplicationFontFromData(c.read_bytes())
            fams = QFontDatabase.applicationFontFamilies(fid) if fid >= 0 else []
            if fams:
                _font_family = fams[0]
                return _font_family
    _font_family = "Malgun Gothic"
    return _font_family


def _to_qimage(bgr: np.ndarray):
    from PySide6.QtGui import QImage
    rgb = np.ascontiguousarray(bgr[:, :, ::-1])
    h, w = rgb.shape[:2]
    return QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()


def _from_qimage(q) -> np.ndarray:
    from app.core.image_io import qimage_to_bgr
    return qimage_to_bgr(q)
