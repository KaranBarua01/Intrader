from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from intrader.config import AppConfig
from intrader.historical import Candle
from intrader.instruments import Instrument, NiftyInstruments
from intrader.price_pipeline import PricePipelineError, build_stored_price_structure
from intrader.storage import SQLiteStore


IST = ZoneInfo("Asia/Kolkata")
DAY = date(2026, 9, 28)
OPEN = datetime(2026, 9, 28, 9, 15, tzinfo=IST)


def _instrument(token: str, exchange: str, kind: str) -> Instrument:
    return Instrument(
        token,
        token,
        "NIFTY",
        kind,
        exchange,
        date(2026, 9, 29),
        Decimal("23150"),
        65,
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


def _session(day: date, count: int, *, volume: int) -> list[Candle]:
    start = datetime(day.year, day.month, day.day, 9, 15, tzinfo=IST)
    candles: list[Candle] = []
    for index in range(count):
        close = Decimal(23000 + index)
        candles.append(
            Candle(
                start + timedelta(minutes=index),
                close - Decimal(1),
                close + Decimal(1),
                close - Decimal(2),
                close,
                volume,
            )
        )
    return candles


def test_pipeline_uses_latest_prior_spot_and_prior_future_sessions(tmp_path) -> None:
    bundle = _bundle()
    previous_day = date(2026, 9, 25)
    current_spot = _session(DAY, 30, volume=0)
    current_future = _session(DAY, 30, volume=100)
    previous_spot = _session(previous_day, 30, volume=0)
    previous_future = _session(previous_day, 30, volume=50)

    with SQLiteStore(tmp_path / "intrader.db") as store:
        store.store_candles(bundle.spot, "ONE_MINUTE", previous_spot + current_spot)
        store.store_candles(
            bundle.future,
            "ONE_MINUTE",
            previous_future + current_future,
        )

        snapshot = build_stored_price_structure(
            store,
            bundle,
            DAY,
            OPEN + timedelta(minutes=29),
            AppConfig(),
        )

    assert snapshot.previous_session_high == previous_spot[-1].high
    assert snapshot.previous_session_low == previous_spot[0].low
    assert snapshot.relative_volume == Decimal("2")
    assert snapshot.future_vwap is not None


def test_pipeline_fails_closed_when_current_spot_history_is_missing(tmp_path) -> None:
    bundle = _bundle()

    with SQLiteStore(tmp_path / "intrader.db") as store:
        with pytest.raises(PricePipelineError, match="unavailable"):
            build_stored_price_structure(
                store,
                bundle,
                DAY,
                OPEN + timedelta(minutes=29),
                AppConfig(),
            )
