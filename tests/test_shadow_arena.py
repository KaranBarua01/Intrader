"""Tests for the parallel Shadow Arena paper-trader engine."""

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from types import SimpleNamespace

from intrader.historical import Candle, INDIA_TIME
from intrader.shadow_arena import (
    _paperize_phase,
    _select_non_overlapping,
    run_shadow_arena,
)
from intrader.shadow_lab import ShadowReplayConfig


def _sessions(count: int) -> tuple[Candle, ...]:
    rows = []
    day = date(2026, 1, 5)
    built = 0
    while built < count:
        if day.weekday() < 5:
            start = datetime.combine(day, time(9, 15), INDIA_TIME)
            base = Decimal("24000") + Decimal(built * 15)
            for minute in range(90):
                wave = Decimal((minute % 12) - 6)
                open_ = base + wave
                close = open_ + (Decimal("3") if minute % 4 < 2 else Decimal("-3"))
                rows.append(
                    Candle(
                        at=start + timedelta(minutes=minute),
                        open=open_,
                        high=max(open_, close) + Decimal("1"),
                        low=min(open_, close) - Decimal("1"),
                        close=close,
                        volume=1000 + minute * 5,
                    )
                )
            built += 1
        day += timedelta(days=1)
    return tuple(rows)


def test_shadow_arena_runs_four_independent_timeframes() -> None:
    config = ShadowReplayConfig(
        development_sessions=8,
        blind_sessions=4,
        mode_key="LOW",
        starting_capital=Decimal("50000"),
        allocation_pct=Decimal("25"),
        friction_bps=Decimal("5"),
        trader_timeframes=(1, 5, 10, 15),
    )

    report = run_shadow_arena(_sessions(12), config)

    assert report.schema == "intrader-shadow-arena-v1"
    assert report.total_sessions == 12
    assert report.actual_sessions == 12
    assert [item.timeframe_minutes for item in report.trader_reports] == [1, 5, 10, 15]
    assert all(
        item.blind_paper.starting_capital == Decimal("50000")
        for item in report.trader_reports
    )


def test_overlapping_signals_are_rejected_per_timeframe() -> None:
    at = datetime(2026, 8, 3, 10, 0, tzinfo=INDIA_TIME)
    first = SimpleNamespace(
        phase="BLIND",
        at=at.isoformat(),
        direction="CALL / LONG",
    )
    second = SimpleNamespace(
        phase="BLIND",
        at=(at + timedelta(minutes=5)).isoformat(),
        direction="CALL / LONG",
    )
    third = SimpleNamespace(
        phase="BLIND",
        at=(at + timedelta(minutes=31)).isoformat(),
        direction="PUT / SHORT",
    )
    report = SimpleNamespace(trades=(first, second, third))

    accepted, rejected = _select_non_overlapping(report, 5)

    assert accepted == (first, third)
    assert len(rejected) == 1
    assert rejected[0].reason == "position already open in this timeframe trader"


def test_paper_money_applies_allocation_and_friction() -> None:
    trade = SimpleNamespace(
        phase="BLIND",
        at="2026-08-03T10:00:00+05:30",
        direction="CALL / LONG",
        entry_underlying=Decimal("24000"),
        approx_exit_underlying_30m=Decimal("24240"),
        return_30m_pct=Decimal("1.0"),
        regime=None,
    )
    config = ShadowReplayConfig(
        development_sessions=1,
        blind_sessions=1,
        starting_capital=Decimal("10000"),
        allocation_pct=Decimal("50"),
        friction_bps=Decimal("10"),
        trader_timeframes=(5,),
    )

    rows, account = _paperize_phase(
        (trade,),
        timeframe_minutes=5,
        strategy_name="Synthetic",
        config=config,
    )

    # 10 bps = 0.10%, so net trade return = 0.90%.
    # 50% of 10,000 = 5,000 allocated; P&L = 45.
    assert rows[0].net_return_30m_pct == Decimal("0.9")
    assert rows[0].paper_pnl == Decimal("45.000")
    assert account.ending_capital == Decimal("10045.000")
    assert account.net_pnl == Decimal("45.000")
