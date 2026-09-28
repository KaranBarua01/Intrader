"""Causal event-driven Shadow Trader engine for Intrader 0.5.0.

The engine consumes one-minute candles in timestamp order, aggregates them into
independent 1m/5m/10m/15m bars, applies a frozen strategy selected only from the
development block, optionally confirms/rejects signals with historical feature
families, and updates an isolated paper account.

No broker order path exists in this module.
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime, timedelta, time
from decimal import Decimal
from typing import Iterable, Mapping, Sequence

from intrader.historical import Candle, INDIA_TIME
from intrader.shadow_execution import execution_adapter
from intrader.shadow_lab import ShadowReplayConfig, TRADER_HOLD_MINUTES
from intrader.strategy_lab import detect_strategy_signal


D = Decimal
_HOLD = dict(TRADER_HOLD_MINUTES)


@dataclass(frozen=True, slots=True)
class FeatureEvent:
    at: datetime
    family: str
    score: Decimal
    label: str


@dataclass(frozen=True, slots=True)
class RiskWindow:
    start: datetime
    end: datetime
    label: str


@dataclass(frozen=True, slots=True)
class FeatureSnapshot:
    at: datetime
    scores: tuple[tuple[str, Decimal], ...]
    labels: tuple[str, ...]
    high_impact_event_active: bool


class HistoricalFeatureTimeline:
    """Sparse causal feature timeline queried strictly as-of simulated time."""

    def __init__(
        self,
        events: Sequence[FeatureEvent] = (),
        risk_windows: Sequence[RiskWindow] = (),
    ) -> None:
        grouped: dict[str, list[FeatureEvent]] = {}
        for event in sorted(events, key=lambda item: item.at):
            grouped.setdefault(event.family, []).append(event)
        self._events = {key: tuple(value) for key, value in grouped.items()}
        self._times = {
            key: tuple(item.at for item in value)
            for key, value in self._events.items()
        }
        self._risk_windows = tuple(
            sorted(risk_windows, key=lambda item: (item.start, item.end))
        )

    @property
    def families(self) -> tuple[str, ...]:
        return tuple(sorted(self._events))

    def snapshot(
        self,
        at: datetime,
        families: Sequence[str],
        *,
        max_age_minutes: int = 10,
    ) -> FeatureSnapshot:
        if at.tzinfo is None:
            raise ValueError("feature snapshot timestamp must be timezone aware")
        scores: list[tuple[str, Decimal]] = []
        labels: list[str] = []
        max_age = timedelta(minutes=max_age_minutes)
        for family in families:
            rows = self._events.get(family)
            times = self._times.get(family)
            if not rows or not times:
                continue
            index = bisect_right(times, at) - 1
            if index < 0:
                continue
            row = rows[index]
            if at - row.at > max_age:
                continue
            scores.append((family, row.score))
            labels.append(row.label)

        active = any(window.start <= at <= window.end for window in self._risk_windows)
        return FeatureSnapshot(
            at=at,
            scores=tuple(scores),
            labels=tuple(labels),
            high_impact_event_active=active,
        )


@dataclass(frozen=True, slots=True)
class FrozenEngineSpec:
    timeframe_minutes: int
    strategy_id: str
    strategy_name: str
    engine_id: str
    hold_minutes: int
    enabled_families: tuple[str, ...]
    training_start: str
    training_end: str


@dataclass(frozen=True, slots=True)
class StreamTrade:
    timeframe_minutes: int
    engine_id: str
    strategy_name: str
    opened_at: str
    closed_at: str
    direction: str
    entry_underlying: Decimal
    exit_underlying: Decimal
    gross_return_pct: Decimal
    net_return_pct: Decimal
    paper_pnl: Decimal
    balance_after: Decimal
    mfe_pct: Decimal
    mae_pct: Decimal
    regime: str
    time_bucket: str
    feature_scores: tuple[tuple[str, Decimal], ...]
    exit_reason: str
    result: str


@dataclass(frozen=True, slots=True)
class StreamRejectedSignal:
    timeframe_minutes: int
    engine_id: str
    at: str
    direction: str
    reason: str
    hypothetical_return_pct: Decimal | None
    hypothetical_pnl: Decimal | None
    classification: str


@dataclass(frozen=True, slots=True)
class StreamAccountSummary:
    starting_capital: Decimal
    ending_capital: Decimal
    net_pnl: Decimal
    return_pct: Decimal
    max_drawdown: Decimal
    max_drawdown_pct: Decimal
    trades: int
    wins: int
    losses: int
    flats: int
    profit_factor: Decimal | None
    average_return_pct: Decimal | None
    max_losing_streak: int


@dataclass(frozen=True, slots=True)
class SliceStat:
    key: str
    trades: int
    wins: int
    losses: int
    average_return_pct: Decimal | None
    net_pnl: Decimal
    profit_factor: Decimal | None


@dataclass(frozen=True, slots=True)
class StreamEngineReport:
    spec: FrozenEngineSpec
    account: StreamAccountSummary
    trades: tuple[StreamTrade, ...]
    rejected_signals: tuple[StreamRejectedSignal, ...]
    regime_stats: tuple[SliceStat, ...]
    time_stats: tuple[SliceStat, ...]
    equity_curve: tuple[tuple[str, Decimal], ...]


@dataclass(slots=True)
class _OpenPosition:
    opened_at: datetime
    direction: int
    entry_price: Decimal
    allocated_capital: Decimal
    regime: str
    time_bucket: str
    feature_scores: tuple[tuple[str, Decimal], ...]
    mfe_pct: Decimal = D(0)
    mae_pct: Decimal = D(0)


@dataclass(slots=True)
class _PendingRejected:
    at: datetime
    direction: int
    entry_price: Decimal
    reason: str
    allocated_capital: Decimal


class CausalBarAggregator:
    """Aggregate one-minute candles without seeing future bucket contents."""

    def __init__(self, timeframe_minutes: int) -> None:
        if timeframe_minutes not in {1, 5, 10, 15}:
            raise ValueError("unsupported Shadow Trader timeframe")
        self.timeframe_minutes = timeframe_minutes
        self._bucket: list[Candle] = []
        self._bucket_key: tuple[object, int] | None = None

    def feed(self, candle: Candle) -> Candle | None:
        if self.timeframe_minutes == 1:
            return candle
        local = candle.at.astimezone(INDIA_TIME)
        minute_index = local.hour * 60 + local.minute
        anchor = 9 * 60 + 15
        bucket_id = (minute_index - anchor) // self.timeframe_minutes
        key = (local.date(), bucket_id)

        if self._bucket_key is not None and key != self._bucket_key:
            completed = self._build()
            self._bucket = [candle]
            self._bucket_key = key
            return completed

        if self._bucket_key is None:
            self._bucket_key = key
        self._bucket.append(candle)

        offset = minute_index - anchor
        if offset >= 0 and offset % self.timeframe_minutes == self.timeframe_minutes - 1:
            completed = self._build()
            self._bucket = []
            self._bucket_key = None
            return completed
        return None

    def flush(self) -> Candle | None:
        if not self._bucket:
            return None
        completed = self._build()
        self._bucket = []
        self._bucket_key = None
        return completed

    def _build(self) -> Candle:
        rows = self._bucket
        first = rows[0]
        last = rows[-1]
        return Candle(
            at=last.at,
            open=first.open,
            high=max(item.high for item in rows),
            low=min(item.low for item in rows),
            close=last.close,
            volume=sum(int(item.volume or 0) for item in rows),
        )


def _pct(change: Decimal, base: Decimal) -> Decimal:
    if base == 0:
        return D(0)
    return change / base * D(100)


def _time_bucket(at: datetime) -> str:
    local = at.astimezone(INDIA_TIME).time()
    if local < time(10, 0):
        return "09:15–10:00"
    if local < time(11, 30):
        return "10:00–11:30"
    if local < time(13, 30):
        return "11:30–13:30"
    if local < time(14, 30):
        return "13:30–14:30"
    return "14:30–15:30"


def _regime(candles: Sequence[Candle]) -> str:
    if len(candles) < 10:
        return "INSUFFICIENT"
    window = candles[-20:]
    start = window[0].close
    end = window[-1].close
    move = _pct(end - start, start)
    ranges = [
        _pct(item.high - item.low, item.close)
        for item in window if item.close > 0
    ]
    average_range = (
        D(0) if not ranges else sum(ranges, D(0)) / D(len(ranges))
    )
    if average_range >= D("0.35"):
        return "HIGH_VOLATILITY"
    if move >= D("0.30"):
        return "TRENDING_UP"
    if move <= D("-0.30"):
        return "TRENDING_DOWN"
    return "RANGE"


def _derived_scores(candles: Sequence[Candle]) -> dict[str, Decimal]:
    scores: dict[str, Decimal] = {}
    if len(candles) >= 2:
        current = candles[-1]
        previous = candles[-2]
        ret = _pct(current.close - previous.close, previous.close)
        scores["NIFTY price / structure"] = max(D("-1"), min(D("1"), ret / D("0.15")))
    if len(candles) >= 6:
        current = candles[-1].close
        past = candles[-6].close
        momentum = _pct(current - past, past)
        scores["Momentum / volatility"] = max(
            D("-1"), min(D("1"), momentum / D("0.40"))
        )
    return scores


def _slice_stats(trades: Sequence[StreamTrade], attr: str) -> tuple[SliceStat, ...]:
    groups: dict[str, list[StreamTrade]] = {}
    for trade in trades:
        groups.setdefault(str(getattr(trade, attr)), []).append(trade)
    rows: list[SliceStat] = []
    for key in sorted(groups):
        items = groups[key]
        returns = [item.net_return_pct for item in items]
        wins = sum(1 for value in returns if value > 0)
        losses = sum(1 for value in returns if value < 0)
        positive = sum((value for value in returns if value > 0), D(0))
        negative = abs(sum((value for value in returns if value < 0), D(0)))
        rows.append(
            SliceStat(
                key=key,
                trades=len(items),
                wins=wins,
                losses=losses,
                average_return_pct=(
                    None if not returns else sum(returns, D(0)) / D(len(returns))
                ),
                net_pnl=sum((item.paper_pnl for item in items), D(0)),
                profit_factor=None if negative == 0 else positive / negative,
            )
        )
    return tuple(rows)


class CausalFrozenEngine:
    """One frozen timeframe engine consuming market data in chronological order."""

    def __init__(
        self,
        spec: FrozenEngineSpec,
        config: ShadowReplayConfig,
        *,
        timeline: HistoricalFeatureTimeline | None = None,
    ) -> None:
        self.spec = spec
        self.config = config
        self.timeline = timeline or HistoricalFeatureTimeline()
        self.execution = execution_adapter(config.execution_mode)
        self.aggregator = CausalBarAggregator(spec.timeframe_minutes)
        self.history: list[Candle] = []
        self.position: _OpenPosition | None = None
        self.pending_rejected: list[_PendingRejected] = []
        self.trades: list[StreamTrade] = []
        self.rejected: list[StreamRejectedSignal] = []
        self.balance = config.starting_capital
        self.peak = self.balance
        self.max_drawdown = D(0)
        self.max_drawdown_pct = D(0)
        self.equity_curve: list[tuple[str, Decimal]] = []

    def seed(self, one_minute_candles: Sequence[Candle]) -> None:
        """Warm detector state with development candles without opening trades."""

        for candle in sorted(one_minute_candles, key=lambda item: item.at):
            bar = self.aggregator.feed(candle)
            if bar is not None:
                self._append_history(bar)
        flushed = self.aggregator.flush()
        if flushed is not None:
            self._append_history(flushed)

    def consume(self, candle: Candle) -> None:
        """Consume exactly one new one-minute candle."""

        self._mark_position(candle)
        self._settle_rejected(candle)
        if self.position is not None:
            due = self.position.opened_at + timedelta(minutes=self.spec.hold_minutes)
            if candle.at >= due:
                self._close_position(candle, "TIME_EXIT")

        bar = self.aggregator.feed(candle)
        if bar is None:
            return
        self._append_history(bar)
        direction = detect_strategy_signal(self.spec.strategy_id, self.history)
        if direction is None:
            return

        snapshot = self._feature_snapshot(bar.at)
        local_at = bar.at.astimezone(INDIA_TIME)
        market_close = datetime.combine(
            local_at.date(),
            time(15, 30),
            INDIA_TIME,
        )
        rejection = None
        if bar.at + timedelta(minutes=self.spec.hold_minutes) > market_close:
            rejection = "insufficient session time for hold horizon"
        if rejection is None:
            rejection = self._gate(direction, snapshot)
        if rejection is None and self.position is not None:
            rejection = "position already open in this timeframe trader"

        if rejection is not None:
            allocated = self.balance * self.config.allocation_pct / D(100)
            self.pending_rejected.append(
                _PendingRejected(
                    at=bar.at,
                    direction=direction,
                    entry_price=bar.close,
                    reason=rejection,
                    allocated_capital=allocated,
                )
            )
            return

        feature_scores = tuple(snapshot.scores)
        self.position = _OpenPosition(
            opened_at=bar.at,
            direction=direction,
            entry_price=bar.close,
            allocated_capital=self.balance * self.config.allocation_pct / D(100),
            regime=_regime(self.history),
            time_bucket=_time_bucket(bar.at),
            feature_scores=feature_scores,
        )

    def finish(self, last_candle: Candle | None = None) -> None:
        flushed = self.aggregator.flush()
        if flushed is not None:
            self._append_history(flushed)
        if last_candle is not None:
            self._mark_position(last_candle)
            self._settle_rejected(last_candle)
            if self.position is not None:
                self._close_position(last_candle, "SESSION_END")
            # Rejected signals whose evaluation horizon extends beyond market
            # close remain explicitly unevaluated; they are never rolled into
            # the next trading day.
            for pending in self.pending_rejected:
                self.rejected.append(
                    StreamRejectedSignal(
                        timeframe_minutes=self.spec.timeframe_minutes,
                        engine_id=self.spec.engine_id,
                        at=pending.at.isoformat(),
                        direction=(
                            "CALL / LONG"
                            if pending.direction > 0
                            else "PUT / SHORT"
                        ),
                        reason=pending.reason,
                        hypothetical_return_pct=None,
                        hypothetical_pnl=None,
                        classification="UNEVALUATED_SESSION_END",
                    )
                )
            self.pending_rejected = []

    def report(self) -> StreamEngineReport:
        returns = [item.net_return_pct for item in self.trades]
        wins = sum(1 for value in returns if value > 0)
        losses = sum(1 for value in returns if value < 0)
        flats = sum(1 for value in returns if value == 0)
        positive = sum((value for value in returns if value > 0), D(0))
        negative = abs(sum((value for value in returns if value < 0), D(0)))
        streak = longest = 0
        for value in returns:
            if value < 0:
                streak += 1
                longest = max(longest, streak)
            else:
                streak = 0
        net_pnl = self.balance - self.config.starting_capital
        summary = StreamAccountSummary(
            starting_capital=self.config.starting_capital,
            ending_capital=self.balance,
            net_pnl=net_pnl,
            return_pct=net_pnl / self.config.starting_capital * D(100),
            max_drawdown=self.max_drawdown,
            max_drawdown_pct=self.max_drawdown_pct,
            trades=len(returns),
            wins=wins,
            losses=losses,
            flats=flats,
            profit_factor=None if negative == 0 else positive / negative,
            average_return_pct=(
                None if not returns else sum(returns, D(0)) / D(len(returns))
            ),
            max_losing_streak=longest,
        )
        return StreamEngineReport(
            spec=self.spec,
            account=summary,
            trades=tuple(self.trades),
            rejected_signals=tuple(self.rejected),
            regime_stats=_slice_stats(self.trades, "regime"),
            time_stats=_slice_stats(self.trades, "time_bucket"),
            equity_curve=tuple(self.equity_curve),
        )

    def _append_history(self, bar: Candle) -> None:
        self.history.append(bar)
        days = sorted({item.at.astimezone(INDIA_TIME).date() for item in self.history})
        if len(days) > 2:
            keep = set(days[-2:])
            self.history = [
                item for item in self.history
                if item.at.astimezone(INDIA_TIME).date() in keep
            ]

    def _feature_snapshot(self, at: datetime) -> FeatureSnapshot:
        external = self.timeline.snapshot(at, self.spec.enabled_families)
        derived = _derived_scores(self.history)
        merged = dict(external.scores)
        for family, score in derived.items():
            if family in self.spec.enabled_families:
                merged[family] = score
        return FeatureSnapshot(
            at=at,
            scores=tuple(sorted(merged.items())),
            labels=external.labels,
            high_impact_event_active=external.high_impact_event_active,
        )

    def _gate(self, direction: int, snapshot: FeatureSnapshot) -> str | None:
        if (
            snapshot.high_impact_event_active
            and any(
                family in self.spec.enabled_families
                for family in (
                    "Volatility / macro context",
                    "News / regime / time",
                )
            )
        ):
            return "high-impact event risk window"
        directional = [score * D(direction) for _family, score in snapshot.scores]
        if directional:
            confirmation = sum(directional, D(0)) / D(len(directional))
            if confirmation <= D("-0.35"):
                return "multi-family feature contradiction"
        return None

    def _mark_position(self, candle: Candle) -> None:
        position = self.position
        if position is None:
            return
        if position.direction > 0:
            favorable = _pct(candle.high - position.entry_price, position.entry_price)
            adverse = _pct(candle.low - position.entry_price, position.entry_price)
        else:
            favorable = _pct(position.entry_price - candle.low, position.entry_price)
            adverse = _pct(position.entry_price - candle.high, position.entry_price)
        position.mfe_pct = max(position.mfe_pct, favorable)
        position.mae_pct = min(position.mae_pct, adverse)

    def _close_position(self, candle: Candle, reason: str) -> None:
        position = self.position
        if position is None:
            return
        execution = self.execution.evaluate(
            entry_price=position.entry_price,
            exit_price=candle.close,
            direction=position.direction,
            allocated_capital=position.allocated_capital,
            friction_bps=self.config.friction_bps,
        )
        gross = execution.gross_return_pct
        net = execution.net_return_pct
        pnl = execution.paper_pnl
        self.balance += pnl
        self.peak = max(self.peak, self.balance)
        drawdown = self.peak - self.balance
        self.max_drawdown = max(self.max_drawdown, drawdown)
        if self.peak > 0:
            self.max_drawdown_pct = max(
                self.max_drawdown_pct,
                drawdown / self.peak * D(100),
            )
        result = "WIN" if net > 0 else "LOSS" if net < 0 else "FLAT"
        self.trades.append(
            StreamTrade(
                timeframe_minutes=self.spec.timeframe_minutes,
                engine_id=self.spec.engine_id,
                strategy_name=self.spec.strategy_name,
                opened_at=position.opened_at.isoformat(),
                closed_at=candle.at.isoformat(),
                direction="CALL / LONG" if position.direction > 0 else "PUT / SHORT",
                entry_underlying=position.entry_price,
                exit_underlying=candle.close,
                gross_return_pct=gross,
                net_return_pct=net,
                paper_pnl=pnl,
                balance_after=self.balance,
                mfe_pct=position.mfe_pct,
                mae_pct=position.mae_pct,
                regime=position.regime,
                time_bucket=position.time_bucket,
                feature_scores=position.feature_scores,
                exit_reason=reason,
                result=result,
            )
        )
        self.equity_curve.append((candle.at.isoformat(), self.balance))
        self.position = None

    def _settle_rejected(self, candle: Candle) -> None:
        remaining: list[_PendingRejected] = []
        for pending in self.pending_rejected:
            due = pending.at + timedelta(minutes=self.spec.hold_minutes)
            if candle.at < due:
                remaining.append(pending)
                continue
            execution = self.execution.evaluate(
                entry_price=pending.entry_price,
                exit_price=candle.close,
                direction=pending.direction,
                allocated_capital=pending.allocated_capital,
                friction_bps=self.config.friction_bps,
            )
            net = execution.net_return_pct
            pnl = execution.paper_pnl
            classification = (
                "MISSED_WINNER" if net > 0
                else "GOOD_REJECTION" if net < 0
                else "NEUTRAL"
            )
            self.rejected.append(
                StreamRejectedSignal(
                    timeframe_minutes=self.spec.timeframe_minutes,
                    engine_id=self.spec.engine_id,
                    at=pending.at.isoformat(),
                    direction="CALL / LONG" if pending.direction > 0 else "PUT / SHORT",
                    reason=pending.reason,
                    hypothetical_return_pct=net,
                    hypothetical_pnl=pnl,
                    classification=classification,
                )
            )
        self.pending_rejected = remaining


def run_stream_engine(
    *,
    blind_candles: Sequence[Candle],
    development_seed_candles: Sequence[Candle],
    spec: FrozenEngineSpec,
    config: ShadowReplayConfig,
    timeline: HistoricalFeatureTimeline | None = None,
) -> StreamEngineReport:
    """Run one frozen engine over blind candles in strict timestamp order."""

    engine = CausalFrozenEngine(spec, config, timeline=timeline)
    engine.seed(development_seed_candles)
    ordered = tuple(sorted(blind_candles, key=lambda item: item.at))
    previous_day = None
    last_candle = None
    for candle in ordered:
        day = candle.at.astimezone(INDIA_TIME).date()
        if previous_day is not None and day != previous_day and last_candle is not None:
            engine.finish(last_candle)
        engine.consume(candle)
        previous_day = day
        last_candle = candle
    if last_candle is not None:
        engine.finish(last_candle)
    return engine.report()
