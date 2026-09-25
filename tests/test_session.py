from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from intrader.backfill import BackfillReport
from intrader.config import AppConfig
from intrader.feed_health import HealthSnapshot
from intrader.session import (
    SessionCoordinator,
    SessionScheduleError,
    SessionState,
    WarmupRunner,
    build_session_schedule,
)


IST = ZoneInfo("Asia/Kolkata")
DAY = date(2026, 9, 28)


def _config(**kwargs) -> AppConfig:
    values = {
        "trading_start": time(12, 0),
        "warmup_minutes": 30,
        "trading_duration_minutes": 30,
        "warmup_start_grace_seconds": 120,
    }
    values.update(kwargs)
    return AppConfig(**values)


def test_schedule_builds_0915_backfill_1130_warmup_and_1200_live() -> None:
    schedule = build_session_schedule(_config(), DAY)

    assert schedule.market_open == datetime(2026, 9, 28, 9, 15, tzinfo=IST)
    assert schedule.warmup_start == datetime(2026, 9, 28, 11, 30, tzinfo=IST)
    assert schedule.live_start == datetime(2026, 9, 28, 12, 0, tzinfo=IST)
    assert schedule.live_end == datetime(2026, 9, 28, 12, 30, tzinfo=IST)


def test_weekend_and_warmup_before_market_open_are_rejected() -> None:
    with pytest.raises(SessionScheduleError, match="weekend"):
        build_session_schedule(_config(), date(2026, 9, 26))

    with pytest.raises(SessionScheduleError, match="before market open"):
        build_session_schedule(_config(trading_start=time(9, 30)), DAY)


def test_coordinator_does_not_start_network_work_before_warmup() -> None:
    schedule = build_session_schedule(_config(), DAY)
    coordinator = SessionCoordinator(schedule)

    state = coordinator.begin(datetime(2026, 9, 28, 11, 29, tzinfo=IST))

    assert state == SessionState.CONFIGURED
    assert coordinator.reasons == ("WARMUP_NOT_STARTED",)


def test_late_start_fails_closed() -> None:
    schedule = build_session_schedule(_config(), DAY)
    coordinator = SessionCoordinator(schedule, warmup_start_grace_seconds=120)

    state = coordinator.begin(datetime(2026, 9, 28, 11, 32, 1, tzinfo=IST))

    assert state == SessionState.NO_TRADE
    assert coordinator.reasons == ("MISSED_WARMUP",)


def test_fresh_complete_health_reaches_ready_then_live_then_ended() -> None:
    schedule = build_session_schedule(_config(), DAY)
    coordinator = SessionCoordinator(schedule)
    assert coordinator.begin(schedule.warmup_start) == SessionState.PREPARING
    coordinator.syncing()
    coordinator.analysing()
    coordinator.syncing()
    coordinator.validating()

    state = coordinator.finish_validation(
        HealthSnapshot("READY", (), 21, 21)
    )

    assert state == SessionState.READY
    assert coordinator.advance(schedule.live_start) == SessionState.LIVE
    assert coordinator.advance(schedule.live_end) == SessionState.ENDED


@pytest.mark.parametrize(
    "health",
    [
        HealthSnapshot("NO TRADE", ("DISCONNECTED",), 0, 21),
        HealthSnapshot("NO TRADE", ("STALE_OPTION",), 20, 21),
        HealthSnapshot("READY", (), 20, 21),
    ],
)
def test_incomplete_or_stale_health_forces_no_trade(health: HealthSnapshot) -> None:
    schedule = build_session_schedule(_config(), DAY)
    coordinator = SessionCoordinator(schedule)
    coordinator.begin(schedule.warmup_start)
    coordinator.syncing()
    coordinator.analysing()
    coordinator.syncing()
    coordinator.validating()

    assert coordinator.finish_validation(health) == SessionState.NO_TRADE


def test_warmup_runner_performs_two_backfills_and_live_window() -> None:
    schedule = build_session_schedule(_config(), DAY)
    coordinator = SessionCoordinator(schedule)
    backfills: list[tuple[datetime, datetime]] = []
    durations: list[float] = []

    def backfill(start: datetime, end: datetime) -> BackfillReport:
        backfills.append((start, end))
        return BackfillReport(100, 25, 3)

    def live(seconds: float) -> HealthSnapshot:
        durations.append(seconds)
        return HealthSnapshot("READY", (), 21, 21)

    runner = WarmupRunner(schedule, coordinator, backfill, live)
    report = runner.run(schedule.warmup_start)

    assert report.state == SessionState.READY
    assert backfills == [
        (schedule.market_open, schedule.warmup_start),
        (schedule.warmup_start, schedule.live_start),
    ]
    assert durations == [1800.0]
    assert report.initial_backfill == BackfillReport(100, 25, 3)
    assert report.final_backfill == BackfillReport(100, 25, 3)


def test_runner_failure_is_no_trade_and_stops_sequence() -> None:
    schedule = build_session_schedule(_config(), DAY)
    coordinator = SessionCoordinator(schedule)
    live_called = False

    def broken_backfill(_start: datetime, _end: datetime) -> BackfillReport:
        raise RuntimeError("unavailable")

    def live(_seconds: float) -> HealthSnapshot:
        nonlocal live_called
        live_called = True
        return HealthSnapshot("READY", (), 21, 21)

    report = WarmupRunner(
        schedule, coordinator, broken_backfill, live
    ).run(schedule.warmup_start)

    assert report.state == SessionState.NO_TRADE
    assert report.reasons == ("PREPARATION_FAILED",)
    assert not live_called


def test_runner_started_one_minute_late_shortens_live_window_safely() -> None:
    schedule = build_session_schedule(_config(), DAY)
    coordinator = SessionCoordinator(schedule)
    durations: list[float] = []

    runner = WarmupRunner(
        schedule,
        coordinator,
        lambda _start, _end: BackfillReport(1, 1, 3),
        lambda seconds: durations.append(seconds)
        or HealthSnapshot("READY", (), 21, 21),
    )

    report = runner.run(schedule.warmup_start + timedelta(minutes=1))

    assert report.state == SessionState.READY
    assert durations == [1740.0]
