"""설정 창, 전송 전 확인 창, 전송 내역 창 (모듈 08·10)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QFormLayout, QGroupBox, QHBoxLayout,
                               QLabel, QLineEdit, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem,
                               QVBoxLayout)

from app.config import load_user_settings, save_user_settings
from app.security.privacy import NOTICE_CONSENT, NOTICE_RETENTION, TransferLog
from app.security.secrets import GEMINI_KEY, delete_key, get_key, mask_key, set_key
from app.ui.widgets import bgr_to_pixmap, big_button

AI_STUDIO_LOGGING = ("추가 권장: Google AI Studio의 Logs and Datasets → Settings에서 Generate Content API 로깅을 꺼 두세요. "
                     "앱은 요청마다 store=false(서버 기록 끄기)를 보냅니다.")


class SettingsDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("설정")
        self.setMinimumWidth(520)
        self.settings = load_user_settings()

        self.watermark = QCheckBox("결과물에 \"가상 시공 예상도\" 표기 넣기")
        self.watermark.setChecked(self.settings["watermark"])

        g = QGroupBox("고품질 모드 (Google Gemini, 선택 기능)")
        self.hq_on = QCheckBox("고품질 모드 사용 (사진 일부가 인터넷으로 전송됨)")
        self.hq_on.setChecked(self.settings["gemini_enabled"])
        self.paid = QCheckBox("Cloud Billing이 연결된 유료 키임을 확인함")
        self.paid.setChecked(self.settings["gemini_paid_key_confirmed"])
        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_edit.setPlaceholderText("새 API 키 붙여넣기")
        self.key_state = QLabel()
        self.btn_key_del = QPushButton("키 삭제")
        self.btn_key_del.clicked.connect(self._delete_key)
        self.candidates = QSpinBox()
        self.candidates.setRange(1, 3)
        self.candidates.setValue(self.settings["hq_candidates"])
        notes = QLabel(f"{NOTICE_CONSENT}\n\n{NOTICE_RETENTION}\n\n{AI_STUDIO_LOGGING}")
        notes.setWordWrap(True)
        notes.setObjectName("banner")
        form = QFormLayout()
        form.addRow(self.hq_on)
        form.addRow(self.paid)
        key_row = QHBoxLayout()
        key_row.addWidget(self.key_edit, 1)
        key_row.addWidget(self.btn_key_del)
        form.addRow("API 키", key_row)
        form.addRow("저장된 키", self.key_state)
        form.addRow("후보 수", self.candidates)
        gl = QVBoxLayout(g)
        gl.addLayout(form)
        gl.addWidget(notes)
        self.error = QLabel("")
        self.error.setStyleSheet("color: #c0392b;")

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._save)
        bb.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(self.watermark)
        lay.addWidget(g)
        lay.addWidget(self.error)
        lay.addWidget(bb)
        self._refresh_key()

    def _refresh_key(self) -> None:
        k = get_key(GEMINI_KEY)
        self.key_state.setText(mask_key(k) if k else "없음")
        self.btn_key_del.setEnabled(bool(k))

    def _delete_key(self) -> None:
        delete_key(GEMINI_KEY)
        self._refresh_key()

    def _save(self) -> None:
        new_key = self.key_edit.text()
        if new_key.strip():
            try:
                set_key(GEMINI_KEY, new_key)
            except ValueError as e:
                self.error.setText(str(e))
                return
            except Exception as e:
                self.error.setText(f"키를 Windows 자격 증명 관리자에 저장하지 못했습니다({type(e).__name__}). "
                                   "Windows 계정 상태를 확인하세요.")
                return
            finally:
                self.key_edit.clear()
        self.settings.update(watermark=self.watermark.isChecked(), gemini_enabled=self.hq_on.isChecked(),
                             gemini_paid_key_confirmed=self.paid.isChecked(), hq_candidates=self.candidates.value())
        save_user_settings(self.settings)
        self.accept()


class SendConfirmDialog(QDialog):
    """보낼 이미지 미리보기, 해상도, 대상 표시 후 [보내기]/[취소]."""

    def __init__(self, package, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("외부 전송 확인")
        img = QLabel()
        pix = bgr_to_pixmap(package.preview)
        img.setPixmap(pix.scaled(480, 360, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        w, h = package.sent_size
        info = QLabel(f"대상: {package.target}\n보낼 이미지: 2장(현장 사진 중 길 주변 일부, 로컬 예상도 같은 영역)\n"
                      f"해상도: {w}×{h}px, 사진 정보(EXIF·GPS)·파일명은 보내지 않음\n\n{NOTICE_CONSENT}")
        info.setWordWrap(True)
        self.skip = QCheckBox("이번 실행 동안 묻지 않기")
        self.btn_send = big_button("보내기", primary=True)
        self.btn_cancel = big_button("취소")
        self.btn_send.clicked.connect(self.accept)
        self.btn_cancel.clicked.connect(self.reject)
        row = QHBoxLayout()
        row.addWidget(self.skip)
        row.addStretch(1)
        row.addWidget(self.btn_cancel)
        row.addWidget(self.btn_send)
        lay = QVBoxLayout(self)
        lay.addWidget(img, alignment=Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(info)
        lay.addLayout(row)


class TransferLogDialog(QDialog):
    def __init__(self, log: TransferLog, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("이번 실행의 전송 내역")
        items = log.entries()
        t = QTableWidget(len(items), 4)
        t.setHorizontalHeaderLabels(["시각", "대상", "보낸 해상도", "잘라낸 영역"])
        for i, r in enumerate(items):
            for j, v in enumerate((r.time, r.target, "%d×%d ×%d장" % (*r.sent_size, r.images), "%d×%d" % r.region)):
                t.setItem(i, j, QTableWidgetItem(v))
        t.resizeColumnsToContents()
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("이미지 자체는 기록하지 않습니다." if items else "이번 실행에서 외부로 보낸 사진이 없습니다."))
        lay.addWidget(t)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.resize(560, 320)
