"""Dedicated Shadow Trader research workspace for Intrader.

This page is additive: it reuses the existing immutable shadow-trade records and
does not alter broker connectivity, order handling, Time Travel, Strategy Lab,
or the existing Market Brain.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from PySide6.QtCore import QPointF, QTimer, Signal
from PySide6.QtGui import QPainter, QPainterPath, QPen
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
from intrader.ui.components import (
    Card,
    DataTable,
    MarketChart,
    MetricCard,
    ResponsiveMetricGrid,
)


class ReplayEquityCurve(QWidget):
    """Small dependency-free cumulative-return chart for replay results."""

    def __init__(self) -> None:
        super().__init__()
        self._values: list[float] = [0.0]
        self.setMinimumHeight(180)

    def set_returns(self, returns) -> None:
        cumulative = 0.0
        values = [0.0]
        for value in returns:
            if value is None:
                continue
            cumulative += float(value)
            values.append(cumulative)
        self._values = values
        self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(12, 12, -12, -18)
        if rect.width() <= 2 or rect.height() <= 2:
            return

        values = self._values or [0.0]
        low = min(values)
        high = max(values)
        if high == low:
            high += 1.0
            low -= 1.0

        def point(index: int, value: float) -> QPointF:
            x = rect.left() if len(values) == 1 else (
                rect.left() + rect.width() * index / (len(values) - 1)
            )
            y = rect.bottom() - rect.height() * ((value - low) / (high - low))
            return QPointF(float(x), float(y))

        axis_pen = QPen(self.palette().mid().color())
        axis_pen.setWidth(1)
        painter.setPen(axis_pen)
        zero_y = point(0, 0.0).y()
        painter.drawLine(
            QPointF(float(rect.left()), zero_y),
            QPointF(float(rect.right()), zero_y),
        )

        path = QPainterPath()
        first = point(0, values[0])
        path.moveTo(first)
        for index, value in enumerate(values[1:], start=1):
            path.lineTo(point(index, value))

        curve_pen = QPen(self.palette().highlight().color())
        curve_pen.setWidth(2)
        painter.setPen(curve_pen)
        painter.drawPath(path)


class ShadowTraderPage(QWidget):
    """Research, historical replay, and forward-validation workspace."""

    replay_requested = Signal(int, str)
    replay_export_requested = Signal(int, str)
    playback_finished = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.plan = DEFAULT_SHADOW_LAB_PLAN
        self._replay_running = False
        self._playback_timer = QTimer(self)
        self._playback_timer.setInterval(50)
        self._playback_timer.timeout.connect(self._playback_tick)
        self._playback_candles = ()
        self._playback_report = None
        self._playback_index = 0
        self._playback_trade_index = 0
        self._playback_trades = ()
        self._playback_open: list[tuple[object, datetime]] = []
        self._playback_tape_rows: list[list[object]] = []
        self._playback_realized = 0.0
        self._playback_session_dates = ()
        self._playback_last_chart_at = None

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
        self.live_page = self._build_live_replay()
        self.live_tab_index = self.tabs.addTab(self.live_page, "Live Replay")
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

    def _build_live_replay(self) -> QWidget:
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(4, 8, 4, 4)
        root.setSpacing(8)

        controls = Card("SIMULATED LIVE REPLAY")
        row = QHBoxLayout()
        self.live_status = QLabel(
            "Waiting for a historical replay. This view is display-only and never sends broker orders."
        )
        self.live_status.setWordWrap(True)
        row.addWidget(self.live_status, 1)

        row.addWidget(QLabel("Speed"))
        self.live_speed = QComboBox()
        for label, speed in (
            ("100x", 100),
            ("500x", 500),
            ("1000x", 1000),
            ("MAX", 5000),
        ):
            self.live_speed.addItem(label, speed)
        self.live_speed.setCurrentIndex(self.live_speed.findData(500))
        row.addWidget(self.live_speed)

        self.live_pause_button = QPushButton("Ⅱ  Pause")
        self.live_pause_button.setEnabled(False)
        self.live_pause_button.clicked.connect(self._toggle_playback_pause)
        row.addWidget(self.live_pause_button)

        self.live_skip_button = QPushButton("Skip to Results")
        self.live_skip_button.setEnabled(False)
        self.live_skip_button.clicked.connect(self._finish_playback)
        row.addWidget(self.live_skip_button)
        controls.layout_box.addLayout(row)
        root.addWidget(controls)

        self.live_clock_metric = MetricCard("SIMULATED CLOCK")
        self.live_phase_metric = MetricCard("PHASE")
        self.live_price_metric = MetricCard("NIFTY")
        self.live_action_metric = MetricCard("SHADOW STATE")
        self.live_proxy_metric = MetricCard("REALIZED PROXY RETURN")
        self.live_session_metric = MetricCard("SESSION")
        for metric in (
            self.live_clock_metric,
            self.live_phase_metric,
            self.live_price_metric,
            self.live_action_metric,
            self.live_proxy_metric,
            self.live_session_metric,
        ):
            metric.set_value("—")
        root.addWidget(
            ResponsiveMetricGrid(
                [
                    self.live_clock_metric,
                    self.live_phase_metric,
                    self.live_price_metric,
                    self.live_action_metric,
                    self.live_proxy_metric,
                    self.live_session_metric,
                ],
                compact_height=78,
            )
        )

        self.live_chart = MarketChart("SIMULATED NIFTY — HISTORICAL PLAYBACK")
        self.live_chart.set_timeframe("1m")
        root.addWidget(self.live_chart, 1)

        tape = Card("SHADOW TRADE TAPE")
        self.live_tape = DataTable(
            [
                "Time", "Phase", "Event", "Direction", "Entry NIFTY",
                "Current / Exit", "30m Return", "Status",
            ]
        )
        tape.add_widget(self.live_tape)
        root.addWidget(tape, 1)

        note = QLabel(
            "Development playback is research visualization because the frozen strategy is selected "
            "from the full development block. The blind segment is the authentic live-like test. "
            "Trade outcomes are revealed only after simulated time reaches +30 minutes."
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

        summary = Card("LATEST REPLAY RESULTS")
        top = QHBoxLayout()
        self.results_summary = QLabel(
            "No historical replay has completed in this app session yet."
        )
        self.results_summary.setWordWrap(True)
        top.addWidget(self.results_summary, 1)
        self.results_export_button = QPushButton("↓  Export Full Review")
        self.results_export_button.setObjectName("SecondaryButton")
        self.results_export_button.setEnabled(False)
        self.results_export_button.clicked.connect(self._request_export)
        top.addWidget(self.results_export_button)
        summary.layout_box.addLayout(top)
        root.addWidget(summary)

        self.results_strategy_metric = MetricCard("FROZEN STRATEGY")
        self.results_range_metric = MetricCard("RANGE")
        self.results_mode_metric = MetricCard("MODE")
        self.results_period_metric = MetricCard("TEST PERIOD")
        for metric in (
            self.results_strategy_metric,
            self.results_range_metric,
            self.results_mode_metric,
            self.results_period_metric,
        ):
            metric.set_value("—")
        root.addWidget(
            ResponsiveMetricGrid(
                [
                    self.results_strategy_metric,
                    self.results_range_metric,
                    self.results_mode_metric,
                    self.results_period_metric,
                ],
                compact_height=78,
            )
        )

        self.results_win_metric = MetricCard("BLIND WIN RATE")
        self.results_return_metric = MetricCard("BLIND AVG 30M RETURN")
        self.results_pf_metric = MetricCard("BLIND PROFIT FACTOR")
        self.results_dd_metric = MetricCard("BLIND MAX DRAWDOWN")
        self.results_winner_metric = MetricCard("AVG WINNER")
        self.results_loser_metric = MetricCard("AVG LOSER")
        self.results_streak_metric = MetricCard("MAX LOSING STREAK")
        self.results_signals_metric = MetricCard("BLIND SIGNALS")
        for metric in (
            self.results_win_metric,
            self.results_return_metric,
            self.results_pf_metric,
            self.results_dd_metric,
            self.results_winner_metric,
            self.results_loser_metric,
            self.results_streak_metric,
            self.results_signals_metric,
        ):
            metric.set_value("—")
        root.addWidget(
            ResponsiveMetricGrid(
                [
                    self.results_win_metric,
                    self.results_return_metric,
                    self.results_pf_metric,
                    self.results_dd_metric,
                    self.results_winner_metric,
                    self.results_loser_metric,
                    self.results_streak_metric,
                    self.results_signals_metric,
                ],
                compact_height=78,
            )
        )

        curve = Card("BLIND CUMULATIVE SIGNED RETURN — PROXY")
        self.results_curve = ReplayEquityCurve()
        self.results_curve.setToolTip(
            "Cumulative 30-minute signed NIFTY return for the frozen strategy in the blind period."
        )
        curve.add_widget(self.results_curve)
        root.addWidget(curve)

        comparison = Card("DEVELOPMENT VS BLIND")
        self.results_comparison = DataTable(
            [
                "Phase", "Sessions", "Signals", "Wins", "Losses", "Win Rate",
                "Avg 30m", "Profit Factor", "Max DD", "Max Loss Streak",
            ]
        )
        comparison.add_widget(self.results_comparison)
        root.addWidget(comparison)

        candidates = Card("DEVELOPMENT STRATEGY CANDIDATES")
        self.results_candidates = DataTable(
            ["Strategy", "Signals", "30m Hit Rate", "Avg 30m Return", "Sample"]
        )
        candidates.add_widget(self.results_candidates)
        root.addWidget(candidates)

        trades = Card("TRADE-BY-TRADE REPLAY")
        self.results_trades = DataTable(
            [
                "Phase", "Time", "Direction", "Entry NIFTY", "Approx Exit 30m",
                "+5m", "+15m", "+30m", "MFE", "MAE", "Result",
            ]
        )
        trades.add_widget(self.results_trades)
        root.addWidget(trades)

        rejected = Card("REJECTED SIGNALS")
        self.results_rejected = QLabel(
            "The current candle-proxy replay does not yet generate a separate rejected-signal "
            "stream. This section will populate when the full decision/filter engine is wired "
            "into historical replay."
        )
        self.results_rejected.setWordWrap(True)
        rejected.add_widget(self.results_rejected)
        root.addWidget(rejected)

        limitation = Card("MONEY RESULT STATUS")
        self.results_money_note = QLabel(
            "Current results measure signed NIFTY movement. Exact option premium P&L, charges, "
            "slippage and rupee drawdown stay unavailable until historical expired-option data "
            "is connected. Intrader will not invent those numbers."
        )
        self.results_money_note.setWordWrap(True)
        limitation.add_widget(self.results_money_note)
        root.addWidget(limitation)
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

    @staticmethod
    def _fmt_pct(value, digits: int = 2) -> str:
        return "N/A" if value is None else f"{value:.{digits}f}%"

    @staticmethod
    def _fmt_number(value, digits: int = 2) -> str:
        return "N/A" if value is None else f"{value:.{digits}f}"

    def set_replay_report(self, report, *, open_results: bool = True) -> None:
        strategy = report.selected_strategy_name or "None"
        self.replay_strategy_metric.set_value(strategy)
        self.replay_win_metric.set_value(
            self._fmt_pct(report.blind.win_rate_pct, 2)
        )
        self.replay_expectancy_metric.set_value(
            self._fmt_pct(report.blind.average_return_30m_pct, 4)
        )
        self.replay_signal_metric.set_value(str(report.blind.evaluable_signals))

        self.results_summary.setText(
            f"{report.actual_sessions} trading sessions completed in {report.mode} mode. "
            f"The strategy was selected only from the first {report.development_sessions} "
            f"development sessions and then frozen for {report.blind_sessions} blind sessions."
        )
        self.results_strategy_metric.set_value(strategy)
        self.results_range_metric.set_value(f"{report.actual_sessions} sessions")
        self.results_mode_metric.set_value(
            f"{report.mode} • {report.requested_touchpoints} touchpoints"
        )
        self.results_period_metric.set_value(
            f"{report.first_session or '—'} → {report.last_session or '—'}"
        )

        blind = report.blind
        self.results_win_metric.set_value(self._fmt_pct(blind.win_rate_pct, 2))
        self.results_return_metric.set_value(
            self._fmt_pct(blind.average_return_30m_pct, 4)
        )
        self.results_pf_metric.set_value(
            self._fmt_number(blind.profit_factor, 3)
        )
        self.results_dd_metric.set_value(
            f"{blind.max_drawdown_pct_points:.4f} pp"
        )
        self.results_winner_metric.set_value(
            self._fmt_pct(blind.average_winner_pct, 4)
        )
        self.results_loser_metric.set_value(
            self._fmt_pct(blind.average_loser_pct, 4)
        )
        self.results_streak_metric.set_value(str(blind.max_losing_streak))
        self.results_signals_metric.set_value(str(blind.evaluable_signals))

        def metrics_row(label, metrics):
            return [
                label,
                metrics.sessions,
                metrics.evaluable_signals,
                metrics.wins,
                metrics.losses,
                self._fmt_pct(metrics.win_rate_pct, 2),
                self._fmt_pct(metrics.average_return_30m_pct, 4),
                self._fmt_number(metrics.profit_factor, 3),
                f"{metrics.max_drawdown_pct_points:.4f} pp",
                metrics.max_losing_streak,
            ]

        self.results_comparison.set_rows(
            [
                metrics_row("DEVELOPMENT", report.development),
                metrics_row("BLIND", report.blind),
            ]
        )

        self.results_candidates.set_rows(
            [
                [
                    candidate.strategy_name,
                    candidate.signals,
                    self._fmt_pct(candidate.hit_rate_30m_pct, 2),
                    self._fmt_pct(candidate.average_return_30m_pct, 4),
                    candidate.sample_label,
                ]
                for candidate in report.candidates
            ]
        )

        self.results_trades.set_rows(
            [
                [
                    trade.phase,
                    trade.at.replace("T", " ")[:16],
                    trade.direction,
                    f"{trade.entry_underlying:.2f}",
                    (
                        "N/A"
                        if trade.approx_exit_underlying_30m is None
                        else f"{trade.approx_exit_underlying_30m:.2f}"
                    ),
                    self._fmt_pct(trade.return_5m_pct, 4),
                    self._fmt_pct(trade.return_15m_pct, 4),
                    self._fmt_pct(trade.return_30m_pct, 4),
                    self._fmt_pct(trade.mfe_30m_pct, 4),
                    self._fmt_pct(trade.mae_30m_pct, 4),
                    trade.result,
                ]
                for trade in report.trades
            ]
        )

        self.results_curve.set_returns(
            [
                trade.return_30m_pct
                for trade in report.trades
                if trade.phase == "BLIND"
            ]
        )
        self.results_export_button.setEnabled(True)
        if open_results:
            self.tabs.setCurrentIndex(self.results_tab_index)

    def begin_visual_playback(self, candles, report) -> None:
        """Animate a display-only historical playback without changing replay results."""

        self._playback_timer.stop()
        self._playback_candles = tuple(sorted(candles, key=lambda item: item.at))
        self._playback_report = report
        self._playback_index = 0
        self._playback_trade_index = 0
        self._playback_trades = tuple(
            sorted(
                report.trades,
                key=lambda trade: datetime.fromisoformat(trade.at),
            )
        )
        self._playback_open = []
        self._playback_tape_rows = []
        self._playback_realized = 0.0
        self._playback_session_dates = tuple(sorted({
            candle.at.date() for candle in self._playback_candles
        }))
        self._playback_last_chart_at = None
        self.live_tape.set_rows([])
        self.live_chart.set_empty_message("Preparing simulated historical playback…")
        self.live_pause_button.setEnabled(bool(self._playback_candles))
        self.live_pause_button.setText("Ⅱ  Pause")
        self.live_skip_button.setEnabled(bool(self._playback_candles))
        self.tabs.setCurrentIndex(self.live_tab_index)

        if not self._playback_candles:
            self.live_status.setText("No candles are available for visual playback.")
            self._finish_playback()
            return

        self.live_status.setText(
            "PLAYING — historical candles are being revealed chronologically. "
            "No future trade outcome is shown before simulated +30 minutes."
        )
        self._playback_timer.start()

    def _playback_speed(self) -> int:
        value = self.live_speed.currentData()
        try:
            return max(1, int(value))
        except (TypeError, ValueError):
            return 500

    def _playback_phase(self, day) -> tuple[str, int]:
        try:
            session_index = self._playback_session_dates.index(day)
        except ValueError:
            return "UNKNOWN", 0
        report = self._playback_report
        if report is None:
            return "UNKNOWN", session_index + 1
        if session_index < report.development_sessions:
            return "DEVELOPMENT", session_index + 1
        return "BLIND — FROZEN", session_index + 1

    def _append_tape_row(self, row: list[object]) -> None:
        self._playback_tape_rows.append(row)
        self._playback_tape_rows = self._playback_tape_rows[-60:]
        self.live_tape.set_rows(self._playback_tape_rows)

    def _open_due_trades(self, current_at: datetime) -> None:
        while self._playback_trade_index < len(self._playback_trades):
            trade = self._playback_trades[self._playback_trade_index]
            opened_at = datetime.fromisoformat(trade.at)
            if opened_at > current_at:
                break
            self._playback_trade_index += 1
            self._playback_open.append((trade, opened_at))
            self._append_tape_row(
                [
                    opened_at.strftime("%d %b %H:%M"),
                    trade.phase,
                    "OPEN",
                    trade.direction,
                    f"{trade.entry_underlying:.2f}",
                    "—",
                    "hidden",
                    "ACTIVE",
                ]
            )

    def _close_due_trades(self, current_at: datetime) -> None:
        still_open: list[tuple[object, datetime]] = []
        for trade, opened_at in self._playback_open:
            if current_at < opened_at + timedelta(minutes=30):
                still_open.append((trade, opened_at))
                continue
            value = trade.return_30m_pct
            if value is not None:
                self._playback_realized += float(value)
            self._append_tape_row(
                [
                    current_at.strftime("%d %b %H:%M"),
                    trade.phase,
                    "CLOSE +30m",
                    trade.direction,
                    f"{trade.entry_underlying:.2f}",
                    (
                        "N/A"
                        if trade.approx_exit_underlying_30m is None
                        else f"{trade.approx_exit_underlying_30m:.2f}"
                    ),
                    self._fmt_pct(value, 4),
                    trade.result,
                ]
            )
        self._playback_open = still_open

    def _current_shadow_state(self, current_price) -> str:
        if not self._playback_open:
            return "WAIT / NO OPEN SIGNAL"
        trade, _opened_at = self._playback_open[-1]
        entry = float(trade.entry_underlying)
        price = float(current_price)
        signed = ((price - entry) / entry) * 100.0
        if "PUT" in trade.direction or "SHORT" in trade.direction:
            signed *= -1.0
        return f"{trade.direction} • {signed:+.3f}% proxy"

    def _playback_tick(self) -> None:
        if not self._playback_candles or self._playback_index >= len(self._playback_candles):
            self._finish_playback()
            return

        speed = self._playback_speed()
        candles_per_tick = max(1, int(speed * self._playback_timer.interval() / 1000))
        next_index = min(
            len(self._playback_candles),
            self._playback_index + candles_per_tick,
        )
        current = self._playback_candles[next_index - 1]
        self._playback_index = next_index

        current_at = current.at
        self._open_due_trades(current_at)
        self._close_due_trades(current_at)

        phase, session_number = self._playback_phase(current_at.date())
        self.live_clock_metric.set_value(current_at.strftime("%d %b %Y • %H:%M"))
        self.live_phase_metric.set_value(phase)
        self.live_price_metric.set_value(f"{float(current.close):,.2f}")
        self.live_action_metric.set_value(self._current_shadow_state(current.close))
        self.live_proxy_metric.set_value(f"{self._playback_realized:+.4f}%")
        self.live_session_metric.set_value(
            f"{session_number} / {len(self._playback_session_dates)}"
        )

        current_day = current_at.date()
        visible = [
            candle
            for candle in self._playback_candles[:next_index]
            if candle.at.date() == current_day
        ][-120:]
        if visible:
            self.live_chart.set_candle_objects(visible)

        report = self._playback_report
        if report is not None:
            self.set_replay_progress(
                min(session_number, report.requested_sessions),
                report.requested_sessions,
                (
                    f"VISUAL REPLAY — {phase} • {current_at.strftime('%d %b %H:%M')} • "
                    f"{len(self._playback_open)} active research signal(s)"
                ),
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
            self.live_status.setText(
                "PLAYING — historical candles are being revealed chronologically."
            )

    def _finish_playback(self) -> None:
        was_running = self._playback_timer.isActive() or (
            self._playback_candles and self._playback_index < len(self._playback_candles)
        )
        self._playback_timer.stop()
        self.live_pause_button.setEnabled(False)
        self.live_skip_button.setEnabled(False)
        if self._playback_report is not None:
            self.live_status.setText(
                "PLAYBACK COMPLETE — opening the locked replay results."
            )
        if was_running or self._playback_report is not None:
            self.playback_finished.emit()

    def show_replay_results(self) -> None:
        self.tabs.setCurrentIndex(self.results_tab_index)

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
