"""실행 진입점: python -m app.main"""
from __future__ import annotations

import sys

from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import QApplication

from app.config import load_config, resolve_resource
from app.security.privacy import cleanup_temp, setup_logging


APP_USER_MODEL_ID = "Ecoart.ConstructionSimulator"     # 작업 표시줄이 python.exe 대신 이 앱 아이콘으로 묶도록


def _set_taskbar_identity() -> None:
    """Windows 작업 표시줄 아이콘·묶음을 앱 단위로 지정(소스 실행 시 python 아이콘으로 보이는 문제)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except (AttributeError, OSError):
        pass                            # 실패해도 기능에는 영향 없음(아이콘 묶음만 기본값)


def main() -> int:
    setup_logging()
    _set_taskbar_identity()
    cleanup_temp()                      # 지난 비정상 종료로 남은 임시 파일 정리
    app = QApplication(sys.argv)
    app.setFont(QFont("Malgun Gothic", 10))
    app.setApplicationDisplayName("")                    # 창 제목 뒤에 프로그램 이름이 두 번 붙지 않게
    icon = resolve_resource("assets/app.png")
    if icon.is_file():
        app.setWindowIcon(QIcon(str(icon)))           # 창 왼쪽 위·작업 표시줄 아이콘
    app.aboutToQuit.connect(cleanup_temp)
    # 기본: 간편 모드(사진 → Gemini 앱에서 변환 → 결과 불러오기 → 전·후 비교). --classic: 단계별 로컬 렌더 화면
    try:
        if "--classic" in sys.argv[1:]:
            from app.ui.main_window import MainWindow
            window = MainWindow(load_config())
        else:
            from app.ui.quick_window import QuickWindow
            window = QuickWindow(load_config())
    except (ValueError, FileNotFoundError) as e:     # 설정 누락·형식 오류: 시작 시 명확하게 알리고 종료
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.critical(None, "설정 오류", str(e))
        return 1
    if hasattr(window, "fit_to_screen") and window.fit_to_screen():
        window.showMaximized()                         # 태블릿·작은 화면: 화면 가득
    else:
        window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
