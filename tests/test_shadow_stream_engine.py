"""Causality and execution tests for the Intrader 0.5 stream engine."""

from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from intrader.historical import Candle, INDIA_TIME
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


def test_exact_option_adapter_refuses_to_invent_premiums() -> None:
    adapter = execution_adapter("OPTION_PREMIUM")

    with pytest.raises(ShadowExecutionError, match="expired-option prices"):
        adapter.evaluate()
