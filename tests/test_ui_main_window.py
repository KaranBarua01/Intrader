import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

import intrader.ui.utility_pages as utility_pages
from intrader.ui.main_window import MainWindow


def _window(monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(utility_pages, "QWebEngineView", None)
    monkeypatch.setattr(MainWindow, "refresh_all", lambda self: None)
    window = MainWindow()
    return app, window


def test_bottom_dock_is_hidden_until_requested(monkeypatch) -> None:
    app, window = _window(monkeypatch)
    window.resize(1000, 700)
    app.processEvents()

    assert window.bottom_dock.isHidden()
    assert window.dock_handle.isVisible()

    window.toggle_bottom_dock()
    app.processEvents()

    assert window.bottom_dock.isVisible()
    assert window.bottom_dock.geometry().left() >= 0
    assert window.bottom_dock.geometry().right() <= window.centralWidget().width()


def test_windowed_mode_uses_scrollable_responsive_page_wrappers(monkeypatch) -> None:
    app, window = _window(monkeypatch)
    window.resize(900, 620)
    window.show_page("Strategy Lab")
    app.processEvents()

    assert window.minimumWidth() == 900
    wrapper = window._pages["Strategy Lab"]
    assert wrapper.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    assert wrapper.widgetResizable() is True


def test_theme_and_layout_preset_are_runtime_switchable(monkeypatch) -> None:
    app, window = _window(monkeypatch)

    window.apply_theme("Frost")
    window.show_page("Time Travel")
    window.apply_layout_preset("Analysis")
    app.processEvents()

    assert window.current_theme == "Frost"
    assert window.layout_combo.currentText() in {
        "Balanced", "Compact", "Analysis", "Monitoring"
    }
