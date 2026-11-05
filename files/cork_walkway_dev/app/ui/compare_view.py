"""전·후 비교 화면 (모듈 08): 가운데 세로선 슬라이더 / 좌우 나란히 / 전·후 전환."""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from app.ui.widgets import bgr_to_pixmap

NOTICE = "가상 시공 예상도 — 실제 시공 결과와 다를 수 있음"
AFTER_LABEL = "시공 후 · AI 예상"      # AI가 만든 결과임을 분명히 표시
BG = QColor("#0F172A")
KEY_STEP = 0.05                        # ← → 키 한 번에 움직이는 비율


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
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)     # 키보드로도 비교(← → / 스페이스)

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
        p.fillRect(self.rect(), BG)
        if self._before is None:
            return
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        full = QRectF(self.rect())
        if self._after is None:
            # 결과가 아직 없으면 원본만 '시공 전'으로 보인다. 원본에 '시공 후(예상)'·예상도 표기를 붙이지 않는다(오인 방지)
            r = self._fit(self._before, full)
            p.drawPixmap(r, self._before, QRectF(self._before.rect()))
            self._label(p, r, "시공 전")
            return
        after = self._after
        if self.mode == "side":
            half = full.width() / 2
            for i, (pix, label) in enumerate(((self._before, "시공 전"), (after, AFTER_LABEL))):
                r = self._fit(pix, QRectF(full.x() + i * half, full.y(), half, full.height()))
                p.drawPixmap(r, pix, QRectF(pix.rect()))
                self._label(p, r, label)
        elif self.mode == "toggle":
            pix = after if self.show_after else self._before
            r = self._fit(pix, full)
            p.drawPixmap(r, pix, QRectF(pix.rect()))
            self._label(p, r, AFTER_LABEL if self.show_after else "시공 전")
        else:
            r = self._fit(self._before, full)
            p.drawPixmap(r, self._before, QRectF(self._before.rect()))
            x = r.x() + r.width() * self.split
            src_w = self._before.width() * self.split
            p.drawPixmap(QRectF(x, r.y(), r.right() - x, r.height()), after,
                         QRectF(src_w, 0, after.width() - src_w, after.height()))
            p.setPen(QPen(QColor("white"), 2))
            p.drawLine(int(x), int(r.y()), int(x), int(r.bottom()))
            cy = int(r.center().y())
            p.setPen(QPen(QColor(15, 23, 42, 60), 1))
            p.setBrush(QColor("white"))
            p.drawEllipse(int(x) - 18, cy - 18, 36, 36)
            p.setPen(QPen(QColor("#0F172A"), 2))                      # 좌우 화살표: 끌 수 있음을 알림
            for d in (-1, 1):                                          # ‹ › 모양(바깥쪽을 가리킴)
                p.drawLine(int(x) + d * 10, cy, int(x) + d * 5, cy - 5)
                p.drawLine(int(x) + d * 10, cy, int(x) + d * 5, cy + 5)
            self._label(p, QRectF(r.x(), r.y(), x - r.x(), r.height()), "시공 전")
            self._label(p, QRectF(x, r.y(), r.right() - x, r.height()), AFTER_LABEL, right=True)
        if self.notice_visible:
            self._notice(p, full)

    def _label(self, p: QPainter, r: QRectF, text: str, right: bool = False) -> None:
        if r.width() < 80:
            return
        p.setFont(QFont("Malgun Gothic", 11, QFont.Weight.Bold))
        fm = p.fontMetrics()
        w = fm.horizontalAdvance(text) + 20
        x = r.right() - w - 10 if right else r.x() + 10
        box = QRectF(x, r.y() + 10, w, fm.height() + 10)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(15, 23, 42, 190))
        p.drawRoundedRect(box, 8, 8)
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

    def keyPressEvent(self, e) -> None:
        if self._after is not None and self.mode == "slider" and e.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            d = KEY_STEP if e.key() == Qt.Key.Key_Right else -KEY_STEP
            self.split = float(np.clip(self.split + d, 0, 1))
            self.update()
        elif self._after is not None and self.mode == "toggle" and e.key() == Qt.Key.Key_Space:
            self.toggle()
        else:
            super().keyPressEvent(e)

    def _move_split(self, x: float) -> None:
        if self._before is None:
            return
        r = self._fit(self._before, QRectF(self.rect()))
        self.split = float(np.clip((x - r.x()) / max(r.width(), 1), 0, 1))
        self.update()
