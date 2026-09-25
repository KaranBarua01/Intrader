from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from intrader.auth import SmartSession
from intrader.historical import (
    CANDLE_URL,
    OI_URL,
    HistoricalDataError,
    fetch_candles,
    fetch_oi,
)
from intrader.instruments import Instrument


IST = timezone(timedelta(hours=5, minutes=30))
START = datetime(2026, 9, 25, 9, 15, tzinfo=IST)
END = datetime(2026, 9, 25, 9, 17, tzinfo=IST)


def _instrument(exchange: str = "NSE") -> Instrument:
    return Instrument(
        "99926000" if exchange == "NSE" else "68407",
        "NIFTY 50" if exchange == "NSE" else "NIFTY29SEP26FUT",
        "NIFTY",
        "AMXIDX" if exchange == "NSE" else "FUTIDX",
        exchange,
        date(2026, 9, 29),
        Decimal("0"),
        65,
    )


def _session() -> SmartSession:
    return SmartSession("dummy-api", "dummy-client", "dummy-jwt", "dummy-refresh", "dummy-feed")


class FakeTransport:
    def __init__(self, responses: dict[str, dict]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, dict]] = []

    def public_ip(self) -> str:
        return "203.0.113.7"

    def post_json(self, url: str, headers: dict, body: dict, timeout: int) -> dict:
        self.calls.append((url, body))
        return self.responses[url]


def test_fetch_candles_uses_documented_request_and_normalizes_utc() -> None:
    transport = FakeTransport({
        CANDLE_URL: {
            "status": True,
            "data": [["2026-09-25T09:15:00+05:30", 23100, 23200, 23050, 23150, 10]],
        }
    })

    candles = fetch_candles(_session(), transport, _instrument(), START, END)

    assert transport.calls == [(
        CANDLE_URL,
        {
            "exchange": "NSE",
            "symboltoken": "99926000",
            "interval": "ONE_MINUTE",
            "fromdate": "2026-09-25 09:15",
            "todate": "2026-09-25 09:17",
        },
    )]
    assert candles[0].at == datetime(2026, 9, 25, 3, 45, tzinfo=timezone.utc)
    assert candles[0].close == Decimal("23150")


def test_fetch_oi_parses_live_nfo_contract_history() -> None:
    transport = FakeTransport({
        OI_URL: {
            "status": True,
            "data": [{"time": "2026-09-25T09:15:00+05:30", "oi": 166100}],
        }
    })

    observations = fetch_oi(_session(), transport, _instrument("NFO"), START, END)

    assert observations[0].oi == 166100
    assert transport.calls[0][0] == OI_URL


def test_more_than_30_days_is_rejected_before_network() -> None:
    transport = FakeTransport({})

    with pytest.raises(HistoricalDataError, match="exceeds interval limit"):
        fetch_candles(
            _session(), transport, _instrument(),
            START, START + timedelta(days=31),
        )

    assert transport.calls == []


@pytest.mark.parametrize(
    "response",
    [
        {"status": False, "message": "dummy-jwt"},
        {"status": True, "data": [["bad-time", 1, 2, 1, 1, 0]]},
        {"status": True, "data": [["2026-09-25T09:15:00+05:30", 2, 1, 1, 2, 0]]},
    ],
)
def test_invalid_candle_response_fails_closed_without_echoing_payload(response: dict) -> None:
    transport = FakeTransport({CANDLE_URL: response})

    with pytest.raises(HistoricalDataError) as error:
        fetch_candles(_session(), transport, _instrument(), START, END)

    assert "dummy-jwt" not in str(error.value)
