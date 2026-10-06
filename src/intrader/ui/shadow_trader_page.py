"""Dedicated Shadow Trader research workspace for Intrader.

The workspace is research-only. Historical replay, paper capital and visual
playback never send broker orders or mutate Intrader's live execution rules.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from intrader.shadow_lab import (
    DATA_COVERAGE,
    DEFAULT_SHADOW_LAB_PLAN,
    DEFAULT_TRADER_TIMEFRAMES,
    FEATURE_FAMILIES,
    EXECUTION_MODES,
    MAX_REPLAY_SESSION_INPUT,
    NEWS_RESOURCES,
    REPLAY_MODES,
    VALIDATION_MODES,
    ShadowReplayConfig,
    replay_mode,
    validate_replay_config,
)
from intrader.ui.components import Card, DataTable, MarketChart, MetricCard, ResponsiveMetricGrid


TRADER_TITLES = {
    1: "1M SCALPER",
    5: "5M FAST",
    10: "10M MOMENTUM",
    15: "15M TREND",
}


class ShadowTraderPage(QWidget):
    """Historical validation, Shadow Arena and forward shadow workspace."""

    replay_requested = Signal(object)
    replay_export_requested = Signal(object)
    playback_finished = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.plan = DEFAULT_SHADOW_LAB_PLAN
        self._replay_running = False
        self._latest_config = ShadowReplayConfig()

        self._playback_timer = QTimer(self)
        self._playback_timer.setInterval(50)
        self._playback_timer.timeout.connect(self._playback_tick)
        self._playback_candles = ()
        self._playback_report = None
        self._playback_index = 0
        self._playback_events = ()
        self._playback_event_index = 0
        self._playback_open: dict[int, list[tuple[object, datetime]]] = {}
        self._playback_tape_rows: list[list[object]] = []
        self._playback_session_dates = ()
        self._playback_session_bounds: dict[object, tuple[int, int]] = {}
        self._playback_phase = None
        self._arena_runtime: dict[int, dict[str, object]] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 34)
        root.setSpacing(8)

        header = QHBoxLayout()
        title_box = QVBoxLayout()
        title = QLabel("Shadow Trader")
        title.setObjectName("PageTitle")
        subtitle = QLabel(
            "Configurable historical validation + four parallel paper traders + future shadow trading. "
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
        self.tabs.addTab(self._build_historical(), "Replay Setup")
        self.live_page = self._build_live_replay()
        self.live_tab_index = self.tabs.addTab(self.live_page, "Shadow Arena")
        self.results_page = self._build_results()
        self.results_tab_index = self.tabs.addTab(self.results_page, "Results")
        self.tabs.addTab(self._build_forward(), "60-Day Forward")
        self.tabs.addTab(self._build_features(), "50 Features")
        self.tabs.addTab(self._build_data(), "Data Coverage")
        self.tabs.addTab(self._build_news(), "News Resources")

    def _build_overview(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(4, 8, 4, 4)
        root.setSpacing(8)

        self.hist_metric = MetricCard("DEVELOPMENT")
        self.hist_metric.set_value("1–500 days")
        self.split_metric = MetricCard("BLIND")
        self.split_metric.set_value("1–500 days")
        self.forward_metric = MetricCard("FORWARD")
        self.forward_metric.set_value(f"{self.plan.forward_sessions} days")
        self.feature_metric = MetricCard("PARALLEL TRADERS")
        self.feature_metric.set_value("1M • 5M • 10M • 15M")
        root.addWidget(
            ResponsiveMetricGrid(
                [self.hist_metric, self.split_metric, self.forward_metric, self.feature_metric],
                compact_height=78,
            )
        )

        protocol = Card("VALIDATION PROTOCOL")
        protocol_text = QLabel(
            "You choose development and blind periods independently. Development may be inspected "
            "and used to select a strategy. Blind is locked: no strategy, threshold or feature "
            "changes after it begins. At simulated time T, the decision side may read only "
            "observations timestamped at or before T."
        )
        protocol_text.setWordWrap(True)
        protocol.add_widget(protocol_text)
        root.addWidget(protocol)

        current = Card("CURRENT FORWARD SHADOW STATE")
        self.active_text = QLabel("No active forward shadow trade.")
        self.active_text.setWordWrap(True)
        current.add_widget(self.active_text)
        root.addWidget(current)

        history = Card("RECENT COMPLETED FORWARD SHADOW TRADES")
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

        controls = Card("REPLAY CONFIGURATION")
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)

        grid.addWidget(QLabel("Development"), 0, 0)
        self.development_days = QSpinBox()
        self.development_days.setRange(1, MAX_REPLAY_SESSION_INPUT)
        self.development_days.setValue(60)
        self.development_days.setSuffix(" trading days")
        grid.addWidget(self.development_days, 0, 1)

        grid.addWidget(QLabel("Blind"), 0, 2)
        self.blind_days = QSpinBox()
        self.blind_days.setRange(1, MAX_REPLAY_SESSION_INPUT)
        self.blind_days.setValue(30)
        self.blind_days.setSuffix(" trading days")
        grid.addWidget(self.blind_days, 0, 3)

        grid.addWidget(QLabel("Data depth"), 0, 4)
        self.replay_mode = QComboBox()
        for mode in REPLAY_MODES:
            self.replay_mode.addItem(
                f"{mode.label} — {mode.feature_count} touchpoints", mode.key
            )
        self.replay_mode.setCurrentIndex(self.replay_mode.findData("MEDIUM"))
        grid.addWidget(self.replay_mode, 0, 5)

        grid.addWidget(QLabel("Fake starting money"), 1, 0)
        self.starting_capital = QDoubleSpinBox()
        self.starting_capital.setRange(100, 100000000)
        self.starting_capital.setDecimals(0)
        self.starting_capital.setSingleStep(5000)
        self.starting_capital.setValue(50000)
        self.starting_capital.setPrefix("₹")
        grid.addWidget(self.starting_capital, 1, 1)

        grid.addWidget(QLabel("Position size"), 1, 2)
        self.allocation_pct = QDoubleSpinBox()
        self.allocation_pct.setRange(1, 100)
        self.allocation_pct.setDecimals(1)
        self.allocation_pct.setValue(25)
        self.allocation_pct.setSuffix("% of equity")
        grid.addWidget(self.allocation_pct, 1, 3)

        grid.addWidget(QLabel("Estimated friction"), 1, 4)
        self.friction_bps = QDoubleSpinBox()
        self.friction_bps.setRange(0, 1000)
        self.friction_bps.setDecimals(1)
        self.friction_bps.setValue(5)
        self.friction_bps.setSuffix(" bps / trade")
        grid.addWidget(self.friction_bps, 1, 5)

        grid.addWidget(QLabel("Validation"), 2, 0)
        self.validation_mode = QComboBox()
        self.validation_mode.addItem("Standard frozen blind", "STANDARD")
        self.validation_mode.addItem("Walk-forward + frozen blind", "WALK_FORWARD")
        grid.addWidget(self.validation_mode, 2, 1)

        grid.addWidget(QLabel("Execution"), 2, 2)
        self.execution_mode = QComboBox()
        self.execution_mode.addItem("NIFTY proxy", "PROXY")
        self.execution_mode.addItem("Exact option premium (when available)", "OPTION_PREMIUM")
        self.execution_mode.setToolTip(
            "Exact option mode requires timestamped historical option premiums. "
            "Intrader will refuse it when the data is unavailable."
        )
        grid.addWidget(self.execution_mode, 2, 3)

        grid.addWidget(QLabel("Walk train / test"), 2, 4)
        walk_row = QHBoxLayout()
        self.walk_train_days = QSpinBox()
        self.walk_train_days.setRange(1, MAX_REPLAY_SESSION_INPUT)
        self.walk_train_days.setValue(60)
        self.walk_train_days.setSuffix(" train")
        self.walk_test_days = QSpinBox()
        self.walk_test_days.setRange(1, MAX_REPLAY_SESSION_INPUT)
        self.walk_test_days.setValue(15)
        self.walk_test_days.setSuffix(" test")
        walk_row.addWidget(self.walk_train_days)
        walk_row.addWidget(self.walk_test_days)
        grid.addLayout(walk_row, 2, 5)

        grid.addWidget(QLabel("Walk step / windows"), 3, 0)
        walk_step_row = QHBoxLayout()
        self.walk_step_days = QSpinBox()
        self.walk_step_days.setRange(1, MAX_REPLAY_SESSION_INPUT)
        self.walk_step_days.setValue(15)
        self.walk_step_days.setSuffix(" step")
        self.walk_windows = QSpinBox()
        self.walk_windows.setRange(1, 20)
        self.walk_windows.setValue(4)
        self.walk_windows.setSuffix(" windows")
        walk_step_row.addWidget(self.walk_step_days)
        walk_step_row.addWidget(self.walk_windows)
        grid.addLayout(walk_step_row, 3, 1, 1, 2)

        grid.addWidget(QLabel("Parallel traders"), 3, 3)
        trader_row = QHBoxLayout()
        self.trader_checks: dict[int, QCheckBox] = {}
        for timeframe in DEFAULT_TRADER_TIMEFRAMES:
            check = QCheckBox(TRADER_TITLES[timeframe])
            check.setChecked(True)
            self.trader_checks[timeframe] = check
            trader_row.addWidget(check)
        trader_row.addStretch(1)
        grid.addLayout(trader_row, 3, 4, 1, 2)
        controls.layout_box.addLayout(grid)

        self.mode_description = QLabel()
        self.mode_description.setWordWrap(True)
        controls.add_widget(self.mode_description)

        buttons = QHBoxLayout()
        self.replay_start_button = QPushButton("▶  Start Shadow Arena")
        self.replay_start_button.setObjectName("PrimaryButton")
        self.replay_export_button = QPushButton("↓  Export Results")
        self.replay_export_button.setObjectName("SecondaryButton")
        buttons.addWidget(self.replay_start_button)
        buttons.addStretch(1)
        buttons.addWidget(self.replay_export_button)
        controls.layout_box.addLayout(buttons)

        self.replay_status = QLabel("READY — configure the experiment, then start.")
        self.replay_status.setWordWrap(True)
        controls.add_widget(self.replay_status)
        root.addWidget(controls)

        self.split_card = Card("EXPERIMENT DESIGN")
        self.split_text = QLabel()
        self.split_text.setWordWrap(True)
        self.split_card.add_widget(self.split_text)
        root.addWidget(self.split_card)

        self.historical_progress = QProgressBar()
        self.historical_progress.setRange(0, 90)
        self.historical_progress.setValue(0)
        self.historical_progress.setFormat("%v / %m trading sessions")
        root.addWidget(self.historical_progress)

        self.setup_total_metric = MetricCard("TOTAL SESSIONS")
        self.setup_dev_metric = MetricCard("DEVELOPMENT")
        self.setup_blind_metric = MetricCard("BLIND")
        self.setup_money_metric = MetricCard("FAKE MONEY / TRADER")
        root.addWidget(
            ResponsiveMetricGrid(
                [
                    self.setup_total_metric,
                    self.setup_dev_metric,
                    self.setup_blind_metric,
                    self.setup_money_metric,
                ],
                compact_height=78,
            )
        )

        integrity = Card("INTEGRITY RULES")
        label = QLabel(
            "No look-ahead. Blind rules are frozen. Four timeframe traders are independent. "
            "Each gets the same fake starting capital. Holding horizon is timeframe-specific "
            "(1M=10m, 5M=30m, 10M=45m, 15M=60m). Overlapping signals are recorded as rejected. Historical "
            "option premiums are never invented."
        )
        label.setWordWrap(True)
        integrity.add_widget(label)
        root.addWidget(integrity)
        root.addStretch(1)

        for widget in (
            self.development_days,
            self.blind_days,
            self.replay_mode,
            self.starting_capital,
            self.allocation_pct,
            self.friction_bps,
            self.validation_mode,
            self.execution_mode,
            self.walk_train_days,
            self.walk_test_days,
            self.walk_step_days,
            self.walk_windows,
        ):
            if hasattr(widget, "valueChanged"):
                widget.valueChanged.connect(self._sync_replay_controls)
            elif hasattr(widget, "currentIndexChanged"):
                widget.currentIndexChanged.connect(self._sync_replay_controls)
        self.replay_mode.currentIndexChanged.connect(self._sync_replay_controls)
        for check in self.trader_checks.values():
            check.toggled.connect(self._sync_replay_controls)
        self.replay_start_button.clicked.connect(self._request_replay)
        self.replay_export_button.clicked.connect(self._request_export)
        self._sync_replay_controls()
        return page

    def _build_live_replay(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(4, 8, 4, 4)
        root.setSpacing(8)

        controls = Card("SHADOW ARENA — SIMULATED LIVE REPLAY")
        row = QHBoxLayout()
        self.live_status = QLabel(
            "Waiting for a replay. Shadow Arena is display-only and never sends broker orders."
        )
        self.live_status.setWordWrap(True)
        row.addWidget(self.live_status, 1)

        row.addWidget(QLabel("Day pace"))
        self.live_speed = QComboBox()
        for label, seconds_per_day in (
            ("5 sec / day", 5),
            ("10 sec / day", 10),
            ("20 sec / day", 20),
            ("MAX", 0),
        ):
            self.live_speed.addItem(label, seconds_per_day)
        self.live_speed.setCurrentIndex(self.live_speed.findData(10))
        self.live_speed.setToolTip(
            "Visual pacing only. Every historical candle and event is still processed in timestamp order."
        )
        row.addWidget(self.live_speed)

        self.live_pause_button = QPushButton("Ⅱ  Pause")
        self.live_pause_button.setEnabled(False)
        self.live_pause_button.clicked.connect(self._toggle_playback_pause)
        row.addWidget(self.live_pause_button)

        self.live_chart_button = QPushButton("Open Chart")
        self.live_chart_button.setEnabled(False)
        self.live_chart_button.clicked.connect(self._toggle_live_chart)
        row.addWidget(self.live_chart_button)

        self.live_skip_button = QPushButton("Skip to Results")
        self.live_skip_button.setEnabled(False)
        self.live_skip_button.clicked.connect(self._finish_playback)
        row.addWidget(self.live_skip_button)
        controls.layout_box.addLayout(row)
        root.addWidget(controls)

        self.live_clock_metric = MetricCard("SIMULATED CLOCK")
        self.live_phase_metric = MetricCard("PHASE")
        self.live_price_metric = MetricCard("NIFTY")
        self.live_session_metric = MetricCard("SESSION")
        root.addWidget(
            ResponsiveMetricGrid(
                [
                    self.live_clock_metric,
                    self.live_phase_metric,
                    self.live_price_metric,
                    self.live_session_metric,
                ],
                compact_height=78,
            )
        )
        for metric in (
            self.live_clock_metric,
            self.live_phase_metric,
            self.live_price_metric,
            self.live_session_metric,
        ):
            metric.set_value("—")

        arena = Card("FOUR-TRADER PAPER TOURNAMENT")
        trader_grid = QGridLayout()
        self.trader_cards: dict[int, dict[str, object]] = {}
        for index, timeframe in enumerate(DEFAULT_TRADER_TIMEFRAMES):
            card = Card(TRADER_TITLES[timeframe])
            state = QLabel("WAITING")
            state.setObjectName("HeroValue")
            balance = QLabel("Balance —")
            pnl = QLabel("P&L —")
            wl = QLabel("W 0 / L 0")
            dd = QLabel("Drawdown —")
            for label in (balance, pnl, wl, dd):
                label.setObjectName("Muted")
            card.add_widget(state)
            card.add_widget(balance)
            card.add_widget(pnl)
            card.add_widget(wl)
            card.add_widget(dd)
            trader_grid.addWidget(card, index // 2, index % 2)
            self.trader_cards[timeframe] = {
                "card": card,
                "state": state,
                "balance": balance,
                "pnl": pnl,
                "wl": wl,
                "dd": dd,
            }
        arena.layout_box.addLayout(trader_grid)
        root.addWidget(arena)

        tape = Card("EVENT STREAM")
        self.live_tape = DataTable(
            ["Time", "Phase", "Trader", "Event", "Direction", "Entry", "Current / Exit", "P&L", "Status"]
        )
        tape.add_widget(self.live_tape)
        root.addWidget(tape, 1)

        self.live_chart = MarketChart("ON-DEMAND NIFTY INSPECTION")
        self.live_chart.set_timeframe("1m")
        self.live_chart.setMaximumHeight(300)
        self.live_chart.setVisible(False)
        root.addWidget(self.live_chart)

        note = QLabel(
            "Development is research visualization. Blind is the authentic frozen test. "
            "Outcome and paper P&L are revealed only when each frozen engine reaches its own causal exit timestamp."
        )
        note.setWordWrap(True)
        note.setObjectName("Muted")
        root.addWidget(note)
        return page

    def _build_results(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(4, 8, 4, 4)
        root.setSpacing(8)

        summary = Card("LATEST SHADOW ARENA RESULTS")
        row = QHBoxLayout()
        self.results_summary = QLabel("No Shadow Arena replay has completed in this app session yet.")
        self.results_summary.setWordWrap(True)
        row.addWidget(self.results_summary, 1)
        self.results_export_button = QPushButton("↓  Export Full Review")
        self.results_export_button.setObjectName("SecondaryButton")
        self.results_export_button.setEnabled(False)
        self.results_export_button.clicked.connect(self._request_export)
        row.addWidget(self.results_export_button)
        summary.layout_box.addLayout(row)
        root.addWidget(summary)

        self.results_total_metric = MetricCard("TOTAL")
        self.results_dev_metric = MetricCard("DEVELOPMENT")
        self.results_blind_metric = MetricCard("BLIND")
        self.results_capital_metric = MetricCard("STARTING CAPITAL / TRADER")
        self.results_blind_status_metric = MetricCard("BLIND STATUS")
        self.results_touchpoints_metric = MetricCard("TOUCHPOINTS USED")
        self.results_available_metric = MetricCard("TOUCHPOINTS AVAILABLE")
        self.results_engines_metric = MetricCard("FROZEN ENGINES")
        root.addWidget(
            ResponsiveMetricGrid(
                [
                    self.results_total_metric,
                    self.results_dev_metric,
                    self.results_blind_metric,
                    self.results_capital_metric,
                    self.results_blind_status_metric,
                    self.results_touchpoints_metric,
                    self.results_available_metric,
                    self.results_engines_metric,
                ],
                compact_height=78,
            )
        )

        coverage = Card("FEATURE COVERAGE AUDIT")
        self.results_coverage = DataTable(
            ["Family", "Requested", "Historically Available", "Used by Frozen Engine"]
        )
        coverage.add_widget(self.results_coverage)
        root.addWidget(coverage)

        ablation = Card("ABLATION — SAME BLIND DATES")
        self.results_ablation = DataTable(
            ["Trader", "Variant", "Families", "Trades", "Net P&L", "Return", "PF", "Max DD"]
        )
        ablation.add_widget(self.results_ablation)
        root.addWidget(ablation)

        walk = Card("WALK-FORWARD WINDOWS")
        self.results_walk_forward = DataTable(
            ["Trader", "Window", "Train", "Test", "Engine", "Trades", "Net P&L", "Return", "PF", "Max DD"]
        )
        walk.add_widget(self.results_walk_forward)
        root.addWidget(walk)

        slices = Card("REGIME + TIME-OF-DAY")
        self.results_slices = DataTable(
            ["Trader", "Slice Type", "Slice", "Trades", "Wins", "Losses", "Avg Return", "Net P&L", "PF"]
        )
        slices.add_widget(self.results_slices)
        root.addWidget(slices)

        tournament = Card("TIMEFRAME TOURNAMENT — BLIND PHASE")
        self.results_tournament = DataTable(
            [
                "Trader", "Engine ID", "Frozen Strategy", "Hold", "Trades", "Wins", "Losses", "Win Rate",
                "Avg Net Return", "Profit Factor", "Start", "End", "Net P&L", "Return", "Max DD",
            ]
        )
        tournament.add_widget(self.results_tournament)
        root.addWidget(tournament)

        trades = Card("TRADE-BY-TRADE PAPER REPLAY")
        self.results_trades = DataTable(
            [
                "Trader", "Opened", "Closed", "Hold", "Direction", "Entry", "Exit",
                "Gross", "Net", "Paper P&L", "Balance", "Regime", "Time Bucket", "Exit", "Result",
            ]
        )
        trades.add_widget(self.results_trades)
        root.addWidget(trades)

        rejected = Card("REJECTED SIGNALS")
        self.results_rejected = DataTable(
            ["Trader", "Time", "Direction", "Reason", "Hypothetical Return", "Hypothetical P&L", "Classification"]
        )
        rejected.add_widget(self.results_rejected)
        root.addWidget(rejected)

        limitation = Card("MONEY RESULT STATUS")
        note = QLabel(
            "PROXY uses directional NIFTY returns. OPTION_PREMIUM uses cached Upstox expired-option "
            "1-minute premiums, causal next-bar entry and discrete lot sizing; missing session files fail closed."
        )
        note.setWordWrap(True)
        limitation.add_widget(note)
        root.addWidget(limitation)
        return page

    def _build_forward(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(4, 8, 4, 4)
        card = Card("60 FUTURE TRADING SESSIONS")
        text = QLabel(
            "After historical development and blind testing, the same frozen logic can be observed "
            "against future live candles using simulated execution only. No real broker order is permitted."
        )
        text.setWordWrap(True)
        card.add_widget(text)
        root.addWidget(card)
        self.forward_progress = QProgressBar()
        self.forward_progress.setRange(0, self.plan.forward_sessions)
        self.forward_progress.setValue(0)
        self.forward_progress.setFormat("Forward validation — %v / %m sessions")
        root.addWidget(self.forward_progress)
        root.addStretch(1)
        return page

    def _build_features(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        intro = QLabel(
            "High mode requests all 50 versioned feature touchpoints. Medium and Low deliberately "
            "request smaller families so additional data can be tested rather than assumed useful."
        )
        intro.setWordWrap(True)
        root.addWidget(intro)
        table = DataTable(["Family", "Feature", "Role"])
        rows = []
        for family, features in FEATURE_FAMILIES:
            for feature in features:
                rows.append(
                    [
                        family,
                        feature,
                        "Measured cross-index evidence"
                        if family == "SENSEX confirmation"
                        else "Candidate model input",
                    ]
                )
        table.set_rows(rows)
        root.addWidget(table, 1)
        return page

    def _build_data(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        table = DataTable(["Dataset", "Source", "Status", "Rule"])
        table.set_rows([list(row) for row in DATA_COVERAGE])
        root.addWidget(table, 1)
        note = QLabel(
            "Requested replay length is limited by what the connected historical sources actually provide. "
            "Unavailable historical option families stay missing rather than being synthesized."
        )
        note.setWordWrap(True)
        root.addWidget(note)
        return page

    def _build_news(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        note = QLabel(
            "During historical replay, only timestamped information published at or before the simulated clock may be used."
        )
        note.setWordWrap(True)
        root.addWidget(note)
        table = DataTable(["Resource", "URL", "Use"])
        table.set_rows(
            [[name, url, "Timestamped research / market context"] for name, url in NEWS_RESOURCES]
        )
        root.addWidget(table, 1)
        return page

    def selected_config(self) -> ShadowReplayConfig:
        frames = tuple(
            timeframe
            for timeframe, check in self.trader_checks.items()
            if check.isChecked()
        )
        return validate_replay_config(
            ShadowReplayConfig(
                development_sessions=self.development_days.value(),
                blind_sessions=self.blind_days.value(),
                mode_key=str(self.replay_mode.currentData()),
                validation_mode=str(self.validation_mode.currentData()),
                walk_train_sessions=self.walk_train_days.value(),
                walk_test_sessions=self.walk_test_days.value(),
                walk_step_sessions=self.walk_step_days.value(),
                walk_windows=self.walk_windows.value(),
                execution_mode=str(self.execution_mode.currentData()),
                starting_capital=Decimal(str(self.starting_capital.value())),
                allocation_pct=Decimal(str(self.allocation_pct.value())),
                friction_bps=Decimal(str(self.friction_bps.value())),
                trader_timeframes=frames,
            )
        )

    def selected_replay_sessions(self) -> int:
        return self.development_days.value() + self.blind_days.value()

    def selected_replay_mode(self) -> str:
        return str(self.replay_mode.currentData())

    def _sync_replay_controls(self, *_args) -> None:
        try:
            config = self.selected_config()
            valid = True
        except ValueError as exc:
            valid = False
            config = None
            self.split_text.setText(str(exc))
        self.replay_start_button.setEnabled(valid and not self._replay_running)
        if config is None:
            return
        mode = replay_mode(config.mode_key)
        self._latest_config = config
        self.historical_progress.setRange(0, config.total_sessions)
        if not self._replay_running:
            self.historical_progress.setValue(0)
        self.mode_description.setText(
            f"{mode.label.upper()} MODE — {mode.feature_count} requested touchpoints. {mode.description}"
        )
        self.split_text.setText(
            f"{config.development_sessions} development + {config.blind_sessions} blind = "
            f"{config.total_sessions} standard sessions. Validation={config.validation_mode}. "
            f"Required history={config.required_sessions} sessions. Blind starts only after all "
            "timeframe strategies are frozen. Source availability is the final historical limit."
        )
        self.setup_total_metric.set_value(
            f"{config.total_sessions} / req {config.required_sessions}"
        )
        self.setup_dev_metric.set_value(str(config.development_sessions))
        self.setup_blind_metric.set_value(str(config.blind_sessions))
        self.setup_money_metric.set_value(f"₹{config.starting_capital:,.0f}")

    def _request_replay(self) -> None:
        if self._replay_running:
            return
        try:
            config = self.selected_config()
        except ValueError as exc:
            self.replay_status.setText(f"CONFIGURATION ERROR — {exc}")
            return
        self._latest_config = config
        self._replay_running = True
        self.replay_start_button.setEnabled(False)
        self.replay_export_button.setEnabled(False)
        self.replay_status.setText("STARTING — preparing causal history and the four-trader tournament…")
        self.replay_requested.emit(config)

    def _request_export(self) -> None:
        self.replay_export_requested.emit(self._latest_config)

    def set_replay_progress(self, completed: int, total: int, status: str) -> None:
        total = max(1, int(total))
        self.historical_progress.setRange(0, total)
        self.historical_progress.setValue(max(0, min(int(completed), total)))
        self.historical_progress.setFormat("%v / %m trading sessions")
        self.replay_status.setText(status)

    @staticmethod
    def _fmt_pct(value, digits: int = 2) -> str:
        return "N/A" if value is None else f"{value:.{digits}f}%"

    @staticmethod
    def _fmt_money(value) -> str:
        return "N/A" if value is None else f"₹{value:,.2f}"

    @staticmethod
    def _fmt_number(value, digits: int = 2) -> str:
        return "N/A" if value is None else f"{value:.{digits}f}"

    def set_replay_report(self, report, *, open_results: bool = True) -> None:
        config = report.config
        self._latest_config = config
        blind_label = (
            "REUSED BLIND WINDOW — diagnostic only"
            if report.blind_previously_reviewed
            else "FRESH BLIND WINDOW"
        )
        self.results_summary.setText(
            f"{report.actual_sessions} sessions completed: {config.development_sessions} development + "
            f"{config.blind_sessions} blind. {len(report.trader_reports)} independently frozen timeframe engines. "
            f"{blind_label}: {report.blind_start} → {report.blind_end}."
        )
        self.results_total_metric.set_value(str(report.actual_sessions))
        self.results_dev_metric.set_value(str(config.development_sessions))
        self.results_blind_metric.set_value(str(config.blind_sessions))
        self.results_capital_metric.set_value(self._fmt_money(config.starting_capital))
        self.results_blind_status_metric.set_value(
            "REUSED / NOT FRESH"
            if report.blind_previously_reviewed
            else "FRESH"
        )
        coverage = report.feature_coverage
        self.results_touchpoints_metric.set_value(
            f"{coverage.decision_used_touchpoints} / {coverage.requested_touchpoints}"
        )
        self.results_available_metric.set_value(
            f"{coverage.available_touchpoints} / {coverage.requested_touchpoints}"
        )
        self.results_engines_metric.set_value(str(len(report.trader_reports)))
        self.results_coverage.set_rows(
            [
                [
                    family,
                    "YES",
                    "YES" if family in coverage.available_families else "NO",
                    "YES" if family in coverage.decision_used_families else "NO",
                ]
                for family in coverage.requested_families
            ]
        )

        tournament_rows = []
        trade_rows = []
        rejected_rows = []
        for trader in report.trader_reports:
            metrics = trader.blind_metrics
            paper = trader.blind_paper
            tournament_rows.append(
                [
                    trader.trader_label,
                    trader.engine_id,
                    trader.selected_strategy_name or "None",
                    f"{trader.hold_minutes}m",
                    metrics.trades,
                    metrics.wins,
                    metrics.losses,
                    self._fmt_pct(metrics.win_rate_pct, 2),
                    self._fmt_pct(metrics.average_return_pct, 4),
                    self._fmt_number(metrics.profit_factor, 3),
                    self._fmt_money(paper.starting_capital),
                    self._fmt_money(paper.ending_capital),
                    self._fmt_money(paper.net_pnl),
                    self._fmt_pct(paper.return_pct, 3),
                    self._fmt_pct(paper.max_drawdown_pct, 3),
                ]
            )
            for trade in trader.trades:
                trade_rows.append(
                    [
                        trader.trader_label,
                        trade.opened_at.replace("T", " ")[:16],
                        trade.closed_at.replace("T", " ")[:16],
                        f"{trade.hold_minutes}m",
                        trade.direction,
                        (
                            f"{getattr(trade, 'option_entry_price', None):.2f}"
                            if getattr(trade, "option_entry_price", None) is not None
                            else f"{trade.entry_underlying:.2f}"
                        ),
                        (
                            f"{getattr(trade, 'option_exit_price', None):.2f}"
                            if getattr(trade, "option_exit_price", None) is not None
                            else f"{trade.exit_underlying:.2f}"
                        ),
                        self._fmt_pct(trade.gross_return_pct, 4),
                        self._fmt_pct(trade.net_return_pct, 4),
                        self._fmt_money(trade.paper_pnl),
                        self._fmt_money(trade.paper_balance_after),
                        trade.regime,
                        trade.time_bucket,
                        trade.exit_reason,
                        trade.result,
                    ]
                )
            for rejected in trader.rejected_signals:
                rejected_rows.append(
                    [
                        rejected.trader_label,
                        rejected.at.replace("T", " ")[:16],
                        rejected.direction,
                        rejected.reason,
                        self._fmt_pct(rejected.hypothetical_return_pct, 4),
                        self._fmt_money(rejected.hypothetical_pnl),
                        rejected.classification,
                    ]
                )

        ablation_rows = [
            [
                item.trader_label,
                item.label,
                ", ".join(item.families) or "Strategy only",
                item.trades,
                self._fmt_money(item.net_pnl),
                self._fmt_pct(item.return_pct, 3),
                self._fmt_number(item.profit_factor, 3),
                self._fmt_pct(item.max_drawdown_pct, 3),
            ]
            for item in report.ablation_results
        ]
        walk_rows = [
            [
                item.trader_label,
                item.window_index,
                f"{item.training_start} → {item.training_end}",
                f"{item.test_start} → {item.test_end}",
                item.engine_id,
                item.trades,
                self._fmt_money(item.net_pnl),
                self._fmt_pct(item.return_pct, 3),
                self._fmt_number(item.profit_factor, 3),
                self._fmt_pct(item.max_drawdown_pct, 3),
            ]
            for item in report.walk_forward_results
        ]
        slice_rows = []
        for trader in report.trader_reports:
            for item in trader.regime_stats:
                slice_rows.append(
                    [
                        trader.trader_label, "REGIME", item.key, item.trades,
                        item.wins, item.losses,
                        self._fmt_pct(item.average_return_pct, 4),
                        self._fmt_money(item.net_pnl),
                        self._fmt_number(item.profit_factor, 3),
                    ]
                )
            for item in trader.time_stats:
                slice_rows.append(
                    [
                        trader.trader_label, "TIME", item.key, item.trades,
                        item.wins, item.losses,
                        self._fmt_pct(item.average_return_pct, 4),
                        self._fmt_money(item.net_pnl),
                        self._fmt_number(item.profit_factor, 3),
                    ]
                )

        self.results_ablation.set_rows(ablation_rows)
        self.results_walk_forward.set_rows(walk_rows)
        self.results_slices.set_rows(slice_rows)
        self.results_tournament.set_rows(tournament_rows)
        self.results_trades.set_rows(sorted(trade_rows, key=lambda row: row[1]))
        self.results_rejected.set_rows(sorted(rejected_rows, key=lambda row: row[1]))
        self.results_export_button.setEnabled(True)
        if open_results:
            self.tabs.setCurrentIndex(self.results_tab_index)

    def begin_visual_playback(self, candles, report) -> None:
        self._playback_timer.stop()
        self._playback_candles = tuple(sorted(candles, key=lambda item: item.at))
        self._playback_report = report
        self._playback_index = 0
        events = []
        for trader in report.trader_reports:
            for trade in trader.trades:
                events.append((datetime.fromisoformat(trade.opened_at), "OPEN", trade))
                events.append((datetime.fromisoformat(trade.closed_at), "CLOSE", trade))
            for rejected in trader.rejected_signals:
                events.append((datetime.fromisoformat(rejected.at), "REJECT", rejected))
        self._playback_events = tuple(sorted(events, key=lambda item: (item[0], item[1])))
        self._playback_event_index = 0
        self._playback_open = {timeframe: [] for timeframe in DEFAULT_TRADER_TIMEFRAMES}
        self._playback_tape_rows = []
        self._playback_session_dates = tuple(sorted({candle.at.date() for candle in self._playback_candles}))
        self._playback_session_bounds = {}
        for session_day in self._playback_session_dates:
            indices = [
                index
                for index, candle in enumerate(self._playback_candles)
                if candle.at.date() == session_day
            ]
            if indices:
                self._playback_session_bounds[session_day] = (
                    indices[0],
                    indices[-1] + 1,
                )
        self._playback_phase = None
        self._arena_runtime = {}
        for timeframe in DEFAULT_TRADER_TIMEFRAMES:
            self._arena_runtime[timeframe] = {
                "balance": report.config.starting_capital,
                "peak": report.config.starting_capital,
                "wins": 0,
                "losses": 0,
            }
            self._refresh_trader_card(timeframe, "WAIT")
        self.live_tape.set_rows([])
        self.live_chart.setVisible(False)
        self.live_chart_button.setText("Open Chart")
        self.live_chart_button.setEnabled(bool(self._playback_candles))
        self.live_pause_button.setEnabled(bool(self._playback_candles))
        self.live_skip_button.setEnabled(bool(self._playback_candles))
        self.live_pause_button.setText("Ⅱ  Pause")
        self.tabs.setCurrentIndex(self.live_tab_index)

        if not self._playback_candles:
            self.live_status.setText("No candles are available for Shadow Arena playback.")
            self._finish_playback()
            return
        self.live_status.setText(
            "PLAYING — four independent paper traders are competing on the same causal historical stream."
        )
        self._playback_timer.start()

    def _playback_step_size(self) -> int:
        """Return candles per UI tick for the selected seconds-per-day pace."""

        try:
            seconds_per_day = int(self.live_speed.currentData())
        except (TypeError, ValueError):
            seconds_per_day = 10
        if seconds_per_day <= 0:
            return 100000

        if not self._playback_candles or self._playback_index >= len(self._playback_candles):
            return 1
        day = self._playback_candles[self._playback_index].at.date()
        bounds = self._playback_session_bounds.get(day)
        if bounds is None:
            session_count = 375
        else:
            session_count = max(1, bounds[1] - bounds[0])
        ticks_per_day = max(
            1,
            round(seconds_per_day * 1000 / self._playback_timer.interval()),
        )
        return max(1, (session_count + ticks_per_day - 1) // ticks_per_day)

    def _phase_for_session(self, session_number: int) -> str:
        if self._playback_report is None:
            return "UNKNOWN"
        if session_number <= self._playback_report.config.development_sessions:
            return "DEVELOPMENT"
        return "BLIND — FROZEN"

    def _reset_arena_phase(self, phase: str) -> None:
        if self._playback_phase == phase:
            return
        self._playback_phase = phase
        if phase.startswith("BLIND") and self._playback_report is not None:
            start = self._playback_report.config.starting_capital
            for timeframe in self._arena_runtime:
                self._arena_runtime[timeframe] = {
                    "balance": start,
                    "peak": start,
                    "wins": 0,
                    "losses": 0,
                }
                self._playback_open[timeframe] = []
                self._refresh_trader_card(timeframe, "WAIT")
            self._append_event_row(["—", "BLIND", "ALL", "RESET", "—", "—", "—", "—", "Accounts reset"])

    def _append_event_row(self, row: list[object]) -> None:
        self._playback_tape_rows.append(row)
        self._playback_tape_rows = self._playback_tape_rows[-80:]
        self.live_tape.set_rows(self._playback_tape_rows)

    def _refresh_trader_card(self, timeframe: int, state: str | None = None) -> None:
        controls = self.trader_cards[timeframe]
        runtime = self._arena_runtime.get(timeframe, {})
        balance = Decimal(runtime.get("balance", self._latest_config.starting_capital))
        peak = Decimal(runtime.get("peak", balance))
        wins = int(runtime.get("wins", 0))
        losses = int(runtime.get("losses", 0))
        if state is not None:
            controls["state"].setText(state)
        pnl = balance - self._latest_config.starting_capital
        drawdown = Decimal(0) if peak == 0 else (peak - balance) / peak * Decimal(100)
        controls["balance"].setText(f"Balance  ₹{balance:,.2f}")
        controls["pnl"].setText(f"P&L  {pnl:+,.2f}")
        controls["wl"].setText(f"W {wins} / L {losses}")
        controls["dd"].setText(f"Drawdown  {drawdown:.2f}%")

    def _process_playback_events(self, current_at: datetime) -> None:
        while self._playback_event_index < len(self._playback_events):
            at, event_type, payload = self._playback_events[self._playback_event_index]
            if at > current_at:
                break
            self._playback_event_index += 1
            timeframe = int(payload.timeframe_minutes)
            if event_type == "REJECT":
                self._append_event_row(
                    [
                        at.strftime("%d %b %H:%M"),
                        "BLIND",
                        payload.trader_label,
                        "REJECT",
                        payload.direction,
                        "—",
                        "—",
                        "—",
                        payload.reason,
                    ]
                )
                continue
            if event_type == "OPEN":
                self._playback_open[timeframe].append((payload, at))
                self._refresh_trader_card(timeframe, payload.direction)
                self._append_event_row(
                    [
                        at.strftime("%d %b %H:%M"),
                        "BLIND",
                        payload.trader_label,
                        "OPEN",
                        payload.direction,
                        f"{payload.entry_underlying:.2f}",
                        "—",
                        "hidden",
                        "ACTIVE",
                    ]
                )
                continue

            runtime = self._arena_runtime[timeframe]
            if payload.paper_balance_after is not None:
                runtime["balance"] = payload.paper_balance_after
                runtime["peak"] = max(Decimal(runtime["peak"]), payload.paper_balance_after)
            if payload.result == "WIN":
                runtime["wins"] = int(runtime["wins"]) + 1
            elif payload.result == "LOSS":
                runtime["losses"] = int(runtime["losses"]) + 1
            self._playback_open[timeframe] = [
                item for item in self._playback_open[timeframe] if item[0] is not payload
            ]
            state = "WAIT" if not self._playback_open[timeframe] else self._playback_open[timeframe][-1][0].direction
            self._refresh_trader_card(timeframe, state)
            self._append_event_row(
                [
                    at.strftime("%d %b %H:%M"),
                    "BLIND",
                    payload.trader_label,
                    f"CLOSE {payload.hold_minutes}m",
                    payload.direction,
                    f"{payload.entry_underlying:.2f}",
                    f"{payload.exit_underlying:.2f}",
                    self._fmt_money(payload.paper_pnl),
                    payload.result,
                ]
            )

    def _playback_tick(self) -> None:
        if not self._playback_candles or self._playback_index >= len(self._playback_candles):
            self._finish_playback()
            return

        candles_per_tick = self._playback_step_size()
        next_index = min(len(self._playback_candles), self._playback_index + candles_per_tick)
        if self._playback_index < len(self._playback_candles):
            current_day = self._playback_candles[self._playback_index].at.date()
            bounds = self._playback_session_bounds.get(current_day)
            if bounds is not None:
                next_index = min(next_index, bounds[1])
        current = self._playback_candles[next_index - 1]
        self._playback_index = next_index

        try:
            session_number = self._playback_session_dates.index(current.at.date()) + 1
        except ValueError:
            session_number = 1
        phase = self._phase_for_session(session_number)
        self._reset_arena_phase(phase)
        self._process_playback_events(current.at)

        self.live_clock_metric.set_value(current.at.strftime("%d %b %Y • %H:%M"))
        self.live_phase_metric.set_value(phase)
        self.live_price_metric.set_value(f"{float(current.close):,.2f}")
        self.live_session_metric.set_value(f"{session_number} / {len(self._playback_session_dates)}")

        if self.live_chart.isVisible():
            visible = [
                candle
                for candle in self._playback_candles[:next_index]
                if candle.at.date() == current.at.date()
            ][-120:]
            if visible:
                self.live_chart.set_candle_objects(visible)

        self.set_replay_progress(
            session_number,
            len(self._playback_session_dates),
            f"SHADOW ARENA — {phase} • {current.at.strftime('%d %b %H:%M')}",
        )

        if self._playback_index >= len(self._playback_candles):
            self._finish_playback()

    def _toggle_playback_pause(self) -> None:
        if self._playback_timer.isActive():
            self._playback_timer.stop()
            self.live_pause_button.setText("▶  Resume")
            self.live_status.setText("PAUSED — simulated market clock is frozen.")
        elif self._playback_candles and self._playback_index < len(self._playback_candles):
            self._playback_timer.start()
            self.live_pause_button.setText("Ⅱ  Pause")
            self.live_status.setText("PLAYING — Shadow Arena resumed.")

    def _toggle_live_chart(self) -> None:
        visible = not self.live_chart.isVisible()
        self.live_chart.setVisible(visible)
        self.live_chart_button.setText("Hide Chart" if visible else "Open Chart")

    def _finish_playback(self) -> None:
        active = self._playback_timer.isActive() or (
            self._playback_candles and self._playback_index < len(self._playback_candles)
        )
        self._playback_timer.stop()
        self.live_pause_button.setEnabled(False)
        self.live_skip_button.setEnabled(False)
        self.live_chart_button.setEnabled(False)
        if self._playback_report is not None:
            self.live_status.setText("PLAYBACK COMPLETE — opening tournament results.")
        if active or self._playback_report is not None:
            self.playback_finished.emit()

    def show_replay_results(self) -> None:
        self.tabs.setCurrentIndex(self.results_tab_index)

    def set_replay_finished(self, status: str) -> None:
        self._replay_running = False
        self.replay_start_button.setEnabled(True)
        self.replay_export_button.setEnabled(True)
        self.replay_status.setText(status)
        self._sync_replay_controls()

    def set_replay_failed(self, status: str) -> None:
        self.set_replay_finished(f"FAILED — {status}")

    def refresh(self, desktop) -> None:
        trade = desktop.active_shadow_trade
        if trade is None:
            self.active_text.setText("No active forward shadow trade.")
        else:
            self.active_text.setText(
                f"{trade.action}\n{trade.strike} {trade.option_type}\n"
                f"Entry {trade.entry_price} • Stop {trade.stop_price} • Target {trade.target_price}\n"
                f"Quantity {trade.quantity} • {trade.shadow_version}"
            )
        rows = []
        for _decision, completed_trade, outcome in reversed(desktop.completed_bundles[-50:]):
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
