import os
from decimal import Decimal
from types import SimpleNamespace

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


def test_shadow_trader_replay_controls_are_present(monkeypatch) -> None:
    app, window = _window(monkeypatch)
    page = window.shadow_page
    app.processEvents()

    assert [page.replay_range.itemData(i) for i in range(page.replay_range.count())] == [30, 60, 90]
    assert [page.replay_mode.itemData(i) for i in range(page.replay_mode.count())] == [
        "LOW", "MEDIUM", "HIGH"
    ]
    assert page.selected_replay_sessions() == 90
    assert page.selected_replay_mode() == "MEDIUM"
    assert page.replay_start_button.text().startswith("▶")
    assert "Export Results" in page.replay_export_button.text()


def test_shadow_trader_results_tab_populates_and_opens(monkeypatch) -> None:
    app, window = _window(monkeypatch)
    page = window.shadow_page

    metrics = SimpleNamespace(
        sessions=10,
        evaluable_signals=3,
        wins=2,
        losses=1,
        win_rate_pct=Decimal("66.6667"),
        average_return_30m_pct=Decimal("0.12"),
        average_winner_pct=Decimal("0.20"),
        average_loser_pct=Decimal("-0.04"),
        profit_factor=Decimal("2.5"),
        max_drawdown_pct_points=Decimal("0.04"),
        max_losing_streak=1,
    )
    candidate = SimpleNamespace(
        strategy_name="Synthetic Strategy",
        signals=8,
        hit_rate_30m_pct=Decimal("62.5"),
        average_return_30m_pct=Decimal("0.08"),
        sample_label="EARLY",
    )
    trade = SimpleNamespace(
        phase="BLIND",
        at="2026-08-01T10:00:00+05:30",
        direction="CALL / LONG",
        entry_underlying=Decimal("24000"),
        approx_exit_underlying_30m=Decimal("24024"),
        return_5m_pct=Decimal("0.02"),
        return_15m_pct=Decimal("0.06"),
        return_30m_pct=Decimal("0.10"),
        mfe_30m_pct=Decimal("0.14"),
        mae_30m_pct=Decimal("-0.03"),
        result="WIN",
    )
    report = SimpleNamespace(
        selected_strategy_name="Synthetic Strategy",
        development_sessions=20,
        blind_sessions=10,
        actual_sessions=30,
        requested_touchpoints=30,
        mode="MEDIUM",
        first_session="2026-07-01",
        last_session="2026-08-15",
        development=metrics,
        blind=metrics,
        candidates=(candidate,),
        trades=(trade,),
    )

    page.set_replay_report(report)
    app.processEvents()

    assert page.tabs.tabText(page.results_tab_index) == "Results"
    assert page.tabs.currentIndex() == page.results_tab_index
    assert page.results_export_button.isEnabled()
    assert page.results_trades.rowCount() == 1
    assert page.results_comparison.rowCount() == 2
    assert page.results_candidates.rowCount() == 1
