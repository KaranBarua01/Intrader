from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import sqlite3

import pytest

from intrader.historical import Candle, OIObservation
from intrader.instruments import Instrument, NiftyInstruments
from intrader.market_brain import FamilyEvidence
from intrader.outcomes import ShadowOutcome
from intrader.records import DecisionReason, DecisionRecord
from intrader.shadow import ShadowTrade
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
    assert store._connection.execute("PRAGMA user_version").fetchone()[0] == 7
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



def _decision_record() -> DecisionRecord:
    return DecisionRecord(
        decision_id="DEC-TEST-1",
        decided_at=NOW,
        session_date=NOW.date(),
        brain_version="brain-v0.1",
        rule_version="rules-v0.1",
        brain_state="BULLISH SETUP",
        action="BUY_CALL",
        rejected_action="BUY_PUT",
        direction_score=Decimal("62"),
        entry_quality=Decimal("70"),
        reversal_risk=Decimal("30"),
        confidence=Decimal("75"),
        family_coverage=Decimal("100"),
        regime="TRENDING_UP",
        spot_price=Decimal("23150"),
        future_price=Decimal("23200"),
        vix=Decimal("12.4"),
        ema9=Decimal("23140"),
        ema20=Decimal("23120"),
        rsi14=Decimal("63"),
        atr14=Decimal("30"),
        opening_range_high=Decimal("23100"),
        opening_range_low=Decimal("23020"),
        future_oi=100000,
        future_oi_change=5000,
        future_volume_change=25000,
        basis=Decimal("50"),
        basis_change=Decimal("8"),
        oi_pcr=Decimal("1.2"),
        volume_pcr=Decimal("1.1"),
        breadth_pct=Decimal("32"),
        depth_imbalance=Decimal("0.25"),
        high_impact_event_active=False,
        families=(
            FamilyEvidence("PRICE", Decimal("30"), Decimal("0.7")),
        ),
        reasons=(
            DecisionReason(
                "CHOSEN",
                "PRICE_SUPPORTS_CALL",
                "PRICE",
                Decimal("0.7"),
                1,
                "Price supports call.",
            ),
            DecisionReason(
                "REJECTED",
                "REJECT_BUY_PUT_PRICE",
                "PRICE",
                Decimal("0.7"),
                1,
                "Price rejects put.",
            ),
        ),
    )


def test_decision_ledger_is_idempotent_and_immutable(tmp_path) -> None:
    record = _decision_record()

    with SQLiteStore(tmp_path / "intrader.db") as store:
        assert store.store_decision_record(record) is True
        assert store.store_decision_record(record) is False
        assert store.count("decision_records") == 1
        assert store.count("decision_families") == 1
        assert store.count("decision_reasons") == 2

        loaded = store.load_decision_record(record.decision_id)
        assert loaded is not None
        assert loaded.action == "BUY_CALL"
        assert loaded.rejected_action == "BUY_PUT"
        assert loaded.reasons == record.reasons

        with pytest.raises(sqlite3.IntegrityError):
            store._connection.execute(
                "UPDATE decision_records SET action = 'BUY_PUT' "
                "WHERE decision_id = ?",
                (record.decision_id,),
            )

        with pytest.raises(sqlite3.IntegrityError):
            store._connection.execute(
                "DELETE FROM decision_reasons WHERE decision_id = ?",
                (record.decision_id,),
            )



def test_shadow_trade_entry_is_idempotent_and_immutable(tmp_path) -> None:
    decision = _decision_record()
    trade = ShadowTrade(
        trade_id="SHD-TEST-1",
        decision_id=decision.decision_id,
        shadow_version="shadow-v0.1",
        opened_at=NOW,
        action="BUY_CALL",
        token="call",
        strike=Decimal("23150"),
        option_type="CE",
        entry_price=Decimal("100"),
        quantity=65,
        lot_size=65,
        lots=1,
        stop_price=Decimal("80"),
        target_price=Decimal("130"),
        max_minutes=30,
    )

    with SQLiteStore(tmp_path / "intrader.db") as store:
        store.store_decision_record(decision)
        assert store.store_shadow_trade(trade) is True
        assert store.store_shadow_trade(trade) is False
        assert store.count("shadow_trades") == 1

        loaded = store.load_shadow_trade(trade.trade_id)
        assert loaded == trade
        assert store.load_shadow_trade_for_decision(decision.decision_id) == trade

        with pytest.raises(sqlite3.IntegrityError):
            store._connection.execute(
                "UPDATE shadow_trades SET entry_price = 999 "
                "WHERE trade_id = ?",
                (trade.trade_id,),
            )



def test_shadow_outcome_is_idempotent_and_immutable(tmp_path) -> None:
    decision = _decision_record()
    trade = ShadowTrade(
        trade_id="SHD-OUTCOME-1",
        decision_id=decision.decision_id,
        shadow_version="shadow-v0.1",
        opened_at=NOW,
        action="BUY_CALL",
        token="call",
        strike=Decimal("23150"),
        option_type="CE",
        entry_price=Decimal("100"),
        quantity=65,
        lot_size=65,
        lots=1,
        stop_price=Decimal("80"),
        target_price=Decimal("130"),
        max_minutes=30,
    )
    outcome = ShadowOutcome(
        trade_id=trade.trade_id,
        evaluated_at=NOW + timedelta(minutes=5),
        exit_at=NOW + timedelta(minutes=5),
        exit_reason="TARGET",
        exit_price=Decimal("131"),
        gross_pnl=Decimal("2015"),
        estimated_friction=Decimal("7.51"),
        adjusted_pnl=Decimal("2007.49"),
        gross_return_pct=Decimal("31"),
        adjusted_return_pct=Decimal("30.88"),
        mfe_price=Decimal("31"),
        mae_price=Decimal("-5"),
        mfe_amount=Decimal("2015"),
        mae_amount=Decimal("-325"),
        spot_exit=Decimal("23190"),
        spot_change=Decimal("40"),
        directional_spot_change=Decimal("40"),
        forward_returns=(
            (1, Decimal("-5")),
            (3, Decimal("10")),
            (5, Decimal("31")),
            (10, None),
            (15, None),
            (30, None),
        ),
    )

    with SQLiteStore(tmp_path / "intrader.db") as store:
        store.store_decision_record(decision)
        store.store_shadow_trade(trade)
        assert store.store_shadow_outcome(outcome) is True
        assert store.store_shadow_outcome(outcome) is False
        assert store.count("shadow_outcomes") == 1
        assert store.load_shadow_outcome(trade.trade_id) == outcome
        assert store.load_unsettled_shadow_trades() == ()

        with pytest.raises(sqlite3.IntegrityError):
            store._connection.execute(
                "UPDATE shadow_outcomes SET gross_pnl = 0 WHERE trade_id = ?",
                (trade.trade_id,),
            )
