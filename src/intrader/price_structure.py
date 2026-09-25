"""Deterministic price-structure measurements for Intrader Phase 2."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Sequence
from zoneinfo import ZoneInfo

from intrader.historical import Candle


class PriceStructureError(Exception):
    """Price-structure inputs are incomplete or internally invalid."""


@dataclass(frozen=True, slots=True)
class PriceStructureSnapshot:
    at: datetime
    spot_close: Decimal
    ema9: Decimal
    ema20: Decimal
    rsi14: Decimal
    atr14: Decimal
    candle_body: Decimal
    upper_wick: Decimal
    lower_wick: Decimal
    opening_range_high: Decimal
    opening_range_low: Decimal
    previous_session_high: Decimal | None
    previous_session_low: Decimal | None
    future_close: Decimal | None
    future_vwap: Decimal | None
    relative_volume: Decimal | None


def _validate_candles(candles: Sequence[Candle], *, name: str) -> None:
    if not candles:
        raise PriceStructureError(f"{name} candles unavailable")
    previous_at: datetime | None = None
    for candle in candles:
        if candle.at.tzinfo is None:
            raise PriceStructureError(f"{name} timestamp must be timezone aware")
        if previous_at is not None and candle.at <= previous_at:
            raise PriceStructureError(f"{name} candles must be strictly increasing")
        previous_at = candle.at
        prices = (candle.open, candle.high, candle.low, candle.close)
        if any(price <= 0 or not price.is_finite() for price in prices):
            raise PriceStructureError(f"{name} price invalid")
        if candle.high < max(candle.open, candle.close, candle.low):
            raise PriceStructureError(f"{name} OHLC invalid")
        if candle.low > min(candle.open, candle.close, candle.high):
            raise PriceStructureError(f"{name} OHLC invalid")
        if candle.volume < 0:
            raise PriceStructureError(f"{name} volume invalid")


def ema(values: Sequence[Decimal], period: int) -> Decimal:
    """Return the latest EMA using an SMA seed and standard alpha."""

    if period <= 0 or len(values) < period:
        raise PriceStructureError("EMA history insufficient")
    if any(not value.is_finite() for value in values):
        raise PriceStructureError("EMA input invalid")

    period_decimal = Decimal(period)
    current = sum(values[:period], Decimal(0)) / period_decimal
    alpha = Decimal(2) / Decimal(period + 1)
    one_minus_alpha = Decimal(1) - alpha
    for value in values[period:]:
        current = (value * alpha) + (current * one_minus_alpha)
    return current


def rsi_wilder(values: Sequence[Decimal], period: int = 14) -> Decimal:
    """Return Wilder RSI for the latest close."""

    if period <= 0 or len(values) < period + 1:
        raise PriceStructureError("RSI history insufficient")
    changes = [values[index] - values[index - 1] for index in range(1, len(values))]
    gains = [max(change, Decimal(0)) for change in changes]
    losses = [max(-change, Decimal(0)) for change in changes]

    p = Decimal(period)
    average_gain = sum(gains[:period], Decimal(0)) / p
    average_loss = sum(losses[:period], Decimal(0)) / p
    for gain, loss in zip(gains[period:], losses[period:]):
        average_gain = ((average_gain * Decimal(period - 1)) + gain) / p
        average_loss = ((average_loss * Decimal(period - 1)) + loss) / p

    if average_loss == 0:
        return Decimal(100) if average_gain > 0 else Decimal(50)
    if average_gain == 0:
        return Decimal(0)
    relative_strength = average_gain / average_loss
    return Decimal(100) - (Decimal(100) / (Decimal(1) + relative_strength))


def atr_wilder(candles: Sequence[Candle], period: int = 14) -> Decimal:
    """Return Wilder ATR using close-to-close true range."""

    _validate_candles(candles, name="ATR")
    if period <= 0 or len(candles) < period + 1:
        raise PriceStructureError("ATR history insufficient")

    true_ranges: list[Decimal] = []
    for previous, current in zip(candles, candles[1:]):
        true_ranges.append(
            max(
                current.high - current.low,
                abs(current.high - previous.close),
                abs(current.low - previous.close),
            )
        )

    p = Decimal(period)
    current_atr = sum(true_ranges[:period], Decimal(0)) / p
    for true_range in true_ranges[period:]:
        current_atr = (
            (current_atr * Decimal(period - 1)) + true_range
        ) / p
    return current_atr


def opening_range(
    candles: Sequence[Candle],
    market_open: datetime,
    minutes: int = 15,
) -> tuple[Decimal, Decimal]:
    """Return high/low for a complete one-minute opening range."""

    _validate_candles(candles, name="opening range")
    if market_open.tzinfo is None or minutes <= 0:
        raise PriceStructureError("opening range configuration invalid")

    zone = market_open.tzinfo
    end = market_open + timedelta(minutes=minutes)
    selected = [
        candle
        for candle in candles
        if market_open <= candle.at.astimezone(zone) < end
    ]
    observed_minutes = {
        candle.at.astimezone(zone).replace(second=0, microsecond=0)
        for candle in selected
    }
    expected_minutes = {
        (market_open + timedelta(minutes=offset)).replace(second=0, microsecond=0)
        for offset in range(minutes)
    }
    if observed_minutes != expected_minutes:
        raise PriceStructureError("opening range incomplete")
    return (
        max(candle.high for candle in selected),
        min(candle.low for candle in selected),
    )


def previous_session_levels(
    candles: Sequence[Candle],
) -> tuple[Decimal, Decimal]:
    """Return the supplied prior session's high and low."""

    _validate_candles(candles, name="previous session")
    return (
        max(candle.high for candle in candles),
        min(candle.low for candle in candles),
    )


def futures_vwap(candles: Sequence[Candle]) -> Decimal:
    """Return cumulative futures VWAP using typical price and traded volume."""

    _validate_candles(candles, name="future")
    total_volume = sum((candle.volume for candle in candles), 0)
    if total_volume <= 0:
        raise PriceStructureError("future VWAP volume unavailable")

    weighted = sum(
        (
            ((candle.high + candle.low + candle.close) / Decimal(3))
            * Decimal(candle.volume)
            for candle in candles
        ),
        Decimal(0),
    )
    return weighted / Decimal(total_volume)


def cumulative_relative_volume(
    current_session: Sequence[Candle],
    prior_sessions: Sequence[Sequence[Candle]],
    at: datetime,
    *,
    timezone_name: str = "Asia/Kolkata",
) -> Decimal:
    """Compare cumulative futures volume to prior sessions at the same minute."""

    _validate_candles(current_session, name="current future")
    if at.tzinfo is None:
        raise PriceStructureError("relative-volume timestamp invalid")
    zone = ZoneInfo(timezone_name)
    cutoff = at.astimezone(zone).time().replace(second=0, microsecond=0)

    current_volume = sum(
        candle.volume
        for candle in current_session
        if candle.at.astimezone(zone).time().replace(second=0, microsecond=0) <= cutoff
    )

    baselines: list[int] = []
    for session in prior_sessions:
        if not session:
            continue
        _validate_candles(session, name="relative-volume baseline")
        cumulative = sum(
            candle.volume
            for candle in session
            if candle.at.astimezone(zone).time().replace(second=0, microsecond=0) <= cutoff
        )
        if cumulative > 0:
            baselines.append(cumulative)

    if not baselines:
        raise PriceStructureError("relative-volume baseline unavailable")
    average_baseline = Decimal(sum(baselines)) / Decimal(len(baselines))
    return Decimal(current_volume) / average_baseline


def build_price_structure_snapshot(
    spot_candles: Sequence[Candle],
    future_candles: Sequence[Candle],
    *,
    market_open: datetime,
    at: datetime | None = None,
    previous_spot_candles: Sequence[Candle] | None = None,
    future_volume_baselines: Sequence[Sequence[Candle]] = (),
    opening_range_minutes: int = 15,
) -> PriceStructureSnapshot:
    """Build one raw, non-directional price-structure snapshot."""

    _validate_candles(spot_candles, name="spot")
    if at is None:
        at = spot_candles[-1].at
    if at.tzinfo is None:
        raise PriceStructureError("snapshot timestamp invalid")

    spot = [candle for candle in spot_candles if candle.at <= at]
    if len(spot) < 20:
        raise PriceStructureError("spot history insufficient")
    _validate_candles(spot, name="spot")

    closes = [candle.close for candle in spot]
    latest = spot[-1]
    ema9_value = ema(closes, 9)
    ema20_value = ema(closes, 20)
    rsi14_value = rsi_wilder(closes, 14)
    atr14_value = atr_wilder(spot, 14)
    opening_high, opening_low = opening_range(
        spot, market_open, opening_range_minutes
    )

    body = latest.close - latest.open
    upper_wick = latest.high - max(latest.open, latest.close)
    lower_wick = min(latest.open, latest.close) - latest.low

    previous_high: Decimal | None = None
    previous_low: Decimal | None = None
    if previous_spot_candles:
        previous_high, previous_low = previous_session_levels(
            previous_spot_candles
        )

    future = [candle for candle in future_candles if candle.at <= at]
    future_close: Decimal | None = None
    vwap_value: Decimal | None = None
    relative_volume_value: Decimal | None = None
    if future:
        _validate_candles(future, name="future")
        future_close = future[-1].close
        try:
            vwap_value = futures_vwap(future)
        except PriceStructureError:
            vwap_value = None
        if future_volume_baselines:
            try:
                relative_volume_value = cumulative_relative_volume(
                    future,
                    future_volume_baselines,
                    at,
                )
            except PriceStructureError:
                relative_volume_value = None

    return PriceStructureSnapshot(
        at=latest.at,
        spot_close=latest.close,
        ema9=ema9_value,
        ema20=ema20_value,
        rsi14=rsi14_value,
        atr14=atr14_value,
        candle_body=body,
        upper_wick=upper_wick,
        lower_wick=lower_wick,
        opening_range_high=opening_high,
        opening_range_low=opening_low,
        previous_session_high=previous_high,
        previous_session_low=previous_low,
        future_close=future_close,
        future_vwap=vwap_value,
        relative_volume=relative_volume_value,
    )
