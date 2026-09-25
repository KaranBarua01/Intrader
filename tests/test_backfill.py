from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from intrader.auth import SmartSession
from intrader.backfill import BackfillError, backfill_core_market
from intrader.historical import Candle, HistoricalDataError, OIObservation
from intrader.instruments import Instrument, NiftyInstruments
from intrader.storage import SQLiteStore


START = datetime(2026, 9, 25, 3, 45, tzinfo=timezone.utc)
END = datetime(2026, 9, 25, 4, 0, tzinfo=timezone.utc)


def _instrument(token: str, exchange: str, kind: str) -> Instrument:
    return Instrument(
        token, token, "NIFTY", kind, exchange,
        date(2026, 9, 29), Decimal("23150"), 65,
    )


def _bundle() -> NiftyInstruments:
    return NiftyInstruments(
        _instrument("spot", "NSE", "AMXIDX"),
        _instrument("vix", "NSE", "AMXIDX"),
        _instrument("future", "NFO", "FUTIDX"),
        date(2026, 9, 29),
        Decimal("23150"),
        (Decimal("23150"),),
        (_instrument("call", "NFO", "OPTIDX"),),
        (_instrument("put", "NFO", "OPTIDX"),),
    )


def _session() -> SmartSession:
    return SmartSession("dummy-api", "dummy-client", "dummy-jwt", "dummy-refresh", "dummy-feed")


def _candle() -> tuple[Candle, ...]:
    return (
        Candle(START, Decimal("100"), Decimal("110"), Decimal("90"), Decimal("105"), 10),
    )


def test_backfill_fetches_three_core_candles_and_future_oi_atomically(tmp_path, monkeypatch) -> None:
    candle_tokens: list[str] = []
    delays: list[float] = []

    def fake_candles(_session, _transport, instrument, _start, _end, _interval):
        candle_tokens.append(instrument.token)
        return _candle()

    monkeypatch.setattr("intrader.backfill.fetch_candles", fake_candles)
    monkeypatch.setattr(
        "intrader.backfill.fetch_oi",
        lambda *_args: (OIObservation(START, 1000),),
    )

    with SQLiteStore(tmp_path / "intrader.db") as store:
        report = backfill_core_market(
            store, _session(), object(), _bundle(), START, END,
            request_delay=0.35, sleeper=delays.append,
        )
        assert report.candle_rows == 3
        assert report.oi_rows == 1
        assert report.candle_instruments == 3
        assert candle_tokens == ["spot", "vix", "future"]
        assert delays == [0.35, 0.35, 0.35]
        assert store.count("candles") == 3
        assert store.count("oi_observations") == 1

        backfill_core_market(
            store, _session(), object(), _bundle(), START, END,
            request_delay=0, sleeper=lambda _delay: None,
        )
        assert store.count("candles") == 3
        assert store.count("oi_observations") == 1


def test_failed_source_does_not_write_partial_backfill(tmp_path, monkeypatch) -> None:
    calls = 0

    def fake_candles(*_args):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise HistoricalDataError("unavailable")
        return _candle()

    monkeypatch.setattr("intrader.backfill.fetch_candles", fake_candles)

    with SQLiteStore(tmp_path / "intrader.db") as store:
        with pytest.raises(BackfillError, match="session backfill unavailable"):
            backfill_core_market(
                store, _session(), object(), _bundle(), START, END,
                request_delay=0, sleeper=lambda _delay: None,
            )
        assert store.count("candles") == 0
        assert store.count("oi_observations") == 0
