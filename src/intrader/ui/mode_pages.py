"""Primary Intrader, Time Travel, and Analysis mode pages."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from PySide6.QtCore import QDate, QTime, QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractSpinBox, QDateEdit, QGridLayout, QHBoxLayout, QLabel, QProgressBar,
    QPushButton, QSlider, QSplitter, QTabWidget, QTimeEdit, QVBoxLayout, QWidget,
)
import pyqtgraph as pg

from intrader.historical import INDIA_TIME
from intrader.ui.components import (
    BEARISH_COLOR, BULLISH_COLOR, BulletList, Card, DataTable, DecisionCard,
    DotMatrix, MarketChart, MetricCard, MetricRibbon, MixBars, ReasonList,
    ResponsiveMetricGrid, TextPanel,
)


def _tone(value: Decimal | None) -> str:
    if value is None or value == 0:
        return "neutral"
    return "positive" if value > 0 else "negative"


def _text(value) -> str:
    return "N/A" if value is None else str(value)


class OpeningScenarioPanel(QWidget):
    """Right-side Time Travel intelligence stack matching the approved mockup."""

    def __init__(self) -> None:
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        context = Card()
        context_head = QHBoxLayout()
        title = QLabel("Analysis Context")
        title.setObjectName("SectionTitle")
        context_head.addWidget(title)
        context_head.addStretch(1)
        context_head.addWidget(DotMatrix(columns=4, rows=3))
        context.layout_box.addLayout(context_head)
        self.context_text = QLabel(
            "Run Analyze Period to build evidence-based context for this range."
        )
        self.context_text.setWordWrap(True)
        self.context_text.setObjectName("Muted")
        context.layout_box.addWidget(self.context_text)
        root.addWidget(context)

        metric_row = QHBoxLayout()
        metric_row.setSpacing(8)
        self._metric_cards: dict[str, tuple[MetricCard, QProgressBar, QProgressBar | None]] = {}
        for key, label in (
            ("bullish", "BULLISH OPEN WEIGHT"),
            ("balanced", "BALANCED OPEN WEIGHT"),
            ("bearish", "BEARISH OPEN WEIGHT"),
            ("gap", "GAP RISK"),
        ):
            card = MetricCard(label, "N/A")
            bar = QProgressBar()
            bar.setRange(0, 1000)
            bar.setTextVisible(False)
            card.layout_box.addWidget(bar)
            metric_row.addWidget(card, 1)
            self._metric_cards[key] = (card, bar, None)
        root.addLayout(metric_row)

        detail = Card()
        detail_head = QHBoxLayout()
        detail_title = QLabel("Next-Session Opening Possibilities")
        detail_title.setObjectName("SectionTitle")
        detail_head.addWidget(detail_title)
        detail_head.addStretch(1)
        evidence = QLabel("Evidence Based")
        evidence.setObjectName("Muted")
        detail_head.addWidget(evidence)
        detail.layout_box.addLayout(detail_head)

        body = QHBoxLayout()
        body.setSpacing(18)
        left = QWidget()
        left_layout = QGridLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setHorizontalSpacing(8)
        left_layout.setVerticalSpacing(7)
        self._detail_values: dict[str, QLabel] = {}
        for row, (key, label) in enumerate((
            ("bullish", "Bullish"),
            ("balanced", "Balanced"),
            ("bearish", "Bearish"),
            ("gap", "Gap Risk"),
        )):
            value = QLabel("N/A")
            value.setObjectName("MetricValue")
            bar = QProgressBar()
            bar.setRange(0, 1000)
            bar.setTextVisible(False)
            left_layout.addWidget(value, row, 0)
            left_layout.addWidget(QLabel(label), row, 1)
            left_layout.addWidget(bar, row, 2)
            self._detail_values[key] = value
            card, top_bar, _detail = self._metric_cards[key]
            self._metric_cards[key] = (card, top_bar, bar)
        body.addWidget(left, 1)

        self.drivers = QLabel("No opening evidence available for this selection.")
        self.drivers.setWordWrap(True)
        self.drivers.setObjectName("Muted")
        body.addWidget(self.drivers, 1)
        detail.layout_box.addLayout(body)

        self.meta = QLabel("Scenario weights only — not calibrated probabilities.")
        self.meta.setWordWrap(True)
        self.meta.setObjectName("Muted")
        detail.layout_box.addWidget(self.meta)
        root.addWidget(detail, 1)

    def set_analysis_context(self, text: str) -> None:
        self.context_text.setText(
            text or "No period context is available for this range."
        )

    def _set_metric(self, key: str, value, tone: str = "neutral") -> None:
        numeric = max(0.0, min(100.0, float(value)))
        card, top_bar, detail_bar = self._metric_cards[key]
        card.set_value(
            f"{numeric:.0f}%",
            "positive" if tone == "positive" else "negative" if tone == "negative" else "neutral",
        )
        color = (
            BULLISH_COLOR
            if tone == "positive"
            else BEARISH_COLOR
            if tone == "negative"
            else "#6E7880"
        )
        for bar in (top_bar, detail_bar):
            if bar is None:
                continue
            bar.setValue(round(numeric * 10))
            bar.setStyleSheet(
                "QProgressBar{background:#ECE9E3;border:none;border-radius:4px;"
                "min-height:8px;max-height:8px;}"
                f"QProgressBar::chunk{{background:{color};border-radius:4px;}}"
            )
        self._detail_values[key].setText(f"{numeric:.0f}%")

    def set_snapshot(self, opening) -> None:
        self._set_metric("bullish", opening.bullish_weight, "positive")
        self._set_metric("balanced", opening.balanced_weight)
        self._set_metric("bearish", opening.bearish_weight, "negative")
        self._set_metric(
            "gap",
            opening.gap_risk,
            "negative" if opening.gap_risk >= 60 else "neutral",
        )
        self.meta.setText(
            f"Next session: {opening.next_session_candidate}  •  "
            f"Bias {opening.bias_score:.1f}  •  "
            f"Evidence coverage {opening.evidence_coverage:.0f}%\n"
            "Scenario weights are evidence weights, not calibrated probabilities."
        )
        evidence = list(opening.drivers[:5])
        if opening.limitations:
            evidence.append(f"Limit: {opening.limitations[0]}")
        self.drivers.setText(
            "\n".join(f"• {item}" for item in evidence)
            if evidence
            else "No opening evidence available for this selection."
        )


class IntraderModePage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 36)
        root.setSpacing(10)

        status_row = QHBoxLayout()
        status_row.setContentsMargins(0, 0, 0, 0)
        dots = DotMatrix(columns=4, rows=3)
        status_row.addWidget(dots)
        self.metrics = MetricRibbon([
            ("WAITING", "No Action"),
            ("DIRECTION", "N/A"),
            ("CONFIDENCE", "N/A"),
            ("ENTRY QUALITY", "N/A"),
            ("REVERSAL RISK", "N/A"),
        ])
        status_row.addWidget(self.metrics, 1)
        root.addLayout(status_row)

        self.runtime_status = QLabel("SESSION RUNTIME — STARTING")
        self.runtime_status.setObjectName("StatusPill")
        self.runtime_status.setWordWrap(True)
        root.addWidget(self.runtime_status)

        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(10)

        self.chart = MarketChart("NIFTY 50")
        self.chart.setMinimumHeight(330)
        left_layout.addWidget(self.chart, 3)

        reasoning = Card()
        reason_row = QHBoxLayout()
        reason_row.setContentsMargins(2, 0, 2, 0)
        reason_row.setSpacing(18)

        why_box = QWidget()
        why_layout = QVBoxLayout(why_box)
        why_layout.setContentsMargins(6, 2, 6, 2)
        why_title = QLabel("↗  Why this action")
        why_title.setObjectName("SectionTitle")
        self.why = BulletList()
        why_layout.addWidget(why_title)
        why_layout.addWidget(self.why, 1)

        why_not_box = QWidget()
        why_not_layout = QVBoxLayout(why_not_box)
        why_not_layout.setContentsMargins(6, 2, 6, 2)
        why_not_title = QLabel("↘  Why not the opposite")
        why_not_title.setObjectName("SectionTitle")
        self.why_not = BulletList()
        why_not_layout.addWidget(why_not_title)
        why_not_layout.addWidget(self.why_not, 1)

        context_box = QWidget()
        context_layout = QVBoxLayout(context_box)
        context_layout.setContentsMargins(6, 2, 6, 2)
        context_title = QLabel("Context")
        context_title.setObjectName("SectionTitle")
        self.context_text = QLabel("No live context snapshot yet.")
        self.context_text.setObjectName("Muted")
        self.context_text.setWordWrap(True)
        context_layout.addWidget(context_title)
        context_layout.addWidget(self.context_text, 1)

        reason_row.addWidget(why_box, 2)
        reason_row.addWidget(why_not_box, 2)
        reason_row.addWidget(context_box, 1)
        reasoning.layout_box.addLayout(reason_row)
        reasoning.setMinimumHeight(175)
        left_layout.addWidget(reasoning, 1)

        self.main_splitter.addWidget(left)

        right_widget = QWidget()
        right = QVBoxLayout(right_widget)
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(10)

        self.shadow = Card()
        shadow_head = QHBoxLayout()
        shadow_title = QLabel("●  Shadow Trade")
        shadow_title.setObjectName("SectionTitle")
        shadow_head.addWidget(shadow_title)
        shadow_head.addStretch(1)
        paper = QLabel("Paper Mode")
        paper.setObjectName("Muted")
        shadow_head.addWidget(paper)
        self.shadow.layout_box.addLayout(shadow_head)
        self.shadow_text = QLabel("No active position")
        self.shadow_text.setWordWrap(True)
        self.shadow_text.setObjectName("Muted")
        self.shadow.layout_box.addWidget(self.shadow_text)
        right.addWidget(self.shadow, 1)

        interpretation = Card()
        interpretation_head = QHBoxLayout()
        interpretation_title = QLabel("Current Interpretation")
        interpretation_title.setObjectName("SectionTitle")
        interpretation_head.addWidget(interpretation_title)
        interpretation_head.addStretch(1)
        interpretation_head.addWidget(DotMatrix(columns=4, rows=3))
        interpretation.layout_box.addLayout(interpretation_head)
        self.interpretation_values: dict[str, QLabel] = {}
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(7)
        for row_index, (key, label) in enumerate((
            ("PRICE", "Price Action"),
            ("FUTURES", "Futures"),
            ("OPTIONS", "Options Flow"),
            ("BREADTH", "Market Breadth"),
            ("ORDER_FLOW", "Order Flow"),
        )):
            name = QLabel(label)
            name.setObjectName("Muted")
            value = QLabel("N/A")
            value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self.interpretation_values[key] = value
            grid.addWidget(name, row_index, 0)
            grid.addWidget(value, row_index, 1)
        interpretation.layout_box.addLayout(grid)
        self.interpretation_summary = QLabel("Waiting for a verified Market Brain decision.")
        self.interpretation_summary.setWordWrap(True)
        self.interpretation_summary.setObjectName("Muted")
        interpretation.layout_box.addWidget(self.interpretation_summary)
        right.addWidget(interpretation, 2)

        self.news = Card()
        news_head = QHBoxLayout()
        news_title = QLabel("Global News / Events")
        news_title.setObjectName("SectionTitle")
        news_head.addWidget(news_title)
        news_head.addStretch(1)
        view_all = QLabel("View All  →")
        view_all.setObjectName("Muted")
        news_head.addWidget(view_all)
        self.news.layout_box.addLayout(news_head)
        self.news_table = DataTable(["Time", "Source", "Headline / Event"])
        self.news.layout_box.addWidget(self.news_table)
        right.addWidget(self.news, 3)

        self.main_splitter.addWidget(right_widget)
        self.main_splitter.setStretchFactor(0, 64)
        self.main_splitter.setStretchFactor(1, 36)
        root.addWidget(self.main_splitter, 1)

    def resizeEvent(self, event) -> None:
        self.main_splitter.setOrientation(
            Qt.Orientation.Vertical
            if event.size().width() < 1050
            else Qt.Orientation.Horizontal
        )
        super().resizeEvent(event)

    def apply_layout_preset(self, preset: str) -> None:
        width = max(1, self.width())
        if self.main_splitter.orientation() == Qt.Orientation.Horizontal:
            self.main_splitter.setSizes([int(width * 0.64), int(width * 0.36)])

    def _set_interpretation(self, decision) -> None:
        family_map = {family.name: family.value for family in decision.families}
        states = []
        for key, label in self.interpretation_values.items():
            value = family_map.get(key)
            if value is None:
                state = "N/A"
                object_name = "Muted"
            elif value > Decimal("0.15"):
                state = "Bullish"
                object_name = "Positive"
                states.append("bullish")
            elif value < Decimal("-0.15"):
                state = "Bearish"
                object_name = "Negative"
                states.append("bearish")
            else:
                state = "Neutral"
                object_name = "Muted"
                states.append("neutral")
            label.setText(state)
            label.setObjectName(object_name)
            label.style().unpolish(label)
            label.style().polish(label)

        if decision.action == "WAIT":
            summary = "Mixed confirmation. Entry conditions are not strong enough for a shadow entry."
        elif decision.action == "NO_TRADE":
            summary = "Safety gates are active. Intrader is deliberately standing aside."
        elif decision.action == "BUY_CALL":
            summary = "Bullish evidence is leading the current Market Brain thesis."
        elif decision.action == "BUY_PUT":
            summary = "Bearish evidence is leading the current Market Brain thesis."
        else:
            summary = f"{decision.brain_state} • {decision.regime}"
        self.interpretation_summary.setText(summary)

    def _set_live_brain_interpretation(self, brain) -> None:
        family_map = {family.name: family.value for family in brain.families}
        for key, label in self.interpretation_values.items():
            value = family_map.get(key)
            if value is None:
                state = "N/A"
                object_name = "Muted"
            elif value > Decimal("0.15"):
                state = "Bullish"
                object_name = "Positive"
            elif value < Decimal("-0.15"):
                state = "Bearish"
                object_name = "Negative"
            else:
                state = "Neutral"
                object_name = "Muted"
            label.setText(state)
            label.setObjectName(object_name)
            label.style().unpolish(label)
            label.style().polish(label)

        reasons = " • ".join(brain.reasons[:3]) if brain.reasons else "No active safety gate."
        self.interpretation_summary.setText(
            f"{brain.state} • family coverage {brain.family_coverage}% • {reasons}"
        )

    def refresh_snapshot(self, snapshot) -> None:
        runtime = snapshot.runtime_status
        next_text = ""
        if runtime.next_transition is not None:
            remaining = max(
                0,
                int(
                    (
                        runtime.next_transition.astimezone(INDIA_TIME)
                        - datetime.now(INDIA_TIME)
                    ).total_seconds()
                    // 60
                ),
            )
            next_text = (
                f" • next {runtime.next_transition.astimezone(INDIA_TIME):%H:%M}"
                f" ({remaining}m)"
            )
        feed_text = (
            "feed connecting"
            if runtime.expected_count == 0
            else f"feed {runtime.fresh_count}/{runtime.expected_count}"
        )
        recovery = " • late-start recovered" if runtime.recovered_late else ""
        self.runtime_status.setText(
            f"{runtime.phase.replace('_', ' ')} • {feed_text}{next_text}{recovery} • "
            f"{runtime.message}"
        )

        decision = snapshot.latest_decision
        brain = snapshot.live_brain

        if decision is None and brain is None:
            self.metrics.set_metric(
                "WAITING",
                runtime.phase.replace("_", " "),
            )
            for key in ("DIRECTION", "CONFIDENCE", "ENTRY QUALITY", "REVERSAL RISK"):
                self.metrics.set_metric(key, "N/A")
            self.why.set_reasons([])
            self.why_not.set_reasons([])
            self.context_text.setText(
                "Live recorder is starting. Interpretation appears when the required "
                "market families are synchronized."
            )
            for label in self.interpretation_values.values():
                label.setText("N/A")
                label.setObjectName("Muted")
            self.interpretation_summary.setText(
                "Waiting for synchronized live market data."
            )
        elif decision is None and brain is not None:
            self.metrics.set_metric(
                "WAITING",
                runtime.phase.replace("_", " "),
                "neutral",
            )
            self.metrics.set_metric(
                "DIRECTION",
                str(brain.direction_score),
                _tone(brain.direction_score),
            )
            self.metrics.set_metric("CONFIDENCE", f"{brain.confidence}%")
            self.metrics.set_metric("ENTRY QUALITY", str(brain.entry_quality))
            self.metrics.set_metric(
                "REVERSAL RISK",
                str(brain.reversal_risk),
                "negative" if brain.reversal_risk > 70 else "neutral",
            )
            self.why.set_reasons(
                [("LIVE_BRAIN", reason) for reason in brain.reasons[:4]]
            )
            self.why_not.set_reasons([])
            self.context_text.setText(
                f"Live Market Brain • {runtime.phase.replace('_', ' ')}\n"
                f"Family coverage     {brain.family_coverage}%\n"
                f"Trading permission  {'YES' if runtime.phase == 'LIVE' else 'NO'}"
            )
            self._set_live_brain_interpretation(brain)
        else:
            action_tone = (
                "positive" if decision.action == "BUY_CALL"
                else "negative" if decision.action == "BUY_PUT"
                else "neutral"
            )
            self.metrics.set_metric("WAITING", decision.action.replace("_", " "), action_tone)
            self.metrics.set_metric(
                "DIRECTION", str(decision.direction_score), _tone(decision.direction_score)
            )
            self.metrics.set_metric("CONFIDENCE", f"{decision.confidence}%")
            self.metrics.set_metric("ENTRY QUALITY", str(decision.entry_quality))
            self.metrics.set_metric(
                "REVERSAL RISK",
                str(decision.reversal_risk),
                "negative" if decision.reversal_risk > 70 else "neutral",
            )
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
            self._set_interpretation(decision)
            self.context_text.setText(
                f"Higher TF trend   {decision.regime}\n"
                f"Spot              {decision.spot_price}\n"
                f"VIX               {decision.vix}\n"
                f"Basis             {decision.basis}\n"
                f"Breadth            {_text(decision.breadth_pct)}"
            )

        trade = snapshot.active_shadow_trade
        if trade is None:
            self.shadow_text.setText(
                "No active shadow position.\n"
                + (
                    "Paper entries are disabled outside the configured live window."
                    if runtime.phase != "LIVE"
                    else "Paper-mode entries will appear here when the Market Brain qualifies one."
                )
            )
        else:
            self.shadow_text.setText(
                f"{trade.action} • {trade.strike} {trade.option_type}\n"
                f"Entry  {trade.entry_price}     Stop  {trade.stop_price}\n"
                f"Target {trade.target_price}     Qty   {trade.quantity}\n"
                f"Max hold {trade.max_minutes} min • {trade.shadow_version}"
            )

        rows = []
        for event in snapshot.upcoming_events[:5]:
            rows.append([
                event.scheduled_at.astimezone(INDIA_TIME).strftime("%H:%M"),
                event.source,
                event.name,
            ])
        for item in snapshot.recent_news[:7]:
            rows.append([
                item.published_at.astimezone(INDIA_TIME).strftime("%H:%M"),
                item.source,
                item.title,
            ])
        self.news_table.set_rows(
            rows[:8] or [["—", "—", "No relevant market context cached yet."]]
        )

    def set_candles(self, candles) -> None:
        if candles:
            self.chart.set_candle_objects(candles)
        else:
            self.chart.set_empty_message("No stored NIFTY candles for this session.")


class TimeTravelPage(QWidget):
    session_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._decisions = ()
        self._bundles = ()
        self._news = ()
        self._key_moments = ()
        self._session_mode = False

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 34)
        root.setSpacing(8)

        title_row = QHBoxLayout()
        title = QLabel("Time Travel")
        title.setObjectName("PageTitle")
        title_row.addWidget(title)
        hint = QLabel("Historical research • opening possibilities")
        hint.setObjectName("Muted")
        title_row.addWidget(hint)
        title_row.addStretch(1)
        self.session_view_button = QPushButton("Session to Now")
        self.session_view_button.setObjectName("PrimaryButton")
        self.replay_view_button = QPushButton("30m Replay")
        self.replay_view_button.setObjectName("SecondaryButton")
        self.range_view_button = QPushButton("Range Analysis")
        self.range_view_button.setObjectName("SecondaryButton")
        title_row.addWidget(self.session_view_button)
        title_row.addWidget(self.replay_view_button)
        title_row.addWidget(self.range_view_button)
        title_row.addWidget(DotMatrix(columns=4, rows=3))
        root.addLayout(title_row)

        self.tabs = QTabWidget()
        self.tabs.tabBar().setVisible(False)
        root.addWidget(self.tabs, 1)
        self._build_replay_tab()
        self._build_range_tab()
        self.tabs.setCurrentIndex(1)
        self.session_view_button.clicked.connect(self.session_requested.emit)
        self.replay_view_button.clicked.connect(self._show_replay)
        self.range_view_button.clicked.connect(self._show_range)

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
        self.day.setDisplayFormat("dd MMM yyyy")
        self.end_time = QTimeEdit(QTime.currentTime())
        self.end_time.setDisplayFormat("HH:mm")
        self.end_time.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
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
        self.chart.setMinimumHeight(250)
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
        range_root.setContentsMargins(4, 4, 4, 4)
        range_root.setSpacing(10)

        controls_card = Card()
        controls = QHBoxLayout()
        controls.setContentsMargins(0, 0, 0, 0)
        controls.setSpacing(8)

        controls.addWidget(QLabel("From"))
        self.range_from_day = QDateEdit(QDate.currentDate().addDays(-5))
        self.range_from_day.setCalendarPopup(True)
        self.range_from_day.setDisplayFormat("dd MMM yyyy")
        self.range_from_time = QTimeEdit(QTime(9, 15))
        self.range_from_time.setDisplayFormat("HH:mm")
        self.range_from_time.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        controls.addWidget(self.range_from_day)
        controls.addWidget(self.range_from_time)

        arrow = QLabel("→")
        arrow.setObjectName("Muted")
        controls.addWidget(arrow)

        self.range_to_day = QDateEdit(QDate.currentDate())
        self.range_to_day.setCalendarPopup(True)
        self.range_to_day.setDisplayFormat("dd MMM yyyy")
        self.range_to_time = QTimeEdit(QTime(15, 30))
        self.range_to_time.setDisplayFormat("HH:mm")
        self.range_to_time.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        controls.addWidget(self.range_to_day)
        controls.addWidget(self.range_to_time)

        self.range_load_button = QPushButton("▶  Analyze Period")
        self.range_load_button.setObjectName("PrimaryButton")
        controls.addWidget(self.range_load_button)
        self.range_enrich_button = QPushButton("Fetch Missing")
        self.range_enrich_button.setObjectName("SecondaryButton")
        self.range_enrich_button.setToolTip(
            "Manual retry for candles/news/context. Analyze Period already refreshes "
            "the selected range on a best-effort basis."
        )
        controls.addWidget(self.range_enrich_button)
        controls.addStretch(1)

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
            button.setObjectName("SecondaryButton")
            controls.addWidget(button)

        controls_card.layout_box.addLayout(controls)
        range_root.addWidget(controls_card)

        state_row = QHBoxLayout()
        state_row.addStretch(1)
        self.range_state = QLabel("No range analyzed yet.")
        self.range_state.setObjectName("Muted")
        state_row.addWidget(self.range_state)
        range_root.addLayout(state_row)

        self.range_metrics = MetricRibbon([
            ("NIFTY CHANGE", "N/A"),
            ("SESSIONS", "0"),
            ("HIGH / LOW", "N/A"),
            ("SHADOW P&L", "0"),
            ("EXPECTANCY", "N/A"),
            ("RELEVANT NEWS", "0"),
        ])
        range_root.addWidget(self.range_metrics)

        self.session_guidance = Card()
        guidance_row = QHBoxLayout()
        guidance_row.setContentsMargins(0, 0, 0, 0)
        guidance_row.setSpacing(16)
        action_box = QWidget()
        action_layout = QVBoxLayout(action_box)
        action_layout.setContentsMargins(0, 0, 0, 0)
        action_layout.setSpacing(2)
        action_label = QLabel("CURRENT ADVISORY")
        action_label.setObjectName("CardTitle")
        self.session_action = QLabel("WAIT")
        self.session_action.setObjectName("HeroValue")
        action_layout.addWidget(action_label)
        action_layout.addWidget(self.session_action)
        guidance_row.addWidget(action_box)

        self.session_guidance_metrics = MetricRibbon([
            ("REGIME", "N/A"),
            ("DIRECTION", "N/A"),
            ("CONFIDENCE", "N/A"),
            ("ENTRY", "N/A"),
            ("RISK", "N/A"),
        ])
        guidance_row.addWidget(self.session_guidance_metrics, 1)

        self.session_guidance_text = QLabel(
            "Session-to-Now uses only recorded Market Brain evidence for CALL/PUT guidance."
        )
        self.session_guidance_text.setWordWrap(True)
        self.session_guidance_text.setObjectName("Muted")
        self.session_guidance.layout_box.addLayout(guidance_row)
        self.session_guidance.layout_box.addWidget(self.session_guidance_text)
        self.session_guidance.hide()
        range_root.addWidget(self.session_guidance)

        self.range_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.range_chart = MarketChart("Price Chart — Selected Range")
        self.range_chart.setMinimumHeight(330)
        self.range_splitter.addWidget(self.range_chart)

        self.opening_panel = OpeningScenarioPanel()
        self.range_splitter.addWidget(self.opening_panel)
        self.range_splitter.setStretchFactor(0, 58)
        self.range_splitter.setStretchFactor(1, 42)
        range_root.addWidget(self.range_splitter, 4)

        bottom_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.detail_tabs = QTabWidget()
        self.key_moments = DataTable(
            ["Date / Time", "Event", "Importance", "Context", "Detail"]
        )
        self.detail_tabs.addTab(self.key_moments, "Key Moments")

        self.range_notes = TextPanel(
            "Period Analysis",
            "No period analysis available yet.",
        )
        self.detail_tabs.addTab(self.range_notes, "Period Analysis")

        self.range_news_context = DataTable(
            ["Date / Time", "Type", "Source", "Context"]
        )
        self.detail_tabs.addTab(self.range_news_context, "News Context")

        self.range_coverage = DataTable(["Data family", "Coverage"])
        self.detail_tabs.addTab(self.range_coverage, "Data Coverage")
        self.detail_tabs.setMinimumHeight(190)
        bottom_splitter.addWidget(self.detail_tabs)

        side = QWidget()
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(0, 0, 0, 0)
        side_layout.setSpacing(8)

        decision_card = Card("Decision Mix")
        self.range_decisions = MixBars()
        decision_card.add_widget(self.range_decisions)
        side_layout.addWidget(decision_card)

        regime_card = Card("Regime Mix")
        self.range_regimes = MixBars()
        regime_card.add_widget(self.range_regimes)
        side_layout.addWidget(regime_card)

        bottom_splitter.addWidget(side)
        bottom_splitter.setStretchFactor(0, 70)
        bottom_splitter.setStretchFactor(1, 30)
        range_root.addWidget(bottom_splitter, 2)

        self.tabs.addTab(range_tab, "Range Analysis / Opening Possibilities")

    def _show_replay(self) -> None:
        self._session_mode = False
        self.tabs.setCurrentIndex(0)

    def _show_range(self) -> None:
        self._session_mode = False
        self.session_guidance.hide()
        self.tabs.setCurrentIndex(1)

    def set_range_inputs(self, start: datetime, end: datetime) -> None:
        start = start.astimezone(INDIA_TIME)
        end = end.astimezone(INDIA_TIME)
        self.range_from_day.setDate(
            QDate(start.year, start.month, start.day)
        )
        self.range_from_time.setTime(QTime(start.hour, start.minute))
        self.range_to_day.setDate(
            QDate(end.year, end.month, end.day)
        )
        self.range_to_time.setTime(QTime(end.hour, end.minute))

    def _set_session_guidance(self, decision, analysis) -> None:
        self.session_guidance.show()
        if decision is None:
            self.session_action.setText("WAIT")
            self.session_action.setObjectName("HeroValue")
            for key in ("REGIME", "DIRECTION", "CONFIDENCE", "ENTRY", "RISK"):
                self.session_guidance_metrics.set_metric(key, "N/A")
            self.session_guidance_text.setText(
                "No complete Market Brain decision was recorded in this session. "
                "Candles and news are descriptive only, so Intrader will not invent "
                "a CALL/PUT recommendation."
            )
        else:
            tone = (
                "positive" if decision.action == "BUY_CALL"
                else "negative" if decision.action == "BUY_PUT"
                else "neutral"
            )
            self.session_action.setText(decision.action.replace("_", " "))
            self.session_action.setObjectName(
                "Positive" if tone == "positive"
                else "Negative" if tone == "negative"
                else "HeroValue"
            )
            self.session_action.style().unpolish(self.session_action)
            self.session_action.style().polish(self.session_action)
            self.session_guidance_metrics.set_metric("REGIME", decision.regime)
            self.session_guidance_metrics.set_metric(
                "DIRECTION", str(decision.direction_score), _tone(decision.direction_score)
            )
            self.session_guidance_metrics.set_metric(
                "CONFIDENCE", f"{decision.confidence}%"
            )
            self.session_guidance_metrics.set_metric(
                "ENTRY", str(decision.entry_quality)
            )
            self.session_guidance_metrics.set_metric(
                "RISK",
                str(decision.reversal_risk),
                "negative" if decision.reversal_risk > 70 else "neutral",
            )
            self.session_guidance_text.setText(
                f"Latest verified Brain decision at "
                f"{decision.decided_at.astimezone(INDIA_TIME):%H:%M}. "
                f"Family coverage {decision.family_coverage}%. "
                "This remains advisory/shadow guidance; real execution is manual."
            )

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
        if self.range_splitter.orientation() == Qt.Orientation.Horizontal:
            self.range_splitter.setSizes([int(width * 0.58), int(width * 0.42)])
            self.replay_splitter.setSizes([int(width * 0.70), int(width * 0.30)])
        self.detail_tabs.setMinimumHeight(190)
        self.replay_details.setMaximumHeight(170)

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
        if days is not None and days >= 5:
            self.range_chart.set_timeframe("Auto")
        elif days == 0:
            self.range_chart.set_timeframe("5m")

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
        if window:
            self.chart.set_candle_objects(window)
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

    def set_range_analysis(
        self,
        analysis,
        opening,
        candles,
        news=(),
        events=(),
        *,
        session_decision=None,
        session_mode: bool = False,
    ) -> None:
        self._session_mode = session_mode
        prefix = "Session-to-Now" if session_mode else "Analyzed"
        self.range_state.setText(
            f"{prefix} {analysis.start.astimezone(INDIA_TIME):%d %b %H:%M} → "
            f"{analysis.end.astimezone(INDIA_TIME):%d %b %H:%M} • "
            f"{analysis.candle_count:,} candles"
        )
        self.range_metrics.set_metric(
            "NIFTY CHANGE",
            "N/A" if analysis.change_pct is None else f"{analysis.change_pct:.3f}%",
            _tone(analysis.change_pct),
        )
        self.range_metrics.set_metric(
            "SESSIONS",
            str(analysis.session_count),
            tooltip="Unique local trading dates",
        )
        self.range_metrics.set_metric(
            "HIGH / LOW",
            "N/A"
            if analysis.high is None or analysis.low is None
            else f"{analysis.high} / {analysis.low}",
        )
        self.range_metrics.set_metric(
            "SHADOW P&L",
            str(analysis.adjusted_pnl),
            _tone(analysis.adjusted_pnl),
        )
        self.range_metrics.set_metric(
            "EXPECTANCY",
            _text(analysis.expectancy),
            _tone(analysis.expectancy),
        )
        self.range_metrics.set_metric(
            "RELEVANT NEWS",
            str(analysis.news_count),
            tooltip="Filtered market-relevant context",
        )

        if candles:
            if analysis.end - analysis.start >= timedelta(days=5):
                self.range_chart.set_timeframe("Auto")
            elif session_mode:
                self.range_chart.set_timeframe("5m")
            self.range_chart.set_candle_objects(candles)
        else:
            self.range_chart.set_empty_message(
                "No local NIFTY candles in this range. Use Fetch Missing if needed."
            )

        self.opening_panel.set_snapshot(opening)
        if session_mode:
            self._set_session_guidance(session_decision, analysis)
        else:
            self.session_guidance.hide()
        context_summary = " ".join(str(item) for item in analysis.analysis_notes[:2])
        self.opening_panel.set_analysis_context(
            context_summary
            or (
                f"NIFTY range analysis covers {analysis.session_count} sessions "
                f"with {analysis.candle_count:,} stored candles."
            )
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
        context_rows = []
        for item in news:
            context_rows.append([
                item.published_at.astimezone(INDIA_TIME).strftime("%Y-%m-%d %H:%M"),
                "NEWS",
                item.source,
                item.title,
            ])
        for event in events:
            context_rows.append([
                event.scheduled_at.astimezone(INDIA_TIME).strftime("%Y-%m-%d %H:%M"),
                f"EVENT • {event.impact}",
                event.source,
                event.name,
            ])
        context_rows.sort(key=lambda row: row[0], reverse=True)
        self.range_news_context.set_rows(
            context_rows
            or [["—", "—", "—", "No cached news or scheduled events in this range."]]
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

        self.metrics = MetricRibbon([
            ("P&L", "0"),
            ("WIN RATE", "N/A"),
            ("EXPECTANCY", "N/A"),
            ("PROFIT FACTOR", "N/A"),
            ("DRAWDOWN", "0"),
            ("TRADES", "0"),
        ])
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
        self.metrics.set_metric(
            "P&L", str(overall.adjusted_pnl), _tone(overall.adjusted_pnl)
        )
        self.metrics.set_metric(
            "WIN RATE",
            "N/A" if overall.win_rate is None else f"{overall.win_rate:.2f}%",
        )
        self.metrics.set_metric(
            "EXPECTANCY", _text(overall.expectancy), _tone(overall.expectancy)
        )
        self.metrics.set_metric("PROFIT FACTOR", _text(overall.profit_factor))
        self.metrics.set_metric(
            "DRAWDOWN",
            str(overall.max_drawdown),
            "negative" if overall.max_drawdown > 0 else "neutral",
        )
        self.metrics.set_metric("TRADES", str(overall.trades))

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
