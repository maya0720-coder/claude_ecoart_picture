"""프레젠테이션 모드 (모듈 08, 고객용): 전체 화면, 전·후 비교, 하단 색 칩, 고지 상시 표시."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from app.ui.compare_view import CompareView
from app.ui.widgets import PresetChips, big_button, flow_row


class PresentationWindow(QWidget):
    presetRequested = Signal(str)
    closed = Signal()

    def __init__(self, presets, current_id: str, parent=None) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self.setWindowTitle("프레젠테이션")
        self.setStyleSheet("PresentationWindow, QWidget#bar { background: #111; } QLabel { color: white; }")
        self.view = CompareView()
        self.btn_close = QPushButton("✕")
        self.btn_close.setFixedSize(56, 56)
        self.btn_close.setToolTip("프레젠테이션 끝내기(ESC)")
        self.btn_close.clicked.connect(self.close)
        self.btn_slider = big_button("슬라이더", checkable=True)
        self.btn_side = big_button("나란히", checkable=True)
        self.btn_toggle = big_button("전/후 전환")
        self.btn_slider.setChecked(True)
        self.btn_slider.clicked.connect(lambda: self._mode("slider"))
        self.btn_side.clicked.connect(lambda: self._mode("side"))
        self.btn_toggle.clicked.connect(self._toggle)
        self.chips = PresetChips(presets)
        self.chips.set_current(current_id)
        self.chips.presetChosen.connect(self.presetRequested)
        self.status = QLabel("")

        top = QHBoxLayout()
        top.addStretch(1)
        top.addWidget(self.btn_close)
        bar = QWidget(objectName="bar")
        bl = QVBoxLayout(bar)
        bl.addWidget(flow_row(self.btn_slider, self.btn_side, self.btn_toggle, self.status))
        bl.addWidget(self.chips)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 8)
        lay.addLayout(top)
        lay.addWidget(self.view, 1)
        lay.addWidget(bar)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def set_images(self, before, after) -> None:
        self.view.set_images(before, after)

    def set_busy(self, text: str) -> None:
        self.status.setText(text)

    def _mode(self, m: str) -> None:
        self.btn_slider.setChecked(m == "slider")
        self.btn_side.setChecked(m == "side")
        self.view.set_mode(m)

    def _toggle(self) -> None:
        self.btn_slider.setChecked(False)
        self.btn_side.setChecked(False)
        if self.view.mode != "toggle":
            self.view.set_mode("toggle")
            self.view.show_after = False
        self.view.toggle()

    def showEvent(self, e) -> None:
        super().showEvent(e)
        self.activateWindow()
        self.setFocus()

    def keyPressEvent(self, e) -> None:
        if e.key() == Qt.Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(e)

    def closeEvent(self, e) -> None:
        self.closed.emit()
        super().closeEvent(e)
