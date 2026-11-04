from PySide6.QtMultimedia import QCameraDevice

from app.ui import camera_dialog as cd


class FakeDev:
    def __init__(self, pos, null=False):
        self._pos, self._null = pos, null

    def position(self):
        return self._pos

    def isNull(self):
        return self._null


def fake_devices(monkeypatch, devices, default=None):
    class FakeMD:
        @staticmethod
        def videoInputs():
            return devices

        @staticmethod
        def defaultVideoInput():
            return default or FakeDev(None, null=True)

    monkeypatch.setattr(cd, "QMediaDevices", FakeMD)


def test_has_camera_real_system_no_error(qapp):
    assert isinstance(cd.has_camera(), bool)


def test_no_camera(monkeypatch, qapp):
    fake_devices(monkeypatch, [])
    assert cd.has_camera() is False
    assert cd.pick_camera() is None
    dlg = cd.CameraDialog()                  # 카메라 없어도 오류 없이 생성
    assert not dlg.btn_shot.isEnabled()
    assert "카메라를 찾을 수 없습니다" in dlg.status.text()
    dlg.reject()


def test_back_camera_preferred(monkeypatch):
    front = FakeDev(QCameraDevice.Position.FrontFace)
    back = FakeDev(QCameraDevice.Position.BackFace)
    fake_devices(monkeypatch, [front, back], default=front)
    assert cd.pick_camera() is back


def test_default_when_no_back_camera(monkeypatch):
    a = FakeDev(QCameraDevice.Position.UnspecifiedPosition)
    b = FakeDev(QCameraDevice.Position.FrontFace)
    fake_devices(monkeypatch, [a, b], default=b)
    assert cd.pick_camera() is b
