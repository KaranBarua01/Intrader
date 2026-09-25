from datetime import datetime
from zoneinfo import ZoneInfo

from intrader.context_sources import (
    parse_bls_calendar_ics,
    parse_fomc_calendar,
    parse_rbi_press_release_rss,
)


def test_rbi_rss_parser_preserves_authoritative_timestamp_and_link() -> None:
    xml = """<?xml version="1.0"?>
    <rss><channel><item>
      <title>Monetary Policy Statement</title>
      <link>https://rbi.example/policy</link>
      <pubDate>Mon, 28 Sep 2026 05:30:00 GMT</pubDate>
    </item></channel></rss>"""

    result = parse_rbi_press_release_rss(xml)

    assert len(result) == 1
    assert result[0].source == "RBI"
    assert result[0].title == "Monetary Policy Statement"
    assert result[0].published_at.isoformat() == "2026-09-28T05:30:00+00:00"


def test_bls_ics_parser_selects_macro_events_and_handles_tzid() -> None:
    ics = """BEGIN:VCALENDAR
BEGIN:VEVENT
DTSTART;TZID=America/New_York:20261014T083000
SUMMARY:Consumer Price Index for September 2026
END:VEVENT
BEGIN:VEVENT
DTSTART;TZID=America/New_York:20261020T100000
SUMMARY:State Employment and Unemployment
END:VEVENT
BEGIN:VEVENT
DTSTART;TZID=America/New_York:20261103T100000
SUMMARY:Job Openings and Labor Turnover Survey for September 2026
END:VEVENT
END:VCALENDAR"""

    result = parse_bls_calendar_ics(ics)

    assert len(result) == 2
    assert result[0].category == "US_CPI"
    assert result[0].impact == "HIGH"
    assert result[0].scheduled_at.hour == 8
    assert result[1].category == "US_JOLTS"
    assert result[1].impact == "MEDIUM"


def test_fomc_parser_uses_second_day_at_2pm_eastern() -> None:
    html = """
    <h4>2026 FOMC Meetings</h4>
    <div>January</div><div>27-28</div>
    <div>March</div><div>17-18*</div>
    <h4>2025 FOMC Meetings</h4>
    """

    result = parse_fomc_calendar(html, 2026)

    eastern = ZoneInfo("America/New_York")
    assert len(result) == 2
    assert result[0].scheduled_at == datetime(
        2026, 1, 28, 14, 0, tzinfo=eastern
    )
    assert result[1].scheduled_at == datetime(
        2026, 3, 18, 14, 0, tzinfo=eastern
    )
    assert all(event.impact == "HIGH" for event in result)
