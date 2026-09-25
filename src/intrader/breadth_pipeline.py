"""Build NIFTY 50 breadth from locally stored constituent QUOTE snapshots."""

from collections import defaultdict
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from intrader.breadth import (
    BreadthError,
    BreadthMember,
    BreadthSnapshot,
    build_breadth_snapshot,
)
from intrader.config import AppConfig
from intrader.storage import SQLiteStore, StorageError


class BreadthPipelineError(Exception):
    """Stored constituent data cannot produce trustworthy breadth."""


def build_stored_breadth(
    store: SQLiteStore,
    session_date: date,
    at: datetime,
    config: AppConfig,
    *,
    expected_members: int = 50,
    max_age_seconds: float = 10.0,
) -> BreadthSnapshot:
    """Select one fresh quote per constituent and build raw breadth metrics."""

    if at.tzinfo is None:
        raise BreadthPipelineError("breadth timestamp must be timezone aware")
    if expected_members <= 0 or max_age_seconds <= 0:
        raise BreadthPipelineError("breadth configuration invalid")

    zone = ZoneInfo(config.timezone)
    at_local = at.astimezone(zone)
    market_open = datetime.combine(session_date, time(9, 15), zone)
    if at_local.date() != session_date or at_local < market_open:
        raise BreadthPipelineError("breadth timestamp outside session")

    try:
        snapshots = store.load_breadth_snapshots(
            start=market_open,
            end=at_local,
        )
    except StorageError:
        raise BreadthPipelineError("stored breadth unavailable") from None

    grouped = defaultdict(list)
    for snapshot in snapshots:
        grouped[snapshot.symbol].append(snapshot)

    if len(grouped) != expected_members:
        raise BreadthPipelineError("breadth membership incomplete")

    members: list[BreadthMember] = []
    for symbol in sorted(grouped):
        latest = grouped[symbol][-1]
        age = (
            at_local - latest.exchange_at.astimezone(zone)
        ).total_seconds()
        if age < -2 or age > max_age_seconds:
            raise BreadthPipelineError("breadth snapshot stale")
        members.append(
            BreadthMember(
                symbol=latest.symbol,
                previous_close=latest.previous_close,
                current_price=latest.current_price,
                weight=None,
                sector=latest.industry,
            )
        )

    try:
        return build_breadth_snapshot(members, at_local)
    except BreadthError:
        raise BreadthPipelineError("stored breadth unavailable") from None
