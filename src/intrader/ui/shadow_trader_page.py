"""Dedicated Shadow Trader research workspace for Intrader.

This page is additive: it reuses the existing immutable shadow-trade records and
does not alter broker connectivity, order handling, Time Travel, Strategy Lab,
or the existing Market Brain.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from intrader.shadow_lab import (
    DATA_COVERAGE,
    DEFAULT_SHADOW_LAB_PLAN,
    FEATURE_FAMILIES,
    NEWS_RESOURCES,
    REPLAY_MODES,
    REPLAY_SESSION_OPTIONS,
    development_blind_split,
    replay_mode,
)
from intrader.ui.components import Card, DataTable, MetricCard, ResponsiveMetricGrid


class ShadowTraderPage(QWidget):
    """Research, historical replay, and forward-validation workspace."""

    replay_requested = Signal(int, str)
    replay_export_requested = Signal(int, str)

    def __init__(self) -> None:
        super().__init__()
        self.plan = DEFAULT_SHADOW_LAB_PLAN
        self._replay_running = False

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
        self.tabs.addTab(self._build_historical(), "Replay")
        self.tabs.addTab(self._build_forward(), "60-Day Forward")
        self.tabs.addTab(self._build_features(), "50 Features")
        self.tabs.addTab(self._build_data(), "Data Coverage")
        self.tabs.addTab(self._build_news(), "News Resources")

    def _build_overview(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(4, 8, 4, 4)
        root.setSpacing(8)

        self.hist_metric = MetricCard("MAX HISTORICAL SESSIONS")
        self.hist_metric.set_value(str(self.plan.historical_sessions))
        self.split_metric = MetricCard("DEFAULT VALIDATION SPLIT")
        self.split_metric.set_value("60 + 30")
        self.forward_metric = MetricCard("FORWARD SESSIONS")
        self.forward_metric.set_value(str(self.plan.forward_sessions))
        self.feature_metric = MetricCard("HIGH MODE FEATURES")
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
            "Choose 30, 60 or 90 historical trading sessions. The first two-thirds are "
            "development and the final one-third is locked blind validation. Within every "
            "session, the replay brain may only read observations with timestamp <= the "
            "simulated clock. The next 60 real trading sessions remain forward shadow testing."
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

        controls = Card("REPLAY CONTROL")
        selectors = QHBoxLayout()

        range_label = QLabel("Range")
        selectors.addWidget(range_label)
        self.replay_range = QComboBox()
        for sessions in REPLAY_SESSION_OPTIONS:
            self.replay_range.addItem(f"{sessions} trading days", sessions)
        self.replay_range.setCurrentIndex(self.replay_range.findData(90))
        selectors.addWidget(self.replay_range)

        mode_label = QLabel("Mode")
        selectors.addWidget(mode_label)
        self.replay_mode = QComboBox()
        for mode in REPLAY_MODES:
            self.replay_mode.addItem(
                f"{mode.label} — {mode.feature_count} touchpoints",
                mode.key,
            )
        self.replay_mode.setCurrentIndex(self.replay_mode.findData("MEDIUM"))
        selectors.addWidget(self.replay_mode)
        selectors.addStretch(1)
        controls.layout_box.addLayout(selectors)

        self.mode_description = QLabel()
        self.mode_description.setWordWrap(True)
        controls.add_widget(self.mode_description)

        buttons = QHBoxLayout()
        self.replay_start_button = QPushButton("▶  Start Replay")
        self.replay_start_button.setObjectName("PrimaryButton")
        self.replay_export_button = QPushButton("↓  Export Results")
        self.replay_export_button.setObjectName("SecondaryButton")
        buttons.addWidget(self.replay_start_button)
        buttons.addStretch(1)
        buttons.addWidget(self.replay_export_button)
        controls.layout_box.addLayout(buttons)

        self.replay_status = QLabel(
            "READY — choose a range and depth, then start the historical shadow replay."
        )
        self.replay_status.setWordWrap(True)
        controls.add_widget(self.replay_status)
        root.addWidget(controls)

        self.split_card = Card("VALIDATION SPLIT")
        self.split_text = QLabel()
        self.split_text.setWordWrap(True)
        self.split_card.add_widget(self.split_text)
        root.addWidget(self.split_card)

        self.historical_progress = QProgressBar()
        self.historical_progress.setRange(0, 90)
        self.historical_progress.setValue(0)
        self.historical_progress.setFormat("%v / %m trading sessions")
        root.addWidget(self.historical_progress)

        self.replay_strategy_metric = MetricCard("FROZEN STRATEGY")
        self.replay_strategy_metric.set_value("—")
        self.replay_win_metric = MetricCard("BLIND WIN RATE")
        self.replay_win_metric.set_value("—")
        self.replay_expectancy_metric = MetricCard("BLIND AVG 30M RETURN")
        self.replay_expectancy_metric.set_value("—")
        self.replay_signal_metric = MetricCard("BLIND SIGNALS")
        self.replay_signal_metric.set_value("—")
        root.addWidget(
            ResponsiveMetricGrid(
                [
                    self.replay_strategy_metric,
                    self.replay_win_metric,
                    self.replay_expectancy_metric,
                    self.replay_signal_metric,
                ],
                compact_height=78,
            )
        )

        integrity = Card("REPLAY INTEGRITY")
        integrity_text = QLabel(
            "No look-ahead: future candles, future news, end-of-day highs/lows, future "
            "normalization values and blind-period observations are unavailable to the "
            "decision engine until the simulated clock reaches them."
        )
        integrity_text.setWordWrap(True)
        integrity.add_widget(integrity_text)
        root.addWidget(integrity)

        metrics = Card("RESULTS CAPTURED FOR REVIEW")
        outputs = QLabel(
            "Taken signals • rejected signals • entry/exit • stop/target • friction-adjusted "
            "P&L when executable price data exists • MFE/MAE • win rate • expectancy • "
            "profit factor • drawdown • streaks • regime/time performance • feature coverage "
            "• strategy/version metadata. Export Results creates a review bundle you can upload "
            "back into ChatGPT for diagnosis."
        )
        outputs.setWordWrap(True)
        metrics.add_widget(outputs)
        root.addWidget(metrics)
        root.addStretch(1)

        self.replay_range.currentIndexChanged.connect(self._sync_replay_controls)
        self.replay_mode.currentIndexChanged.connect(self._sync_replay_controls)
        self.replay_start_button.clicked.connect(self._request_replay)
        self.replay_export_button.clicked.connect(self._request_export)
        self._sync_replay_controls()
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
            "High mode requests all 50 versioned features. Medium and Low deliberately use "
            "smaller family sets so we can compare whether extra data genuinely improves "
            "expectancy or only adds complexity. SENSEX remains measured evidence, not a "
            "hard-coded cause of NIFTY movement."
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
            "High mode must mark unavailable historical option families as missing; it must "
            "never manufacture them. Nothing here replaces the existing Angel One pipeline."
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

    def selected_replay_sessions(self) -> int:
        return int(self.replay_range.currentData())

    def selected_replay_mode(self) -> str:
        return str(self.replay_mode.currentData())

    def _sync_replay_controls(self) -> None:
        sessions = self.selected_replay_sessions()
        mode = replay_mode(self.selected_replay_mode())
        development, blind = development_blind_split(sessions)
        self.historical_progress.setRange(0, sessions)
        if not self._replay_running:
            self.historical_progress.setValue(0)
        self.mode_description.setText(
            f"{mode.label.upper()} MODE — {mode.feature_count} touchpoints. "
            f"{mode.description}"
        )
        self.split_text.setText(
            f"{development} development sessions + {blind} locked blind sessions. "
            "The blind segment starts only after the replay configuration is frozen."
        )

    def _request_replay(self) -> None:
        if self._replay_running:
            return
        self._replay_running = True
        self.replay_start_button.setEnabled(False)
        self.replay_range.setEnabled(False)
        self.replay_mode.setEnabled(False)
        self.replay_export_button.setEnabled(False)
        self.replay_status.setText(
            "STARTING — preparing timestamp-causal historical data and replay state…"
        )
        self.replay_requested.emit(
            self.selected_replay_sessions(),
            self.selected_replay_mode(),
        )

    def _request_export(self) -> None:
        self.replay_export_requested.emit(
            self.selected_replay_sessions(),
            self.selected_replay_mode(),
        )

    def set_replay_progress(
        self,
        completed: int,
        total: int,
        status: str,
    ) -> None:
        total = max(1, int(total))
        completed = max(0, min(int(completed), total))
        self.historical_progress.setRange(0, total)
        self.historical_progress.setValue(completed)
        self.historical_progress.setFormat("%v / %m trading sessions")
        self.replay_status.setText(status)

    def set_replay_report(self, report) -> None:
        strategy = report.selected_strategy_name or "None"
        self.replay_strategy_metric.set_value(strategy)
        self.replay_win_metric.set_value(
            "N/A"
            if report.blind.win_rate_pct is None
            else f"{report.blind.win_rate_pct:.2f}%"
        )
        self.replay_expectancy_metric.set_value(
            "N/A"
            if report.blind.average_return_30m_pct is None
            else f"{report.blind.average_return_30m_pct:.4f}%"
        )
        self.replay_signal_metric.set_value(str(report.blind.evaluable_signals))

    def set_replay_finished(self, status: str) -> None:
        self._replay_running = False
        self.replay_start_button.setEnabled(True)
        self.replay_range.setEnabled(True)
        self.replay_mode.setEnabled(True)
        self.replay_export_button.setEnabled(True)
        self.replay_status.setText(status)

    def set_replay_failed(self, status: str) -> None:
        self.set_replay_finished(f"FAILED — {status}")

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
