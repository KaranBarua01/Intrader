from datetime import date, datetime, timezone
from decimal import Decimal
import json

import pytest

from intrader.auth import SmartSession
from intrader.historical import Candle, INDIA_TIME
from intrader.instruments import Instrument, NiftyInstruments
from intrader.today_download import (
    TodayDownloadError,
    completed_market_window,
    download_today_1m,
)


def _instrument(
    token: str,
    exchange: str,
    kind: str,
    symbol: str | None = None,
    strike: str = "0",
) -> Instrument:
    return Instrument(
        token=token,
        symbol=symbol or token,
        name="NIFTY" if token != "vix" else "INDIA VIX",
        instrument_type=kind,
        exchange=exchange,
        expiry=date(2026, 10, 6) if exchange == "NFO" else None,
        strike=Decimal(strike),
        lot_size=65 if exchange == "NFO" else 1,
    )


def _bundle() -> NiftyInstruments:
    spot = _instrument("spot", "NSE", "AMXIDX", "NIFTY 50")
    vix = _instrument("vix", "NSE", "AMXIDX", "India VIX")
    future = _instrument("future", "NFO", "FUTIDX", "NIFTY06OCT26FUT")
    call = _instrument("call", "NFO", "OPTIDX", "NIFTY06OCT2622400CE", "22400")
    put = _instrument("put", "NFO", "OPTIDX", "NIFTY06OCT2622400PE", "22400")
    return NiftyInstruments(
        spot=spot,
        vix=vix,
        future=future,
        option_expiry=date(2026, 10, 6),
        atm_strike=Decimal("22400"),
        strikes=(Decimal("22400"),),
        calls=(call,),
        puts=(put,),
    )


def _session() -> SmartSession:
    return SmartSession(
        "dummy-api",
        "dummy-client",
        "dummy-jwt",
        "dummy-refresh",
        "dummy-feed",
    )


def test_completed_market_window_after_close_is_full_session() -> None:
    start, end = completed_market_window(
        datetime(2026, 10, 1, 16, 0, tzinfo=INDIA_TIME)
    )

    assert start.strftime("%Y-%m-%d %H:%M") == "2026-10-01 09:15"
    assert end.strftime("%Y-%m-%d %H:%M") == "2026-10-01 15:30"


def test_completed_market_window_during_session_uses_last_finished_minute() -> None:
    start, end = completed_market_window(
        datetime(2026, 10, 1, 13, 50, 48, tzinfo=INDIA_TIME)
    )

    assert start.strftime("%H:%M") == "09:15"
    assert end.strftime("%H:%M") == "13:49"


def test_completed_market_window_before_first_finished_minute_fails() -> None:
    with pytest.raises(TodayDownloadError):
        completed_market_window(
            datetime(2026, 10, 1, 9, 15, 30, tzinfo=INDIA_TIME)
        )


def test_download_today_writes_combined_csv_and_manifest(tmp_path, monkeypatch) -> None:
    calls: list[str] = []
    candle_at = datetime(2026, 10, 1, 3, 45, tzinfo=timezone.utc)

    def fake_fetch(
        _session,
        _transport,
        instrument,
        _start,
        _end,
        _interval,
    ):
        calls.append(instrument.token)
        return (
            Candle(
                candle_at,
                Decimal("100"),
                Decimal("110"),
                Decimal("90"),
                Decimal("105"),
                123,
            ),
        )

    monkeypatch.setattr("intrader.today_download.fetch_candles", fake_fetch)

    report = download_today_1m(
        _session(),
        object(),
        _bundle(),
        output_root=tmp_path,
        now=datetime(2026, 10, 1, 16, 0, tzinfo=INDIA_TIME),
        request_delay=0,
        sleeper=lambda _delay: None,
    )

    assert calls == ["spot", "vix", "future", "call", "put"]
    assert report.total_rows == 5
    assert report.csv_path.exists()
    assert report.manifest_path.exists()

    csv_text = report.csv_path.read_text(encoding="utf-8")
    assert "timestamp_ist,exchange,token,symbol" in csv_text
    assert "2026-10-01T09:15:00+05:30" in csv_text
    assert "22400,CE" in csv_text
    assert "22400,PE" in csv_text

    manifest = json.loads(report.manifest_path.read_text(encoding="utf-8"))
    assert manifest["trading_date"] == "2026-10-01"
    assert manifest["interval"] == "ONE_MINUTE"
    assert manifest["total_rows"] == 5
    assert len(manifest["instruments"]) == 5
