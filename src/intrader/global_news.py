"""Global market-news acquisition through the public GDELT DOC API."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

import requests

from intrader.context import NewsItem


GDELT_DOC_URL = "https://api.gdeltproject.org/api/v2/doc/doc"
GLOBAL_MARKET_QUERY = (
    '("Federal Reserve" OR FOMC OR CPI OR PPI OR payrolls OR inflation '
    'OR "Treasury yields" OR "bond yields" OR "S&P 500" OR Nasdaq OR Dow '
    'OR crude OR oil OR OPEC OR DXY OR USDINR OR dollar OR rupee '
    'OR tariffs OR sanctions OR "central bank" OR recession OR "stock market" '
    'OR "global markets" OR RBI OR ECB OR BOJ OR China OR geopolitics)'
)

_MARKET_TERMS = {
    "federal reserve": 5, "fomc": 5, "cpi": 5, "ppi": 4, "payroll": 5,
    "jobs report": 4, "inflation": 4, "treasury": 4, "bond yield": 4,
    "yield": 2, "s&p 500": 4, "nasdaq": 4, "dow": 3, "stock market": 3,
    "global market": 3, "crude": 4, "oil": 3, "opec": 4, "dxy": 5,
    "usdinr": 5, "dollar": 2, "rupee": 3, "currency": 2, "rbi": 5,
    "reserve bank of india": 5, "ecb": 4, "european central bank": 4,
    "boj": 4, "bank of japan": 4, "tariff": 3, "sanction": 3,
    "recession": 3, "china": 2, "geopolit": 2, "war": 1,
}
_TRUSTED_MARKET_DOMAINS = {
    "reuters.com", "bloomberg.com", "cnbc.com", "ft.com", "wsj.com",
    "marketwatch.com", "investing.com", "moneycontrol.com",
    "economictimes.indiatimes.com", "business-standard.com", "livemint.com",
}


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


def market_relevance_score(title: str, domain: str = "") -> int:
    """Return a conservative headline relevance score for market context."""

    text = " ".join(title.lower().split())
    score = sum(weight for term, weight in _MARKET_TERMS.items() if term in text)
    clean_domain = domain.lower().removeprefix("www.")
    if clean_domain in _TRUSTED_MARKET_DOMAINS:
        score += 2
    return score


def _normalized_title(title: str) -> str:
    return " ".join(
        "".join(ch.lower() if ch.isalnum() else " " for ch in title).split()
    )


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
    seen_titles: set[str] = set()
    for article in articles:
        if not isinstance(article, dict):
            continue
        title = str(article.get("title") or "").strip()
        url = str(article.get("url") or "").strip()
        published = _parse_seen(article.get("seendate"))
        domain = str(article.get("domain") or "GDELT").strip()
        normalized = _normalized_title(title)
        if (
            not title
            or not url
            or published is None
            or url in seen_urls
            or normalized in seen_titles
            or market_relevance_score(title, domain) < 3
        ):
            continue
        seen_urls.add(url)
        seen_titles.add(normalized)
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
