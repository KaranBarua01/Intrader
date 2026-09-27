"""Shadow Trader should prefer cached candles before requiring SmartAPI."""

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from intrader.auth import SmartAPIError
from intrader.historical import Candle, INDIA_TIME
from intrader.ui.data_service import DesktopDataService


def _weekday_sessions(count: int, end_day: date) -> tuple[Candle, ...]:
    days = []
    day = end_day
    while len(days) < count:
        if day.weekday() < 5:
            days.append(day)
        day -= timedelta(days=1)
    rows = []
    for index, session_day in enumerate(reversed(days)):
        at = datetime.combine(session_day, time(9, 15), INDIA_TIME)
        price = Decimal("24000") + Decimal(index)
        rows.append(
            Candle(
                at=at,
                open=price,
                high=price + Decimal("2"),
                low=price - Decimal("2"),
                close=price + Decimal("1"),
                volume=1000,
            )
        )
    return tuple(rows)


def test_shadow_replay_uses_local_cache_without_broker_login(monkeypatch) -> None:
    service = DesktopDataService(Path("unused.db"))
    end_day = date(2026, 9, 25)
    candles = _weekday_sessions(30, end_day)
    backfill_calls = []

    def fake_load(start, end, *, backfill_missing=False):
        backfill_calls.append(backfill_missing)
        assert backfill_missing is False
        return tuple(c for c in candles if start <= c.at <= end)

    monkeypatch.setattr(service, "load_nifty_candle_range", fake_load)

    rows = service.load_shadow_replay_candles(
        30,
        now=datetime(2026, 9, 28, 4, 0, tzinfo=INDIA_TIME),
    )

    assert len({row.at.date() for row in rows}) >= 30
    assert backfill_calls
    assert all(value is False for value in backfill_calls)


def test_shadow_replay_explains_cache_shortfall_when_smartapi_unavailable(monkeypatch) -> None:
    service = DesktopDataService(Path("unused.db"))
    end_day = date(2026, 9, 25)
    candles = _weekday_sessions(8, end_day)

    def fake_load(start, end, *, backfill_missing=False):
        if backfill_missing:
            raise SmartAPIError("SmartAPI network request failed")
        return tuple(c for c in candles if start <= c.at <= end)

    monkeypatch.setattr(service, "load_nifty_candle_range", fake_load)

    with pytest.raises(
        ValueError,
        match=r"8/30 requested sessions cached locally.*SmartAPI network request failed",
    ):
        service.load_shadow_replay_candles(
            30,
            now=datetime(2026, 9, 28, 4, 0, tzinfo=INDIA_TIME),
        )
