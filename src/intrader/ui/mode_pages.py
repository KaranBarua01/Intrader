"""Primary Intrader, Time Travel, and Analysis mode pages."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from PySide6.QtCore import QDate, QTime, QTimer, Qt
from PySide6.QtWidgets import (
    QDateEdit, QGridLayout, QHBoxLayout, QLabel, QPushButton, QSlider,
    QTabWidget, QTimeEdit, QVBoxLayout, QWidget,
)
import pyqtgraph as pg

from intrader.historical import INDIA_TIME
from intrader.ui.components import Card, DataTable, DecisionCard, MarketChart, MetricCard, ReasonList


def _tone(value: Decimal | None) -> str:
    if value is None or value == 0:
        return "neutral"
    return "positive" if value > 0 else "negative"


def _text(value) -> str:
    return "N/A" if value is None else str(value)


class IntraderModePage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        title_row = QHBoxLayout()
        title = QLabel("Intrader Mode")
        title.setObjectName("PageTitle")
        self.session_label = QLabel("Live market operation + shadow trading")
        self.session_label.setObjectName("Muted")
        title_row.addWidget(title)
        title_row.addStretch(1)
        title_row.addWidget(self.session_label)
        root.addLayout(title_row)

        top = QHBoxLayout()
        self.decision = DecisionCard()
        top.addWidget(self.decision, 2)
        self.direction = MetricCard("DIRECTION", "N/A")
        self.confidence = MetricCard("CONFIDENCE", "N/A")
        self.entry = MetricCard("ENTRY QUALITY", "N/A")
        self.risk = MetricCard("REVERSAL RISK", "N/A")
        self.regime = MetricCard("REGIME", "N/A")
        for card in (self.direction, self.confidence, self.entry, self.risk, self.regime):
            top.addWidget(card, 1)
        root.addLayout(top)

        middle = QHBoxLayout()
        self.chart = MarketChart()
        self.chart.setMinimumHeight(390)
        middle.addWidget(self.chart, 3)

        right = QVBoxLayout()
        self.shadow = Card("SHADOW TRADE")
        self.shadow_text = QLabel("No active shadow position.")
        self.shadow_text.setWordWrap(True)
        self.shadow.add_widget(self.shadow_text)
        right.addWidget(self.shadow)
        self.news = Card("GLOBAL NEWS / EVENTS")
        self.news_table = DataTable(["Time", "Source", "Headline / Event"])
        self.news_table.setMaximumHeight(210)
        self.news.add_widget(self.news_table)
        right.addWidget(self.news, 1)
        middle.addLayout(right, 2)
        root.addLayout(middle, 1)

        reasoning = QHBoxLayout()
        self.why = ReasonList("WHY THIS ACTION")
        self.why_not = ReasonList("WHY NOT THE OPPOSITE")
        reasoning.addWidget(self.why)
        reasoning.addWidget(self.why_not)
        root.addLayout(reasoning)

    def refresh_snapshot(self, snapshot) -> None:
        decision = snapshot.latest_decision
        if decision is None:
            self.decision.set_decision("WAITING FOR DATA", "No immutable Market Brain decision recorded yet.")
            for card in (self.direction, self.confidence, self.entry, self.risk, self.regime):
                card.set_value("N/A")
            self.why.set_reasons([])
            self.why_not.set_reasons([])
        else:
            self.decision.set_decision(decision.action, f"{decision.brain_state} • {decision.brain_version}")
            self.direction.set_value(str(decision.direction_score), _tone(decision.direction_score))
            self.confidence.set_value(str(decision.confidence))
            self.entry.set_value(str(decision.entry_quality))
            self.risk.set_value(str(decision.reversal_risk), "negative" if decision.reversal_risk > 70 else "neutral")
            self.regime.set_value(decision.regime)
            chosen = [
                (r.reason_code, r.explanation) for r in decision.reasons if r.thesis == "CHOSEN"
            ]
            rejected = [
                (r.reason_code, r.explanation) for r in decision.reasons if r.thesis == "REJECTED"
            ]
            self.why.set_reasons(chosen)
            self.why_not.set_reasons(rejected)

        trade = snapshot.active_shadow_trade
        if trade is None:
            self.shadow_text.setText("No active shadow position.")
        else:
            self.shadow_text.setText(
                f"{trade.action}  •  {trade.strike} {trade.option_type}\n"
                f"Entry  {trade.entry_price}     Stop  {trade.stop_price}\n"
                f"Target {trade.target_price}     Qty   {trade.quantity}\n"
                f"Version {trade.shadow_version}  •  Max {trade.max_minutes} min"
            )

        rows = []
        for event in snapshot.upcoming_events[:6]:
            rows.append([event.scheduled_at.astimezone(INDIA_TIME).strftime("%H:%M"), event.source, event.name])
        for item in snapshot.recent_news[:8]:
            rows.append([item.published_at.astimezone(INDIA_TIME).strftime("%H:%M"), item.source, item.title])
        self.news_table.set_rows(rows[:10])

    def set_candles(self, candles) -> None:
        rows = [
            (float(index), float(c.open), float(c.close), float(c.low), float(c.high))
            for index, c in enumerate(candles)
        ]
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
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        title = QLabel("Time Travel")
        title.setObjectName("PageTitle")
        root.addWidget(title)

        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)

        # --------------------------------------------------------------
        # 30-minute replay
        # --------------------------------------------------------------
        replay = QWidget()
        replay_root = QVBoxLayout(replay)
        replay_root.setContentsMargins(8, 8, 8, 8)

        header = QHBoxLayout()
        header.addWidget(QLabel("Replay end"))
        self.day = QDateEdit(QDate.currentDate())
        self.day.setCalendarPopup(True)
        self.end_time = QTimeEdit(QTime.currentTime())
        self.end_time.setDisplayFormat("HH:mm")
        self.load_button = QPushButton("Load 30-Minute Window")
        self.load_button.setObjectName("PrimaryButton")
        self.reanalyze_button = QPushButton("Re-analyze with Current Brain")
        self.reanalyze_button.setObjectName("PrimaryButton")
        self.analysis_source = QLabel("RECORDED")
        self.analysis_source.setObjectName("Muted")
        header.addWidget(self.day)
        header.addWidget(self.end_time)
        header.addWidget(self.load_button)
        header.addWidget(self.reanalyze_button)
        header.addWidget(self.analysis_source)
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
        controls.addWidget(self.back)
        controls.addWidget(self.play)
        controls.addWidget(self.forward)
        controls.addWidget(QLabel("T-30m"))
        controls.addWidget(self.slider, 1)
        controls.addWidget(QLabel("Selected"))
        controls.addWidget(self.position)
        replay_root.addLayout(controls)

        body = QHBoxLayout()
        self.chart = MarketChart("30-MINUTE MARKET REPLAY")
        self.chart.setMinimumHeight(360)
        body.addWidget(self.chart, 3)
        side = QVBoxLayout()
        self.decision = DecisionCard()
        side.addWidget(self.decision)
        self.forward_table = DataTable(["Outcome", "Value"])
        outcome_card = Card("WHAT HAPPENED NEXT")
        outcome_card.add_widget(self.forward_table)
        side.addWidget(outcome_card)
        self.news_table = DataTable(["Time", "Source", "Global context"])
        news_card = Card("GLOBAL NEWS AT THIS TIME")
        news_card.add_widget(self.news_table)
        side.addWidget(news_card, 1)
        body.addLayout(side, 2)
        replay_root.addLayout(body, 1)

        reasoning = QHBoxLayout()
        self.why = ReasonList("REASONING AT THIS TIMESTAMP")
        self.rejected = ReasonList("REJECTED THESIS")
        reasoning.addWidget(self.why)
        reasoning.addWidget(self.rejected)
        replay_root.addLayout(reasoning)

        self.tabs.addTab(replay, "30-Minute Replay")

        # --------------------------------------------------------------
        # Range analysis: 1 hour -> 30 days
        # --------------------------------------------------------------
        range_tab = QWidget()
        range_root = QVBoxLayout(range_tab)
        range_root.setContentsMargins(8, 8, 8, 8)
        range_controls = QHBoxLayout()
        range_controls.addWidget(QLabel("From"))
        self.range_from_day = QDateEdit(QDate.currentDate().addDays(-5))
        self.range_from_day.setCalendarPopup(True)
        self.range_from_time = QTimeEdit(QTime(9, 15))
        self.range_from_time.setDisplayFormat("HH:mm")
        range_controls.addWidget(self.range_from_day)
        range_controls.addWidget(self.range_from_time)
        range_controls.addWidget(QLabel("To"))
        self.range_to_day = QDateEdit(QDate.currentDate())
        self.range_to_day.setCalendarPopup(True)
        self.range_to_time = QTimeEdit(QTime(15, 30))
        self.range_to_time.setDisplayFormat("HH:mm")
        range_controls.addWidget(self.range_to_day)
        range_controls.addWidget(self.range_to_time)

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
            range_controls.addWidget(button)

        self.range_load_button = QPushButton("Analyze Period")
        self.range_load_button.setObjectName("PrimaryButton")
        range_controls.addWidget(self.range_load_button)
        range_controls.addStretch(1)
        range_root.addLayout(range_controls)

        metrics = QHBoxLayout()
        self.range_change = MetricCard("NIFTY CHANGE", "N/A")
        self.range_sessions = MetricCard("SESSIONS", "0")
        self.range_high_low = MetricCard("HIGH / LOW", "N/A")
        self.range_pnl = MetricCard("SHADOW P&L", "0")
        self.range_expectancy = MetricCard("EXPECTANCY", "N/A")
        self.range_news = MetricCard("GLOBAL NEWS", "0")
        for card in (
            self.range_change,
            self.range_sessions,
            self.range_high_low,
            self.range_pnl,
            self.range_expectancy,
            self.range_news,
        ):
            metrics.addWidget(card)
        range_root.addLayout(metrics)

        range_middle = QHBoxLayout()
        self.range_chart = MarketChart("SELECTED RANGE")
        self.range_chart.setMinimumHeight(300)
        range_middle.addWidget(self.range_chart, 3)

        scenario = QVBoxLayout()
        scenario_row = QHBoxLayout()
        self.open_bull = MetricCard("BULLISH OPEN WEIGHT", "N/A")
        self.open_flat = MetricCard("BALANCED OPEN WEIGHT", "N/A")
        self.open_bear = MetricCard("BEARISH OPEN WEIGHT", "N/A")
        self.open_gap = MetricCard("GAP RISK", "N/A")
        for card in (self.open_bull, self.open_flat, self.open_bear, self.open_gap):
            scenario_row.addWidget(card)
        scenario.addLayout(scenario_row)
        self.opening_meta = QLabel(
            "Opening possibilities are evidence weights, not calibrated probabilities."
        )
        self.opening_meta.setWordWrap(True)
        self.opening_meta.setObjectName("Muted")
        scenario.addWidget(self.opening_meta)

        self.opening_drivers = DataTable(["Opening evidence / limitation"])
        scenario_card = Card("NEXT-SESSION OPENING POSSIBILITIES")
        scenario_card.add_widget(self.opening_drivers)
        scenario.addWidget(scenario_card, 1)
        range_middle.addLayout(scenario, 2)
        range_root.addLayout(range_middle, 1)

        range_bottom = QHBoxLayout()
        self.key_moments = DataTable(
            ["Time", "Type", "Importance", "Summary", "Detail"]
        )
        moments_card = Card("KEY MOMENTS — DOUBLE-CLICK TO OPEN 30-MIN REPLAY")
        moments_card.add_widget(self.key_moments)
        range_bottom.addWidget(moments_card, 3)

        summary_side = QVBoxLayout()
        self.range_decisions = DataTable(["Decision", "Count"])
        decision_card = Card("DECISION MIX")
        decision_card.add_widget(self.range_decisions)
        summary_side.addWidget(decision_card)
        self.range_regimes = DataTable(["Regime", "Count"])
        regime_card = Card("REGIME MIX")
        regime_card.add_widget(self.range_regimes)
        summary_side.addWidget(regime_card)
        self.range_coverage = DataTable(["Data family", "Coverage"])
        coverage_card = Card("DATA COVERAGE")
        coverage_card.add_widget(self.range_coverage)
        summary_side.addWidget(coverage_card)
        range_bottom.addLayout(summary_side, 2)
        range_root.addLayout(range_bottom, 1)

        self.tabs.addTab(range_tab, "Range Analysis / Opening Possibilities")

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
        self.key_moments.cellDoubleClicked.connect(self._open_key_moment)

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
        start = datetime(
            fd.year(), fd.month(), fd.day(),
            ft.hour(), ft.minute(), tzinfo=INDIA_TIME
        )
        end = datetime(
            td.year(), td.month(), td.day(),
            tt.hour(), tt.minute(), tzinfo=INDIA_TIME
        )
        return start, end

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
        rows = [
            (float(i), float(c.open), float(c.close), float(c.low), float(c.high))
            for i, c in enumerate(window)
        ]
        if rows:
            self.chart.set_candles(rows)
        else:
            self.chart.set_empty_message(
                "No candles in this 30-minute replay window."
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
        self.range_change.set_value(
            "N/A" if analysis.change_pct is None else f"{analysis.change_pct:.3f}%",
            _tone(analysis.change_pct),
        )
        self.range_sessions.set_value(str(analysis.session_count))
        self.range_high_low.set_value(
            "N/A"
            if analysis.high is None or analysis.low is None
            else f"{analysis.high} / {analysis.low}"
        )
        self.range_pnl.set_value(str(analysis.adjusted_pnl), _tone(analysis.adjusted_pnl))
        self.range_expectancy.set_value(_text(analysis.expectancy), _tone(analysis.expectancy))
        self.range_news.set_value(str(analysis.news_count))

        rows = [
            (float(i), float(c.open), float(c.close), float(c.low), float(c.high))
            for i, c in enumerate(candles)
        ]
        # Keep long ranges readable without fabricating intermediate data.
        if len(rows) > 1200:
            step = max(1, len(rows) // 1200)
            rows = rows[::step]
        if rows:
            self.range_chart.set_candles(rows)
        else:
            self.range_chart.set_empty_message(
                "No NIFTY candles available in the selected range."
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
            "These are scenario weights, not calibrated probabilities or a trade recommendation."
        )
        evidence_rows = [[driver] for driver in opening.drivers]
        evidence_rows.extend([[f"LIMITATION: {item}"] for item in opening.limitations])
        self.opening_drivers.set_rows(evidence_rows)

        self._key_moments = analysis.key_moments
        self.key_moments.set_rows([
            [
                moment.at.astimezone(INDIA_TIME).strftime("%Y-%m-%d %H:%M"),
                moment.kind,
                f"{moment.importance:.2f}",
                moment.summary,
                moment.detail,
            ]
            for moment in analysis.key_moments
        ])
        self.range_decisions.set_rows([
            [name, count] for name, count in analysis.decision_counts
        ])
        self.range_regimes.set_rows([
            [name, count] for name, count in analysis.regime_counts
        ])
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
        ])
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
            self.forward_table.set_rows([])
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
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)
        title = QLabel("Analysis Mode")
        title.setObjectName("PageTitle")
        root.addWidget(title)

        metrics = QHBoxLayout()
        self.pnl = MetricCard("ADJUSTED P&L")
        self.win_rate = MetricCard("WIN RATE")
        self.expectancy = MetricCard("EXPECTANCY")
        self.profit_factor = MetricCard("PROFIT FACTOR")
        self.drawdown = MetricCard("MAX DRAWDOWN")
        self.trades = MetricCard("COMPLETED TRADES")
        for card in (self.pnl, self.win_rate, self.expectancy, self.profit_factor, self.drawdown, self.trades):
            metrics.addWidget(card)
        root.addLayout(metrics)

        center = QHBoxLayout()
        equity_card = Card("SHADOW EQUITY CURVE")
        self.equity_plot = pg.PlotWidget()
        self.equity_plot.setBackground("#fffefa")
        self.equity_plot.showGrid(x=True, y=True, alpha=0.12)
        equity_card.add_widget(self.equity_plot)
        center.addWidget(equity_card, 3)

        self.reason_table = DataTable(["Reason", "n", "Profit", "Loss", "Supported", "Contradicted", "Avg P&L"])
        reason_card = Card("REASON-CODE PERFORMANCE")
        reason_card.add_widget(self.reason_table)
        center.addWidget(reason_card, 2)
        root.addLayout(center, 1)

        bottom = QHBoxLayout()
        self.action_table = DataTable(["Action", "Trades", "Win %", "P&L", "Expectancy"])
        action_card = Card("CALL VS PUT")
        action_card.add_widget(self.action_table)
        bottom.addWidget(action_card)
        self.regime_table = DataTable(["Regime", "Trades", "Win %", "P&L", "Expectancy"])
        regime_card = Card("REGIME PERFORMANCE")
        regime_card.add_widget(self.regime_table)
        bottom.addWidget(regime_card)
        self.time_table = DataTable(["Hour", "Trades", "P&L", "Expectancy"])
        time_card = Card("TIME-OF-DAY PERFORMANCE")
        time_card.add_widget(self.time_table)
        bottom.addWidget(time_card)
        root.addLayout(bottom)

    def refresh_manager(self, snapshot, completed_bundles) -> None:
        overall = snapshot.overall
        self.pnl.set_value(str(overall.adjusted_pnl), _tone(overall.adjusted_pnl))
        self.win_rate.set_value("N/A" if overall.win_rate is None else f"{overall.win_rate:.2f}%")
        self.expectancy.set_value(_text(overall.expectancy), _tone(overall.expectancy))
        self.profit_factor.set_value(_text(overall.profit_factor))
        self.drawdown.set_value(str(overall.max_drawdown), "negative" if overall.max_drawdown > 0 else "neutral")
        self.trades.set_value(str(overall.trades))

        equity = float(snapshot.starting_capital)
        ys = [equity]
        for _decision, _trade, outcome in completed_bundles:
            equity += float(outcome.adjusted_pnl)
            ys.append(equity)
        self.equity_plot.clear()
        self.equity_plot.plot(list(range(len(ys))), ys, pen=pg.mkPen("#5f8d9c", width=2))

        self.action_table.set_rows([[name, m.trades, _text(m.win_rate), m.adjusted_pnl, _text(m.expectancy)] for name, m in snapshot.by_action])
        self.regime_table.set_rows([[name, m.trades, _text(m.win_rate), m.adjusted_pnl, _text(m.expectancy)] for name, m in snapshot.by_regime])
        self.time_table.set_rows([[name, m.trades, m.adjusted_pnl, _text(m.expectancy)] for name, m in snapshot.by_hour])
        self.reason_table.set_rows([[r.reason_code, r.occurrences, r.profitable, r.losing, r.supported, r.contradicted, r.average_pnl] for r in snapshot.reasons[:30]])
