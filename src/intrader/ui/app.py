"""Desktop application entry point."""

from __future__ import annotations

import os
import sys

from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication

from intrader import __version__
from intrader.ui.main_window import MainWindow


def main() -> int:
    os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")
    QCoreApplication.setOrganizationName("Intrader")
    QCoreApplication.setApplicationName("Intrader")
    QCoreApplication.setApplicationVersion(__version__)
    app = QApplication.instance() or QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
