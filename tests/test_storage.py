from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from intrader.historical import Candle, OIObservation
from intrader.instruments import Instrument, NiftyInstruments
from intrader.storage import MarketSnapshotSink, OptionSnapshotSink, SQLiteStore, StorageError
from intrader.stream_protocol import DepthLevel, MarketTick


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
    assert store._connection.execute("PRAGMA user_version").fetchone()[0] == 4
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



def test_load_option_snapshots_filters_expiry_and_orders_rows(tmp_path) -> None:
    bundle = _bundle()
    call = bundle.calls[0]
    later = NOW + timedelta(seconds=2)
    earlier = NOW + timedelta(seconds=1)

    with SQLiteStore(tmp_path / "intrader.db") as store:
        store.store_option_tick(
            call,
            MarketTick(
                "NFO",
                call.token,
                3,
                2,
                later,
                later,
                Decimal("126"),
                124000,
                988000,
            ),
        )
        store.store_option_tick(
            call,
            MarketTick(
                "NFO",
                call.token,
                3,
                1,
                earlier,
                earlier,
                Decimal("125"),
                123000,
                987000,
            ),
        )

        loaded = store.load_option_snapshots(
            start=NOW,
            end=later,
            expiry=call.expiry.isoformat(),
        )

    assert [snapshot.sequence for snapshot in loaded] == [1, 2]
    assert [snapshot.ltp for snapshot in loaded] == [
        Decimal("125.0"),
        Decimal("126.0"),
    ]
    assert all(snapshot.token == call.token for snapshot in loaded)



def test_market_snapshot_sink_persists_spot_vix_and_future_order_flow(tmp_path) -> None:
    bundle = _bundle()
    now = NOW + timedelta(seconds=10)
    spot_tick = MarketTick(
        "NSE", bundle.spot.token, 1, 1, now, now,
        Decimal("23150"), None,
    )
    vix_tick = MarketTick(
        "NSE", bundle.vix.token, 1, 2, now, now,
        Decimal("12.5"), None,
    )
    future_tick = MarketTick(
        "NFO",
        bundle.future.token,
        3,
        3,
        now,
        now,
        Decimal("23200"),
        150000,
        250000,
        total_buy_quantity=Decimal("50000"),
        total_sell_quantity=Decimal("40000"),
        best_5_buy=(
            DepthLevel(Decimal("23199"), 1000, 10),
            DepthLevel(Decimal("23198"), 800, 8),
        ),
        best_5_sell=(
            DepthLevel(Decimal("23201"), 900, 9),
            DepthLevel(Decimal("23202"), 700, 7),
        ),
    )

    with SQLiteStore(tmp_path / "intrader.db") as store:
        sink = MarketSnapshotSink(store, bundle)
        sink(spot_tick)
        sink(vix_tick)
        sink(future_tick)

        assert store.count("index_snapshots") == 2
        assert store.count("future_snapshots") == 1

        spot = store.load_index_snapshots(bundle.spot.token)
        vix = store.load_index_snapshots(bundle.vix.token)
        future = store.load_future_snapshots(bundle.future.token)

    assert spot[0].ltp == Decimal("23150.0")
    assert vix[0].ltp == Decimal("12.5")
    assert future[0].ltp == Decimal("23200.0")
    assert future[0].open_interest == 150000
    assert future[0].volume == 250000
    assert future[0].best_bid_price == Decimal("23199.0")
    assert future[0].best_ask_price == Decimal("23201.0")
    assert future[0].depth_buy_quantity == 1800
    assert future[0].depth_sell_quantity == 1600
