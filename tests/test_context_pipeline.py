from datetime import datetime, timezone

from intrader.context_pipeline import refresh_context
from intrader.context_sources import (
    BLS_CALENDAR_ICS,
    FOMC_CALENDAR_URL,
    RBI_PRESS_RELEASE_RSS,
)
from intrader.storage import SQLiteStore


NOW = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)


class Transport:
    def get_text(self, url: str, timeout: int) -> str:
        assert timeout == 10
        if url == RBI_PRESS_RELEASE_RSS:
            return """<rss><channel><item>
            <title>RBI release</title>
            <link>https://rbi.example/1</link>
            <pubDate>Wed, 14 Oct 2026 11:00:00 GMT</pubDate>
            </item></channel></rss>"""
        if url == BLS_CALENDAR_ICS:
            return """BEGIN:VCALENDAR
BEGIN:VEVENT
DTSTART;TZID=America/New_York:20261014T083000
SUMMARY:Consumer Price Index for September 2026
END:VEVENT
END:VCALENDAR"""
        if url == FOMC_CALENDAR_URL:
            return """<h4>2026 FOMC Meetings</h4>
            <div>October</div><div>27-28</div>
            <h4>2025 FOMC Meetings</h4>"""
        raise AssertionError(url)


class PartialFailureTransport(Transport):
    def get_text(self, url: str, timeout: int) -> str:
        if url == RBI_PRESS_RELEASE_RSS:
            raise RuntimeError("RBI unavailable")
        return super().get_text(url, timeout)


def test_refresh_context_caches_independent_sources(tmp_path) -> None:
    with SQLiteStore(tmp_path / "intrader.db") as store:
        result = refresh_context(store, Transport(), NOW)

        assert result.refreshed_sources == ("BLS", "FED", "RBI")
        assert result.failed_sources == ()
        assert store.count("news_items") == 1
        assert store.count("scheduled_events") == 2
        assert len(result.snapshot.recent_news) == 1
        assert any(
            event.category == "US_CPI"
            for event in result.snapshot.upcoming_events
        )


def test_failed_source_keeps_other_context_and_cached_data(tmp_path) -> None:
    with SQLiteStore(tmp_path / "intrader.db") as store:
        refresh_context(store, Transport(), NOW)
        result = refresh_context(store, PartialFailureTransport(), NOW)

        assert result.refreshed_sources == ("BLS", "FED")
        assert result.failed_sources == ("RBI",)
        assert len(result.snapshot.recent_news) == 1
        assert result.snapshot.recent_news[0].source == "RBI"
