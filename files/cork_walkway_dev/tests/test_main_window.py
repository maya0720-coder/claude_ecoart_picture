from app.config import DEFAULTS
from app.ui.main_window import MainWindow


def test_main_window_shows(qapp):
    w = MainWindow(DEFAULTS)
    w.show()
    qapp.processEvents()
    assert w.isVisible()
    assert w.windowTitle() == "시공 시뮬레이터 — 단계별 화면"
    w.close()
