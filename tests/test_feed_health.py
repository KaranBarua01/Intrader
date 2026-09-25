from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from intrader.feed_health import FeedHealth
from intrader.instruments import Instrument, NiftyInstruments
from intrader.stream_protocol import MarketTick


NOW = datetime(2026, 9, 28, 4, 0, tzinfo=timezone.utc)


def _instrument(token: str, exchange: str) -> Instrument:
    return Instrument(token, token, "NIFTY", "OPTIDX", exchange, date(2026, 9, 29), Decimal(23150), 65)


def _bundle() -> NiftyInstruments:
    return NiftyInstruments(
        _instrument("spot", "NSE"), _instrument("vix", "NSE"),
        _instrument("future", "NFO"), date(2026, 9, 29), Decimal(23150),
        (Decimal(23150),), (_instrument("call", "NFO"),), (_instrument("put", "NFO"),),
    )


def _tick(token: str, exchange: str, sequence: int = 1, at: datetime = NOW) -> MarketTick:
    return MarketTick(exchange, token, 1 if exchange == "NSE" else 3, sequence, at, at, Decimal(23150), 123 if exchange == "NFO" else None)


def _ready_health() -> FeedHealth:
    health = FeedHealth(_bundle(), stale_tick_seconds=5, stale_option_seconds=8)
    health.on_connected()
    for token, exchange in (("spot", "NSE"), ("vix", "NSE"), ("future", "NFO"), ("call", "NFO"), ("put", "NFO")):
        health.accept(_tick(token, exchange))
    return health


def test_connecting_requires_every_critical_tick_before_ready() -> None:
    health = FeedHealth(_bundle(), 5, 8)

    assert health.snapshot(NOW).state == "NO TRADE"
    assert "DISCONNECTED" in health.snapshot(NOW).reasons
    health.on_connected()
    health.accept(_tick("spot", "NSE"))
    assert health.snapshot(NOW).state == "NO TRADE"
    assert "MISSING_TICKS" in health.snapshot(NOW).reasons
    for token, exchange in (("vix", "NSE"), ("future", "NFO"), ("call", "NFO"), ("put", "NFO")):
        health.accept(_tick(token, exchange))
    assert health.snapshot(NOW).state == "READY"


def test_stale_reception_or_exchange_timestamp_forces_no_trade() -> None:
    health = _ready_health()
    assert health.snapshot(NOW + timedelta(seconds=5.1)).state == "NO TRADE"
    assert "STALE_TICK" in health.snapshot(NOW + timedelta(seconds=5.1)).reasons

    health = _ready_health()
    health.accept(replace(_tick("call", "NFO", sequence=2), exchange_at=NOW - timedelta(seconds=30)))
    assert health.snapshot(NOW).state == "NO TRADE"
    assert "STALE_OPTION" in health.snapshot(NOW).reasons


def test_wrong_exchange_token_or_old_sequence_does_not_refresh_health() -> None:
    health = _ready_health()
    late = NOW + timedelta(seconds=6)
    health.accept(_tick("spot", "NFO", sequence=2, at=late))
    health.accept(_tick("other", "NSE", sequence=2, at=late))
    health.accept(_tick("spot", "NSE", sequence=1, at=late))

    assert health.snapshot(late).state == "NO TRADE"
    assert "STALE_TICK" in health.snapshot(late).reasons


def test_disconnect_and_reconnect_discard_prior_freshness() -> None:
    health = _ready_health()
    health.on_disconnected()
    assert health.snapshot(NOW).state == "NO TRADE"
    assert "DISCONNECTED" in health.snapshot(NOW).reasons

    health.on_connected()
    assert health.snapshot(NOW).state == "NO TRADE"
    assert "MISSING_TICKS" in health.snapshot(NOW).reasons
