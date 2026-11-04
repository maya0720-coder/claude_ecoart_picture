"""실행 진입점: python -m app.main"""
from __future__ import annotations

import sys

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from app.config import load_config
from app.security.privacy import cleanup_temp, setup_logging
from app.ui.main_window import MainWindow


def main() -> int:
    setup_logging()
    cleanup_temp()                      # 지난 비정상 종료로 남은 임시 파일 정리
    app = QApplication(sys.argv)
    app.setFont(QFont("Malgun Gothic", 10))
    app.aboutToQuit.connect(cleanup_temp)
    window = MainWindow(load_config())
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
