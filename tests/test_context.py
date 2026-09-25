from datetime import datetime, timedelta, timezone

from intrader.context import (
    NewsItem,
    ScheduledEvent,
    build_context_snapshot,
)


NOW = datetime(2026, 9, 28, 6, 30, tzinfo=timezone.utc)


def test_context_deduplicates_news_and_filters_time_windows() -> None:
    news = (
        NewsItem(
            "RBI", "Policy update", NOW - timedelta(hours=1),
            "https://example.test/a", "RBI_PRESS_RELEASE",
        ),
        NewsItem(
            "RBI", "Policy update", NOW - timedelta(hours=2),
            "https://example.test/a", "RBI_PRESS_RELEASE",
        ),
        NewsItem(
            "RBI", "Old", NOW - timedelta(hours=30),
            "https://example.test/old", "RBI_PRESS_RELEASE",
        ),
        NewsItem(
            "RBI", "Future", NOW + timedelta(minutes=1),
            "https://example.test/future", "RBI_PRESS_RELEASE",
        ),
    )

    result = build_context_snapshot(news, (), NOW)

    assert len(result.recent_news) == 1
    assert result.recent_news[0].title == "Policy update"


def test_high_and_medium_event_windows_are_descriptive() -> None:
    high = ScheduledEvent(
        "BLS", "Consumer Price Index",
        NOW + timedelta(minutes=20), "US_CPI", "HIGH",
    )
    medium = ScheduledEvent(
        "BLS", "JOLTS",
        NOW + timedelta(minutes=5), "US_JOLTS", "MEDIUM",
    )

    result = build_context_snapshot((), (high, medium), NOW)

    assert result.upcoming_events == (medium, high)
    assert result.active_event_windows == (medium, high)
    assert result.minutes_to_next_high_impact == 20
    assert result.sources == ("BLS",)


def test_past_event_can_remain_in_post_event_window() -> None:
    event = ScheduledEvent(
        "FED", "FOMC policy decision",
        NOW - timedelta(minutes=10), "FOMC", "HIGH",
    )

    result = build_context_snapshot((), (event,), NOW)

    assert result.upcoming_events == ()
    assert result.active_event_windows == (event,)
    assert result.minutes_to_next_high_impact is None
