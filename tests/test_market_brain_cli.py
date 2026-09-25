from decimal import Decimal

from intrader.__main__ import main
from intrader.market_brain import FamilyEvidence, MarketBrainSnapshot


class DummyStore:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None


class DummyReport:
    instruments = object()


def test_market_brain_cli_prints_final_scores_without_order_action(
    monkeypatch, capsys
) -> None:
    snapshot = MarketBrainSnapshot(
        state="BULLISH SETUP",
        direction_score=Decimal("62"),
        entry_quality=Decimal("74"),
        reversal_risk=Decimal("32"),
        confidence=Decimal("78"),
        family_coverage=Decimal("100"),
        families=(
            FamilyEvidence("PRICE", Decimal("30"), Decimal("0.7")),
            FamilyEvidence("FUTURES", Decimal("25"), Decimal("0.6")),
        ),
        reasons=(),
    )

    monkeypatch.setattr("intrader.__main__.CredentialStore", lambda: object())
    monkeypatch.setattr("intrader.__main__.RequestsTransport", lambda: object())
    monkeypatch.setattr("intrader.__main__.authenticate", lambda *_args: object())
    monkeypatch.setattr(
        "intrader.__main__.check_market_access",
        lambda *_args, **_kwargs: DummyReport(),
    )
    monkeypatch.setattr(
        "intrader.__main__.SQLiteStore",
        lambda *_args: DummyStore(),
    )
    monkeypatch.setattr(
        "intrader.__main__.build_stored_market_brain",
        lambda *_args, **_kwargs: snapshot,
    )

    exit_code = main(["market-brain", "2026-09-28", "12:00"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "MARKET BRAIN: BULLISH SETUP" in output
    assert "Direction: 62" in output
    assert "Entry quality: 74" in output
    assert "Reversal risk: 32" in output
    assert "Confidence: 78" in output
    assert "place order" not in output.lower()
    assert "execute order" not in output.lower()


def test_market_brain_cli_fails_closed_when_core_data_unavailable(
    monkeypatch, capsys
) -> None:
    monkeypatch.setattr(
        "intrader.__main__.authenticate",
        lambda *_args: (_ for _ in ()).throw(RuntimeError("offline")),
    )

    exit_code = main(["market-brain", "2026-09-28", "12:00"])

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "MARKET BRAIN: NO TRADE" in output
    assert "CORE_DATA_UNAVAILABLE" in output
