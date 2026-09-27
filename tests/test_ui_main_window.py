import os
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

import intrader.ui.utility_pages as utility_pages
from intrader.historical import Candle, INDIA_TIME
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

    assert page.development_days.minimum() == 1
    assert page.development_days.maximum() == 500
    assert page.blind_days.minimum() == 1
    assert page.blind_days.maximum() == 500
    assert page.development_days.value() == 60
    assert page.blind_days.value() == 30
    assert [page.replay_mode.itemData(i) for i in range(page.replay_mode.count())] == [
        "LOW", "MEDIUM", "HIGH"
    ]
    assert [page.validation_mode.itemData(i) for i in range(page.validation_mode.count())] == [
        "STANDARD", "WALK_FORWARD"
    ]
    assert [page.execution_mode.itemData(i) for i in range(page.execution_mode.count())] == [
        "PROXY", "OPTION_PREMIUM"
    ]
    assert page.selected_replay_sessions() == 90
    assert page.selected_replay_mode() == "MEDIUM"
    assert tuple(
        timeframe for timeframe, check in page.trader_checks.items() if check.isChecked()
    ) == (1, 5, 10, 15)
    assert page.starting_capital.value() == 50000
    assert page.replay_start_button.text().startswith("▶")


def _arena_report(*, development_sessions: int = 20):
    config = SimpleNamespace(
        development_sessions=development_sessions,
        blind_sessions=10,
        total_sessions=30,
        mode_key="MEDIUM",
        validation_mode="STANDARD",
        starting_capital=Decimal("50000"),
    )
    metrics = SimpleNamespace(
        trades=1,
        wins=1,
        losses=0,
        win_rate_pct=Decimal("100"),
        average_return_pct=Decimal("0.10"),
        profit_factor=None,
    )
    paper = SimpleNamespace(
        starting_capital=Decimal("50000"),
        ending_capital=Decimal("50012.50"),
        net_pnl=Decimal("12.50"),
        return_pct=Decimal("0.025"),
        max_drawdown_pct=Decimal("0"),
    )
    trade = SimpleNamespace(
        timeframe_minutes=1,
        trader_label="1M SCALPER",
        engine_id="engine1234567890",
        strategy_name="Synthetic Strategy",
        phase="BLIND",
        opened_at="2026-08-01T09:15:00+05:30",
        closed_at="2026-08-01T09:25:00+05:30",
        hold_minutes=10,
        direction="CALL / LONG",
        entry_underlying=Decimal("24001"),
        exit_underlying=Decimal("24031"),
        gross_return_pct=Decimal("0.125"),
        net_return_pct=Decimal("0.100"),
        paper_pnl=Decimal("12.50"),
        paper_balance_after=Decimal("50012.50"),
        mfe_pct=Decimal("0.15"),
        mae_pct=Decimal("-0.02"),
        regime="TRENDING_UP",
        time_bucket="09:15–10:00",
        feature_scores=(("NIFTY price / structure", Decimal("0.4")),),
        exit_reason="TIME_EXIT",
        result="WIN",
    )
    slice_stat = SimpleNamespace(
        key="TRENDING_UP",
        trades=1,
        wins=1,
        losses=0,
        average_return_pct=Decimal("0.10"),
        net_pnl=Decimal("12.50"),
        profit_factor=None,
    )
    trader = SimpleNamespace(
        timeframe_minutes=1,
        trader_label="1M SCALPER",
        engine_id="engine1234567890",
        hold_minutes=10,
        selected_strategy_name="Synthetic Strategy",
        blind_metrics=metrics,
        blind_paper=paper,
        trades=(trade,),
        rejected_signals=(),
        regime_stats=(slice_stat,),
        time_stats=(),
    )
    coverage = SimpleNamespace(
        requested_touchpoints=30,
        available_touchpoints=15,
        decision_used_touchpoints=10,
        requested_families=(
            "NIFTY price / structure",
            "Momentum / volatility",
            "Futures",
        ),
        available_families=(
            "NIFTY price / structure",
            "Momentum / volatility",
            "Futures",
        ),
        decision_used_families=(
            "NIFTY price / structure",
            "Momentum / volatility",
        ),
    )
    ablation = SimpleNamespace(
        trader_label="1M SCALPER",
        label="BASE_STRATEGY",
        families=(),
        trades=1,
        net_pnl=Decimal("12.50"),
        return_pct=Decimal("0.025"),
        profit_factor=None,
        max_drawdown_pct=Decimal("0"),
    )
    return SimpleNamespace(
        config=config,
        actual_sessions=30,
        total_sessions=30,
        first_session="2026-07-01",
        last_session="2026-08-15",
        blind_start="2026-08-01",
        blind_end="2026-08-15",
        blind_previously_reviewed=False,
        feature_coverage=coverage,
        trader_reports=(trader,),
        ablation_results=(ablation,),
        walk_forward_results=(),
    )


def test_shadow_trader_results_tab_populates_05_research_outputs(monkeypatch) -> None:
    app, window = _window(monkeypatch)
    page = window.shadow_page
    report = _arena_report()

    page.set_replay_report(report)
    app.processEvents()

    assert page.tabs.tabText(page.results_tab_index) == "Results"
    assert page.tabs.currentIndex() == page.results_tab_index
    assert page.results_export_button.isEnabled()
    assert page.results_tournament.rowCount() == 1
    assert page.results_trades.rowCount() == 1
    assert page.results_rejected.rowCount() == 0
    assert page.results_ablation.rowCount() == 1
    assert page.results_slices.rowCount() == 1
    assert page.results_touchpoints_metric.value_label.text() == "10 / 30"


def test_shadow_arena_hides_pnl_until_causal_exit(monkeypatch) -> None:
    app, window = _window(monkeypatch)
    page = window.shadow_page
    start = datetime(2026, 8, 1, 9, 15, tzinfo=INDIA_TIME)
    candles = tuple(
        Candle(
            at=start + timedelta(minutes=index),
            open=Decimal("24000") + Decimal(index),
            high=Decimal("24002") + Decimal(index),
            low=Decimal("23998") + Decimal(index),
            close=Decimal("24001") + Decimal(index),
            volume=1000 + index,
        )
        for index in range(11)
    )
    report = _arena_report(development_sessions=0)

    page.begin_visual_playback(candles, report)
    page._playback_timer.stop()
    page.live_speed.setCurrentIndex(page.live_speed.findData(10))

    page._playback_tick()
    app.processEvents()

    open_rows = [
        row for row in range(page.live_tape.rowCount())
        if page.live_tape.item(row, 3).text() == "OPEN"
    ]
    assert open_rows
    row = open_rows[-1]
    assert page.live_tape.item(row, 7).text() == "hidden"
    assert page.live_tape.item(row, 8).text() == "ACTIVE"

    for _ in range(10):
        page._playback_tick()
    app.processEvents()

    close_rows = [
        row for row in range(page.live_tape.rowCount())
        if page.live_tape.item(row, 3).text() == "CLOSE 10m"
    ]
    assert close_rows
    row = close_rows[-1]
    assert page.live_tape.item(row, 7).text() == "₹12.50"
    assert page.live_tape.item(row, 8).text() == "WIN"


def test_shadow_arena_has_day_pacing_skip_and_on_demand_chart(monkeypatch) -> None:
    app, window = _window(monkeypatch)
    page = window.shadow_page
    app.processEvents()

    assert [page.live_speed.itemText(i) for i in range(page.live_speed.count())] == [
        "5 sec / day", "10 sec / day", "20 sec / day", "MAX"
    ]
    assert page.live_speed.currentData() == 10
    assert page.live_skip_button.text() == "Skip to Results"
    assert page.live_chart_button.text() == "Open Chart"
    assert page.live_chart.isHidden()
