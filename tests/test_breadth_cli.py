from datetime import datetime, timezone
from decimal import Decimal

from intrader.__main__ import main
from intrader.breadth import BreadthSnapshot, SectorBreadth


class DummyStore:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None


def test_breadth_cli_is_local_and_descriptive(monkeypatch, capsys) -> None:
    snapshot = BreadthSnapshot(
        at=datetime(2026, 9, 28, 6, 30, tzinfo=timezone.utc),
        total=50,
        advancing=30,
        declining=18,
        unchanged=2,
        advance_decline_ratio=Decimal("1.6667"),
        equal_weight_breadth_pct=Decimal("24"),
        weighted_return_pct=None,
        top_positive_contributors=(),
        top_negative_contributors=(),
        sectors=(
            SectorBreadth(
                "Financial Services",
                8,
                4,
                0,
                Decimal("33.3333333333"),
            ),
        ),
    )
    monkeypatch.setattr(
        "intrader.__main__.SQLiteStore",
        lambda *_args: DummyStore(),
    )
    monkeypatch.setattr(
        "intrader.__main__.build_stored_breadth",
        lambda *_args, **_kwargs: snapshot,
    )

    def forbidden_auth(*_args, **_kwargs):
        raise AssertionError("breadth diagnostic must not authenticate")

    monkeypatch.setattr("intrader.__main__.authenticate", forbidden_auth)

    exit_code = main(["breadth", "2026-09-28", "12:00"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "BREADTH OK" in output
    assert "Members: 50" in output
    assert "Advancing: 30" in output
    assert "Equal-weight breadth %: 24" in output
    assert "Weighted return %: N/A" in output
    assert "BUY" not in output
    assert "SELL" not in output
    assert "BULLISH" not in output
    assert "BEARISH" not in output
