from datetime import datetime, timezone

from intrader.global_news import fetch_global_market_news, market_relevance_score


class Response:
    def raise_for_status(self):
        return None

    def json(self):
        return {
            "articles": [
                {
                    "title": "Global markets react to central bank decision",
                    "url": "https://example.test/global",
                    "seendate": "20260928T063000Z",
                    "domain": "example.test",
                },
                {
                    "title": "Duplicate",
                    "url": "https://example.test/global",
                    "seendate": "20260928T062900Z",
                    "domain": "example.test",
                },
            ]
        }


def test_global_news_maps_gdelt_articles_to_context_news(monkeypatch) -> None:
    monkeypatch.setattr("intrader.global_news.requests.get", lambda *_args, **_kwargs: Response())
    start = datetime(2026, 9, 28, 6, 0, tzinfo=timezone.utc)
    end = datetime(2026, 9, 28, 7, 0, tzinfo=timezone.utc)

    items = fetch_global_market_news(start, end)

    assert len(items) == 1
    assert items[0].source == "example.test"
    assert items[0].category == "GLOBAL_MARKET_NEWS"
    assert items[0].published_at == datetime(2026, 9, 28, 6, 30, tzinfo=timezone.utc)



def test_market_relevance_score_rejects_unrelated_local_story() -> None:
    assert market_relevance_score(
        "Local council opens a new park after weekend ceremony",
        "example.test",
    ) < 3


def test_market_relevance_score_prioritizes_macro_market_context() -> None:
    assert market_relevance_score(
        "Federal Reserve decision pushes Treasury yields and Nasdaq lower",
        "reuters.com",
    ) >= 10
