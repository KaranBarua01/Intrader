from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from intrader.config import AppConfig
from intrader.instruments import Instrument, NiftyInstruments
from intrader.market_confirmation_pipeline import (
    MarketConfirmationPipelineError,
    build_stored_market_confirmation,
)
from intrader.storage import MarketSnapshotSink, SQLiteStore
from intrader.stream_protocol import DepthLevel, MarketTick


IST = ZoneInfo("Asia/Kolkata")
DAY = date(2026, 9, 28)
NOW = datetime(2026, 9, 28, 12, 0, tzinfo=IST)


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


def _future_tick(at: datetime, sequence: int, ltp: str, oi: int, volume: int) -> MarketTick:
    return MarketTick(
        "NFO",
        "future",
        3,
        sequence,
        at,
        at,
        Decimal(ltp),
        oi,
        volume,
        total_buy_quantity=Decimal("12000"),
        total_sell_quantity=Decimal("10000"),
        best_5_buy=(DepthLevel(Decimal(ltp) - Decimal("1"), 1000, 10),),
        best_5_sell=(DepthLevel(Decimal(ltp) + Decimal("1"), 900, 9),),
    )


def test_pipeline_loads_aligned_market_histories(tmp_path) -> None:
    bundle = _bundle()
    baseline = NOW - timedelta(minutes=5)
    with SQLiteStore(tmp_path / "intrader.db") as store:
        sink = MarketSnapshotSink(store, bundle)
        sink(MarketTick("NSE", "spot", 1, 1, baseline, baseline, Decimal("23100"), None))
        sink(MarketTick("NSE", "spot", 1, 2, NOW, NOW, Decimal("23120"), None))
        sink(MarketTick("NSE", "vix", 1, 1, baseline, baseline, Decimal("12"), None))
        sink(MarketTick("NSE", "vix", 1, 2, NOW, NOW, Decimal("12.5"), None))
        sink(_future_tick(baseline, 1, "23150", 1000, 5000))
        sink(_future_tick(NOW, 2, "23180", 1200, 6000))

        result = build_stored_market_confirmation(
            store,
            bundle,
            DAY,
            NOW,
            AppConfig(stale_tick_seconds=5),
        )

    assert result.futures.basis == Decimal("60")
    assert result.futures.basis_change == Decimal("10")
    assert result.vix.change == Decimal("0.5")
    assert result.order_flow.best_bid == Decimal("23179.0")


def test_pipeline_fails_closed_when_stream_is_missing(tmp_path) -> None:
    bundle = _bundle()
    with SQLiteStore(tmp_path / "intrader.db") as store:
        with pytest.raises(MarketConfirmationPipelineError, match="unavailable"):
            build_stored_market_confirmation(
                store,
                bundle,
                DAY,
                NOW,
                AppConfig(),
            )
