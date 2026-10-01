from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from intrader.checkpoint2 import INDIA_TIME
from intrader.historical import (
    HistoricalCandleClient,
    HistoricalDownloadError,
    _today_window,
)
from intrader.instruments import Instrument
from intrader.auth import SmartSession


class FakeTransport:
    def __init__(self, response: dict) -> None:
        self.response = response
        self.calls: list[tuple[str, dict]] = []

    def public_ip(self) -> str:
        return "203.0.113.7"

    def post_json(self, url: str, headers: dict, body: dict, timeout: int) -> dict:
        self.calls.append((url, body))
        return self.response


def _instrument() -> Instrument:
    return Instrument(
        token="99926000",
        symbol="NIFTY 50",
        name="NIFTY",
        instrument_type="AMXIDX",
        exchange="NSE",
        expiry=None,
        strike=Decimal("0"),
        lot_size=1,
    )


def _session() -> SmartSession:
    return SmartSession(
        api_key="dummy-api-key",
        client_code="dummy-client",
        jwt_token="dummy-jwt",
        refresh_token="dummy-refresh",
        feed_token="dummy-feed",
    )


def test_today_window_after_market_close_returns_full_session() -> None:
    now = datetime(2026, 10, 1, 16, 0, tzinfo=INDIA_TIME)

    start, end = _today_window(now)

    assert start.strftime("%Y-%m-%d %H:%M") == "2026-10-01 09:15"
    assert end.strftime("%Y-%m-%d %H:%M") == "2026-10-01 15:30"


def test_today_window_during_market_uses_last_completed_minute() -> None:
    now = datetime(2026, 10, 1, 13, 50, 48, tzinfo=INDIA_TIME)

    start, end = _today_window(now)

    assert start.strftime("%H:%M") == "09:15"
    assert end.strftime("%H:%M") == "13:49"


def test_today_window_before_first_completed_minute_fails() -> None:
    now = datetime(2026, 10, 1, 9, 15, 30, tzinfo=INDIA_TIME)

    with pytest.raises(HistoricalDownloadError):
        _today_window(now)


def test_client_requests_one_minute_candles_and_parses_rows() -> None:
    transport = FakeTransport(
        {
            "status": True,
            "data": [
                ["2026-10-01T09:15:00+05:30", 22500.1, 22503.2, 22498.0, 22501.5, 1234],
                ["2026-10-01T09:16:00+05:30", 22501.5, 22505.0, 22499.2, 22504.4, 2345],
            ],
        }
    )
    client = HistoricalCandleClient(_session(), transport)
    instrument = _instrument()
    start = datetime(2026, 10, 1, 9, 15, tzinfo=INDIA_TIME)
    end = datetime(2026, 10, 1, 9, 16, tzinfo=INDIA_TIME)

    candles = client.one_minute(instrument, start, end)

    assert len(candles) == 2
    assert candles[0].open == Decimal("22500.1")
    assert candles[1].close == Decimal("22504.4")
    assert transport.calls[0][1] == {
        "exchange": "NSE",
        "symboltoken": "99926000",
        "interval": "ONE_MINUTE",
        "fromdate": "2026-10-01 09:15",
        "todate": "2026-10-01 09:16",
    }


def test_client_rejects_malformed_candle_rows() -> None:
    client = HistoricalCandleClient(
        _session(),
        FakeTransport({"status": True, "data": [["bad"]]}),
    )
    start = datetime(2026, 10, 1, 9, 15, tzinfo=INDIA_TIME)

    with pytest.raises(HistoricalDownloadError):
        client.one_minute(_instrument(), start, start)
