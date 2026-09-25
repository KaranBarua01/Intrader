"""Refresh and merge authoritative news/event context through SQLite."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from intrader.context import ContextSnapshot, build_context_snapshot
from intrader.context_sources import (
    BLS_CALENDAR_ICS,
    FOMC_CALENDAR_URL,
    RBI_PRESS_RELEASE_RSS,
    ContextSourceError,
    TextTransport,
    parse_bls_calendar_ics,
    parse_fomc_calendar,
    parse_rbi_press_release_rss,
)
from intrader.storage import SQLiteStore, StorageError


class ContextPipelineError(Exception):
    """The local context cache cannot be refreshed or read."""


@dataclass(frozen=True, slots=True)
class ContextRefreshResult:
    snapshot: ContextSnapshot
    refreshed_sources: tuple[str, ...]
    failed_sources: tuple[str, ...]


def refresh_context(
    store: SQLiteStore,
    transport: TextTransport,
    at: datetime,
    *,
    recent_hours: int = 24,
    lookahead_hours: int = 24,
) -> ContextRefreshResult:
    """Refresh each public context source independently, then read merged cache."""

    if at.tzinfo is None:
        raise ContextPipelineError("context timestamp must be timezone aware")

    refreshed: list[str] = []
    failed: list[str] = []

    try:
        rbi_news = parse_rbi_press_release_rss(
            transport.get_text(RBI_PRESS_RELEASE_RSS, timeout=10)
        )
        store.store_news_items(rbi_news)
        refreshed.append("RBI")
    except (ContextSourceError, StorageError, Exception):
        failed.append("RBI")

    try:
        bls_events = parse_bls_calendar_ics(
            transport.get_text(BLS_CALENDAR_ICS, timeout=10)
        )
        store.store_scheduled_events(bls_events)
        refreshed.append("BLS")
    except (ContextSourceError, StorageError, Exception):
        failed.append("BLS")

    try:
        html = transport.get_text(FOMC_CALENDAR_URL, timeout=10)
        fed_events = list(parse_fomc_calendar(html, at.year))
        try:
            fed_events.extend(parse_fomc_calendar(html, at.year + 1))
        except ContextSourceError:
            pass
        store.store_scheduled_events(fed_events)
        refreshed.append("FED")
    except (ContextSourceError, StorageError, Exception):
        failed.append("FED")

    try:
        news = store.load_news_items(
            start=at - timedelta(hours=recent_hours),
            end=at,
        )
        events = store.load_scheduled_events(
            start=at - timedelta(minutes=15),
            end=at + timedelta(hours=lookahead_hours),
        )
        snapshot = build_context_snapshot(
            news,
            events,
            at,
            recent_hours=recent_hours,
            lookahead_hours=lookahead_hours,
        )
    except (StorageError, Exception):
        raise ContextPipelineError("local context cache unavailable") from None

    return ContextRefreshResult(
        snapshot=snapshot,
        refreshed_sources=tuple(sorted(set(refreshed))),
        failed_sources=tuple(sorted(set(failed))),
    )



def load_cached_context(
    store: SQLiteStore,
    at: datetime,
    *,
    recent_hours: int = 24,
    lookahead_hours: int = 24,
) -> ContextSnapshot:
    """Build context from the local cache without network access."""

    if at.tzinfo is None:
        raise ContextPipelineError("context timestamp must be timezone aware")
    try:
        news = store.load_news_items(
            start=at - timedelta(hours=recent_hours),
            end=at,
        )
        events = store.load_scheduled_events(
            start=at - timedelta(minutes=15),
            end=at + timedelta(hours=lookahead_hours),
        )
        return build_context_snapshot(
            news,
            events,
            at,
            recent_hours=recent_hours,
            lookahead_hours=lookahead_hours,
        )
    except (StorageError, Exception):
        raise ContextPipelineError("local context cache unavailable") from None
