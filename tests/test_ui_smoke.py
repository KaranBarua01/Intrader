import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

from types import SimpleNamespace

from PySide6.QtWidgets import QApplication

from intrader.ui.components import (
    BEARISH_COLOR, BULLISH_COLOR, LOGO_GREY, LOGO_RED, LogoMark,
    MarketChart, TriangleDockButton,
)
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
    assert page.range_load_button.text() == "▶  Analyze Period"
    assert page.range_enrich_button.text() == "Fetch Missing"
    assert page.replay_enrich_button.text() == "Fetch Missing"


def test_market_chart_empty_state_hides_meaningless_axes() -> None:
    app = QApplication.instance() or QApplication([])
    chart = MarketChart()

    chart.set_empty_message("No candle data available.")

    assert chart.plot.getAxis("left").isVisible() is False
    assert chart.plot.getAxis("bottom").isVisible() is False


def test_time_travel_range_results_render_without_fake_data() -> None:
    app = QApplication.instance() or QApplication([])
    page = TimeTravelPage()
    from datetime import datetime
    from intrader.historical import INDIA_TIME

    analysis = SimpleNamespace(
        start=datetime(2026, 9, 25, 9, 15, tzinfo=INDIA_TIME),
        end=datetime(2026, 9, 25, 15, 30, tzinfo=INDIA_TIME),
        candle_count=0,
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

    assert page.range_metrics.value("NIFTY CHANGE") == "N/A"
    assert page.range_metrics.value("SESSIONS") == "0"
    assert page.range_coverage.rowCount() == 1
    assert "No evidence available." in page.range_notes.text.toPlainText()



def test_strategy_lab_is_separate_research_mode() -> None:
    app = QApplication.instance() or QApplication([])
    page = StrategyLabPage()

    assert page.analyze_button.text() == "▶  Analyze Strategies"
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

    assert page.metrics.value("SIGNALS") == "0"
    assert page.metrics.value("ACTIVE") == "0"
    assert page.metrics.value("BEST 30M") == "N/A"
    assert "LAB ONLY" in page.notes.text.toPlainText()



def test_time_travel_uses_real_timestamp_chart_coordinates() -> None:
    from datetime import datetime
    from intrader.historical import INDIA_TIME

    app = QApplication.instance() or QApplication([])
    chart = MarketChart()
    at = datetime(2026, 9, 25, 10, 0, tzinfo=INDIA_TIME)
    chart.set_candles([
        (at.timestamp(), 23000.0, 23005.0, 22990.0, 23010.0)
    ])
    bounds = chart.candles.boundingRect()

    assert bounds.left() > 1_000_000_000


def test_strategy_lab_has_explicit_fetch_missing_control() -> None:
    app = QApplication.instance() or QApplication([])
    page = StrategyLabPage()

    assert page.fetch_button.text() == "Fetch Missing"



def test_time_travel_marks_results_stale_when_inputs_change() -> None:
    from PySide6.QtCore import QDate

    app = QApplication.instance() or QApplication([])
    page = TimeTravelPage()
    page.range_state.setText("Analyzed")
    page.range_from_day.setDate(QDate(2026, 9, 20))
    app.processEvents()

    assert "Analyze Period to refresh" in page.range_state.text()



def test_market_chart_exposes_candle_timeframes_and_aggregates() -> None:
    from datetime import datetime, timedelta
    from decimal import Decimal
    from intrader.historical import Candle, INDIA_TIME

    app = QApplication.instance() or QApplication([])
    chart = MarketChart()
    start = datetime(2026, 9, 25, 9, 15, tzinfo=INDIA_TIME)
    candles = tuple(
        Candle(
            start + timedelta(minutes=i),
            Decimal(str(100 + i)),
            Decimal(str(101 + i)),
            Decimal(str(99 + i)),
            Decimal(str(100.5 + i)),
            1000 + i,
        )
        for i in range(5)
    )

    assert set(chart.timeframe_buttons) == {
        "1m", "3m", "5m", "15m", "30m", "1H", "Auto"
    }

    chart.set_candle_objects(candles)
    chart.set_timeframe("5m")

    assert chart.selected_timeframe() == "5m"
    assert chart.candles.boundingRect().width() > 0


def test_dock_triangle_uses_candlestick_direction_colors() -> None:
    app = QApplication.instance() or QApplication([])
    button = TriangleDockButton()

    assert BULLISH_COLOR == "#2d8a60"
    assert BEARISH_COLOR == "#c64b4b"
    assert button.dock_open() is False

    button.set_dock_open(True)
    assert button.dock_open() is True



def test_30m_candle_aggregation_is_anchored_to_market_open() -> None:
    from datetime import datetime, timedelta
    from decimal import Decimal
    from intrader.historical import Candle, INDIA_TIME

    start = datetime(2026, 9, 25, 9, 15, tzinfo=INDIA_TIME)
    candles = tuple(
        Candle(
            start + timedelta(minutes=i),
            Decimal("100"),
            Decimal("102"),
            Decimal("99"),
            Decimal("101"),
            1000,
        )
        for i in range(40)
    )

    rows = MarketChart._aggregate(candles, 30)

    assert len(rows) == 2
    assert rows[0][0] == start.timestamp()
    assert rows[1][0] == (start + timedelta(minutes=30)).timestamp()



def test_time_travel_defaults_to_approved_range_workspace() -> None:
    app = QApplication.instance() or QApplication([])
    page = TimeTravelPage()

    assert page.tabs.currentIndex() == 1
    assert page.tabs.tabBar().isVisible() is False
    assert page.replay_view_button.text() == "30m Replay"
    assert page.range_view_button.text() == "Range Analysis"


def test_intrader_mode_uses_one_screen_workstation_sections() -> None:
    app = QApplication.instance() or QApplication([])
    page = IntraderModePage()

    assert page.metrics.value("WAITING") == "No Action"
    assert page.chart._title == "NIFTY 50"
    assert set(page.interpretation_values) == {
        "PRICE", "FUTURES", "OPTIONS", "BREADTH", "ORDER_FLOW"
    }



def test_logo_colors_are_fixed_and_not_accent_driven() -> None:
    app = QApplication.instance() or QApplication([])
    mark = LogoMark()

    assert LOGO_RED == "#FF1018"
    assert LOGO_GREY == "#666666"
    assert not hasattr(mark, "set_accent")
