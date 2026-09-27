"""Tests for Intrader 0.5 event-driven Shadow Arena."""

from datetime import date, datetime, time, timedelta
from decimal import Decimal

from intrader.historical import Candle, INDIA_TIME
from intrader.shadow_arena import run_shadow_arena
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
                close = open_ + (
                    Decimal("3") if minute % 4 < 2 else Decimal("-3")
                )
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


def test_shadow_arena_builds_four_frozen_event_driven_engines() -> None:
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

    assert report.schema == "intrader-shadow-arena-v3-event-driven"
    assert report.total_sessions == 12
    assert report.actual_sessions == 12
    assert [item.timeframe_minutes for item in report.trader_reports] == [
        1, 5, 10, 15
    ]
    assert [item.hold_minutes for item in report.trader_reports] == [
        10, 30, 45, 60
    ]
    assert all(item.engine_id for item in report.trader_reports)
    assert report.blind_start <= report.blind_end
    assert len(report.blind_window_id) == 16
    assert all(
        item.blind_paper.starting_capital == Decimal("50000")
        for item in report.trader_reports
    )


def test_shadow_arena_ablation_uses_same_blind_window() -> None:
    config = ShadowReplayConfig(
        development_sessions=8,
        blind_sessions=4,
        mode_key="LOW",
        trader_timeframes=(5,),
    )

    report = run_shadow_arena(_sessions(12), config)

    assert report.ablation_results
    assert {
        item.timeframe_minutes for item in report.ablation_results
    } == {5}
    assert report.walk_forward_results == ()


def test_walk_forward_produces_rolling_windows_when_enabled() -> None:
    config = ShadowReplayConfig(
        development_sessions=8,
        blind_sessions=4,
        mode_key="LOW",
        validation_mode="WALK_FORWARD",
        walk_train_sessions=6,
        walk_test_sessions=2,
        walk_step_sessions=2,
        walk_windows=2,
        trader_timeframes=(5,),
    )

    report = run_shadow_arena(_sessions(12), config)

    assert len(report.walk_forward_results) == 2
    assert [row.window_index for row in report.walk_forward_results] == [1, 2]
    assert all(row.test_start <= row.test_end for row in report.walk_forward_results)
