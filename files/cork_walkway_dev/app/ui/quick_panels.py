"""간편 화면 구성 요소: 구역 카드, 소재 목록, 추가 요청 입력, 사진 놓는 곳, 소재 추가 창."""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (QCheckBox, QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QPlainTextEdit, QPushButton, QSizePolicy, QVBoxLayout, QWidget)

from app.ai.gemini_convert import NOTE_MAX, reference_path
from app.config import resolve_resource
from app.core import image_io
from app.core.materials import NAME_MAX, CustomMaterial
from app.ui.widgets import bgr_to_pixmap

THUMB = 48
PHOTO_FILTER = "사진 (*.jpg *.jpeg *.png *.heic *.heif)"


class ElidedLabel(QLabel):
    """긴 글자(띄어쓰기 없는 파일 이름 등)를 '…'로 줄여 한 줄에 표시. 전체 글자는 툴팁.

    QLabel은 줄바꿈할 곳이 없는 긴 글자만큼 최소 폭을 요구해 패널을 밀어내므로(화면 잘림), 최소 폭을 0으로 둔다.
    """

    def __init__(self, text: str = "", parent=None, objectName: str = "") -> None:
        super().__init__(parent, objectName=objectName)
        self._full = ""
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(1)
        self.set_full_text(text)

    def set_full_text(self, text: str) -> None:
        self._full = text
        self.setToolTip(text)
        self._elide()

    def full_text(self) -> str:
        return self._full

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self._elide()

    def _elide(self) -> None:
        super().setText(self.fontMetrics().elidedText(self._full, Qt.TextElideMode.ElideMiddle, max(10, self.width())))


def button(text: str, primary: bool = False, ghost: bool = False, danger: bool = False,
           tip: str = "") -> QPushButton:
    b = QPushButton(text)
    b.setMinimumHeight(40)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setProperty("primary", primary)
    b.setProperty("ghost", ghost)
    b.setProperty("danger", danger)
    if tip:
        b.setToolTip(tip)
    return b


def header_bar(title: str, subtitle: str) -> tuple[QFrame, QPushButton, QPushButton]:
    """상단 바: 앱 아이콘 + 제목 + 설명 | [전송 내역] [설정]. (바, 전송 내역 버튼, 설정 버튼)."""
    bar = QFrame(objectName="header")
    lay = QHBoxLayout(bar)
    lay.setContentsMargins(20, 10, 16, 10)
    lay.setSpacing(10)
    mark = QLabel()
    icon = resolve_resource("assets/app.png")
    if icon.is_file():
        mark.setPixmap(QPixmap(str(icon)).scaled(28, 28, Qt.AspectRatioMode.KeepAspectRatio,
                                                 Qt.TransformationMode.SmoothTransformation))
    lay.addWidget(mark)
    lay.addWidget(QLabel(title, objectName="brand"))
    sub = QLabel(subtitle, objectName="brandSub")
    sub.setMinimumWidth(1)
    lay.addWidget(sub, 1)
    btn_log = button("전송 내역", ghost=True, tip="이번 실행에서 Google로 보낸 내역")
    btn_settings = button("설정", ghost=True, tip="Gemini API 키·사용 여부")
    lay.addWidget(btn_log)
    lay.addWidget(btn_settings)
    return bar, btn_log, btn_settings


def section(no: str, title: str, hint: str = "") -> tuple[QFrame, QVBoxLayout]:
    """번호·제목·설명이 있는 카드. (카드, 내용 레이아웃)."""
    card = QFrame(objectName="card")
    lay = QVBoxLayout(card)
    lay.setContentsMargins(16, 14, 16, 16)
    lay.setSpacing(10)
    head = QHBoxLayout()
    head.setSpacing(8)
    num = QLabel(no, objectName="stepNo")
    num.setAlignment(Qt.AlignmentFlag.AlignCenter)
    head.addWidget(num)
    head.addWidget(QLabel(title, objectName="sectionTitle"), 1)
    lay.addLayout(head)
    if hint:
        h = QLabel(hint, objectName="hint")
        h.setWordWrap(True)
        h.setMinimumWidth(1)
        lay.addWidget(h)
    return card, lay


def photo_card() -> tuple:
    """① 현장 사진 카드. (카드, 열기 버튼, 카메라 버튼, 파일 이름, 해상도)."""
    card, c = section("1", "현장 사진")
    row = QHBoxLayout()
    btn_open = button("사진 열기", tip="JPG · PNG · HEIC (창에 끌어다 놓아도 됩니다)")
    btn_camera = button("카메라")
    row.addWidget(btn_open, 1)
    row.addWidget(btn_camera)
    c.addLayout(row)
    # 파일 이름과 해상도를 따로 표시: 한 줄로 합치면 말줄임이 확장자·해상도 사이를 잘라 글자가 깨져 보임
    file_label = ElidedLabel("아직 사진이 없습니다", objectName="fileName")
    size_label = QLabel("", objectName="counter")
    size_label.hide()
    c.addWidget(file_label)
    c.addWidget(size_label)
    return card, btn_open, btn_camera, file_label, size_label


def request_card(clear_debris: bool, edge_finish: bool) -> tuple:
    """③ 세부 요청 카드. (카드, 잔해 정리 체크, 가장자리 마감 체크, 추가 요청 입력)."""
    card, c = section("3", "세부 요청 (선택)", "더 자세히 바꾸고 싶은 점을 적으세요. 길 밖은 어떤 요청에도 바뀌지 않습니다.")
    chk_debris = QCheckBox("길 위 나뭇가지·낙엽·돌 깨끗이 정리")
    chk_debris.setToolTip("길 위에 떨어진 잔가지·뿌리·낙엽·돌·쓰레기를 치우고 포장하도록 요청합니다")
    chk_debris.setChecked(clear_debris)
    chk_edge = QCheckBox("길 가장자리 마감재(경계석·자연석 등) 시공")
    chk_edge.setToolTip("길 양옆을 주변 환경과 어울리는 경계석·자연석 등으로 깔끔하게 마감하도록 요청합니다")
    chk_edge.setChecked(edge_finish)
    note = NotePanel()
    for w in (chk_debris, chk_edge, note):
        c.addWidget(w)
    return card, chk_debris, chk_edge, note


def material_icon(material, materials_dir: Path | None) -> QIcon:
    """소재 썸네일: 참고 사진 가운데 정사각 → 없으면 색 견본."""
    pix = QPixmap(THUMB, THUMB)
    p = reference_path(materials_dir, material)
    img = None
    if p is not None:
        try:
            img = image_io.load_image(str(p))
        except (OSError, ValueError):
            img = None
    if img is not None:
        h, w = img.shape[:2]
        s = min(h, w)
        crop = np.ascontiguousarray(img[(h - s) // 2:(h + s) // 2, (w - s) // 2:(w + s) // 2])
        pix = bgr_to_pixmap(crop).scaled(THUMB, THUMB, Qt.AspectRatioMode.IgnoreAspectRatio,
                                         Qt.TransformationMode.SmoothTransformation)
    else:
        colors = list(dict.fromkeys(getattr(material, "base_colors", None) or ["#CBD5E1"]))
        pix.fill(QColor(colors[0]))
        qp = QPainter(pix)
        step = THUMB / len(colors)
        for i, c in enumerate(colors):
            qp.fillRect(int(i * step), 0, int(step) + 1, THUMB, QColor(c))
        qp.end()
    icon = QIcon(pix)
    icon.addPixmap(pix, QIcon.Mode.Selected)       # 선택된 항목에서도 색이 바래지 않게(Qt 기본은 선택색으로 물들임)
    return icon


class MaterialPanel(QWidget):
    """바닥 소재 선택(기본 코르크 + 사용자 추가). changed(id), addRequested, removeRequested(id)."""
    changed = Signal(str)
    addRequested = Signal()
    removeRequested = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self.list = QListWidget(objectName="materials")
        self.list.setIconSize(QSize(THUMB, THUMB))
        self.list.setSpacing(0)
        self.list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.list.currentItemChanged.connect(self._current_changed)
        lay.addWidget(self.list)
        row = QHBoxLayout()
        self.btn_add = button("+ 소재 샘플 추가", tip="다른 바닥재 사진을 등록하면 그 소재로 바꿔 보여 줍니다")
        self.btn_add.clicked.connect(self.addRequested)
        self.btn_remove = button("삭제", ghost=True, danger=True, tip="직접 추가한 소재만 삭제할 수 있습니다")
        self.btn_remove.clicked.connect(lambda: self.removeRequested.emit(self.current_id()))
        row.addWidget(self.btn_add, 1)
        row.addWidget(self.btn_remove)
        lay.addLayout(row)

    def set_materials(self, materials: list, materials_dir: Path | None, select: str | None = None) -> None:
        keep = select or self.current_id()
        self.list.blockSignals(True)
        self.list.clear()
        for m in materials:
            custom = isinstance(m, CustomMaterial)
            it = QListWidgetItem(material_icon(m, materials_dir), f"{m.name}\n{'직접 추가한 소재' if custom else '코르크'}")
            it.setData(Qt.ItemDataRole.UserRole, m.id)
            it.setData(Qt.ItemDataRole.UserRole + 1, custom)
            it.setSizeHint(QSize(0, THUMB + 16))
            self.list.addItem(it)
        self.list.blockSignals(False)
        ids = [m.id for m in materials]
        self.list.setCurrentRow(ids.index(keep) if keep in ids else 0)
        rows = min(len(materials), 5)
        self.list.setFixedHeight(rows * (THUMB + 22) + 4)
        self._sync()

    def current_id(self) -> str:
        it = self.list.currentItem()
        return it.data(Qt.ItemDataRole.UserRole) if it else ""

    def _current_changed(self, *_):
        self._sync()
        self.changed.emit(self.current_id())

    def _sync(self) -> None:
        it = self.list.currentItem()
        self.btn_remove.setEnabled(bool(it and it.data(Qt.ItemDataRole.UserRole + 1)))


class NotePanel(QWidget):
    """추가 요청 입력(선택). 글자 수 제한·표시."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.edit = QPlainTextEdit()
        self.edit.setPlaceholderText("예) 길 가장자리 경계석은 그대로 두고, 벤치 앞 넓은 곳까지 포장해 주세요.")
        self.edit.setFixedHeight(92)
        self.edit.setTabChangesFocus(True)
        self.edit.textChanged.connect(self._changed)
        self.counter = QLabel(f"0 / {NOTE_MAX}", objectName="counter")
        self.counter.setAlignment(Qt.AlignmentFlag.AlignRight)
        lay.addWidget(self.edit)
        lay.addWidget(self.counter)

    def text(self) -> str:
        return self.edit.toPlainText().strip()

    def _changed(self) -> None:
        t = self.edit.toPlainText()
        if len(t) > NOTE_MAX:                      # 붙여넣기로 넘쳐도 자른다
            self.edit.blockSignals(True)
            self.edit.setPlainText(t[:NOTE_MAX])
            self.edit.moveCursor(self.edit.textCursor().MoveOperation.End)
            self.edit.blockSignals(False)
            t = t[:NOTE_MAX]
        self.counter.setText(f"{len(t)} / {NOTE_MAX}")


class DropZone(QFrame):
    """사진이 없을 때 보이는 안내 + [사진 선택]."""
    openRequested = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent, objectName="dropzone")
        lay = QVBoxLayout(self)
        lay.setSpacing(12)
        lay.addStretch(1)
        icon = QLabel("+", objectName="dropIcon")
        icon.setFixedSize(56, 56)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(icon, alignment=Qt.AlignmentFlag.AlignHCenter)
        title = QLabel("현장 사진을 여기에 끌어다 놓으세요", objectName="dropTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(title)
        desc = QLabel("흙길만 선택한 바닥 소재로 바꾼 시공 예상도를 자동으로 만듭니다.\n"
                      "JPG · PNG · HEIC", objectName="hint")
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(desc)
        self.btn = button("사진 선택", primary=True)
        self.btn.setMinimumWidth(160)
        self.btn.clicked.connect(self.openRequested)
        lay.addWidget(self.btn, alignment=Qt.AlignmentFlag.AlignHCenter)
        lay.addStretch(1)


class AddMaterialDialog(QDialog):
    """소재 샘플 사진 + 이름 입력. 검증·저장은 materials.add_custom이 한다."""

    def __init__(self, start_dir: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("소재 샘플 추가")
        self.setMinimumWidth(440)
        self.start_dir, self.path = start_dir, ""
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 20, 20, 20)
        lay.setSpacing(10)
        info = QLabel("바닥재 표면이 화면 가득 잘 보이는 사진을 고르세요. 사람·글자·로고가 없는 사진이 좋습니다.\n"
                      "이 사진은 변환할 때 현장 사진과 함께 Google Gemini로 전송됩니다.", objectName="hint")
        info.setWordWrap(True)
        lay.addWidget(info)
        self.preview = QLabel("선택한 사진 없음", objectName="hint")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setFixedHeight(180)
        self.preview.setStyleSheet("background:#F1F5F9;border-radius:8px;")
        lay.addWidget(self.preview)
        pick = button("사진 고르기…")
        pick.clicked.connect(self._pick)
        lay.addWidget(pick)
        lay.addWidget(QLabel("소재 이름", objectName="sectionTitle"))
        self.name = QLineEdit(placeholderText="예) 화강석 블록, 마사토, 우레탄")
        self.name.setMaxLength(NAME_MAX)
        self.name.textChanged.connect(self._sync)
        lay.addWidget(self.name)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = button("취소")
        cancel.clicked.connect(self.reject)
        self.ok = button("추가", primary=True)
        self.ok.clicked.connect(self.accept)
        row.addWidget(cancel)
        row.addWidget(self.ok)
        lay.addLayout(row)
        self._sync()

    def _pick(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "소재 샘플 사진", self.start_dir, PHOTO_FILTER)
        if path:
            self.set_path(path)

    def set_path(self, path: str) -> None:
        self.path = path
        try:
            img = image_io.make_preview(image_io.load_image(path), 600)[0]
            self.preview.setPixmap(bgr_to_pixmap(img).scaled(400, 180, Qt.AspectRatioMode.KeepAspectRatio,
                                                              Qt.TransformationMode.SmoothTransformation))
        except (OSError, ValueError):
            self.preview.setText("사진으로 읽을 수 없는 파일입니다")
            self.path = ""
        if self.path and not self.name.text().strip():
            self.name.setText(Path(path).stem[:NAME_MAX])
        self._sync()

    def _sync(self) -> None:
        self.ok.setEnabled(bool(self.path and self.name.text().strip()))
