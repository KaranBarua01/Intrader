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
    window.show()
    app.processEvents()
    return app, window


def test_bottom_dock_is_hidden_until_requested(monkeypatch) -> None:
    app, window = _window(monkeypatch)
    window.resize(1000, 700)
    app.processEvents()

    assert window.bottom_dock.isHidden()
    assert window.dock_handle.isVisible()
    assert window.dock_handle.dock_open() is False

    window.toggle_bottom_dock()
    app.processEvents()

    assert window.bottom_dock.isVisible()
    assert window.dock_handle.dock_open() is True
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


def test_accent_is_runtime_switchable_without_theme_modes(monkeypatch) -> None:
    app, window = _window(monkeypatch)

    window.apply_accent("#5E7FAE")
    window.show_page("Time Travel")
    window.apply_layout_preset("Compact")
    app.processEvents()

    assert window.current_accent == "#5E7FAE"
    assert window.accent_selector.accent() == "#5E7FAE"
    assert not hasattr(window, "theme_combo")
    assert not hasattr(window, "layout_combo")


def test_shadow_trader_is_a_primary_navigation_tab(monkeypatch) -> None:
    app, window = _window(monkeypatch)
    app.processEvents()

    assert "Shadow Trader" in window._nav_buttons
    assert window._nav_buttons["Shadow Trader"].text() == "Shadow Trader"
    assert all(
        action.text() != "Shadow Trader"
        for action in window.more_menu.actions()
    )

    window.show_page("Shadow Trader")
    app.processEvents()

    assert window.stack.currentWidget() is window._pages["Shadow Trader"]
    assert window._nav_buttons["Shadow Trader"].property("active") is True
