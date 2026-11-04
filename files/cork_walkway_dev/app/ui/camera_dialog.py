"""PC·태블릿 카메라 촬영 창 (모듈 01).

촬영 이미지는 파일로 저장하지 않고 메모리(QImage)로만 받는다.
"""
from __future__ import annotations

import numpy as np
from PySide6.QtMultimedia import (QCamera, QCameraDevice, QImageCapture,
                                  QMediaCaptureSession, QMediaDevices)
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from app.core.image_io import qimage_to_bgr


def has_camera() -> bool:
    """카메라가 하나라도 있으면 True. False면 [카메라로 촬영] 버튼을 숨긴다."""
    return len(QMediaDevices.videoInputs()) > 0


def pick_camera() -> QCameraDevice | None:
    """후면 카메라 우선, 없으면 기본 카메라, 카메라가 없으면 None."""
    devices = QMediaDevices.videoInputs()
    if not devices:
        return None
    for d in devices:
        if d.position() == QCameraDevice.Position.BackFace:
            return d
    default = QMediaDevices.defaultVideoInput()
    return default if not default.isNull() else devices[0]


class CameraDialog(QDialog):
    """exec()가 Accepted면 self.image에 BGR uint8 사진이 들어 있다."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("카메라로 촬영")
        self.resize(960, 720)
        self.image: np.ndarray | None = None

        self.video = QVideoWidget()
        self.status = QLabel("")
        self.btn_shot = QPushButton("촬영")
        self.btn_cancel = QPushButton("취소")
        for b in (self.btn_shot, self.btn_cancel):
            b.setMinimumHeight(48)
        buttons = QHBoxLayout()
        buttons.addWidget(self.btn_cancel)
        buttons.addWidget(self.btn_shot)
        layout = QVBoxLayout(self)
        layout.addWidget(self.video, 1)
        layout.addWidget(self.status)
        layout.addLayout(buttons)

        self.btn_cancel.clicked.connect(self.reject)
        self.btn_shot.clicked.connect(self._capture)

        device = pick_camera()
        self.camera: QCamera | None = None
        self.capture: QImageCapture | None = None
        if device is None:
            self._fail("카메라를 찾을 수 없습니다. [사진 열기]로 파일을 선택하세요.")
            return
        self.camera = QCamera(device)
        self.capture = QImageCapture()
        self.session = QMediaCaptureSession()
        self.session.setCamera(self.camera)
        self.session.setImageCapture(self.capture)
        self.session.setVideoOutput(self.video)
        self.camera.errorOccurred.connect(
            lambda _err, msg: self._fail(f"카메라 오류: {msg}. 다른 프로그램이 카메라를 쓰고 있으면 닫고 다시 시도하세요."))
        self.capture.errorOccurred.connect(
            lambda _id, _err, msg: self._fail(f"촬영 실패: {msg}. 다시 촬영하세요.", keep_button=True))
        self.capture.imageCaptured.connect(self._on_captured)
        self.camera.start()

    def _capture(self) -> None:
        if self.capture is None or not self.capture.isReadyForCapture():
            self.status.setText("카메라 준비 중입니다. 잠시 후 다시 누르세요.")
            return
        self.btn_shot.setEnabled(False)
        self.status.setText("촬영 중…")
        self.capture.capture()

    def _on_captured(self, _id: int, qimg) -> None:
        try:
            self.image = qimage_to_bgr(qimg)
        except ValueError:
            self._fail("촬영 이미지가 비어 있습니다. 다시 촬영하세요.", keep_button=True)
            return
        self.accept()

    def _fail(self, msg: str, keep_button: bool = False) -> None:
        self.status.setText(msg)
        self.btn_shot.setEnabled(keep_button and self.capture is not None)

    def done(self, result: int) -> None:
        if self.camera is not None:
            self.camera.stop()
        super().done(result)
