"""Standalone historical Strategy Lab.

The rules in this module are research hypotheses only. They do not feed the
Market Brain, live decision engine, shadow trader, calibration or promotion
logic. Book mappings are based on broadly known concepts and are not a
substitute for edition-specific source extraction.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from decimal import Decimal
from math import sqrt
from typing import Callable, Sequence

from intrader.historical import Candle, INDIA_TIME
from intrader.records import DecisionRecord


D = Decimal


@dataclass(frozen=True, slots=True)
class StrategyDefinition:
    strategy_id: str
    source: str
    name: str
    description: str
    direction_scope: str


@dataclass(frozen=True, slots=True)
class StrategyOccurrence:
    strategy_id: str
    at: datetime
    direction: int
    entry_price: Decimal
    regime: str | None
    return_5m: Decimal | None
    return_15m: Decimal | None
    return_30m: Decimal | None
    mfe_30m: Decimal | None
    mae_30m: Decimal | None


@dataclass(frozen=True, slots=True)
class StrategyPerformance:
    definition: StrategyDefinition
    signals: int
    bullish_signals: int
    bearish_signals: int
    hit_rate_5m: Decimal | None
    hit_rate_15m: Decimal | None
    hit_rate_30m: Decimal | None
    avg_return_5m: Decimal | None
    avg_return_15m: Decimal | None
    avg_return_30m: Decimal | None
    avg_mfe_30m: Decimal | None
    avg_mae_30m: Decimal | None
    sample_label: str
    occurrences: tuple[StrategyOccurrence, ...]


@dataclass(frozen=True, slots=True)
class StrategyLabSnapshot:
    start: datetime
    end: datetime
    candle_count: int
    session_count: int
    strategies: tuple[StrategyPerformance, ...]
    notes: tuple[str, ...]


STRATEGIES = (
    StrategyDefinition(
        "NISON_BULLISH_ENGULFING",
        "Steve Nison / Candlestick",
        "Bullish Engulfing",
        "Bullish candle body engulfs the prior bearish body.",
        "BULLISH",
    ),
    StrategyDefinition(
        "NISON_BEARISH_ENGULFING",
        "Steve Nison / Candlestick",
        "Bearish Engulfing",
        "Bearish candle body engulfs the prior bullish body.",
        "BEARISH",
    ),
    StrategyDefinition(
        "NISON_HAMMER",
        "Steve Nison / Candlestick",
        "Hammer After Decline",
        "Hammer-shaped candle after short-term downward price context.",
        "BULLISH",
    ),
    StrategyDefinition(
        "NISON_SHOOTING_STAR",
        "Steve Nison / Candlestick",
        "Shooting Star After Rise",
        "Shooting-star candle after short-term upward price context.",
        "BEARISH",
    ),
    StrategyDefinition(
        "GUJRAL_EMA_PULLBACK",
        "Ashwani Gujral / Intraday",
        "EMA Trend Pullback",
        "Simplified 9/20 EMA trend-pullback continuation hypothesis.",
        "BOTH",
    ),
    StrategyDefinition(
        "GUJRAL_OPENING_RANGE_BREAKOUT",
        "Ashwani Gujral / Intraday",
        "15-Min Opening Range Breakout",
        "Break above/below the first 15-minute session range.",
        "BOTH",
    ),
    StrategyDefinition(
        "GUJRAL_CLASSIC_PIVOT_BREAKOUT",
        "Ashwani Gujral / Intraday",
        "Classic Pivot R1/S1 Breakout",
        "Break of classic R1/S1 levels derived from the previous session.",
        "BOTH",
    ),
    StrategyDefinition(
        "CARTER_SQUEEZE_RELEASE",
        "John Carter / Mastering the Trade",
        "Volatility Squeeze Release",
        "Simplified Bollinger-inside-Keltner compression followed by release.",
        "BOTH",
    ),
)


def _pct(change: Decimal, base: Decimal) -> Decimal:
    if base == 0:
        return D(0)
    return change / base * D(100)


def _ema(values: Sequence[Decimal], period: int) -> list[Decimal | None]:
    result: list[Decimal | None] = [None] * len(values)
    if len(values) < period:
        return result
    seed = sum(values[:period], D(0)) / D(period)
    result[period - 1] = seed
    alpha = D(2) / D(period + 1)
    previous = seed
    for index in range(period, len(values)):
        previous = values[index] * alpha + previous * (D(1) - alpha)
        result[index] = previous
    return result


def _sma(values: Sequence[Decimal], period: int) -> list[Decimal | None]:
    result: list[Decimal | None] = [None] * len(values)
    if len(values) < period:
        return result
    total = sum(values[:period], D(0))
    result[period - 1] = total / D(period)
    for index in range(period, len(values)):
        total += values[index] - values[index - period]
        result[index] = total / D(period)
    return result


def _rolling_std(values: Sequence[Decimal], period: int) -> list[Decimal | None]:
    result: list[Decimal | None] = [None] * len(values)
    for index in range(period - 1, len(values)):
        window = values[index - period + 1 : index + 1]
        mean = sum(window, D(0)) / D(period)
        variance = sum((value - mean) ** 2 for value in window) / D(period)
        result[index] = D(str(sqrt(float(variance))))
    return result


def _atr(candles: Sequence[Candle], period: int) -> list[Decimal | None]:
    trs: list[Decimal] = []
    previous_close: Decimal | None = None
    for candle in candles:
        if previous_close is None:
            tr = candle.high - candle.low
        else:
            tr = max(
                candle.high - candle.low,
                abs(candle.high - previous_close),
                abs(candle.low - previous_close),
            )
        trs.append(tr)
        previous_close = candle.close
    return _sma(trs, period)


def _session_groups(candles: Sequence[Candle]) -> dict:
    groups: dict = {}
    for index, candle in enumerate(candles):
        day = candle.at.astimezone(INDIA_TIME).date()
        groups.setdefault(day, []).append(index)
    return groups


def _nearest_regime(
    at: datetime,
    decisions: Sequence[DecisionRecord],
) -> str | None:
    eligible = [
        decision
        for decision in decisions
        if decision.decided_at <= at
        and at - decision.decided_at <= timedelta(minutes=10)
    ]
    if not eligible:
        return None
    return max(eligible, key=lambda decision: decision.decided_at).regime


def _forward_candle(
    candles: Sequence[Candle],
    index: int,
    minutes: int,
) -> Candle | None:
    signal = candles[index]
    target = signal.at + timedelta(minutes=minutes)
    day = signal.at.astimezone(INDIA_TIME).date()
    for candidate in candles[index + 1 : index + minutes + 4]:
        if candidate.at.astimezone(INDIA_TIME).date() != day:
            return None
        if candidate.at >= target:
            if candidate.at - target <= timedelta(minutes=2):
                return candidate
            return None
    return None


def _signed_return(
    future: Candle | None,
    entry: Decimal,
    direction: int,
) -> Decimal | None:
    if future is None:
        return None
    return _pct(future.close - entry, entry) * D(direction)


def _excursion_30m(
    candles: Sequence[Candle],
    index: int,
    direction: int,
) -> tuple[Decimal | None, Decimal | None]:
    signal = candles[index]
    day = signal.at.astimezone(INDIA_TIME).date()
    end = signal.at + timedelta(minutes=30)
    future = [
        candle
        for candle in candles[index + 1 : index + 34]
        if candle.at.astimezone(INDIA_TIME).date() == day
        and candle.at <= end
    ]
    if not future:
        return None, None
    entry = signal.close
    if direction > 0:
        mfe = _pct(max(c.high for c in future) - entry, entry)
        mae = _pct(min(c.low for c in future) - entry, entry)
    else:
        mfe = _pct(entry - min(c.low for c in future), entry)
        mae = _pct(entry - max(c.high for c in future), entry)
    return mfe, mae


def _engulfing(candles: Sequence[Candle], bullish: bool) -> list[tuple[int, int]]:
    signals: list[tuple[int, int]] = []
    for index in range(1, len(candles)):
        previous = candles[index - 1]
        current = candles[index]
        if previous.at.astimezone(INDIA_TIME).date() != current.at.astimezone(INDIA_TIME).date():
            continue
        if bullish:
            matches = (
                previous.close < previous.open
                and current.close > current.open
                and current.open <= previous.close
                and current.close >= previous.open
            )
            if matches:
                signals.append((index, 1))
        else:
            matches = (
                previous.close > previous.open
                and current.close < current.open
                and current.open >= previous.close
                and current.close <= previous.open
            )
            if matches:
                signals.append((index, -1))
    return signals


def _hammer_or_star(
    candles: Sequence[Candle],
    bullish: bool,
) -> list[tuple[int, int]]:
    signals: list[tuple[int, int]] = []
    for index in range(3, len(candles)):
        current = candles[index]
        prior = candles[index - 3 : index]
        if any(
            candle.at.astimezone(INDIA_TIME).date()
            != current.at.astimezone(INDIA_TIME).date()
            for candle in prior
        ):
            continue
        body = abs(current.close - current.open)
        full_range = current.high - current.low
        if full_range <= 0:
            continue
        body_floor = max(body, full_range * D("0.05"))
        upper = current.high - max(current.open, current.close)
        lower = min(current.open, current.close) - current.low
        if bullish:
            context = prior[-1].close < prior[0].close
            shape = (
                body / full_range <= D("0.40")
                and lower >= body_floor * D(2)
                and upper <= body_floor
            )
            if context and shape:
                signals.append((index, 1))
        else:
            context = prior[-1].close > prior[0].close
            shape = (
                body / full_range <= D("0.40")
                and upper >= body_floor * D(2)
                and lower <= body_floor
            )
            if context and shape:
                signals.append((index, -1))
    return signals


def _ema_pullback(candles: Sequence[Candle]) -> list[tuple[int, int]]:
    closes = [candle.close for candle in candles]
    ema9 = _ema(closes, 9)
    ema20 = _ema(closes, 20)
    signals: list[tuple[int, int]] = []
    for index in range(20, len(candles)):
        previous = candles[index - 1]
        current = candles[index]
        if previous.at.astimezone(INDIA_TIME).date() != current.at.astimezone(INDIA_TIME).date():
            continue
        if None in (ema9[index], ema20[index], ema9[index - 1], ema20[index - 1]):
            continue
        if (
            ema9[index] > ema20[index]
            and previous.close <= ema9[index - 1]
            and current.close > ema9[index]
            and current.close > current.open
        ):
            signals.append((index, 1))
        elif (
            ema9[index] < ema20[index]
            and previous.close >= ema9[index - 1]
            and current.close < ema9[index]
            and current.close < current.open
        ):
            signals.append((index, -1))
    return signals


def _opening_range_breakout(candles: Sequence[Candle]) -> list[tuple[int, int]]:
    signals: list[tuple[int, int]] = []
    for _day, indices in _session_groups(candles).items():
        opening = [
            index
            for index in indices
            if time(9, 15)
            <= candles[index].at.astimezone(INDIA_TIME).time()
            < time(9, 30)
        ]
        if len(opening) < 5:
            continue
        high = max(candles[index].high for index in opening)
        low = min(candles[index].low for index in opening)
        long_seen = short_seen = False
        for index in indices:
            local_time = candles[index].at.astimezone(INDIA_TIME).time()
            if local_time < time(9, 30) or index == 0:
                continue
            previous = candles[index - 1]
            current = candles[index]
            if not long_seen and previous.close <= high < current.close:
                signals.append((index, 1))
                long_seen = True
            if not short_seen and previous.close >= low > current.close:
                signals.append((index, -1))
                short_seen = True
    return signals


def _classic_pivot_breakout(candles: Sequence[Candle]) -> list[tuple[int, int]]:
    groups = _session_groups(candles)
    days = sorted(groups)
    signals: list[tuple[int, int]] = []
    for day_index in range(1, len(days)):
        previous_indices = groups[days[day_index - 1]]
        current_indices = groups[days[day_index]]
        high = max(candles[index].high for index in previous_indices)
        low = min(candles[index].low for index in previous_indices)
        close = candles[previous_indices[-1]].close
        pivot = (high + low + close) / D(3)
        r1 = D(2) * pivot - low
        s1 = D(2) * pivot - high
        long_seen = short_seen = False
        for index in current_indices:
            if index == 0:
                continue
            previous = candles[index - 1]
            current = candles[index]
            if not long_seen and previous.close <= r1 < current.close:
                signals.append((index, 1))
                long_seen = True
            if not short_seen and previous.close >= s1 > current.close:
                signals.append((index, -1))
                short_seen = True
    return signals


def _squeeze_release(candles: Sequence[Candle]) -> list[tuple[int, int]]:
    closes = [candle.close for candle in candles]
    sma20 = _sma(closes, 20)
    ema20 = _ema(closes, 20)
    std20 = _rolling_std(closes, 20)
    atr20 = _atr(candles, 20)
    squeeze: list[bool] = [False] * len(candles)
    for index in range(len(candles)):
        if None in (sma20[index], ema20[index], std20[index], atr20[index]):
            continue
        bb_upper = sma20[index] + D(2) * std20[index]
        bb_lower = sma20[index] - D(2) * std20[index]
        kc_upper = ema20[index] + D("1.5") * atr20[index]
        kc_lower = ema20[index] - D("1.5") * atr20[index]
        squeeze[index] = bb_upper < kc_upper and bb_lower > kc_lower

    signals: list[tuple[int, int]] = []
    for index in range(20, len(candles)):
        if candles[index - 1].at.astimezone(INDIA_TIME).date() != candles[index].at.astimezone(INDIA_TIME).date():
            continue
        prior_window = squeeze[max(0, index - 4) : index]
        if not prior_window or not any(prior_window) or squeeze[index]:
            continue
        if sma20[index] is None:
            continue
        direction = 1 if candles[index].close > sma20[index] else -1
        signals.append((index, direction))
    return signals


_DETECTORS: dict[str, Callable[[Sequence[Candle]], list[tuple[int, int]]]] = {
    "NISON_BULLISH_ENGULFING": lambda candles: _engulfing(candles, True),
    "NISON_BEARISH_ENGULFING": lambda candles: _engulfing(candles, False),
    "NISON_HAMMER": lambda candles: _hammer_or_star(candles, True),
    "NISON_SHOOTING_STAR": lambda candles: _hammer_or_star(candles, False),
    "GUJRAL_EMA_PULLBACK": _ema_pullback,
    "GUJRAL_OPENING_RANGE_BREAKOUT": _opening_range_breakout,
    "GUJRAL_CLASSIC_PIVOT_BREAKOUT": _classic_pivot_breakout,
    "CARTER_SQUEEZE_RELEASE": _squeeze_release,
}


def _average(values: Sequence[Decimal | None]) -> Decimal | None:
    usable = [value for value in values if value is not None]
    if not usable:
        return None
    return sum(usable, D(0)) / D(len(usable))


def _hit_rate(values: Sequence[Decimal | None]) -> Decimal | None:
    usable = [value for value in values if value is not None]
    if not usable:
        return None
    wins = sum(1 for value in usable if value > 0)
    return D(wins) / D(len(usable)) * D(100)


def _sample_label(count: int) -> str:
    if count == 0:
        return "NO SIGNALS"
    if count < 10:
        return "TINY SAMPLE"
    if count < 30:
        return "EARLY"
    if count < 100:
        return "DEVELOPING"
    return "BROADER SAMPLE"


def analyze_strategies(
    candles: Sequence[Candle],
    decisions: Sequence[DecisionRecord],
    start: datetime,
    end: datetime,
) -> StrategyLabSnapshot:
    """Backtest isolated hypotheses on historical NIFTY candles only."""

    if start.tzinfo is None or end.tzinfo is None or start >= end:
        raise ValueError("strategy analysis range invalid")
    if end - start > timedelta(days=30, minutes=1):
        raise ValueError("Strategy Lab is limited to 30 days")

    ordered = tuple(sorted(
        (
            candle
            for candle in candles
            if start <= candle.at.astimezone(start.tzinfo) <= end
        ),
        key=lambda candle: candle.at,
    ))
    sessions = len({
        candle.at.astimezone(INDIA_TIME).date() for candle in ordered
    })

    performances: list[StrategyPerformance] = []
    for definition in STRATEGIES:
        raw = _DETECTORS[definition.strategy_id](ordered)
        occurrences: list[StrategyOccurrence] = []
        for index, direction in raw:
            candle = ordered[index]
            entry = candle.close
            return_5 = _signed_return(
                _forward_candle(ordered, index, 5), entry, direction
            )
            return_15 = _signed_return(
                _forward_candle(ordered, index, 15), entry, direction
            )
            return_30 = _signed_return(
                _forward_candle(ordered, index, 30), entry, direction
            )
            mfe, mae = _excursion_30m(ordered, index, direction)
            occurrences.append(
                StrategyOccurrence(
                    strategy_id=definition.strategy_id,
                    at=candle.at,
                    direction=direction,
                    entry_price=entry,
                    regime=_nearest_regime(candle.at, decisions),
                    return_5m=return_5,
                    return_15m=return_15,
                    return_30m=return_30,
                    mfe_30m=mfe,
                    mae_30m=mae,
                )
            )

        performances.append(
            StrategyPerformance(
                definition=definition,
                signals=len(occurrences),
                bullish_signals=sum(1 for item in occurrences if item.direction > 0),
                bearish_signals=sum(1 for item in occurrences if item.direction < 0),
                hit_rate_5m=_hit_rate([item.return_5m for item in occurrences]),
                hit_rate_15m=_hit_rate([item.return_15m for item in occurrences]),
                hit_rate_30m=_hit_rate([item.return_30m for item in occurrences]),
                avg_return_5m=_average([item.return_5m for item in occurrences]),
                avg_return_15m=_average([item.return_15m for item in occurrences]),
                avg_return_30m=_average([item.return_30m for item in occurrences]),
                avg_mfe_30m=_average([item.mfe_30m for item in occurrences]),
                avg_mae_30m=_average([item.mae_30m for item in occurrences]),
                sample_label=_sample_label(len(occurrences)),
                occurrences=tuple(occurrences),
            )
        )

    notes = (
        "LAB ONLY: no Strategy Lab result is consumed by Intrader Mode or the Market Brain.",
        "Rules are book-inspired research hypotheses based on broadly known concepts; exact edition-specific rules require source verification.",
        "A positive hit rate does not by itself prove tradable edge; sample size, costs, regime stability and untouched validation still matter.",
        "Mark Douglas is treated as process/psychology guidance, not a candle-based predictive strategy in this version.",
    )
    return StrategyLabSnapshot(
        start=start,
        end=end,
        candle_count=len(ordered),
        session_count=sessions,
        strategies=tuple(performances),
        notes=notes,
    )
