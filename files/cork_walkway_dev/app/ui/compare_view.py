"""전·후 비교 화면 (모듈 08): 가운데 세로선 슬라이더 / 좌우 나란히 / 전·후 전환."""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from app.ui.widgets import bgr_to_pixmap

NOTICE = "가상 시공 예상도 — 실제 시공 결과와 다를 수 있음"


class CompareView(QWidget):
    MODES = ("slider", "side", "toggle")

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(240, 180)
        self._before = self._after = None
        self.mode = "slider"
        self.split = 0.5
        self.show_after = True          # toggle 모드에서 보이는 쪽
        self.notice_visible = True
        self._dragging = False

    def set_images(self, before: np.ndarray | None, after: np.ndarray | None) -> None:
        self._before = bgr_to_pixmap(before) if before is not None else None
        self._after = bgr_to_pixmap(after) if after is not None else None
        self.update()

    def set_mode(self, mode: str) -> None:
        assert mode in self.MODES
        self.mode = mode
        self.update()

    def toggle(self) -> None:
        self.show_after = not self.show_after
        self.update()

    def _fit(self, pix, area: QRectF) -> QRectF:
        s = min(area.width() / pix.width(), area.height() / pix.height())
        w, h = pix.width() * s, pix.height() * s
        return QRectF(area.x() + (area.width() - w) / 2, area.y() + (area.height() - h) / 2, w, h)

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(20, 20, 20))
        if self._before is None:
            return
        after = self._after or self._before
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        full = QRectF(self.rect())
        if self.mode == "side":
            half = full.width() / 2
            for i, (pix, label) in enumerate(((self._before, "시공 전"), (after, "시공 후(예상)"))):
                r = self._fit(pix, QRectF(full.x() + i * half, full.y(), half, full.height()))
                p.drawPixmap(r, pix, QRectF(pix.rect()))
                self._label(p, r, label)
        elif self.mode == "toggle":
            pix = after if self.show_after else self._before
            r = self._fit(pix, full)
            p.drawPixmap(r, pix, QRectF(pix.rect()))
            self._label(p, r, "시공 후(예상)" if self.show_after else "시공 전")
        else:
            r = self._fit(self._before, full)
            p.drawPixmap(r, self._before, QRectF(self._before.rect()))
            x = r.x() + r.width() * self.split
            src_w = self._before.width() * self.split
            p.drawPixmap(QRectF(x, r.y(), r.right() - x, r.height()), after,
                         QRectF(src_w, 0, after.width() - src_w, after.height()))
            p.setPen(QPen(QColor("white"), 3))
            p.drawLine(int(x), int(r.y()), int(x), int(r.bottom()))
            p.setBrush(QColor("white"))
            p.drawEllipse(int(x) - 16, int(r.center().y()) - 16, 32, 32)
            self._label(p, QRectF(r.x(), r.y(), x - r.x(), r.height()), "시공 전")
            self._label(p, QRectF(x, r.y(), r.right() - x, r.height()), "시공 후(예상)", right=True)
        if self.notice_visible:
            self._notice(p, full)

    def _label(self, p: QPainter, r: QRectF, text: str, right: bool = False) -> None:
        if r.width() < 80:
            return
        p.setFont(QFont("Malgun Gothic", 12, QFont.Weight.Bold))
        fm = p.fontMetrics()
        w = fm.horizontalAdvance(text) + 20
        x = r.right() - w - 10 if right else r.x() + 10
        box = QRectF(x, r.y() + 10, w, fm.height() + 10)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 150))
        p.drawRoundedRect(box, 5, 5)
        p.setPen(QColor("white"))
        p.drawText(box, Qt.AlignmentFlag.AlignCenter, text)

    def _notice(self, p: QPainter, full: QRectF) -> None:
        p.setFont(QFont("Malgun Gothic", 11))
        fm = p.fontMetrics()
        w = fm.horizontalAdvance(NOTICE) + 24
        box = QRectF(full.center().x() - w / 2, full.bottom() - fm.height() - 22, w, fm.height() + 12)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 160))
        p.drawRoundedRect(box, 5, 5)
        p.setPen(QColor("white"))
        p.drawText(box, Qt.AlignmentFlag.AlignCenter, NOTICE)

    # 슬라이더 끌기(마우스·터치)
    def mousePressEvent(self, e) -> None:
        if self.mode == "slider":
            self._dragging = True
            self._move_split(e.position().x())
        elif self.mode == "toggle":
            self.toggle()

    def mouseMoveEvent(self, e) -> None:
        if self._dragging:
            self._move_split(e.position().x())

    def mouseReleaseEvent(self, _e) -> None:
        self._dragging = False

    def _move_split(self, x: float) -> None:
        if self._before is None:
            return
        r = self._fit(self._before, QRectF(self.rect()))
        self.split = float(np.clip((x - r.x()) / max(r.width(), 1), 0, 1))
        self.update()
