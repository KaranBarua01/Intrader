"""Causality and execution tests for the Intrader 0.5 stream engine."""

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from intrader.historical import Candle, INDIA_TIME
from intrader.historical_options import HistoricalOptionCandle, HistoricalOptionDataset
from intrader.shadow_execution import ShadowExecutionError, execution_adapter
from intrader.shadow_lab import ShadowReplayConfig
from intrader.shadow_stream_engine import (
    CausalFrozenEngine,
    FeatureEvent,
    FrozenEngineSpec,
    HistoricalFeatureTimeline,
)


def _candle(at: datetime, close: str) -> Candle:
    value = Decimal(close)
    return Candle(
        at=at,
        open=value - Decimal("1"),
        high=value + Decimal("2"),
        low=value - Decimal("2"),
        close=value,
        volume=1000,
    )


def _spec() -> FrozenEngineSpec:
    return FrozenEngineSpec(
        timeframe_minutes=1,
        strategy_id="NISON_BULLISH_ENGULFING",
        strategy_name="Synthetic",
        engine_id="engine-test",
        hold_minutes=10,
        enabled_families=("NIFTY price / structure",),
        training_start="2026-01-01",
        training_end="2026-01-10",
    )


def test_feature_timeline_never_reveals_future_event() -> None:
    start = datetime(2026, 8, 3, 10, 0, tzinfo=INDIA_TIME)
    timeline = HistoricalFeatureTimeline(
        (
            FeatureEvent(
                at=start + timedelta(minutes=5),
                family="Futures",
                score=Decimal("0.8"),
                label="future confirmation",
            ),
        )
    )

    before = timeline.snapshot(
        start + timedelta(minutes=4),
        ("Futures",),
    )
    after = timeline.snapshot(
        start + timedelta(minutes=5),
        ("Futures",),
    )

    assert before.scores == ()
    assert after.scores == (("Futures", Decimal("0.8")),)


def test_stream_engine_opens_before_future_outcome_exists(monkeypatch) -> None:
    import intrader.shadow_stream_engine as engine_module

    start = datetime(2026, 8, 3, 9, 15, tzinfo=INDIA_TIME)

    def signal_on_920(_strategy_id, candles):
        return 1 if candles and candles[-1].at == start + timedelta(minutes=5) else None

    monkeypatch.setattr(engine_module, "detect_strategy_signal", signal_on_920)
    engine = CausalFrozenEngine(
        _spec(),
        ShadowReplayConfig(
            development_sessions=1,
            blind_sessions=1,
            starting_capital=Decimal("10000"),
            allocation_pct=Decimal("50"),
            friction_bps=Decimal("0"),
            trader_timeframes=(1,),
        ),
    )

    for minute in range(6):
        engine.consume(_candle(start + timedelta(minutes=minute), str(24000 + minute)))

    assert engine.position is not None
    assert engine.position.opened_at == start + timedelta(minutes=5)
    assert engine.trades == []

    for minute in range(6, 16):
        engine.consume(_candle(start + timedelta(minutes=minute), str(24000 + minute)))

    report = engine.report()
    assert len(report.trades) == 1
    assert report.trades[0].opened_at == (start + timedelta(minutes=5)).isoformat()
    assert report.trades[0].closed_at == (start + timedelta(minutes=15)).isoformat()


def test_exact_option_adapter_uses_real_premium_and_discrete_lots() -> None:
    adapter = execution_adapter("OPTION_PREMIUM")
    result = adapter.evaluate(
        entry_price=Decimal("100"),
        exit_price=Decimal("120"),
        direction=1,
        allocated_capital=Decimal("5000"),
        friction_bps=Decimal("0"),
        lot_size=25,
    )
    assert result.gross_return_pct == Decimal("20")
    assert result.quantity == 50
    assert result.paper_pnl == Decimal("1000")


def test_stream_engine_rejects_entry_that_cannot_finish_before_close(monkeypatch) -> None:
    import intrader.shadow_stream_engine as engine_module

    at = datetime(2026, 8, 3, 15, 25, tzinfo=INDIA_TIME)

    def always_signal(_strategy_id, candles):
        return 1 if candles else None

    monkeypatch.setattr(engine_module, "detect_strategy_signal", always_signal)
    engine = CausalFrozenEngine(
        _spec(),
        ShadowReplayConfig(
            development_sessions=1,
            blind_sessions=1,
            starting_capital=Decimal("10000"),
            allocation_pct=Decimal("50"),
            friction_bps=Decimal("0"),
            trader_timeframes=(1,),
        ),
    )

    engine.consume(_candle(at, "24000"))
    engine.finish(_candle(at + timedelta(minutes=5), "24005"))
    report = engine.report()

    assert engine.position is None
    assert report.trades == ()
    assert report.rejected_signals
    assert report.rejected_signals[0].reason == "insufficient session time for hold horizon"


def _option_dataset(start: datetime) -> HistoricalOptionDataset:
    rows = []
    for side in ("CE", "PE"):
        for offset in range(1, 12):
            at = start + timedelta(minutes=offset)
            open_ = (
                Decimal("100") + Decimal(offset - 1) * Decimal("2")
                if side == "CE" else Decimal("80")
            )
            close = open_ + Decimal("2") if side == "CE" else Decimal("81")
            rows.append(
                HistoricalOptionCandle(
                    at=at,
                    expiry=date(2026, 8, 6),
                    trading_symbol=f"NIFTY 24500 {side} 06 AUG 26",
                    instrument_key=f"NSE_FO|24500-{side}|06-08-2026",
                    strike=Decimal("24500"),
                    option_type=side,
                    lot_size=25,
                    open=open_,
                    high=max(open_, close) + Decimal("1"),
                    low=min(open_, close) - Decimal("1"),
                    close=close,
                    volume=1000,
                    open_interest=2000,
                )
            )
    return HistoricalOptionDataset(rows)


def test_stream_engine_option_mode_uses_next_bar_premium(monkeypatch) -> None:
    import intrader.shadow_stream_engine as engine_module

    start = datetime(2026, 8, 3, 9, 15, tzinfo=INDIA_TIME)

    def signal_on_first(_strategy_id, candles):
        return 1 if candles and candles[-1].at == start else None

    monkeypatch.setattr(engine_module, "detect_strategy_signal", signal_on_first)
    engine = CausalFrozenEngine(
        _spec(),
        ShadowReplayConfig(
            development_sessions=1,
            blind_sessions=1,
            execution_mode="OPTION_PREMIUM",
            starting_capital=Decimal("10000"),
            allocation_pct=Decimal("50"),
            friction_bps=Decimal("0"),
            trader_timeframes=(1,),
        ),
        option_datasets={start.date(): _option_dataset(start)},
    )

    for minute in range(12):
        engine.consume(_candle(start + timedelta(minutes=minute), "24500"))

    trade = engine.report().trades[0]
    assert trade.opened_at == (start + timedelta(minutes=1)).isoformat()
    assert trade.closed_at == (start + timedelta(minutes=11)).isoformat()
    assert trade.pricing_source == "UPSTOX_EXPIRED_OPTION"
    assert trade.option_strike == Decimal("24500")
    assert trade.option_type == "CE"
    assert trade.option_entry_price == Decimal("100")
    assert trade.option_exit_price == Decimal("122")
    assert trade.option_quantity == 50
    assert trade.paper_pnl == Decimal("1100")
