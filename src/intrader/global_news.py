"""Global market-news acquisition through the public GDELT DOC API."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import requests

from intrader.context import NewsItem


GDELT_DOC_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
GLOBAL_MARKET_QUERY = (
    '("Federal Reserve" OR inflation OR "bond yields" OR oil OR crude OR tariffs '
    'OR sanctions OR "central bank" OR recession OR "stock market" OR "US China" '
    'OR geopolitics OR currency OR dollar OR "global markets")'
)


class GlobalNewsError(Exception):
    """Global market-news retrieval failed or returned invalid data."""


def _parse_seen(value: object) -> datetime | None:
    text = str(value or "").strip()
    for fmt in ("%Y%m%dT%H%M%SZ", "%Y%m%d%H%M%S"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def fetch_global_market_news(
    start: datetime | None = None,
    end: datetime | None = None,
    *,
    max_records: int = 75,
) -> tuple[NewsItem, ...]:
    """Fetch global market-relevant headlines without API credentials."""

    end = end or datetime.now(timezone.utc)
    start = start or (end - timedelta(hours=24))
    if start.tzinfo is None or end.tzinfo is None or start >= end:
        raise GlobalNewsError("global news window invalid")
    max_records = min(max(int(max_records), 1), 250)
    params = {
        "query": GLOBAL_MARKET_QUERY,
        "mode": "artlist",
        "format": "json",
        "sort": "datedesc",
        "maxrecords": str(max_records),
        "startdatetime": start.astimezone(timezone.utc).strftime("%Y%m%d%H%M%S"),
        "enddatetime": end.astimezone(timezone.utc).strftime("%Y%m%d%H%M%S"),
    }
    try:
        response = requests.get(
            GDELT_DOC_URL,
            params=params,
            timeout=20,
            headers={"User-Agent": "Intrader/0.4"},
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError):
        raise GlobalNewsError("global news source unavailable") from None

    articles = payload.get("articles") if isinstance(payload, dict) else None
    if not isinstance(articles, list):
        raise GlobalNewsError("global news response invalid")

    items: list[NewsItem] = []
    seen_urls: set[str] = set()
    for article in articles:
        if not isinstance(article, dict):
            continue
        title = str(article.get("title") or "").strip()
        url = str(article.get("url") or "").strip()
        published = _parse_seen(article.get("seendate"))
        domain = str(article.get("domain") or "GDELT").strip()
        if not title or not url or published is None or url in seen_urls:
            continue
        seen_urls.add(url)
        items.append(
            NewsItem(
                source=domain or "GDELT",
                title=title,
                published_at=published,
                url=url,
                category="GLOBAL_MARKET_NEWS",
            )
        )
    return tuple(sorted(items, key=lambda item: item.published_at, reverse=True))
