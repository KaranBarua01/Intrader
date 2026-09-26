"""Primary Intrader, Time Travel, and Analysis mode pages."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from PySide6.QtCore import QDate, QTime, QTimer, Qt
from PySide6.QtWidgets import (
    QDateEdit, QGridLayout, QHBoxLayout, QLabel, QPushButton, QSlider,
    QTimeEdit, QVBoxLayout, QWidget,
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
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        header = QHBoxLayout()
        title = QLabel("Time Travel")
        title.setObjectName("PageTitle")
        header.addWidget(title)
        header.addSpacing(16)
        self.day = QDateEdit(QDate.currentDate())
        self.day.setCalendarPopup(True)
        self.end_time = QTimeEdit(QTime.currentTime())
        self.end_time.setDisplayFormat("HH:mm")
        self.load_button = QPushButton("Load 30-Minute Window")
        self.load_button.setObjectName("PrimaryButton")
        header.addWidget(self.day)
        header.addWidget(self.end_time)
        header.addWidget(self.load_button)
        header.addStretch(1)
        root.addLayout(header)

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
        root.addLayout(controls)

        body = QHBoxLayout()
        self.chart = MarketChart("30-MINUTE MARKET REPLAY")
        self.chart.setMinimumHeight(390)
        body.addWidget(self.chart, 3)
        side = QVBoxLayout()
        self.decision = DecisionCard()
        side.addWidget(self.decision)
        self.forward_table = DataTable(["Outcome", "Value"])
        outcome_card = Card("WHAT HAPPENED NEXT")
        outcome_card.add_widget(self.forward_table)
        side.addWidget(outcome_card)
        body.addLayout(side, 2)
        root.addLayout(body, 1)

        reasoning = QHBoxLayout()
        self.why = ReasonList("REASONING AT THIS TIMESTAMP")
        self.rejected = ReasonList("REJECTED THESIS")
        reasoning.addWidget(self.why)
        reasoning.addWidget(self.rejected)
        root.addLayout(reasoning)

        self.timer = QTimer(self)
        self.timer.setInterval(900)
        self.timer.timeout.connect(self._tick)
        self.play.clicked.connect(self._toggle_play)
        self.back.clicked.connect(lambda: self.slider.setValue(max(0, self.slider.value() - 1)))
        self.forward.clicked.connect(lambda: self.slider.setValue(min(30, self.slider.value() + 1)))
        self.slider.valueChanged.connect(self._render_position)

    def selected_day(self) -> date:
        return self.day.date().toPython()

    def selected_end_datetime(self) -> datetime:
        qd = self.day.date()
        qt = self.end_time.time()
        return datetime(qd.year(), qd.month(), qd.day(), qt.hour(), qt.minute(), tzinfo=INDIA_TIME)

    def set_session_data(self, decisions, bundles, candles) -> None:
        self._decisions = tuple(decisions)
        self._bundles = tuple(bundles)
        end = self.selected_end_datetime()
        start = end - timedelta(minutes=30)
        window = tuple(c for c in candles if start <= c.at.astimezone(INDIA_TIME) <= end)
        rows = [(float(i), float(c.open), float(c.close), float(c.low), float(c.high)) for i, c in enumerate(window)]
        if rows:
            self.chart.set_candles(rows)
        else:
            self.chart.set_empty_message("No candles in this 30-minute replay window.")
        self.slider.setValue(30)
        self._render_position()

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
        value = self.slider.value()
        end = self.selected_end_datetime()
        selected = end - timedelta(minutes=(30 - value))
        self.position.setText(selected.strftime("%H:%M"))
        eligible = [d for d in self._decisions if d.decided_at.astimezone(INDIA_TIME) <= selected]
        decision = eligible[-1] if eligible else None
        if decision is None:
            self.decision.set_decision("NO DECISION", "No recorded decision existed by this replay time.")
            self.why.set_reasons([])
            self.rejected.set_reasons([])
            self.forward_table.set_rows([])
            return
        self.decision.set_decision(decision.action, f"{decision.regime} • {decision.decided_at.astimezone(INDIA_TIME):%H:%M:%S}")
        self.why.set_reasons([(r.reason_code, r.explanation) for r in decision.reasons if r.thesis == "CHOSEN"])
        self.rejected.set_reasons([(r.reason_code, r.explanation) for r in decision.reasons if r.thesis == "REJECTED"])
        bundle = next((b for b in self._bundles if b[0].decision_id == decision.decision_id), None)
        if bundle is None:
            self.forward_table.set_rows([["Shadow outcome", "Not completed / not actionable"]])
        else:
            outcome = bundle[2]
            rows = [["Exit", f"{outcome.exit_reason} @ {outcome.exit_price}"], ["Adjusted P&L", outcome.adjusted_pnl], ["MFE", outcome.mfe_amount], ["MAE", outcome.mae_amount]]
            rows.extend([[f"{minutes}m", "N/A" if result is None else f"{result}%"] for minutes, result in outcome.forward_returns])
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
