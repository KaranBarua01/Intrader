from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from intrader.historical import Candle
from intrader.price_structure import (
    PriceStructureError,
    atr_wilder,
    build_price_structure_snapshot,
    cumulative_relative_volume,
    ema,
    futures_vwap,
    opening_range,
    previous_session_levels,
    rsi_wilder,
)


IST = ZoneInfo("Asia/Kolkata")
DAY = date(2026, 9, 28)
OPEN = datetime(2026, 9, 28, 9, 15, tzinfo=IST)


def _candle(
    minute: int,
    close: str,
    *,
    open_: str | None = None,
    high: str | None = None,
    low: str | None = None,
    volume: int = 100,
    day: date = DAY,
) -> Candle:
    at = datetime.combine(day, OPEN.timetz(), IST) + timedelta(minutes=minute)
    close_value = Decimal(close)
    open_value = Decimal(open_ if open_ is not None else close)
    high_value = Decimal(
        high if high is not None else str(max(open_value, close_value) + Decimal("1"))
    )
    low_value = Decimal(
        low if low is not None else str(min(open_value, close_value) - Decimal("1"))
    )
    return Candle(at, open_value, high_value, low_value, close_value, volume)


def _trend_candles(count: int = 30, *, volume: int = 100) -> list[Candle]:
    return [
        _candle(
            index,
            str(100 + index),
            open_=str(99 + index),
            high=str(101 + index),
            low=str(98 + index),
            volume=volume,
        )
        for index in range(count)
    ]


def test_ema_uses_sma_seed_and_standard_alpha() -> None:
    values = [Decimal(value) for value in range(1, 7)]

    result = ema(values, 3)

    assert result == Decimal("5")


def test_rsi_wilder_is_100_for_persistent_gain_and_50_for_flat_series() -> None:
    rising = [Decimal(value) for value in range(1, 17)]
    flat = [Decimal("10")] * 16

    assert rsi_wilder(rising, 14) == Decimal("100")
    assert rsi_wilder(flat, 14) == Decimal("50")


def test_atr_wilder_uses_true_range_against_previous_close() -> None:
    candles = [
        _candle(index, "100", open_="100", high="102", low="98")
        for index in range(16)
    ]

    assert atr_wilder(candles, 14) == Decimal("4")


def test_opening_range_requires_all_first_15_minutes() -> None:
    candles = _trend_candles(20)

    high, low = opening_range(candles, OPEN, 15)

    assert high == Decimal("115")
    assert low == Decimal("98")

    with pytest.raises(PriceStructureError, match="opening range incomplete"):
        opening_range(candles[1:], OPEN, 15)


def test_previous_session_levels_are_raw_high_and_low() -> None:
    prior_day = date(2026, 9, 25)
    candles = [
        _candle(0, "100", high="110", low="90", day=prior_day),
        _candle(1, "105", high="112", low="95", day=prior_day),
    ]

    assert previous_session_levels(candles) == (
        Decimal("112"),
        Decimal("90"),
    )


def test_future_vwap_uses_typical_price_and_volume() -> None:
    candles = [
        _candle(0, "100", high="102", low="98", volume=100),
        _candle(1, "110", high="112", low="108", volume=300),
    ]

    assert futures_vwap(candles) == Decimal("107.5")


def test_future_vwap_rejects_zero_volume() -> None:
    candles = _trend_candles(20, volume=0)

    with pytest.raises(PriceStructureError, match="volume unavailable"):
        futures_vwap(candles)


def test_relative_volume_aligns_by_minute_of_day_not_list_position() -> None:
    current = [
        _candle(0, "100", volume=100),
        _candle(1, "101", volume=200),
        _candle(2, "102", volume=300),
    ]
    prior_day = date(2026, 9, 25)
    prior = [
        _candle(0, "100", volume=100, day=prior_day),
        _candle(2, "102", volume=100, day=prior_day),
        _candle(10, "110", volume=1000, day=prior_day),
    ]

    result = cumulative_relative_volume(
        current,
        [prior],
        OPEN + timedelta(minutes=2),
    )

    assert result == Decimal("3")


def test_snapshot_keeps_spot_and_future_measurements_separate() -> None:
    spot = _trend_candles(30, volume=0)
    future = _trend_candles(30, volume=100)
    prior_day = date(2026, 9, 25)
    previous_spot = [
        _candle(0, "90", high="95", low="85", day=prior_day),
        _candle(1, "92", high="96", low="86", day=prior_day),
    ]
    baseline = [
        _candle(index, str(100 + index), volume=50, day=prior_day)
        for index in range(30)
    ]

    snapshot = build_price_structure_snapshot(
        spot,
        future,
        market_open=OPEN,
        previous_spot_candles=previous_spot,
        future_volume_baselines=[baseline],
    )

    assert snapshot.spot_close == Decimal("129")
    assert snapshot.ema9 > snapshot.ema20
    assert snapshot.rsi14 == Decimal("100")
    assert snapshot.atr14 == Decimal("3")
    assert snapshot.candle_body == Decimal("1")
    assert snapshot.upper_wick == Decimal("1")
    assert snapshot.lower_wick == Decimal("1")
    assert snapshot.opening_range_high == Decimal("115")
    assert snapshot.opening_range_low == Decimal("98")
    assert snapshot.previous_session_high == Decimal("96")
    assert snapshot.previous_session_low == Decimal("85")
    assert snapshot.future_close == Decimal("129")
    assert snapshot.future_vwap is not None
    assert snapshot.relative_volume == Decimal("2")


def test_snapshot_fails_closed_for_unsorted_or_short_spot_history() -> None:
    candles = _trend_candles(20)

    with pytest.raises(PriceStructureError, match="strictly increasing"):
        build_price_structure_snapshot(
            list(reversed(candles)),
            candles,
            market_open=OPEN,
        )

    with pytest.raises(PriceStructureError, match="spot history insufficient"):
        build_price_structure_snapshot(
            candles[:19],
            candles,
            market_open=OPEN,
        )
