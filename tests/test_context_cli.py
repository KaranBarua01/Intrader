from datetime import datetime, timezone

from intrader.__main__ import main
from intrader.context import ContextSnapshot, NewsItem, ScheduledEvent
from intrader.context_pipeline import ContextRefreshResult


class DummyStore:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None


def test_context_cli_prints_source_health_and_event_windows(monkeypatch, capsys) -> None:
    at = datetime(2026, 9, 28, 6, 30, tzinfo=timezone.utc)
    event = ScheduledEvent(
        "BLS", "Consumer Price Index", at, "US_CPI", "HIGH"
    )
    snapshot = ContextSnapshot(
        at=at,
        recent_news=(
            NewsItem(
                "RBI",
                "RBI release",
                at,
                "https://rbi.example/1",
                "RBI_PRESS_RELEASE",
            ),
        ),
        upcoming_events=(event,),
        active_event_windows=(event,),
        minutes_to_next_high_impact=0.0,
        sources=("BLS", "RBI"),
    )
    result = ContextRefreshResult(
        snapshot=snapshot,
        refreshed_sources=("BLS", "RBI"),
        failed_sources=("FED",),
    )

    monkeypatch.setattr(
        "intrader.__main__.SQLiteStore",
        lambda *_args: DummyStore(),
    )
    monkeypatch.setattr(
        "intrader.__main__.RequestsContextTransport",
        lambda: object(),
    )
    monkeypatch.setattr(
        "intrader.__main__.refresh_context",
        lambda *_args, **_kwargs: result,
    )

    exit_code = main(["context", "2026-09-28", "12:00"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "CONTEXT OK" in output
    assert "Refreshed sources: BLS, RBI" in output
    assert "Failed sources: FED" in output
    assert "Active event windows: 1" in output
    assert "Recent news: 1" in output
    assert "BUY" not in output
    assert "SELL" not in output
    assert "BULLISH" not in output
    assert "BEARISH" not in output
