"""Zero-cost authoritative context-source parsers for Intrader."""

from __future__ import annotations

from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
import re
from typing import Protocol
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

import requests

from intrader.context import NewsItem, ScheduledEvent


RBI_PRESS_RELEASE_RSS = "https://rbi.org.in/pressreleases_rss.xml"
BLS_CALENDAR_ICS = "https://www.bls.gov/schedule/news_release/bls.ics"
FOMC_CALENDAR_URL = (
    "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
)


class ContextSourceError(Exception):
    """An external context source is unavailable or malformed."""


class TextTransport(Protocol):
    def get_text(self, url: str, timeout: int) -> str:
        ...


class RequestsContextTransport:
    def get_text(self, url: str, timeout: int) -> str:
        try:
            response = requests.get(
                url,
                timeout=timeout,
                headers={"User-Agent": "Intrader/0.1"},
            )
            response.raise_for_status()
            return response.text
        except requests.RequestException:
            raise ContextSourceError("context source unavailable") from None


def parse_rbi_press_release_rss(xml_text: str) -> tuple[NewsItem, ...]:
    """Parse RBI's official press-release RSS without interpreting sentiment."""

    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError:
        raise ContextSourceError("RBI RSS invalid") from None

    items: list[NewsItem] = []
    for node in root.findall(".//item"):
        title = (node.findtext("title") or "").strip()
        link = (node.findtext("link") or "").strip()
        published = (node.findtext("pubDate") or "").strip()
        if not title or not link or not published:
            continue
        try:
            published_at = parsedate_to_datetime(published)
        except (TypeError, ValueError):
            continue
        if published_at.tzinfo is None:
            published_at = published_at.replace(tzinfo=timezone.utc)
        items.append(
            NewsItem(
                source="RBI",
                title=title,
                published_at=published_at.astimezone(timezone.utc),
                url=link,
                category="RBI_PRESS_RELEASE",
            )
        )
    if not items:
        raise ContextSourceError("RBI RSS contains no usable items")
    return tuple(items)


def fetch_rbi_press_release_news(
    transport: TextTransport,
) -> tuple[NewsItem, ...]:
    return parse_rbi_press_release_rss(
        transport.get_text(RBI_PRESS_RELEASE_RSS, timeout=10)
    )


def _unfold_ics(text: str) -> list[str]:
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").split("\n"):
        if raw.startswith((" ", "\t")) and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    return lines


_BLS_IMPACT = {
    "Consumer Price Index": ("US_CPI", "HIGH"),
    "Employment Situation": ("US_EMPLOYMENT", "HIGH"),
    "Producer Price Index": ("US_PPI", "HIGH"),
    "Job Openings and Labor Turnover Survey": ("US_JOLTS", "MEDIUM"),
    "Employment Cost Index": ("US_ECI", "MEDIUM"),
}


def _parse_ics_datetime(key: str, value: str) -> datetime | None:
    if "VALUE=DATE" in key or "T" not in value:
        return None
    zone = timezone.utc
    match = re.search(r"TZID=([^;:]+)", key)
    if match:
        try:
            zone = ZoneInfo(match.group(1))
        except Exception:
            raise ContextSourceError("BLS calendar timezone invalid") from None
    if value.endswith("Z"):
        value = value[:-1]
        zone = timezone.utc

    for fmt in ("%Y%m%dT%H%M%S", "%Y%m%dT%H%M"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=zone)
        except ValueError:
            continue
    raise ContextSourceError("BLS calendar datetime invalid")


def parse_bls_calendar_ics(ics_text: str) -> tuple[ScheduledEvent, ...]:
    """Parse selected BLS macro releases from the official ICS calendar."""

    events: list[ScheduledEvent] = []
    block: dict[str, str] | None = None

    for line in _unfold_ics(ics_text):
        if line == "BEGIN:VEVENT":
            block = {}
            continue
        if line == "END:VEVENT":
            if block is not None:
                summary = block.get("SUMMARY", "").strip()
                dt_key = next(
                    (key for key in block if key.startswith("DTSTART")),
                    None,
                )
                match = next(
                    (
                        (prefix, meta)
                        for prefix, meta in _BLS_IMPACT.items()
                        if summary.startswith(prefix)
                    ),
                    None,
                )
                if dt_key is not None and match is not None:
                    scheduled_at = _parse_ics_datetime(
                        dt_key, block[dt_key]
                    )
                    if scheduled_at is not None:
                        category, impact = match[1]
                        events.append(
                            ScheduledEvent(
                                source="BLS",
                                name=summary,
                                scheduled_at=scheduled_at,
                                category=category,
                                impact=impact,
                            )
                        )
            block = None
            continue

        if block is not None and ":" in line:
            key, value = line.split(":", 1)
            block[key] = value.replace("\\,", ",").strip()

    if not events:
        raise ContextSourceError("BLS calendar contains no selected events")
    return tuple(sorted(events, key=lambda event: event.scheduled_at))


def fetch_bls_events(
    transport: TextTransport,
) -> tuple[ScheduledEvent, ...]:
    return parse_bls_calendar_ics(
        transport.get_text(BLS_CALENDAR_ICS, timeout=10)
    )


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        value = " ".join(data.split())
        if value:
            self.parts.append(value)


_MONTHS = {
    name: number
    for number, name in enumerate(
        (
            "January", "February", "March", "April", "May", "June",
            "July", "August", "September", "October", "November", "December",
        ),
        start=1,
    )
}


def parse_fomc_calendar(
    html_text: str,
    year: int,
) -> tuple[ScheduledEvent, ...]:
    """Parse the official FOMC calendar and use the second meeting day at 2pm ET."""

    parser = _VisibleTextParser()
    parser.feed(html_text)
    parts = parser.parts
    heading = f"{year} FOMC Meetings"
    try:
        start = next(
            index for index, part in enumerate(parts)
            if heading in part
        )
    except StopIteration:
        raise ContextSourceError("FOMC calendar year unavailable") from None

    eastern = ZoneInfo("America/New_York")
    events: list[ScheduledEvent] = []
    current_month: int | None = None
    date_pattern = re.compile(r"^(\d{1,2})(?:-(\d{1,2}))?\*?$")

    for part in parts[start + 1:]:
        if re.search(r"\b20\d{2} FOMC Meetings\b", part):
            break
        if part in _MONTHS:
            current_month = _MONTHS[part]
            continue
        if current_month is None:
            continue
        match = date_pattern.match(part)
        if match is None:
            continue
        decision_day = int(match.group(2) or match.group(1))
        try:
            scheduled_at = datetime(
                year, current_month, decision_day, 14, 0, tzinfo=eastern
            )
        except ValueError:
            raise ContextSourceError("FOMC calendar date invalid") from None
        events.append(
            ScheduledEvent(
                source="FED",
                name="FOMC policy decision",
                scheduled_at=scheduled_at,
                category="FOMC",
                impact="HIGH",
            )
        )
        current_month = None

    if not events:
        raise ContextSourceError("FOMC calendar contains no meetings")
    return tuple(events)


def fetch_fomc_events(
    transport: TextTransport,
    year: int,
) -> tuple[ScheduledEvent, ...]:
    return parse_fomc_calendar(
        transport.get_text(FOMC_CALENDAR_URL, timeout=10),
        year,
    )
