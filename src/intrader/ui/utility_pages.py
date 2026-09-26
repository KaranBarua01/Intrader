"""Supporting desktop pages for Intrader Phase 4."""

from __future__ import annotations

from decimal import Decimal

from PySide6.QtCore import QUrl, Signal, Qt
from PySide6.QtWidgets import (
    QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSplitter,
    QVBoxLayout, QWidget,
)

from intrader.ui.components import (
    Card, DataTable, DecisionCard, MetricCard, ReasonList, ResponsiveMetricGrid,
    StatusPill,
)

try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
except Exception:
    QWebEngineView = None


def _fmt(value) -> str:
    return "N/A" if value is None else str(value)


class DashboardPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 34)
        root.setSpacing(8)
        title = QLabel("Dashboard")
        title.setObjectName("PageTitle")
        root.addWidget(title)

        top = QHBoxLayout()
        self.decision = DecisionCard()
        top.addWidget(self.decision, 3)
        self.equity = MetricCard("SHADOW EQUITY")
        self.pnl = MetricCard("ADJUSTED P&L")
        self.trades = MetricCard("TRADES")
        self.win = MetricCard("WIN RATE")
        self.metric_grid = ResponsiveMetricGrid(
            [self.equity, self.pnl, self.trades, self.win],
            compact_height=76,
        )
        top.addWidget(self.metric_grid, 5)
        root.addLayout(top)

        self.dashboard_splitter = QSplitter(Qt.Orientation.Horizontal)
        health = Card("SYSTEM SNAPSHOT")
        self.health_text = QLabel("Waiting for refresh.")
        self.health_text.setWordWrap(True)
        health.add_widget(self.health_text)
        self.dashboard_splitter.addWidget(health)

        context = Card("RECENT CONTEXT")
        self.context = DataTable(["Time", "Source", "Context"])
        context.add_widget(self.context)
        self.dashboard_splitter.addWidget(context)
        self.dashboard_splitter.setStretchFactor(0, 2)
        self.dashboard_splitter.setStretchFactor(1, 5)
        root.addWidget(self.dashboard_splitter, 1)

    def resizeEvent(self, event) -> None:
        self.dashboard_splitter.setOrientation(
            Qt.Orientation.Vertical
            if event.size().width() < 900
            else Qt.Orientation.Horizontal
        )
        super().resizeEvent(event)

    def apply_layout_preset(self, preset: str) -> None:
        width = max(1, self.width())
        if preset == "Monitoring":
            self.dashboard_splitter.setSizes([int(width * 0.35), int(width * 0.65)])
        elif preset == "Analysis":
            self.dashboard_splitter.setSizes([int(width * 0.22), int(width * 0.78)])
        else:
            self.dashboard_splitter.setSizes([int(width * 0.28), int(width * 0.72)])

    def refresh(self, desktop, manager) -> None:
        d = desktop.latest_decision
        if d is None:
            self.decision.set_decision(
                "WAITING FOR DATA",
                "No immutable Market Brain decision recorded yet.",
            )
        else:
            self.decision.set_decision(
                d.action, f"{d.regime} • {d.brain_version}"
            )
        self.equity.set_value(str(manager.current_equity))
        self.pnl.set_value(str(manager.overall.adjusted_pnl))
        self.trades.set_value(str(manager.overall.trades))
        self.win.set_value(
            "N/A"
            if manager.overall.win_rate is None
            else f"{manager.overall.win_rate:.2f}%"
        )
        available = sum(
            1 for _, count in desktop.database_counts if count > 0
        )
        empty = sum(
            1 for _, count in desktop.database_counts if count == 0
        )
        errors = sum(
            1 for _, count in desktop.database_counts if count < 0
        )
        self.health_text.setText(
            f"Available data families: {available}\n"
            f"Empty: {empty} • Errors: {errors}\n"
            f"Active shadow position: {'YES' if desktop.active_shadow_trade else 'NO'}"
        )
        rows = []
        for event in desktop.upcoming_events[:5]:
            rows.append([
                event.scheduled_at.strftime("%H:%M"),
                event.source,
                event.name,
            ])
        for item in desktop.recent_news[:5]:
            rows.append([
                item.published_at.strftime("%H:%M"),
                item.source,
                item.title,
            ])
        self.context.set_rows(
            rows or [["—", "—", "No recent market context. Refresh when needed."]]
        )


class ThesisPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        title = QLabel("Thesis")
        title.setObjectName("PageTitle")
        root.addWidget(title)
        self.decision = DecisionCard()
        root.addWidget(self.decision)
        row = QHBoxLayout()
        self.chosen = ReasonList("CHOSEN THESIS")
        self.rejected = ReasonList("REJECTED OPPOSITE THESIS")
        self.gates = ReasonList("GATES / CONTEXT")
        row.addWidget(self.chosen)
        row.addWidget(self.rejected)
        row.addWidget(self.gates)
        root.addLayout(row, 1)

    def refresh(self, desktop) -> None:
        d = desktop.latest_decision
        if d is None:
            self.decision.set_decision("NO DECISION")
            self.chosen.set_reasons([])
            self.rejected.set_reasons([])
            self.gates.set_reasons([])
            return
        self.decision.set_decision(d.action, f"Direction {d.direction_score} • Confidence {d.confidence} • {d.regime}")
        self.chosen.set_reasons([(r.reason_code, r.explanation) for r in d.reasons if r.thesis == "CHOSEN"])
        self.rejected.set_reasons([(r.reason_code, r.explanation) for r in d.reasons if r.thesis == "REJECTED"])
        self.gates.set_reasons([(r.reason_code, r.explanation) for r in d.reasons if r.thesis == "GATE"])


class ShadowTraderPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        title = QLabel("Shadow Trader")
        title.setObjectName("PageTitle")
        root.addWidget(title)
        self.active = Card("ACTIVE SIMULATED POSITION")
        self.active_text = QLabel("No active shadow trade.")
        self.active_text.setWordWrap(True)
        self.active.add_widget(self.active_text)
        root.addWidget(self.active)
        self.history = DataTable(["Opened", "Action", "Contract", "Entry", "Exit", "Result", "Adjusted P&L"])
        history_card = Card("COMPLETED SHADOW TRADES")
        history_card.add_widget(self.history)
        root.addWidget(history_card, 1)

    def refresh(self, desktop) -> None:
        trade = desktop.active_shadow_trade
        if trade is None:
            self.active_text.setText("No active shadow trade.")
        else:
            self.active_text.setText(f"{trade.action}\n{trade.strike} {trade.option_type}\nEntry {trade.entry_price} • Stop {trade.stop_price} • Target {trade.target_price}\nQuantity {trade.quantity} • {trade.shadow_version}")
        rows = []
        for _decision, trade, outcome in reversed(desktop.completed_bundles[-50:]):
            rows.append([trade.opened_at.strftime("%Y-%m-%d %H:%M"), trade.action, f"{trade.strike} {trade.option_type}", trade.entry_price, outcome.exit_price, outcome.exit_reason, outcome.adjusted_pnl])
        self.history.set_rows(rows)


class TradeHistoryPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        title = QLabel("Trade History")
        title.setObjectName("PageTitle")
        root.addWidget(title)
        self.table = DataTable(["Time", "Action", "Regime", "Contract", "Entry", "Exit", "P&L", "Decision ID"])
        root.addWidget(self.table, 1)

    def refresh(self, desktop) -> None:
        rows = []
        for decision, trade, outcome in reversed(desktop.completed_bundles):
            rows.append([trade.opened_at.strftime("%Y-%m-%d %H:%M"), trade.action, decision.regime, f"{trade.strike} {trade.option_type}", trade.entry_price, outcome.exit_price, outcome.adjusted_pnl, decision.decision_id])
        self.table.set_rows(rows)


class RecordsManagerPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        title = QLabel("Records Manager")
        title.setObjectName("PageTitle")
        root.addWidget(title)
        metrics = QHBoxLayout()
        self.cards = {
            "equity": MetricCard("SHADOW EQUITY"),
            "pnl": MetricCard("ADJUSTED P&L"),
            "expectancy": MetricCard("EXPECTANCY"),
            "pf": MetricCard("PROFIT FACTOR"),
            "dd": MetricCard("MAX DRAWDOWN"),
            "streak": MetricCard("WIN / LOSS STREAK MAX"),
        }
        for card in self.cards.values():
            metrics.addWidget(card)
        root.addLayout(metrics)
        self.reason_table = DataTable(["Reason", "Occurrences", "Profit", "Loss", "Supported", "Contradicted", "Avg P&L"])
        card = Card("REASONING PERFORMANCE")
        card.add_widget(self.reason_table)
        root.addWidget(card, 1)

    def refresh(self, manager) -> None:
        o = manager.overall
        self.cards["equity"].set_value(str(manager.current_equity))
        self.cards["pnl"].set_value(str(o.adjusted_pnl))
        self.cards["expectancy"].set_value(_fmt(o.expectancy))
        self.cards["pf"].set_value(_fmt(o.profit_factor))
        self.cards["dd"].set_value(f"{o.max_drawdown} ({o.max_drawdown_pct:.2f}%)")
        self.cards["streak"].set_value(f"{o.max_winning_streak} / {o.max_losing_streak}")
        self.reason_table.set_rows([[r.reason_code, r.occurrences, r.profitable, r.losing, r.supported, r.contradicted, r.average_pnl] for r in manager.reasons])


class ResearchBrowserPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        title = QLabel("Market Research Browser")
        title.setObjectName("PageTitle")
        root.addWidget(title)
        toolbar = QHBoxLayout()
        self.back = QPushButton("Back")
        self.forward = QPushButton("Forward")
        self.reload = QPushButton("Refresh")
        self.address = QLineEdit("https://news.google.com/home")
        self.go = QPushButton("Go")
        self.go.setObjectName("PrimaryButton")
        for widget in (self.back, self.forward, self.reload):
            toolbar.addWidget(widget)
        toolbar.addWidget(self.address, 1)
        toolbar.addWidget(self.go)
        root.addLayout(toolbar)
        if QWebEngineView is None:
            fallback = QLabel("Qt WebEngine is unavailable. Install the Phase 4 UI dependencies to enable the embedded research browser.")
            fallback.setWordWrap(True)
            root.addWidget(fallback, 1)
            self.browser = None
        else:
            self.browser = QWebEngineView()
            self.browser.setUrl(QUrl(self.address.text()))
            root.addWidget(self.browser, 1)
            self.back.clicked.connect(self.browser.back)
            self.forward.clicked.connect(self.browser.forward)
            self.reload.clicked.connect(self.browser.reload)
            self.go.clicked.connect(self._navigate)
            self.address.returnPressed.connect(self._navigate)
            self.browser.urlChanged.connect(lambda url: self.address.setText(url.toString()))

    def _navigate(self) -> None:
        if self.browser is None:
            return
        text = self.address.text().strip()
        if not text.startswith(("http://", "https://")):
            text = "https://" + text
        self.browser.setUrl(QUrl(text))


class CalibrationPage(QWidget):
    refresh_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        head = QHBoxLayout()
        title = QLabel("Calibration")
        title.setObjectName("PageTitle")
        self.refresh_button = QPushButton("Run Calibration")
        self.refresh_button.setObjectName("PrimaryButton")
        self.refresh_button.clicked.connect(self.refresh_requested.emit)
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(self.refresh_button)
        root.addLayout(head)
        self.summary = QLabel("Calibration requires completed shadow history.")
        self.summary.setWordWrap(True)
        card = Card("TRAIN / VALIDATION / TEST")
        card.add_widget(self.summary)
        root.addWidget(card)
        self.table = DataTable(["Slice", "Trades", "Expectancy", "P&L", "Profit Factor", "Drawdown %"])
        root.addWidget(self.table, 1)

    def set_report(self, report, promotion=None) -> None:
        c = report.candidate
        status = "N/A" if promotion is None else promotion.status
        self.summary.setText(f"Candidate: |Direction| ≥ {c.direction_min}, Confidence ≥ {c.confidence_min}, Entry ≥ {c.entry_quality_min}, Risk ≤ {c.reversal_risk_max}\nPromotion gate: {status}\n{report.limitation}")
        self.table.set_rows([
            ["TRAIN", report.train_metrics.trades, _fmt(report.train_metrics.expectancy), report.train_metrics.adjusted_pnl, _fmt(report.train_metrics.profit_factor), report.train_metrics.max_drawdown_pct],
            ["VALIDATION", report.validation_metrics.trades, _fmt(report.validation_metrics.expectancy), report.validation_metrics.adjusted_pnl, _fmt(report.validation_metrics.profit_factor), report.validation_metrics.max_drawdown_pct],
            ["TEST", report.test_metrics.trades, _fmt(report.test_metrics.expectancy), report.test_metrics.adjusted_pnl, _fmt(report.test_metrics.profit_factor), report.test_metrics.max_drawdown_pct],
        ])


class SystemHealthPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 34)
        title_row = QHBoxLayout()
        title = QLabel("System Health")
        title.setObjectName("PageTitle")
        title_row.addWidget(title)
        note = QLabel("AVAILABLE means data exists; EMPTY is not treated as healthy coverage.")
        note.setObjectName("Muted")
        title_row.addStretch(1)
        title_row.addWidget(note)
        root.addLayout(title_row)

        self.pills_layout = QGridLayout()
        self.pills_layout.setHorizontalSpacing(8)
        self.pills_layout.setVerticalSpacing(8)
        self.pills = {}
        for index, name in enumerate((
            "Database", "Candles", "Options", "Futures", "VIX / Index",
            "Breadth", "Order Flow", "News", "Events", "Decisions",
            "Outcomes", "Audits",
        )):
            pill = StatusPill(name, None)
            self.pills[name] = pill
            self.pills_layout.addWidget(pill, index // 4, index % 4)
        root.addLayout(self.pills_layout)

        self.table = DataTable(["Storage / Context", "Rows", "State"])
        root.addWidget(self.table, 1)

    def refresh(self, desktop) -> None:
        mapping = {
            "candles": "Candles",
            "option_snapshots": "Options",
            "future_snapshots": "Futures",
            "index_snapshots": "VIX / Index",
            "breadth_snapshots": "Breadth",
            "order_flow_context": "Order Flow",
            "news_items": "News",
            "scheduled_events": "Events",
            "decision_records": "Decisions",
            "shadow_outcomes": "Outcomes",
            "reason_audits": "Audits",
        }
        rows = []
        db_ok = True
        for table, count in desktop.database_counts:
            if count < 0:
                state = "ERROR"
                ok = False
                db_ok = False
            elif count == 0:
                state = "EMPTY"
                ok = None
            else:
                state = "AVAILABLE"
                ok = True
            rows.append([table, count if count >= 0 else "N/A", state])
            if table in mapping:
                label = mapping[table]
                self.pills[label].set_status(
                    f"{label}: {state}",
                    ok,
                )
        self.pills["Database"].set_status(
            "Database: OK" if db_ok else "Database: ERROR",
            db_ok,
        )


class ExportPage(QWidget):
    shadow_export_requested = Signal()
    reasoning_export_requested = Signal()
    audit_export_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        title = QLabel("Export")
        title.setObjectName("PageTitle")
        root.addWidget(title)
        card = Card("EXPORT IMMUTABLE SHADOW LEARNING DATA")
        desc = QLabel("Exports are copies only. They never modify the Intrader database.")
        desc.setWordWrap(True)
        card.add_widget(desc)
        row = QWidget()
        row_layout = QHBoxLayout(row)
        self.shadow = QPushButton("Export Shadow Results CSV")
        self.reasoning = QPushButton("Export Full Reasoning JSON")
        self.audits = QPushButton("Export Reason Audits CSV")
        for button in (self.shadow, self.reasoning, self.audits):
            button.setObjectName("PrimaryButton")
            row_layout.addWidget(button)
        card.add_widget(row)
        root.addWidget(card)
        root.addStretch(1)
        self.shadow.clicked.connect(self.shadow_export_requested.emit)
        self.reasoning.clicked.connect(self.reasoning_export_requested.emit)
        self.audits.clicked.connect(self.audit_export_requested.emit)
