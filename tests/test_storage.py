from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from intrader.historical import Candle, OIObservation
from intrader.instruments import Instrument, NiftyInstruments
from intrader.storage import OptionSnapshotSink, SQLiteStore, StorageError
from intrader.stream_protocol import MarketTick


NOW = datetime(2026, 9, 25, 4, 0, tzinfo=timezone.utc)


def _instrument(token: str, symbol: str, exchange: str, kind: str) -> Instrument:
    return Instrument(
        token, symbol, "NIFTY", kind, exchange,
        date(2026, 9, 29), Decimal("23150"), 65,
    )


def _bundle() -> NiftyInstruments:
    spot = _instrument("spot", "NIFTY 50", "NSE", "AMXIDX")
    vix = _instrument("vix", "INDIA VIX", "NSE", "AMXIDX")
    future = _instrument("future", "NIFTY29SEP26FUT", "NFO", "FUTIDX")
    call = _instrument("call", "NIFTY29SEP2623150CE", "NFO", "OPTIDX")
    put = _instrument("put", "NIFTY29SEP2623150PE", "NFO", "OPTIDX")
    return NiftyInstruments(
        spot, vix, future, date(2026, 9, 29), Decimal("23150"),
        (Decimal("23150"),), (call,), (put,),
    )


def _candle(close: str = "23150") -> Candle:
    return Candle(
        NOW, Decimal("23100"), Decimal("23200"), Decimal("23050"),
        Decimal(close), 100,
    )


def _tick(token: str = "call", sequence: int = 1) -> MarketTick:
    return MarketTick(
        "NFO", token, 3, sequence, NOW, NOW,
        Decimal("125.50"), 123456, 987654,
    )


def test_schema_initializes_twice_with_wal_and_reopens(tmp_path) -> None:
    path = tmp_path / "intrader.db"
    store = SQLiteStore(path)
    store.initialize()
    store.initialize()

    assert store._connection.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    assert store._connection.execute("PRAGMA user_version").fetchone()[0] == 1
    store.store_candles(_bundle().spot, "ONE_MINUTE", [_candle()])
    store.close()

    reopened = SQLiteStore(path)
    reopened.initialize()
    assert reopened.count("candles") == 1
    reopened.close()


def test_replayed_rows_are_idempotent(tmp_path) -> None:
    bundle = _bundle()
    with SQLiteStore(tmp_path / "intrader.db") as store:
        store.store_candles(bundle.spot, "ONE_MINUTE", [_candle()])
        store.store_candles(bundle.spot, "ONE_MINUTE", [_candle("23160")])
        store.store_oi(
            bundle.future, "ONE_MINUTE", [OIObservation(NOW, 1000)]
        )
        store.store_oi(
            bundle.future, "ONE_MINUTE", [OIObservation(NOW, 1100)]
        )

        sink = OptionSnapshotSink(store, bundle)
        sink(_tick())
        sink(_tick())

        assert store.count("candles") == 1
        assert store.count("oi_observations") == 1
        assert store.count("option_snapshots") == 1


def test_atomic_backfill_rejects_invalid_batch_without_partial_write(tmp_path) -> None:
    bundle = _bundle()
    with SQLiteStore(tmp_path / "intrader.db") as store:
        with pytest.raises(StorageError):
            store.store_backfill(
                [(bundle.spot, "ONE_MINUTE", [_candle()])],
                [(bundle.future, "ONE_MINUTE", [OIObservation(NOW, -1)])],
            )

        assert store.count("candles") == 0
        assert store.count("oi_observations") == 0


def test_option_sink_ignores_non_option_tokens_and_rejects_bad_option_tick(tmp_path) -> None:
    bundle = _bundle()
    with SQLiteStore(tmp_path / "intrader.db") as store:
        sink = OptionSnapshotSink(store, bundle)
        sink(_tick("future"))
        assert store.count("option_snapshots") == 0

        with pytest.raises(StorageError):
            store.store_option_tick(bundle.calls[0], _tick("put"))



def test_load_candles_returns_ordered_filtered_history(tmp_path) -> None:
    bundle = _bundle()
    candles = [
        Candle(
            NOW + timedelta(minutes=2),
            Decimal("23120"),
            Decimal("23130"),
            Decimal("23110"),
            Decimal("23125"),
            120,
        ),
        Candle(
            NOW,
            Decimal("23100"),
            Decimal("23110"),
            Decimal("23090"),
            Decimal("23105"),
            100,
        ),
        Candle(
            NOW + timedelta(minutes=1),
            Decimal("23105"),
            Decimal("23120"),
            Decimal("23100"),
            Decimal("23115"),
            110,
        ),
    ]

    with SQLiteStore(tmp_path / "intrader.db") as store:
        store.store_candles(bundle.spot, "ONE_MINUTE", candles)
        loaded = store.load_candles(
            "NSE",
            bundle.spot.token,
            "ONE_MINUTE",
            start=NOW + timedelta(minutes=1),
            end=NOW + timedelta(minutes=2),
        )

    assert [candle.at for candle in loaded] == [
        NOW + timedelta(minutes=1),
        NOW + timedelta(minutes=2),
    ]
    assert [candle.close for candle in loaded] == [
        Decimal("23115"),
        Decimal("23125"),
    ]
