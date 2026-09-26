"""Primary Intrader, Time Travel, and Analysis mode pages."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from math import ceil

from PySide6.QtCore import QDate, QTime, QTimer, Qt
from PySide6.QtWidgets import (
    QDateEdit, QGridLayout, QHBoxLayout, QLabel, QPushButton, QSlider,
    QSplitter, QTabWidget, QTimeEdit, QVBoxLayout, QWidget,
)
import pyqtgraph as pg

from intrader.historical import INDIA_TIME
from intrader.ui.components import (
    Card, DataTable, DecisionCard, MarketChart, MetricCard, ReasonList,
    ResponsiveMetricGrid, TextPanel,
)


def _tone(value: Decimal | None) -> str:
    if value is None or value == 0:
        return "neutral"
    return "positive" if value > 0 else "negative"


def _text(value) -> str:
    return "N/A" if value is None else str(value)


def _chart_rows(
    candles,
    *,
    max_points: int | None = None,
) -> list[tuple[float, float, float, float, float]]:
    ordered = list(candles)
    if not ordered:
        return []
    if max_points is None or len(ordered) <= max_points:
        return [
            (
                c.at.timestamp(),
                float(c.open),
                float(c.close),
                float(c.low),
                float(c.high),
            )
            for c in ordered
        ]

    step = max(1, ceil(len(ordered) / max_points))
    rows = []
    for offset in range(0, len(ordered), step):
        chunk = ordered[offset : offset + step]
        first = chunk[0]
        last = chunk[-1]
        rows.append(
            (
                last.at.timestamp(),
                float(first.open),
                float(last.close),
                float(min(c.low for c in chunk)),
                float(max(c.high for c in chunk)),
            )
        )
    return rows


class IntraderModePage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 34)
        root.setSpacing(8)

        title_row = QHBoxLayout()
        title = QLabel("Intrader Mode")
        title.setObjectName("PageTitle")
        self.session_label = QLabel("Live market operation + shadow trading")
        self.session_label.setObjectName("Muted")
        title_row.addWidget(title)
        title_row.addStretch(1)
        title_row.addWidget(self.session_label)
        root.addLayout(title_row)

        self.decision = DecisionCard()
        self.direction = MetricCard("DIRECTION", "N/A")
        self.confidence = MetricCard("CONFIDENCE", "N/A")
        self.entry = MetricCard("ENTRY QUALITY", "N/A")
        self.risk = MetricCard("REVERSAL RISK", "N/A")
        self.regime = MetricCard("REGIME", "N/A")

        top = QHBoxLayout()
        top.addWidget(self.decision, 2)
        self.metrics = ResponsiveMetricGrid(
            [self.direction, self.confidence, self.entry, self.risk, self.regime],
            compact_height=76,
        )
        top.addWidget(self.metrics, 5)
        root.addLayout(top)

        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.chart = MarketChart()
        self.chart.setMinimumHeight(330)
        self.main_splitter.addWidget(self.chart)

        right_widget = QWidget()
        right = QVBoxLayout(right_widget)
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(8)
        self.shadow = Card("SHADOW TRADE")
        self.shadow_text = QLabel("No active shadow position.")
        self.shadow_text.setWordWrap(True)
        self.shadow.add_widget(self.shadow_text)
        right.addWidget(self.shadow)

        self.news = Card("GLOBAL NEWS / EVENTS")
        self.news_table = DataTable(["Time", "Source", "Headline / Event"])
        self.news.add_widget(self.news_table)
        right.addWidget(self.news, 1)
        self.main_splitter.addWidget(right_widget)
        self.main_splitter.setStretchFactor(0, 7)
        self.main_splitter.setStretchFactor(1, 3)
        root.addWidget(self.main_splitter, 1)

        self.reason_tabs = QTabWidget()
        self.why = ReasonList("WHY THIS ACTION")
        self.why_not = ReasonList("WHY NOT THE OPPOSITE")
        self.reason_tabs.addTab(self.why, "Why this action")
        self.reason_tabs.addTab(self.why_not, "Why not the opposite")
        self.reason_tabs.setMaximumHeight(190)
        root.addWidget(self.reason_tabs)

    def resizeEvent(self, event) -> None:
        self.main_splitter.setOrientation(
            Qt.Orientation.Vertical
            if event.size().width() < 1000
            else Qt.Orientation.Horizontal
        )
        super().resizeEvent(event)

    def apply_layout_preset(self, preset: str) -> None:
        width = max(1, self.width())
        if preset == "Analysis":
            self.main_splitter.setSizes([int(width * 0.80), int(width * 0.20)])
            self.reason_tabs.setMaximumHeight(150)
        elif preset == "Monitoring":
            self.main_splitter.setSizes([int(width * 0.58), int(width * 0.42)])
            self.reason_tabs.setMaximumHeight(120)
        elif preset == "Compact":
            self.main_splitter.setSizes([int(width * 0.72), int(width * 0.28)])
            self.reason_tabs.setMaximumHeight(120)
        else:
            self.main_splitter.setSizes([int(width * 0.68), int(width * 0.32)])
            self.reason_tabs.setMaximumHeight(190)

    def refresh_snapshot(self, snapshot) -> None:
        decision = snapshot.latest_decision
        if decision is None:
            self.decision.set_decision(
                "WAITING FOR DATA",
                "No immutable Market Brain decision recorded yet.",
            )
            for card in (
                self.direction,
                self.confidence,
                self.entry,
                self.risk,
                self.regime,
            ):
                card.set_value("N/A")
            self.why.set_reasons([])
            self.why_not.set_reasons([])
        else:
            self.decision.set_decision(
                decision.action,
                f"{decision.brain_state} • {decision.brain_version}",
            )
            self.direction.set_value(
                str(decision.direction_score), _tone(decision.direction_score)
            )
            self.confidence.set_value(str(decision.confidence))
            self.entry.set_value(str(decision.entry_quality))
            self.risk.set_value(
                str(decision.reversal_risk),
                "negative" if decision.reversal_risk > 70 else "neutral",
            )
            self.regime.set_value(decision.regime)
            self.why.set_reasons([
                (r.reason_code, r.explanation)
                for r in decision.reasons
                if r.thesis == "CHOSEN"
            ])
            self.why_not.set_reasons([
                (r.reason_code, r.explanation)
                for r in decision.reasons
                if r.thesis == "REJECTED"
            ])

        trade = snapshot.active_shadow_trade
        if trade is None:
            self.shadow_text.setText(
                "No active shadow position. Completed trades and P&L remain in Analysis."
            )
        else:
            self.shadow_text.setText(
                f"{trade.action} • {trade.strike} {trade.option_type}\n"
                f"Entry {trade.entry_price}   Stop {trade.stop_price}\n"
                f"Target {trade.target_price}   Qty {trade.quantity}\n"
                f"Version {trade.shadow_version} • Max {trade.max_minutes} min"
            )

        rows = []
        for event in snapshot.upcoming_events[:6]:
            rows.append([
                event.scheduled_at.astimezone(INDIA_TIME).strftime("%H:%M"),
                event.source,
                event.name,
            ])
        for item in snapshot.recent_news[:8]:
            rows.append([
                item.published_at.astimezone(INDIA_TIME).strftime("%H:%M"),
                item.source,
                item.title,
            ])
        self.news_table.set_rows(
            rows[:10] or [["—", "—", "No recent market context. Refresh when needed."]]
        )

    def set_candles(self, candles) -> None:
        rows = _chart_rows(candles)
        if rows:
            self.chart.set_candles(rows)
        else:
            self.chart.set_empty_message("No stored NIFTY candles for this session.")


class TimeTravelPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._decisions = ()
        self._bundles = ()
        self._news = ()
        self._key_moments = ()

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 34)
        root.setSpacing(8)

        title_row = QHBoxLayout()
        title = QLabel("Time Travel")
        title.setObjectName("PageTitle")
        title_row.addWidget(title)
        hint = QLabel("Local-first historical research • network enrichment is opt-in")
        hint.setObjectName("Muted")
        title_row.addWidget(hint)
        title_row.addStretch(1)
        root.addLayout(title_row)

        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)
        self._build_replay_tab()
        self._build_range_tab()

        self.timer = QTimer(self)
        self.timer.setInterval(900)
        self.timer.timeout.connect(self._tick)
        self.play.clicked.connect(self._toggle_play)
        self.back.clicked.connect(
            lambda: self.slider.setValue(max(0, self.slider.value() - 1))
        )
        self.forward.clicked.connect(
            lambda: self.slider.setValue(min(30, self.slider.value() + 1))
        )
        self.slider.valueChanged.connect(self._render_position)

        self.preset_1h.clicked.connect(lambda: self._apply_range_preset(hours=1))
        self.preset_today.clicked.connect(lambda: self._apply_range_preset(days=0))
        self.preset_5d.clicked.connect(lambda: self._apply_range_preset(days=5))
        self.preset_10d.clicked.connect(lambda: self._apply_range_preset(days=10))
        self.preset_30d.clicked.connect(lambda: self._apply_range_preset(days=30))
        for editor in (
            self.range_from_day,
            self.range_to_day,
        ):
            editor.dateChanged.connect(lambda _value: self._mark_range_stale())
        for editor in (
            self.range_from_time,
            self.range_to_time,
        ):
            editor.timeChanged.connect(lambda _value: self._mark_range_stale())
        self.key_moments.cellDoubleClicked.connect(self._open_key_moment)

    def _build_replay_tab(self) -> None:
        replay = QWidget()
        replay_root = QVBoxLayout(replay)
        replay_root.setContentsMargins(8, 8, 8, 8)
        replay_root.setSpacing(8)

        header = QHBoxLayout()
        header.addWidget(QLabel("Replay end"))
        self.day = QDateEdit(QDate.currentDate())
        self.day.setCalendarPopup(True)
        self.end_time = QTimeEdit(QTime.currentTime())
        self.end_time.setDisplayFormat("HH:mm")
        self.load_button = QPushButton("Load 30-Minute Window")
        self.load_button.setObjectName("PrimaryButton")
        self.replay_enrich_button = QPushButton("Fetch Missing")
        self.replay_enrich_button.setToolTip(
            "Explicitly fetch missing candles/news. Normal replay stays read-only."
        )
        self.reanalyze_button = QPushButton("Re-analyze with Current Brain")
        self.reanalyze_button.setObjectName("PrimaryButton")
        self.analysis_source = QLabel("RECORDED")
        self.analysis_source.setObjectName("Muted")
        for widget in (
            self.day,
            self.end_time,
            self.load_button,
            self.replay_enrich_button,
        ):
            header.addWidget(widget)
        header.addStretch(1)
        replay_root.addLayout(header)

        controls = QHBoxLayout()
        self.back = QPushButton("◀")
        self.play = QPushButton("▶")
        self.forward = QPushButton("▶|")
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 30)
        self.slider.setValue(30)
        self.position = QLabel("T+30m")
        self.position.setObjectName("Muted")
        for widget in (self.back, self.play, self.forward):
            controls.addWidget(widget)
        controls.addWidget(QLabel("T-30m"))
        controls.addWidget(self.slider, 1)
        controls.addWidget(self.position)
        controls.addWidget(self.reanalyze_button)
        controls.addWidget(self.analysis_source)
        replay_root.addLayout(controls)

        self.replay_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.chart = MarketChart("30-MINUTE MARKET REPLAY")
        self.chart.setMinimumHeight(320)
        self.replay_splitter.addWidget(self.chart)

        side = QWidget()
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(0, 0, 0, 0)
        self.decision = DecisionCard()
        side_layout.addWidget(self.decision)
        self.forward_table = DataTable(["Outcome", "Value"])
        outcome_card = Card("WHAT HAPPENED NEXT")
        outcome_card.add_widget(self.forward_table)
        side_layout.addWidget(outcome_card)
        self.news_table = DataTable(["Time", "Source", "Global context"])
        news_card = Card("GLOBAL NEWS AT THIS TIME")
        news_card.add_widget(self.news_table)
        side_layout.addWidget(news_card, 1)
        self.replay_splitter.addWidget(side)
        self.replay_splitter.setStretchFactor(0, 7)
        self.replay_splitter.setStretchFactor(1, 3)
        replay_root.addWidget(self.replay_splitter, 1)

        self.replay_details = QTabWidget()
        self.why = ReasonList("REASONING AT THIS TIMESTAMP")
        self.rejected = ReasonList("REJECTED THESIS")
        self.replay_details.addTab(self.why, "Reasoning")
        self.replay_details.addTab(self.rejected, "Rejected thesis")
        self.replay_details.setMaximumHeight(190)
        replay_root.addWidget(self.replay_details)
        self.tabs.addTab(replay, "30-Minute Replay")

    def _build_range_tab(self) -> None:
        range_tab = QWidget()
        range_root = QVBoxLayout(range_tab)
        range_root.setContentsMargins(8, 8, 8, 8)
        range_root.setSpacing(8)

        date_row = QHBoxLayout()
        date_row.addWidget(QLabel("From"))
        self.range_from_day = QDateEdit(QDate.currentDate().addDays(-5))
        self.range_from_day.setCalendarPopup(True)
        self.range_from_time = QTimeEdit(QTime(9, 15))
        self.range_from_time.setDisplayFormat("HH:mm")
        date_row.addWidget(self.range_from_day)
        date_row.addWidget(self.range_from_time)
        date_row.addWidget(QLabel("To"))
        self.range_to_day = QDateEdit(QDate.currentDate())
        self.range_to_day.setCalendarPopup(True)
        self.range_to_time = QTimeEdit(QTime(15, 30))
        self.range_to_time.setDisplayFormat("HH:mm")
        date_row.addWidget(self.range_to_day)
        date_row.addWidget(self.range_to_time)
        self.range_load_button = QPushButton("Analyze Period")
        self.range_load_button.setObjectName("PrimaryButton")
        self.range_enrich_button = QPushButton("Fetch Missing")
        self.range_enrich_button.setToolTip(
            "Opt-in network enrichment; analysis itself stays local/read-only."
        )
        date_row.addWidget(self.range_load_button)
        date_row.addWidget(self.range_enrich_button)
        date_row.addStretch(1)
        range_root.addLayout(date_row)

        preset_row = QHBoxLayout()
        preset_row.addWidget(QLabel("Quick range"))
        self.preset_1h = QPushButton("1H")
        self.preset_today = QPushButton("Today")
        self.preset_5d = QPushButton("5D")
        self.preset_10d = QPushButton("10D")
        self.preset_30d = QPushButton("30D")
        for button in (
            self.preset_1h,
            self.preset_today,
            self.preset_5d,
            self.preset_10d,
            self.preset_30d,
        ):
            preset_row.addWidget(button)
        preset_row.addStretch(1)
        self.range_state = QLabel("No range analyzed yet.")
        self.range_state.setObjectName("Muted")
        preset_row.addWidget(self.range_state)
        range_root.addLayout(preset_row)

        self.range_change = MetricCard("NIFTY CHANGE", "N/A")
        self.range_sessions = MetricCard("SESSIONS", "0")
        self.range_high_low = MetricCard("HIGH / LOW", "N/A")
        self.range_pnl = MetricCard("SHADOW P&L", "0")
        self.range_expectancy = MetricCard("EXPECTANCY", "N/A")
        self.range_news = MetricCard("RELEVANT NEWS", "0")
        self.range_metrics = ResponsiveMetricGrid(
            [
                self.range_change,
                self.range_sessions,
                self.range_high_low,
                self.range_pnl,
                self.range_expectancy,
                self.range_news,
            ],
            compact_height=74,
        )
        range_root.addWidget(self.range_metrics)

        self.range_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.range_chart = MarketChart("PRICE CHART — SELECTED RANGE")
        self.range_chart.setMinimumHeight(320)
        self.range_splitter.addWidget(self.range_chart)

        scenario_widget = QWidget()
        scenario = QVBoxLayout(scenario_widget)
        scenario.setContentsMargins(0, 0, 0, 0)
        scenario.setSpacing(8)

        context_card = Card("ANALYSIS CONTEXT")
        self.opening_meta = QLabel(
            "Opening possibilities are evidence weights, not calibrated probabilities."
        )
        self.opening_meta.setWordWrap(True)
        self.opening_meta.setObjectName("Muted")
        context_card.add_widget(self.opening_meta)
        scenario.addWidget(context_card)

        scenario_grid = QWidget()
        grid = QGridLayout(scenario_grid)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(8)
        self.open_bull = MetricCard("BULLISH OPEN WEIGHT", "N/A")
        self.open_flat = MetricCard("BALANCED OPEN WEIGHT", "N/A")
        self.open_bear = MetricCard("BEARISH OPEN WEIGHT", "N/A")
        self.open_gap = MetricCard("GAP RISK", "N/A")
        for index, card in enumerate(
            (self.open_bull, self.open_flat, self.open_bear, self.open_gap)
        ):
            card.setMaximumHeight(104)
            grid.addWidget(card, index // 2, index % 2)
        scenario.addWidget(scenario_grid)

        self.opening_drivers = TextPanel(
            "NEXT-SESSION OPENING POSSIBILITIES",
            "No opening evidence available for this selection.",
        )
        scenario.addWidget(self.opening_drivers, 1)
        self.range_splitter.addWidget(scenario_widget)
        self.range_splitter.setStretchFactor(0, 7)
        self.range_splitter.setStretchFactor(1, 3)
        range_root.addWidget(self.range_splitter, 3)

        self.detail_tabs = QTabWidget()
        self.key_moments = DataTable(
            ["Time", "Type", "Importance", "Summary", "Detail"]
        )
        self.detail_tabs.addTab(self.key_moments, "Key Moments")

        self.range_notes = TextPanel(
            "WHAT HAPPENED / EVIDENCE AROUND WHY",
            "No period analysis available yet.",
        )
        self.detail_tabs.addTab(self.range_notes, "Period Analysis")

        self.range_decisions = DataTable(["Decision", "Count"])
        self.detail_tabs.addTab(self.range_decisions, "Decision Mix")
        self.range_regimes = DataTable(["Regime", "Count"])
        self.detail_tabs.addTab(self.range_regimes, "Regime Mix")
        self.range_coverage = DataTable(["Data family", "Coverage"])
        self.detail_tabs.addTab(self.range_coverage, "Data Coverage")
        self.detail_tabs.setMinimumHeight(190)
        range_root.addWidget(self.detail_tabs, 2)

        self.tabs.addTab(range_tab, "Range Analysis / Opening Possibilities")

    def resizeEvent(self, event) -> None:
        orientation = (
            Qt.Orientation.Vertical
            if event.size().width() < 1050
            else Qt.Orientation.Horizontal
        )
        self.replay_splitter.setOrientation(orientation)
        self.range_splitter.setOrientation(orientation)
        super().resizeEvent(event)

    def apply_layout_preset(self, preset: str) -> None:
        width = max(1, self.width())
        if preset == "Analysis":
            self.range_splitter.setSizes([int(width * 0.78), int(width * 0.22)])
            self.replay_splitter.setSizes([int(width * 0.78), int(width * 0.22)])
            self.detail_tabs.setMinimumHeight(150)
            self.replay_details.setMaximumHeight(140)
        elif preset == "Monitoring":
            self.range_splitter.setSizes([int(width * 0.58), int(width * 0.42)])
            self.replay_splitter.setSizes([int(width * 0.62), int(width * 0.38)])
            self.detail_tabs.setMinimumHeight(190)
        elif preset == "Compact":
            self.range_splitter.setSizes([int(width * 0.72), int(width * 0.28)])
            self.replay_splitter.setSizes([int(width * 0.72), int(width * 0.28)])
            self.detail_tabs.setMinimumHeight(160)
            self.replay_details.setMaximumHeight(130)
        else:
            self.range_splitter.setSizes([int(width * 0.68), int(width * 0.32)])
            self.replay_splitter.setSizes([int(width * 0.68), int(width * 0.32)])
            self.detail_tabs.setMinimumHeight(190)
            self.replay_details.setMaximumHeight(190)

    def _mark_range_stale(self) -> None:
        if hasattr(self, "range_state"):
            self.range_state.setText("Inputs changed • Analyze Period to refresh")

    def selected_day(self) -> date:
        return self.day.date().toPython()

    def selected_end_datetime(self) -> datetime:
        qd = self.day.date()
        qt = self.end_time.time()
        return datetime(
            qd.year(), qd.month(), qd.day(),
            qt.hour(), qt.minute(), tzinfo=INDIA_TIME
        )

    def selected_replay_datetime(self) -> datetime:
        end = self.selected_end_datetime()
        return end - timedelta(minutes=(30 - self.slider.value()))

    def selected_range(self) -> tuple[datetime, datetime]:
        fd = self.range_from_day.date()
        ft = self.range_from_time.time()
        td = self.range_to_day.date()
        tt = self.range_to_time.time()
        return (
            datetime(
                fd.year(), fd.month(), fd.day(),
                ft.hour(), ft.minute(), tzinfo=INDIA_TIME
            ),
            datetime(
                td.year(), td.month(), td.day(),
                tt.hour(), tt.minute(), tzinfo=INDIA_TIME
            ),
        )

    def _apply_range_preset(
        self,
        *,
        hours: int | None = None,
        days: int | None = None,
    ) -> None:
        now = datetime.now(INDIA_TIME)
        if hours is not None:
            start = now - timedelta(hours=hours)
            end = now
        elif days == 0:
            start = now.replace(hour=9, minute=15, second=0, microsecond=0)
            end = now
        else:
            end = now
            start = now - timedelta(days=days or 5)
        self.range_from_day.setDate(QDate(start.year, start.month, start.day))
        self.range_from_time.setTime(QTime(start.hour, start.minute))
        self.range_to_day.setDate(QDate(end.year, end.month, end.day))
        self.range_to_time.setTime(QTime(end.hour, end.minute))

    def set_session_data(self, decisions, bundles, candles, news=()) -> None:
        self._decisions = tuple(decisions)
        self._bundles = tuple(bundles)
        self._news = tuple(news)
        self.analysis_source.setText("RECORDED")
        end = self.selected_end_datetime()
        start = end - timedelta(minutes=30)
        window = tuple(
            c for c in candles
            if start <= c.at.astimezone(INDIA_TIME) <= end
        )
        rows = _chart_rows(window)
        if rows:
            self.chart.set_candles(rows)
        else:
            self.chart.set_empty_message(
                "No local candles in this replay window. Use Fetch Missing if needed."
            )
        self.slider.setValue(30)
        self._render_position()

    def set_reanalysis(self, decision) -> None:
        self.analysis_source.setText(
            f"RE-ANALYZED • {decision.brain_version} / {decision.rule_version}"
        )
        self.decision.set_decision(
            decision.action,
            f"{decision.regime} • re-analysis at "
            f"{decision.decided_at.astimezone(INDIA_TIME):%H:%M:%S}",
        )
        self.why.set_reasons([
            (r.reason_code, r.explanation)
            for r in decision.reasons if r.thesis == "CHOSEN"
        ])
        self.rejected.set_reasons([
            (r.reason_code, r.explanation)
            for r in decision.reasons if r.thesis == "REJECTED"
        ])

    def set_range_analysis(self, analysis, opening, candles) -> None:
        self.range_state.setText(
            f"Analyzed {analysis.start.astimezone(INDIA_TIME):%d %b %H:%M} → "
            f"{analysis.end.astimezone(INDIA_TIME):%d %b %H:%M} • "
            f"{analysis.candle_count:,} candles"
        )
        self.range_change.set_value(
            "N/A" if analysis.change_pct is None else f"{analysis.change_pct:.3f}%",
            _tone(analysis.change_pct),
        )
        self.range_sessions.set_value(
            str(analysis.session_count),
            subtitle="unique local trading dates",
        )
        self.range_high_low.set_value(
            "N/A"
            if analysis.high is None or analysis.low is None
            else f"{analysis.high} / {analysis.low}"
        )
        self.range_pnl.set_value(
            str(analysis.adjusted_pnl), _tone(analysis.adjusted_pnl)
        )
        self.range_expectancy.set_value(
            _text(analysis.expectancy), _tone(analysis.expectancy)
        )
        self.range_news.set_value(
            str(analysis.news_count),
            subtitle="filtered market context",
        )

        rows = _chart_rows(candles, max_points=1400)
        if rows:
            self.range_chart.set_candles(rows)
        else:
            self.range_chart.set_empty_message(
                "No local NIFTY candles in this range. Use Fetch Missing if needed."
            )

        self.open_bull.set_value(f"{opening.bullish_weight:.1f}%", "positive")
        self.open_flat.set_value(f"{opening.balanced_weight:.1f}%")
        self.open_bear.set_value(f"{opening.bearish_weight:.1f}%", "negative")
        self.open_gap.set_value(
            f"{opening.gap_risk:.1f}%",
            "negative" if opening.gap_risk >= 60 else "neutral",
        )
        self.opening_meta.setText(
            f"Next session candidate: {opening.next_session_candidate} • "
            f"Bias score {opening.bias_score:.1f} • "
            f"Evidence coverage {opening.evidence_coverage:.0f}%\n"
            "Scenario weights only — not calibrated probabilities or a trade recommendation."
        )
        evidence = list(opening.drivers)
        evidence.extend(f"LIMITATION: {item}" for item in opening.limitations)
        self.opening_drivers.set_text(
            evidence or ["No opening evidence available for this selection."]
        )

        self.range_notes.set_text(
            list(analysis.analysis_notes)
            or ["No period analysis available for this selection."]
        )

        self._key_moments = analysis.key_moments
        moment_rows = [
            [
                moment.at.astimezone(INDIA_TIME).strftime("%Y-%m-%d %H:%M"),
                moment.kind,
                f"{moment.importance:.2f}",
                moment.summary,
                moment.detail,
            ]
            for moment in analysis.key_moments
        ]
        self.key_moments.set_rows(
            moment_rows
            or [["—", "—", "—", "No key moments in selected range.", ""]]
        )
        self.range_decisions.set_rows(
            [[name, count] for name, count in analysis.decision_counts]
            or [["No recorded decisions in selected range.", 0]]
        )
        self.range_regimes.set_rows(
            [[name, count] for name, count in analysis.regime_counts]
            or [["No recorded regime snapshots in selected range.", 0]]
        )
        self.range_coverage.set_rows([
            [name, status] for name, status in analysis.coverage
        ])

    def _open_key_moment(self, row: int, _column: int) -> None:
        if row < 0 or row >= len(self._key_moments):
            return
        moment = self._key_moments[row]
        at = moment.at.astimezone(INDIA_TIME)
        replay_end = at + timedelta(minutes=15)
        self.day.setDate(QDate(replay_end.year, replay_end.month, replay_end.day))
        self.end_time.setTime(QTime(replay_end.hour, replay_end.minute))
        self.tabs.setCurrentIndex(0)
        self.load_button.click()

    def _toggle_play(self) -> None:
        if self.timer.isActive():
            self.timer.stop()
            self.play.setText("▶")
        else:
            if self.slider.value() >= 30:
                self.slider.setValue(0)
            self.timer.start()
            self.play.setText("Ⅱ")

    def _tick(self) -> None:
        if self.slider.value() >= 30:
            self.timer.stop()
            self.play.setText("▶")
            return
        self.slider.setValue(self.slider.value() + 1)

    def _render_position(self) -> None:
        selected = self.selected_replay_datetime()
        self.position.setText(selected.strftime("%H:%M"))
        self.analysis_source.setText("RECORDED")
        visible_news = [
            item for item in self._news
            if selected - timedelta(minutes=10)
            <= item.published_at.astimezone(INDIA_TIME)
            <= selected
        ]
        self.news_table.set_rows([
            [
                item.published_at.astimezone(INDIA_TIME).strftime("%H:%M"),
                item.source,
                item.title,
            ]
            for item in visible_news[:10]
        ] or [["—", "—", "No relevant cached news in this replay window."]])

        eligible = [
            d for d in self._decisions
            if d.decided_at.astimezone(INDIA_TIME) <= selected
        ]
        decision = eligible[-1] if eligible else None
        if decision is None:
            self.decision.set_decision(
                "NO DECISION",
                "No recorded decision existed by this replay time.",
            )
            self.why.set_reasons([])
            self.rejected.set_reasons([])
            self.forward_table.set_rows(
                [["Outcome", "No completed shadow outcome for this replay point."]]
            )
            return

        self.decision.set_decision(
            decision.action,
            f"{decision.regime} • "
            f"{decision.decided_at.astimezone(INDIA_TIME):%H:%M:%S}",
        )
        self.why.set_reasons([
            (r.reason_code, r.explanation)
            for r in decision.reasons if r.thesis == "CHOSEN"
        ])
        self.rejected.set_reasons([
            (r.reason_code, r.explanation)
            for r in decision.reasons if r.thesis == "REJECTED"
        ])
        bundle = next(
            (b for b in self._bundles if b[0].decision_id == decision.decision_id),
            None,
        )
        if bundle is None:
            self.forward_table.set_rows([
                ["Shadow outcome", "Not completed / not actionable"]
            ])
        else:
            outcome = bundle[2]
            rows = [
                ["Exit", f"{outcome.exit_reason} @ {outcome.exit_price}"],
                ["Adjusted P&L", outcome.adjusted_pnl],
                ["MFE", outcome.mfe_amount],
                ["MAE", outcome.mae_amount],
            ]
            rows.extend([
                [f"{minutes}m", "N/A" if result is None else f"{result}%"]
                for minutes, result in outcome.forward_returns
            ])
            self.forward_table.set_rows(rows)


class AnalysisModePage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 34)
        root.setSpacing(8)

        title = QLabel("Analysis Mode")
        title.setObjectName("PageTitle")
        root.addWidget(title)

        self.pnl = MetricCard("ADJUSTED P&L")
        self.win_rate = MetricCard("WIN RATE")
        self.expectancy = MetricCard("EXPECTANCY")
        self.profit_factor = MetricCard("PROFIT FACTOR")
        self.drawdown = MetricCard("MAX DRAWDOWN")
        self.trades = MetricCard("COMPLETED TRADES")
        self.metrics = ResponsiveMetricGrid(
            [
                self.pnl,
                self.win_rate,
                self.expectancy,
                self.profit_factor,
                self.drawdown,
                self.trades,
            ],
            compact_height=74,
        )
        root.addWidget(self.metrics)

        self.analysis_splitter = QSplitter(Qt.Orientation.Horizontal)
        equity_card = Card("SHADOW EQUITY CURVE")
        self.equity_plot = pg.PlotWidget()
        self.equity_plot.setBackground("#fffefa")
        self.equity_plot.showGrid(x=True, y=True, alpha=0.12)
        equity_card.add_widget(self.equity_plot)
        self.analysis_splitter.addWidget(equity_card)

        self.reason_table = DataTable(
            ["Reason", "n", "Profit", "Loss", "Supported", "Contradicted", "Avg P&L"]
        )
        reason_card = Card("REASON-CODE PERFORMANCE")
        reason_card.add_widget(self.reason_table)
        self.analysis_splitter.addWidget(reason_card)
        self.analysis_splitter.setStretchFactor(0, 7)
        self.analysis_splitter.setStretchFactor(1, 3)
        root.addWidget(self.analysis_splitter, 1)

        self.performance_tabs = QTabWidget()
        self.action_table = DataTable(
            ["Action", "Trades", "Win %", "P&L", "Expectancy"]
        )
        self.regime_table = DataTable(
            ["Regime", "Trades", "Win %", "P&L", "Expectancy"]
        )
        self.time_table = DataTable(["Hour", "Trades", "P&L", "Expectancy"])
        self.performance_tabs.addTab(self.action_table, "CALL vs PUT")
        self.performance_tabs.addTab(self.regime_table, "Regime")
        self.performance_tabs.addTab(self.time_table, "Time of day")
        self.performance_tabs.setMinimumHeight(210)
        root.addWidget(self.performance_tabs)

    def resizeEvent(self, event) -> None:
        self.analysis_splitter.setOrientation(
            Qt.Orientation.Vertical
            if event.size().width() < 1000
            else Qt.Orientation.Horizontal
        )
        super().resizeEvent(event)

    def apply_layout_preset(self, preset: str) -> None:
        width = max(1, self.width())
        if preset == "Analysis":
            self.analysis_splitter.setSizes([int(width * 0.78), int(width * 0.22)])
            self.performance_tabs.setMinimumHeight(180)
        elif preset == "Monitoring":
            self.analysis_splitter.setSizes([int(width * 0.60), int(width * 0.40)])
            self.performance_tabs.setMinimumHeight(230)
        elif preset == "Compact":
            self.analysis_splitter.setSizes([int(width * 0.72), int(width * 0.28)])
            self.performance_tabs.setMinimumHeight(170)
        else:
            self.analysis_splitter.setSizes([int(width * 0.68), int(width * 0.32)])
            self.performance_tabs.setMinimumHeight(210)

    def refresh_manager(self, snapshot, completed_bundles) -> None:
        overall = snapshot.overall
        self.pnl.set_value(str(overall.adjusted_pnl), _tone(overall.adjusted_pnl))
        self.win_rate.set_value(
            "N/A" if overall.win_rate is None else f"{overall.win_rate:.2f}%"
        )
        self.expectancy.set_value(
            _text(overall.expectancy), _tone(overall.expectancy)
        )
        self.profit_factor.set_value(_text(overall.profit_factor))
        self.drawdown.set_value(
            str(overall.max_drawdown),
            "negative" if overall.max_drawdown > 0 else "neutral",
        )
        self.trades.set_value(str(overall.trades))

        self.equity_plot.clear()
        if not completed_bundles:
            self.equity_plot.hideAxis("left")
            self.equity_plot.hideAxis("bottom")
            self.equity_plot.showGrid(x=False, y=False)
            self.equity_plot.setXRange(0, 1, padding=0)
            self.equity_plot.setYRange(0, 1, padding=0)
            empty = pg.TextItem(
                f"No completed shadow trades yet.\nStarting shadow capital: ₹{snapshot.starting_capital}",
                anchor=(0.5, 0.5),
                color="#7b858c",
            )
            self.equity_plot.addItem(empty)
            empty.setPos(0.5, 0.5)
        else:
            self.equity_plot.showAxis("left")
            self.equity_plot.showAxis("bottom")
            self.equity_plot.showGrid(x=True, y=True, alpha=0.12)
            equity = float(snapshot.starting_capital)
            ys = [equity]
            for _decision, _trade, outcome in completed_bundles:
                equity += float(outcome.adjusted_pnl)
                ys.append(equity)
            self.equity_plot.plot(
                list(range(len(ys))),
                ys,
                pen=pg.mkPen("#5f8d9c", width=2),
            )

        self.action_table.set_rows([
            [name, m.trades, _text(m.win_rate), m.adjusted_pnl, _text(m.expectancy)]
            for name, m in snapshot.by_action
        ] or [["No completed trades", 0, "N/A", 0, "N/A"]])
        self.regime_table.set_rows([
            [name, m.trades, _text(m.win_rate), m.adjusted_pnl, _text(m.expectancy)]
            for name, m in snapshot.by_regime
        ] or [["No completed trades", 0, "N/A", 0, "N/A"]])
        self.time_table.set_rows([
            [name, m.trades, m.adjusted_pnl, _text(m.expectancy)]
            for name, m in snapshot.by_hour
        ] or [["No completed trades", 0, 0, "N/A"]])
        self.reason_table.set_rows([
            [
                r.reason_code,
                r.occurrences,
                r.profitable,
                r.losing,
                r.supported,
                r.contradicted,
                r.average_pnl,
            ]
            for r in snapshot.reasons[:30]
        ] or [["No reason audits yet", 0, 0, 0, 0, 0, "N/A"]])
