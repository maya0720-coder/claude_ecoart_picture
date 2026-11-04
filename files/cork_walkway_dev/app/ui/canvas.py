"""사진·마스크 캔버스 (모듈 08): 터치 점, 브러시·지우개, 4점 끌기 + 격자.

화면에는 미리보기 축소본을 그리고, 모든 좌표 신호는 원본 픽셀 좌표로 보낸다.
"""
from __future__ import annotations

import cv2
import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QSizePolicy, QWidget

from app.core.perspective import project_grid
from app.ui.widgets import bgr_to_pixmap

LONG_PRESS_MS = 600
HANDLE_R = 22          # 4점 손잡이 터치 반경(px, 화면)


class ImageCanvas(QWidget):
    pointAdded = Signal(int, int, bool)            # 원본 x, y, 포함(True)/제외(False)
    strokeFinished = Signal(list, int, bool)       # 원본 점 목록, 원본 반지름, 추가(True)/지우기(False)
    quadChanged = Signal(object)                    # (4,2) 원본 좌표, 손을 뗄 때
    polygonFinished = Signal(list)                  # 원본 꼭짓점 목록(3개 이상)

    MODES = ("view", "point", "neg", "brush", "erase", "polygon", "quad")

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(240, 180)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents, True)
        self._pix = None
        self._prev_scale = 1.0          # 미리보기 / 원본
        self._mask_img: QImage | None = None
        self._contours: list[QPolygonF] = []
        self._points: list[tuple[int, int, bool]] = []
        self.quad: np.ndarray | None = None
        self.mode = "view"
        self.brush_px = 30              # 화면 px 기준 브러시 반지름
        self._stroke: list[tuple[float, float]] = []
        self._poly: list[tuple[float, float]] = []
        self._drag_idx: int | None = None
        self._press_pos = None
        self._long = QTimer(self, singleShot=True, interval=LONG_PRESS_MS, timeout=self._on_long_press)
        self._long_fired = False

    # ---- 내용 ----
    def set_image(self, preview_bgr: np.ndarray, prev_scale: float) -> None:
        self._pix = bgr_to_pixmap(preview_bgr)
        self._prev_scale = prev_scale
        self._mask_img, self._contours, self._points, self.quad = None, [], [], None
        self.update()

    def set_mask(self, mask_orig: np.ndarray | None) -> None:
        """원본 크기 마스크 → 반투명 주황 + 굵은 경계선."""
        if mask_orig is None or self._pix is None:
            self._mask_img, self._contours = None, []
            self.update()
            return
        w, h = self._pix.width(), self._pix.height()
        m = cv2.resize(mask_orig, (w, h), interpolation=cv2.INTER_NEAREST)
        rgba = np.zeros((h, w, 4), np.uint8)
        rgba[m > 0] = (255, 140, 30, 110)
        self._mask_img = QImage(rgba.data, w, h, 4 * w, QImage.Format.Format_RGBA8888).copy()
        cs, _ = cv2.findContours((m > 0).astype(np.uint8), cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        self._contours = [QPolygonF([QPointF(float(x), float(y)) for x, y in c.reshape(-1, 2)]) for c in cs if len(c) > 2]
        self.update()

    def set_points(self, pos: list, neg: list) -> None:
        self._points = [(x, y, True) for x, y in pos] + [(x, y, False) for x, y in neg]
        self.update()

    def set_quad(self, quad: np.ndarray | None) -> None:
        self.quad = None if quad is None else np.asarray(quad, np.float32).copy()
        self.update()

    def set_mode(self, mode: str) -> None:
        assert mode in self.MODES
        self.mode = mode
        self._poly = []
        cursor = Qt.CursorShape.CrossCursor if mode in ("point", "neg", "brush", "erase", "polygon") else Qt.CursorShape.ArrowCursor
        self.setCursor(cursor)
        self.update()

    # ---- 좌표 변환 ----
    def _view_rect(self) -> QRectF:
        if self._pix is None:
            return QRectF()
        pw, ph = self._pix.width(), self._pix.height()
        s = min(self.width() / pw, self.height() / ph)
        w, h = pw * s, ph * s
        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)

    def _disp_scale(self) -> float:
        r = self._view_rect()
        return r.width() / self._pix.width() if self._pix else 1.0

    def to_orig(self, p: QPointF) -> tuple[float, float] | None:
        r = self._view_rect()
        if self._pix is None or not r.contains(p):
            return None
        s = self._disp_scale() * self._prev_scale
        return (p.x() - r.x()) / s, (p.y() - r.y()) / s

    def to_widget(self, x: float, y: float) -> QPointF:
        r = self._view_rect()
        s = self._disp_scale() * self._prev_scale
        return QPointF(r.x() + x * s, r.y() + y * s)

    # ---- 그리기 ----
    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(40, 40, 40))
        if self._pix is None:
            p.setPen(QColor(200, 200, 200))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "사진을 불러오세요")
            return
        r = self._view_rect()
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.drawPixmap(r, self._pix, QRectF(self._pix.rect()))
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._mask_img is not None:
            p.drawImage(r, self._mask_img)
            p.save()
            p.translate(r.x(), r.y())
            p.scale(self._disp_scale(), self._disp_scale())
            pen = QPen(QColor(255, 120, 0), 3 / self._disp_scale())
            p.setPen(pen)
            for poly in self._contours:
                p.drawPolygon(poly)
            p.restore()
        for x, y, pos in self._points:
            c = self.to_widget(x, y)
            p.setPen(QPen(QColor("white"), 2))
            p.setBrush(QColor(40, 180, 70) if pos else QColor(220, 50, 50))
            p.drawEllipse(c, 9, 9)
        if self._stroke and self.mode in ("brush", "erase"):
            pen = QPen(QColor(255, 140, 30, 160) if self.mode == "brush" else QColor(60, 160, 255, 160),
                       2 * self.brush_px, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            path = QPainterPath(self.to_widget(*self._stroke[0]))
            for pt in self._stroke[1:]:
                path.lineTo(self.to_widget(*pt))
            p.drawPath(path)
        if self._poly and self.mode == "polygon":
            p.setPen(QPen(QColor(255, 140, 30), 3))
            p.setBrush(QColor(255, 140, 30, 60))
            p.drawPolygon(QPolygonF([self.to_widget(x, y) for x, y in self._poly]))
            p.setBrush(QColor("white"))
            for x, y in self._poly:
                p.drawEllipse(self.to_widget(x, y), 7, 7)
        if self.quad is not None and self.mode in ("quad", "view"):
            self._paint_quad(p)

    def _paint_quad(self, p: QPainter) -> None:
        q = self.quad
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(80, 220, 255, 170), 1.5))
        try:
            for seg in project_grid(q, 4, 8):
                p.drawLine(self.to_widget(*seg[0]), self.to_widget(*seg[1]))
        except Exception:      # 꼬인 4점(조정 중)에서는 격자 생략
            pass
        p.setPen(QPen(QColor(80, 220, 255), 3))
        p.drawPolygon(QPolygonF([self.to_widget(x, y) for x, y in q]))
        if self.mode == "quad":
            p.setBrush(QColor(255, 255, 255, 220))
            p.setPen(QPen(QColor(20, 120, 200), 3))
            for x, y in q:
                p.drawEllipse(self.to_widget(x, y), HANDLE_R * 0.6, HANDLE_R * 0.6)

    # ---- 입력 ----
    def mousePressEvent(self, e) -> None:
        pos = e.position()
        self._press_pos, self._long_fired = pos, False
        if self.mode == "quad" and self.quad is not None:
            d = [np.hypot(*(np.array([pos.x(), pos.y()]) - np.array([w.x(), w.y()])))
                 for w in (self.to_widget(x, y) for x, y in self.quad)]
            i = int(np.argmin(d))
            self._drag_idx = i if d[i] <= HANDLE_R else None
        elif self.mode in ("brush", "erase"):
            o = self.to_orig(pos)
            self._stroke = [o] if o else []
        elif self.mode == "point" and e.button() == Qt.MouseButton.LeftButton:
            self._long.start()

    def mouseMoveEvent(self, e) -> None:
        pos = e.position()
        if self._press_pos is not None and (pos - self._press_pos).manhattanLength() > 12:
            self._long.stop()
        if self._drag_idx is not None and e.buttons():
            o = self.to_orig(pos)
            if o:
                self.quad[self._drag_idx] = o
                self.update()
        elif self._stroke and e.buttons():
            o = self.to_orig(pos)
            if o:
                self._stroke.append(o)
                self.update()

    def mouseReleaseEvent(self, e) -> None:
        self._long.stop()
        pos = e.position()
        if self._drag_idx is not None:
            self._drag_idx = None
            self.quadChanged.emit(self.quad.copy())
        elif self.mode in ("brush", "erase") and self._stroke:
            r = max(1, round(self.brush_px / (self._disp_scale() * self._prev_scale)))
            pts = [(int(round(x)), int(round(y))) for x, y in self._stroke]
            self._stroke = []
            self.strokeFinished.emit(pts, r, self.mode == "brush")
            self.update()
        elif self.mode == "polygon":
            o = self.to_orig(pos)
            if o:
                self._poly.append(o)
                self.update()
        elif self.mode in ("point", "neg") and not self._long_fired:
            o = self.to_orig(pos)
            if o and self._press_pos is not None and (pos - self._press_pos).manhattanLength() <= 12:
                positive = self.mode == "point" and e.button() != Qt.MouseButton.RightButton
                self.pointAdded.emit(int(o[0]), int(o[1]), positive)
        self._press_pos = None

    def mouseDoubleClickEvent(self, e) -> None:
        if self.mode == "polygon":
            self.finish_polygon()

    def finish_polygon(self) -> bool:
        """꼭짓점이 3개 이상이면 다각형 완료 신호. 두 번 누름 또는 [다각형 완료]."""
        pts = [(int(round(x)), int(round(y))) for x, y in self._poly]
        pts = [q for i, q in enumerate(pts) if i == 0 or q != pts[i - 1]]   # 두 번 누름으로 생긴 중복 점 제거
        self._poly = []
        self.update()
        if len(pts) >= 3:
            self.polygonFinished.emit(pts)
            return True
        return False

    def _on_long_press(self) -> None:
        """길게 누름 = 제외 점(태블릿)."""
        if self._press_pos is None:
            return
        o = self.to_orig(self._press_pos)
        if o:
            self._long_fired = True
            self.pointAdded.emit(int(o[0]), int(o[1]), False)
