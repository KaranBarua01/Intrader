"""Strategy Lab desktop mode.

This page is intentionally isolated from Intrader Mode. It visualizes
historical research hypotheses and can drill occurrences into Time Travel.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from PySide6.QtCore import QDate, QTime, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from intrader.historical import INDIA_TIME
from intrader.ui.components import Card, DataTable, MetricCard


def _fmt_pct(value) -> str:
    return "N/A" if value is None else f"{value:.2f}%"


def _fmt(value) -> str:
    return "N/A" if value is None else f"{value:.4f}%"


class StrategyLabPage(QWidget):
    analyze_requested = Signal()
    replay_requested = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self._snapshot = None
        self._visible_strategies = ()
        self._visible_occurrences = ()

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        header = QHBoxLayout()
        title = QLabel("Strategy Lab")
        title.setObjectName("PageTitle")
        header.addWidget(title)
        header.addSpacing(12)

        badge = QLabel("LAB ONLY — NOT USED BY INTRADER MODE")
        badge.setStyleSheet(
            "background:#fff4dc;color:#8a641e;border-radius:9px;"
            "padding:5px 9px;font-weight:700;"
        )
        header.addWidget(badge)
        header.addStretch(1)
        root.addLayout(header)

        explainer = QLabel(
            "Tests isolated book-inspired hypotheses against Time Travel candle "
            "history. A strategy must survive larger samples and untouched "
            "validation before it can ever become an Intrader candidate."
        )
        explainer.setWordWrap(True)
        explainer.setObjectName("Muted")
        root.addWidget(explainer)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("From"))
        self.from_day = QDateEdit(QDate.currentDate().addDays(-5))
        self.from_day.setCalendarPopup(True)
        self.from_time = QTimeEdit(QTime(9, 15))
        self.from_time.setDisplayFormat("HH:mm")
        controls.addWidget(self.from_day)
        controls.addWidget(self.from_time)

        controls.addWidget(QLabel("To"))
        self.to_day = QDateEdit(QDate.currentDate())
        self.to_day.setCalendarPopup(True)
        self.to_time = QTimeEdit(QTime(15, 30))
        self.to_time.setDisplayFormat("HH:mm")
        controls.addWidget(self.to_day)
        controls.addWidget(self.to_time)

        self.preset_5d = QPushButton("5D")
        self.preset_10d = QPushButton("10D")
        self.preset_30d = QPushButton("30D")
        for button in (self.preset_5d, self.preset_10d, self.preset_30d):
            controls.addWidget(button)

        controls.addWidget(QLabel("Source"))
        self.source_filter = QComboBox()
        self.source_filter.addItems(
            ["All", "Steve Nison", "Ashwani Gujral", "John Carter", "Mark Douglas"]
        )
        controls.addWidget(self.source_filter)

        self.analyze_button = QPushButton("Analyze Strategies")
        self.analyze_button.setObjectName("PrimaryButton")
        controls.addWidget(self.analyze_button)
        controls.addStretch(1)
        root.addLayout(controls)

        metrics = QHBoxLayout()
        self.total_signals = MetricCard("TOTAL SIGNALS", "0")
        self.active_strategies = MetricCard("STRATEGIES WITH SIGNALS", "0")
        self.best_hit = MetricCard("HIGHEST OBSERVED 30M HIT", "N/A")
        self.sessions = MetricCard("SESSIONS", "0")
        self.candles = MetricCard("CANDLES TESTED", "0")
        for card in (
            self.total_signals,
            self.active_strategies,
            self.best_hit,
            self.sessions,
            self.candles,
        ):
            metrics.addWidget(card)
        root.addLayout(metrics)

        self.strategy_table = DataTable(
            [
                "Source",
                "Strategy",
                "Signals",
                "Bull",
                "Bear",
                "5m Hit",
                "15m Hit",
                "30m Hit",
                "Avg 30m",
                "MFE 30m",
                "MAE 30m",
                "Sample",
            ]
        )
        strategy_card = Card("STRATEGY PERFORMANCE")
        strategy_card.add_widget(self.strategy_table)
        root.addWidget(strategy_card, 2)

        lower = QHBoxLayout()
        self.occurrence_table = DataTable(
            [
                "Time",
                "Direction",
                "Entry",
                "Regime",
                "5m",
                "15m",
                "30m",
                "MFE",
                "MAE",
            ]
        )
        occurrence_card = Card(
            "OCCURRENCES — DOUBLE-CLICK TO OPEN IN TIME TRAVEL"
        )
        occurrence_card.add_widget(self.occurrence_table)
        lower.addWidget(occurrence_card, 3)

        notes_side = QVBoxLayout()
        self.strategy_detail = DataTable(["Selected strategy"])
        detail_card = Card("HYPOTHESIS")
        detail_card.add_widget(self.strategy_detail)
        notes_side.addWidget(detail_card)

        self.notes = DataTable(["RESEARCH GUARDRAILS"])
        notes_card = Card("INTERPRETATION")
        notes_card.add_widget(self.notes)
        notes_side.addWidget(notes_card, 1)
        lower.addLayout(notes_side, 2)
        root.addLayout(lower, 2)

        self.analyze_button.clicked.connect(self.analyze_requested.emit)
        self.source_filter.currentTextChanged.connect(
            lambda _text: self._render_strategy_table()
        )
        self.strategy_table.currentCellChanged.connect(
            self._strategy_selection_changed
        )
        self.occurrence_table.cellDoubleClicked.connect(
            self._open_occurrence
        )
        self.preset_5d.clicked.connect(lambda: self._set_preset(5))
        self.preset_10d.clicked.connect(lambda: self._set_preset(10))
        self.preset_30d.clicked.connect(lambda: self._set_preset(30))

    def selected_range(self) -> tuple[datetime, datetime]:
        fd = self.from_day.date()
        ft = self.from_time.time()
        td = self.to_day.date()
        tt = self.to_time.time()
        start = datetime(
            fd.year(),
            fd.month(),
            fd.day(),
            ft.hour(),
            ft.minute(),
            tzinfo=INDIA_TIME,
        )
        end = datetime(
            td.year(),
            td.month(),
            td.day(),
            tt.hour(),
            tt.minute(),
            tzinfo=INDIA_TIME,
        )
        return start, end

    def _set_preset(self, days: int) -> None:
        now = datetime.now(INDIA_TIME)
        start = now - timedelta(days=days)
        self.from_day.setDate(QDate(start.year, start.month, start.day))
        self.from_time.setTime(QTime(start.hour, start.minute))
        self.to_day.setDate(QDate(now.year, now.month, now.day))
        self.to_time.setTime(QTime(now.hour, now.minute))

    def set_snapshot(self, snapshot) -> None:
        self._snapshot = snapshot
        self.total_signals.set_value(
            str(sum(strategy.signals for strategy in snapshot.strategies))
        )
        self.active_strategies.set_value(
            str(sum(1 for strategy in snapshot.strategies if strategy.signals))
        )
        available_hits = [
            strategy.hit_rate_30m
            for strategy in snapshot.strategies
            if strategy.hit_rate_30m is not None
        ]
        self.best_hit.set_value(
            "N/A"
            if not available_hits
            else f"{max(available_hits):.2f}%"
        )
        self.sessions.set_value(str(snapshot.session_count))
        self.candles.set_value(str(snapshot.candle_count))
        self.notes.set_rows([[note] for note in snapshot.notes])
        self._render_strategy_table()

    def _source_matches(self, source: str) -> bool:
        selected = self.source_filter.currentText()
        if selected == "All":
            return True
        return selected in source

    def _render_strategy_table(self) -> None:
        if self._snapshot is None:
            self._visible_strategies = ()
            self.strategy_table.set_rows([])
            self.occurrence_table.set_rows([])
            return
        self._visible_strategies = tuple(
            strategy
            for strategy in self._snapshot.strategies
            if self._source_matches(strategy.definition.source)
        )
        self.strategy_table.set_rows(
            [
                [
                    strategy.definition.source,
                    strategy.definition.name,
                    strategy.signals,
                    strategy.bullish_signals,
                    strategy.bearish_signals,
                    _fmt_pct(strategy.hit_rate_5m),
                    _fmt_pct(strategy.hit_rate_15m),
                    _fmt_pct(strategy.hit_rate_30m),
                    _fmt(strategy.avg_return_30m),
                    _fmt(strategy.avg_mfe_30m),
                    _fmt(strategy.avg_mae_30m),
                    strategy.sample_label,
                ]
                for strategy in self._visible_strategies
            ]
        )
        if self._visible_strategies:
            self.strategy_table.selectRow(0)
            self._show_strategy(0)
        else:
            self._show_strategy(-1)

    def _strategy_selection_changed(
        self,
        current_row: int,
        _current_column: int,
        _previous_row: int,
        _previous_column: int,
    ) -> None:
        self._show_strategy(current_row)

    def _show_strategy(self, row: int) -> None:
        if row < 0 or row >= len(self._visible_strategies):
            self.strategy_detail.set_rows([])
            self.occurrence_table.set_rows([])
            self._visible_occurrences = ()
            return
        strategy = self._visible_strategies[row]
        definition = strategy.definition
        self.strategy_detail.set_rows(
            [
                [f"{definition.name} — {definition.source}"],
                [definition.description],
                [f"Direction scope: {definition.direction_scope}"],
                [f"Sample status: {strategy.sample_label}"],
            ]
        )
        self._visible_occurrences = strategy.occurrences
        self.occurrence_table.set_rows(
            [
                [
                    item.at.astimezone(INDIA_TIME).strftime(
                        "%Y-%m-%d %H:%M"
                    ),
                    "BULLISH" if item.direction > 0 else "BEARISH",
                    item.entry_price,
                    item.regime or "N/A",
                    _fmt(item.return_5m),
                    _fmt(item.return_15m),
                    _fmt(item.return_30m),
                    _fmt(item.mfe_30m),
                    _fmt(item.mae_30m),
                ]
                for item in self._visible_occurrences
            ]
        )

    def _open_occurrence(self, row: int, _column: int) -> None:
        if row < 0 or row >= len(self._visible_occurrences):
            return
        self.replay_requested.emit(self._visible_occurrences[row].at)
