"""Deterministic Phase 1 warm-up and session state machine."""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import Enum
from typing import Callable
from zoneinfo import ZoneInfo

from intrader.backfill import BackfillReport
from intrader.config import AppConfig
from intrader.feed_health import HealthSnapshot


class SessionState(str, Enum):
    CONFIGURED = "CONFIGURED"
    PREPARING = "PREPARING"
    SYNCING = "SYNCING"
    ANALYSING = "ANALYSING"
    VALIDATING = "VALIDATING"
    READY = "READY"
    NO_TRADE = "NO TRADE"
    LIVE = "LIVE"
    ENDED = "ENDED"


class SessionScheduleError(Exception):
    """The configured trading window cannot produce a valid warm-up."""


@dataclass(frozen=True, slots=True)
class SessionSchedule:
    session_date: date
    market_open: datetime
    warmup_start: datetime
    live_start: datetime
    live_end: datetime


@dataclass(frozen=True, slots=True)
class PreparationReport:
    state: SessionState
    reasons: tuple[str, ...]
    schedule: SessionSchedule
    initial_backfill: BackfillReport | None = None
    final_backfill: BackfillReport | None = None
    health: HealthSnapshot | None = None


def build_session_schedule(
    config: AppConfig,
    session_date: date,
) -> SessionSchedule:
    """Build one IST-aware session schedule from the configured live start."""

    if session_date.weekday() >= 5:
        raise SessionScheduleError("weekend session unavailable")
    if config.warmup_minutes <= 0 or config.trading_duration_minutes <= 0:
        raise SessionScheduleError("session duration invalid")
    if config.warmup_start_grace_seconds < 0:
        raise SessionScheduleError("warmup grace invalid")

    zone = ZoneInfo(config.timezone)
    market_open = datetime.combine(session_date, time(9, 15), zone)
    live_start = datetime.combine(session_date, config.trading_start, zone)
    warmup_start = live_start - timedelta(minutes=config.warmup_minutes)
    live_end = live_start + timedelta(minutes=config.trading_duration_minutes)

    if warmup_start < market_open:
        raise SessionScheduleError("warmup starts before market open")
    if not market_open < live_start < live_end:
        raise SessionScheduleError("session schedule invalid")

    return SessionSchedule(
        session_date=session_date,
        market_open=market_open,
        warmup_start=warmup_start,
        live_start=live_start,
        live_end=live_end,
    )


class SessionCoordinator:
    """Strict state transitions for one configured trading session."""

    def __init__(
        self,
        schedule: SessionSchedule,
        *,
        warmup_start_grace_seconds: int = 120,
    ) -> None:
        if warmup_start_grace_seconds < 0:
            raise ValueError("warmup grace invalid")
        self.schedule = schedule
        self.warmup_start_grace_seconds = warmup_start_grace_seconds
        self.state = SessionState.CONFIGURED
        self.reasons: tuple[str, ...] = ()

    @staticmethod
    def _require_aware(now: datetime) -> None:
        if now.tzinfo is None:
            raise ValueError("session clock must be timezone aware")

    def begin(self, now: datetime) -> SessionState:
        self._require_aware(now)
        local = now.astimezone(self.schedule.live_start.tzinfo)

        if local >= self.schedule.live_end:
            self.state = SessionState.ENDED
            self.reasons = ("SESSION_ENDED",)
            return self.state
        if local < self.schedule.warmup_start:
            self.state = SessionState.CONFIGURED
            self.reasons = ("WARMUP_NOT_STARTED",)
            return self.state
        latest_start = self.schedule.warmup_start + timedelta(
            seconds=self.warmup_start_grace_seconds
        )
        if local > latest_start:
            self.state = SessionState.NO_TRADE
            self.reasons = ("MISSED_WARMUP",)
            return self.state

        self.state = SessionState.PREPARING
        self.reasons = ()
        return self.state

    def syncing(self) -> None:
        if self.state not in {SessionState.PREPARING, SessionState.ANALYSING}:
            raise RuntimeError("invalid SYNCING transition")
        self.state = SessionState.SYNCING
        self.reasons = ()

    def analysing(self) -> None:
        if self.state != SessionState.SYNCING:
            raise RuntimeError("invalid ANALYSING transition")
        self.state = SessionState.ANALYSING
        self.reasons = ()

    def validating(self) -> None:
        if self.state != SessionState.SYNCING:
            raise RuntimeError("invalid VALIDATING transition")
        self.state = SessionState.VALIDATING
        self.reasons = ()

    def fail(self, reason: str) -> SessionState:
        self.state = SessionState.NO_TRADE
        self.reasons = (reason,)
        return self.state

    def finish_validation(self, health: HealthSnapshot) -> SessionState:
        if self.state != SessionState.VALIDATING:
            raise RuntimeError("invalid validation completion")
        if (
            health.state == "READY"
            and health.fresh_count == health.expected_count
            and not health.reasons
        ):
            self.state = SessionState.READY
            self.reasons = ()
        else:
            self.state = SessionState.NO_TRADE
            self.reasons = health.reasons or ("FEED_UNHEALTHY",)
        return self.state

    def advance(self, now: datetime) -> SessionState:
        self._require_aware(now)
        local = now.astimezone(self.schedule.live_start.tzinfo)
        if local >= self.schedule.live_end:
            self.state = SessionState.ENDED
            self.reasons = ("SESSION_ENDED",)
        elif self.state == SessionState.READY and local >= self.schedule.live_start:
            self.state = SessionState.LIVE
            self.reasons = ()
        return self.state


class WarmupRunner:
    """Coordinate backfill, live accumulation and the final readiness gate."""

    def __init__(
        self,
        schedule: SessionSchedule,
        coordinator: SessionCoordinator,
        backfill_action: Callable[[datetime, datetime], BackfillReport],
        live_action: Callable[[float], HealthSnapshot],
    ) -> None:
        self.schedule = schedule
        self.coordinator = coordinator
        self._backfill_action = backfill_action
        self._live_action = live_action

    def _report(
        self,
        *,
        initial: BackfillReport | None = None,
        final: BackfillReport | None = None,
        health: HealthSnapshot | None = None,
    ) -> PreparationReport:
        return PreparationReport(
            state=self.coordinator.state,
            reasons=self.coordinator.reasons,
            schedule=self.schedule,
            initial_backfill=initial,
            final_backfill=final,
            health=health,
        )

    def run(self, now: datetime) -> PreparationReport:
        state = self.coordinator.begin(now)
        if state != SessionState.PREPARING:
            return self._report()

        local_now = now.astimezone(self.schedule.live_start.tzinfo)
        cutoff = local_now.replace(second=0, microsecond=0)
        if cutoff < self.schedule.warmup_start:
            cutoff = self.schedule.warmup_start

        try:
            self.coordinator.syncing()
            initial = self._backfill_action(self.schedule.market_open, cutoff)

            self.coordinator.analysing()
            remaining = (self.schedule.live_start - local_now).total_seconds()
            if remaining <= 0:
                return self._report(initial=initial)
            health = self._live_action(remaining)

            self.coordinator.syncing()
            final = self._backfill_action(cutoff, self.schedule.live_start)

            self.coordinator.validating()
            self.coordinator.finish_validation(health)
            return self._report(initial=initial, final=final, health=health)
        except Exception:
            self.coordinator.fail("PREPARATION_FAILED")
            return self._report()
