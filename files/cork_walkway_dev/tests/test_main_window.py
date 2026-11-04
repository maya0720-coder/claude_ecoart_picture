from app.config import DEFAULTS
from app.ui.main_window import MainWindow


def test_main_window_shows(qapp):
    w = MainWindow(DEFAULTS)
    w.show()
    qapp.processEvents()
    assert w.isVisible()
    assert w.windowTitle() == "코르크 산책로 시공 예상도"
    w.close()
