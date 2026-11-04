"""공용 위젯: 줄바꿈 버튼 배치(좁은 세로 화면에서도 버튼이 잘리지 않게), 큰 버튼, 프리셋 색 칩."""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QButtonGroup, QLayout, QPushButton, QSizePolicy, QWidget

BUTTON_MIN_H = 48


class FlowLayout(QLayout):
    """가로로 채우다 넘치면 다음 줄로(Qt 공식 예제 방식)."""

    def __init__(self, parent=None, spacing: int = 8) -> None:
        super().__init__(parent)
        self._items = []
        self.setSpacing(spacing)
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for it in self._items:
            size = size.expandedTo(it.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _do_layout(self, rect, test_only):
        x, y, line_h = rect.x(), rect.y(), 0
        sp = self.spacing()
        for it in self._items:
            if it.widget() is not None and not it.widget().isVisibleTo(it.widget().parentWidget()):
                continue
            hint = it.sizeHint()
            w = min(hint.width(), rect.width())
            if x + w > rect.right() + 1 and line_h > 0:
                x, y, line_h = rect.x(), y + line_h + sp, 0
            if not test_only:
                it.setGeometry(QRect(QPoint(x, y), QSize(w, hint.height())))
            x += w + sp
            line_h = max(line_h, hint.height())
        return y + line_h - rect.y()


def big_button(text: str, primary: bool = False, checkable: bool = False) -> QPushButton:
    b = QPushButton(text)
    b.setMinimumHeight(BUTTON_MIN_H)
    b.setCheckable(checkable)
    b.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed)
    b.setProperty("primary", primary)
    return b


def flow_row(*widgets) -> QWidget:
    w = QWidget()
    lay = FlowLayout(w)
    for x in widgets:
        lay.addWidget(x)
    return w


class PresetChips(QWidget):
    """코르크 프리셋 색 칩. 누르면 presetChosen(id)."""
    presetChosen = Signal(str)

    def __init__(self, presets, parent=None) -> None:
        super().__init__(parent)
        lay = FlowLayout(self)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.buttons: dict[str, QPushButton] = {}
        for p in presets:
            b = big_button(p.name, checkable=True)
            c = p.base_colors[0]
            b.setStyleSheet(f"QPushButton {{ border-left: 18px solid {c}; padding: 0 14px; }}"
                            f"QPushButton:checked {{ border: 3px solid #f08a24; border-left: 18px solid {c}; }}")
            b.clicked.connect(lambda _=False, pid=p.id: self.presetChosen.emit(pid))
            self.group.addButton(b)
            lay.addWidget(b)
            self.buttons[p.id] = b

    def set_current(self, pid: str) -> None:
        if pid in self.buttons:
            self.buttons[pid].setChecked(True)


STYLE = """
QWidget { font-size: 11pt; }
QPushButton { padding: 6px 16px; border-radius: 6px; border: 1px solid #b9b9b9; background: #f4f4f4; }
QPushButton:hover { background: #ececec; }
QPushButton:checked { background: #ffe2c4; border-color: #f08a24; }
QPushButton[primary="true"] { background: #f08a24; color: white; border-color: #d97512; font-weight: bold; }
QPushButton[primary="true"]:disabled { background: #f3c79b; }
QPushButton:disabled { color: #9a9a9a; }
QLabel#guide { font-size: 12pt; padding: 4px; }
QLabel#banner { background: #fff4d6; border: 1px solid #e8c66b; padding: 6px; border-radius: 4px; }
QLabel#notice { background: rgba(0,0,0,150); color: white; padding: 4px 10px; border-radius: 4px; }
"""


def bgr_to_pixmap(img: np.ndarray) -> QPixmap:
    h, w = img.shape[:2]
    rgb = np.ascontiguousarray(img[:, :, ::-1])
    q = QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888)
    return QPixmap.fromImage(q.copy())

