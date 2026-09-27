"""Dedicated Shadow Trader research workspace for Intrader.

This page is additive: it reuses the existing immutable shadow-trade records and
does not alter broker connectivity, order handling, Time Travel, Strategy Lab,
or the existing Market Brain.
"""

from __future__ import annotations

from decimal import Decimal

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from intrader.shadow_lab import (
    DATA_COVERAGE,
    DEFAULT_SHADOW_LAB_PLAN,
    FEATURE_FAMILIES,
    NEWS_RESOURCES,
)
from intrader.ui.components import Card, DataTable, MetricCard, ResponsiveMetricGrid


class ShadowTraderPage(QWidget):
    """Research, historical replay, and forward-validation workspace."""

    def __init__(self) -> None:
        super().__init__()
        self.plan = DEFAULT_SHADOW_LAB_PLAN

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 34)
        root.setSpacing(8)

        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("Shadow Trader")
        title.setObjectName("PageTitle")
        subtitle = QLabel(
            "Historical replay + locked blind validation + live shadow trading. "
            "No broker orders are sent from this workspace."
        )
        subtitle.setWordWrap(True)
        subtitle.setObjectName("MutedText")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header.addLayout(title_box, 1)

        source = QLabel("PRIMARY NOW: ANGEL ONE")
        source.setObjectName("StatusPill")
        header.addWidget(source)
        root.addLayout(header)

        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)

        self.tabs.addTab(self._build_overview(), "Overview")
        self.tabs.addTab(self._build_historical(), "90-Day Replay")
        self.tabs.addTab(self._build_forward(), "60-Day Forward")
        self.tabs.addTab(self._build_features(), "50 Features")
        self.tabs.addTab(self._build_data(), "Data Coverage")
        self.tabs.addTab(self._build_news(), "News Resources")

    def _build_overview(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(4, 8, 4, 4)
        root.setSpacing(8)

        self.hist_metric = MetricCard("HISTORICAL SESSIONS")
        self.hist_metric.set_value(str(self.plan.historical_sessions))
        self.split_metric = MetricCard("VALIDATION SPLIT")
        self.split_metric.set_value("60 + 30")
        self.forward_metric = MetricCard("FORWARD SESSIONS")
        self.forward_metric.set_value(str(self.plan.forward_sessions))
        self.feature_metric = MetricCard("FEATURES")
        self.feature_metric.set_value(str(self.plan.feature_count))
        root.addWidget(
            ResponsiveMetricGrid(
                [
                    self.hist_metric,
                    self.split_metric,
                    self.forward_metric,
                    self.feature_metric,
                ],
                compact_height=78,
            )
        )

        protocol = Card("VALIDATION PROTOCOL")
        protocol_text = QLabel(
            "Stage 1 — 60 historical trading sessions for development and diagnostics.\n"
            "Stage 2 — 30 historical trading sessions locked as a blind test. "
            "No threshold, feature, or strategy changes after the blind period begins.\n"
            "Stage 3 — 60 future trading sessions using live data and simulated execution only.\n"
            "A historical replay may only see market/news information whose timestamp is "
            "at or before the simulated clock."
        )
        protocol_text.setWordWrap(True)
        protocol.add_widget(protocol_text)
        root.addWidget(protocol)

        current = Card("CURRENT SHADOW STATE")
        self.active_text = QLabel("No active shadow trade.")
        self.active_text.setWordWrap(True)
        current.add_widget(self.active_text)
        root.addWidget(current)

        history = Card("RECENT COMPLETED SHADOW TRADES")
        self.history = DataTable(
            ["Opened", "Action", "Contract", "Entry", "Exit", "Result", "Adjusted P&L"]
        )
        history.add_widget(self.history)
        root.addWidget(history, 1)
        return page

    def _build_historical(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(4, 8, 4, 4)
        root.setSpacing(8)

        split = Card("90-TRADING-SESSION HISTORICAL LAB")
        split_text = QLabel(
            "Use Angel One immediately for NIFTY, SENSEX, BANK NIFTY, available sector "
            "indices, India VIX and NIFTY constituent history. Expired NIFTY option history "
            "is intentionally marked unavailable until an approved source is connected. "
            "The simulator must not synthesize missing expired-option observations."
        )
        split_text.setWordWrap(True)
        split.add_widget(split_text)
        root.addWidget(split)

        row = QHBoxLayout()
        dev = Card("DEVELOPMENT — 60")
        dev_label = QLabel(
            "Strategies, feature definitions and thresholds may be explored here. "
            "Every change must be versioned."
        )
        dev_label.setWordWrap(True)
        dev.add_widget(dev_label)
        row.addWidget(dev, 2)

        blind = Card("BLIND — 30")
        blind_label = QLabel(
            "Locked examination period. No parameter tuning after entry. Results remain "
            "valid only if the replay is strictly timestamp-causal."
        )
        blind_label.setWordWrap(True)
        blind.add_widget(blind_label)
        row.addWidget(blind, 1)
        root.addLayout(row)

        self.historical_progress = QProgressBar()
        self.historical_progress.setRange(0, self.plan.historical_sessions)
        self.historical_progress.setValue(0)
        self.historical_progress.setFormat(
            "Replay engine not run yet — %v / %m sessions completed"
        )
        root.addWidget(self.historical_progress)

        metrics = Card("REQUIRED OUTPUTS")
        outputs = QLabel(
            "Taken signals • rejected signals • entry/exit • stop/target • friction-adjusted "
            "P&L • MFE/MAE • win rate • expectancy • profit factor • drawdown • streaks • "
            "regime performance • time-of-day performance • feature/strategy variant results."
        )
        outputs.setWordWrap(True)
        metrics.add_widget(outputs)
        root.addWidget(metrics)
        root.addStretch(1)
        return page

    def _build_forward(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(4, 8, 4, 4)
        root.setSpacing(8)

        card = Card("60 FUTURE TRADING SESSIONS")
        text = QLabel(
            "After the historical strategy is locked, run the same rules on future live "
            "market data using simulated execution. No real broker order is permitted. "
            "Angel One option snapshots should be persisted permanently so Intrader retains "
            "its own history after those contracts expire."
        )
        text.setWordWrap(True)
        card.add_widget(text)
        root.addWidget(card)

        self.forward_progress = QProgressBar()
        self.forward_progress.setRange(0, self.plan.forward_sessions)
        self.forward_progress.setValue(0)
        self.forward_progress.setFormat(
            "Forward validation not started — %v / %m sessions completed"
        )
        root.addWidget(self.forward_progress)

        rule = Card("PROMOTION RULE")
        label = QLabel(
            "Historical profitability alone is insufficient. Forward shadow results must be "
            "evaluated after realistic friction and compared with the historical blind period "
            "before any decision about live capital."
        )
        label.setWordWrap(True)
        rule.add_widget(label)
        root.addWidget(rule)
        root.addStretch(1)
        return page

    def _build_features(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(4, 8, 4, 4)
        root.setSpacing(8)

        intro = QLabel(
            "Exactly 50 versioned features grouped into independent families. SENSEX is a "
            "measured confirmation / divergence / lead-lag input; the system does not assume "
            "that SENSEX causes NIFTY movement."
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        table = DataTable(["Family", "Feature", "Role"])
        rows = []
        for family, features in FEATURE_FAMILIES:
            for feature in features:
                role = (
                    "Measured cross-index evidence"
                    if family == "SENSEX confirmation"
                    else "Candidate model input"
                )
                rows.append([family, feature, role])
        table.set_rows(rows)
        root.addWidget(table, 1)
        return page

    def _build_data(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(4, 8, 4, 4)
        root.setSpacing(8)

        table = DataTable(["Dataset", "Source", "Status", "Rule"])
        table.set_rows([list(row) for row in DATA_COVERAGE])
        root.addWidget(table, 1)

        note = QLabel(
            "Upstox expired-options history stays PENDING until account reactivation. "
            "Nothing in this section replaces the existing Angel One pipeline."
        )
        note.setWordWrap(True)
        root.addWidget(note)
        return page

    def _build_news(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(4, 8, 4, 4)
        root.setSpacing(8)

        note = QLabel(
            "These are research resources for the embedded browser. During historical replay, "
            "only timestamped information already published by the simulated time may be used."
        )
        note.setWordWrap(True)
        root.addWidget(note)

        table = DataTable(["Resource", "URL", "Use"])
        table.set_rows(
            [
                [name, url, "Live/manual market context and timestamped research"]
                for name, url in NEWS_RESOURCES
            ]
        )
        root.addWidget(table, 1)
        return page

    def refresh(self, desktop) -> None:
        """Refresh only from existing immutable shadow records."""

        trade = desktop.active_shadow_trade
        if trade is None:
            self.active_text.setText("No active shadow trade.")
        else:
            self.active_text.setText(
                f"{trade.action}\n"
                f"{trade.strike} {trade.option_type}\n"
                f"Entry {trade.entry_price} • Stop {trade.stop_price} • "
                f"Target {trade.target_price}\n"
                f"Quantity {trade.quantity} • {trade.shadow_version}"
            )

        rows = []
        for _decision, completed_trade, outcome in reversed(
            desktop.completed_bundles[-50:]
        ):
            rows.append(
                [
                    completed_trade.opened_at.strftime("%Y-%m-%d %H:%M"),
                    completed_trade.action,
                    f"{completed_trade.strike} {completed_trade.option_type}",
                    completed_trade.entry_price,
                    outcome.exit_price,
                    outcome.exit_reason,
                    outcome.adjusted_pnl,
                ]
            )
        self.history.set_rows(rows)
