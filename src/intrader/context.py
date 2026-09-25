"""Non-directional macro/news context for Intrader Phase 2."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Sequence


class ContextError(Exception):
    """Context inputs are malformed or cannot be evaluated safely."""


@dataclass(frozen=True, slots=True)
class NewsItem:
    source: str
    title: str
    published_at: datetime
    url: str
    category: str


@dataclass(frozen=True, slots=True)
class ScheduledEvent:
    source: str
    name: str
    scheduled_at: datetime
    category: str
    impact: str


@dataclass(frozen=True, slots=True)
class ContextSnapshot:
    at: datetime
    recent_news: tuple[NewsItem, ...]
    upcoming_events: tuple[ScheduledEvent, ...]
    active_event_windows: tuple[ScheduledEvent, ...]
    minutes_to_next_high_impact: float | None
    sources: tuple[str, ...]


_IMPACT_WINDOWS = {
    "HIGH": (30, 15),
    "MEDIUM": (15, 10),
    "LOW": (0, 0),
}


def _validate_news(item: NewsItem) -> None:
    if not item.source or not item.title or not item.url or not item.category:
        raise ContextError("news item incomplete")
    if item.published_at.tzinfo is None:
        raise ContextError("news timestamp must be timezone aware")


def _validate_event(event: ScheduledEvent) -> None:
    if (
        not event.source
        or not event.name
        or not event.category
        or event.impact not in _IMPACT_WINDOWS
    ):
        raise ContextError("scheduled event invalid")
    if event.scheduled_at.tzinfo is None:
        raise ContextError("event timestamp must be timezone aware")


def build_context_snapshot(
    news: Sequence[NewsItem],
    events: Sequence[ScheduledEvent],
    at: datetime,
    *,
    recent_hours: int = 24,
    lookahead_hours: int = 24,
) -> ContextSnapshot:
    """Build a deduplicated, non-directional event/news context snapshot."""

    if at.tzinfo is None:
        raise ContextError("context timestamp must be timezone aware")
    if recent_hours <= 0 or lookahead_hours <= 0:
        raise ContextError("context window invalid")

    recent_start = at - timedelta(hours=recent_hours)
    upcoming_end = at + timedelta(hours=lookahead_hours)

    deduped: dict[tuple[str, str], NewsItem] = {}
    for item in news:
        _validate_news(item)
        if item.published_at > at or item.published_at < recent_start:
            continue
        key = (item.url.strip().lower(), item.title.strip().lower())
        existing = deduped.get(key)
        if existing is None or item.published_at > existing.published_at:
            deduped[key] = item

    recent_news = tuple(
        sorted(
            deduped.values(),
            key=lambda item: item.published_at,
            reverse=True,
        )
    )

    valid_events: list[ScheduledEvent] = []
    active: list[ScheduledEvent] = []
    next_high_minutes: float | None = None
    for event in events:
        _validate_event(event)
        pre_minutes, post_minutes = _IMPACT_WINDOWS[event.impact]
        window_start = event.scheduled_at - timedelta(minutes=pre_minutes)
        window_end = event.scheduled_at + timedelta(minutes=post_minutes)

        if at <= event.scheduled_at <= upcoming_end:
            valid_events.append(event)
            if event.impact == "HIGH":
                minutes = (event.scheduled_at - at).total_seconds() / 60
                if next_high_minutes is None or minutes < next_high_minutes:
                    next_high_minutes = minutes

        if pre_minutes > 0 and window_start <= at <= window_end:
            active.append(event)

    upcoming = tuple(
        sorted(valid_events, key=lambda event: event.scheduled_at)
    )
    active_events = tuple(
        sorted(active, key=lambda event: event.scheduled_at)
    )
    sources = tuple(
        sorted(
            {
                *(item.source for item in recent_news),
                *(event.source for event in upcoming),
                *(event.source for event in active_events),
            }
        )
    )

    return ContextSnapshot(
        at=at,
        recent_news=recent_news,
        upcoming_events=upcoming,
        active_event_windows=active_events,
        minutes_to_next_high_impact=next_high_minutes,
        sources=sources,
    )
