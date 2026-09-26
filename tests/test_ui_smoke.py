import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

from types import SimpleNamespace

from PySide6.QtWidgets import QApplication

from intrader.ui.components import MarketChart
from intrader.ui.mode_pages import AnalysisModePage, IntraderModePage, TimeTravelPage
from intrader.ui.strategy_lab_page import StrategyLabPage
from intrader.ui.utility_pages import (
    DashboardPage, ExportPage, RecordsManagerPage, ShadowTraderPage,
    SystemHealthPage, ThesisPage, TradeHistoryPage,
)


def test_primary_and_supporting_pages_construct_offscreen() -> None:
    app = QApplication.instance() or QApplication([])
    pages = [
        DashboardPage(),
        IntraderModePage(),
        TimeTravelPage(),
        AnalysisModePage(),
        StrategyLabPage(),
        ThesisPage(),
        ShadowTraderPage(),
        RecordsManagerPage(),
        TradeHistoryPage(),
        SystemHealthPage(),
        ExportPage(),
    ]

    assert all(page is not None for page in pages)



def test_time_travel_exposes_replay_range_and_reanalysis_controls() -> None:
    app = QApplication.instance() or QApplication([])
    page = TimeTravelPage()

    assert page.tabs.count() == 2
    assert page.tabs.tabText(0) == "30-Minute Replay"
    assert "Range Analysis" in page.tabs.tabText(1)
    assert page.reanalyze_button.text() == "Re-analyze with Current Brain"
    assert page.range_load_button.text() == "Analyze Period"


def test_market_chart_empty_state_hides_meaningless_axes() -> None:
    app = QApplication.instance() or QApplication([])
    chart = MarketChart()

    chart.set_empty_message("No candle data available.")

    assert chart.plot.getAxis("left").isVisible() is False
    assert chart.plot.getAxis("bottom").isVisible() is False


def test_time_travel_range_results_render_without_fake_data() -> None:
    app = QApplication.instance() or QApplication([])
    page = TimeTravelPage()
    analysis = SimpleNamespace(
        change_pct=None,
        session_count=0,
        high=None,
        low=None,
        adjusted_pnl=0,
        expectancy=None,
        news_count=0,
        analysis_notes=("No evidence available.",),
        key_moments=(),
        decision_counts=(),
        regime_counts=(),
        coverage=(("Candles", "UNAVAILABLE"),),
    )
    opening = SimpleNamespace(
        bullish_weight=33,
        balanced_weight=34,
        bearish_weight=33,
        gap_risk=0,
        next_session_candidate="2026-09-28",
        bias_score=0,
        evidence_coverage=0,
        drivers=(),
        limitations=("Scenario weights are not calibrated probabilities.",),
    )

    page.set_range_analysis(analysis, opening, ())

    assert page.range_change.value_label.text() == "N/A"
    assert page.range_sessions.value_label.text() == "0"
    assert page.range_coverage.rowCount() == 1
    assert page.range_notes.rowCount() == 1



def test_strategy_lab_is_separate_research_mode() -> None:
    app = QApplication.instance() or QApplication([])
    page = StrategyLabPage()

    assert page.analyze_button.text() == "Analyze Strategies"
    assert page.source_filter.findText("Steve Nison") >= 0
    assert page.source_filter.findText("Ashwani Gujral") >= 0
    assert page.source_filter.findText("John Carter") >= 0
    assert page.source_filter.findText("Mark Douglas") >= 0

    snapshot = SimpleNamespace(
        candle_count=0,
        session_count=0,
        strategies=(),
        notes=(
            "LAB ONLY: no Strategy Lab result is consumed by Intrader Mode.",
        ),
    )
    page.set_snapshot(snapshot)

    assert page.total_signals.value_label.text() == "0"
    assert page.active_strategies.value_label.text() == "0"
    assert page.best_hit.value_label.text() == "N/A"
    assert page.notes.rowCount() == 1
