from datetime import datetime, timezone
from decimal import Decimal

from intrader.__main__ import main
from intrader.options_intelligence import (
    OptionChainSnapshot,
    OptionContractMetrics,
)


class DummyStore:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None


def _contract(token: str, strike: str, option_type: str) -> OptionContractMetrics:
    return OptionContractMetrics(
        token=token,
        strike=Decimal(strike),
        option_type=option_type,
        current_ltp=Decimal("100"),
        ltp_change=Decimal("5"),
        ltp_change_pct=Decimal("5.263157894736842105263157895"),
        current_open_interest=1000,
        open_interest_change=100,
        open_interest_change_pct=Decimal("11.11111111111111111111111111"),
        current_volume=2000,
        volume_change=300,
        buildup="LONG_BUILDUP",
    )


def test_options_cli_is_local_and_prints_measurements_only(monkeypatch, capsys) -> None:
    snapshot = OptionChainSnapshot(
        at=datetime(2026, 9, 28, 6, 30, tzinfo=timezone.utc),
        lookback_minutes=5,
        contracts=(
            _contract("CE", "23150", "CE"),
            _contract("PE", "23150", "PE"),
        ),
        total_call_open_interest=1000,
        total_put_open_interest=1200,
        open_interest_pcr=Decimal("1.2"),
        total_call_volume=2000,
        total_put_volume=2200,
        volume_pcr=Decimal("1.1"),
        max_call_open_interest_strike=Decimal("23150"),
        max_put_open_interest_strike=Decimal("23150"),
        max_call_open_interest_change_strike=Decimal("23150"),
        max_put_open_interest_change_strike=Decimal("23150"),
        call_open_interest_concentration=Decimal("1"),
        put_open_interest_concentration=Decimal("1"),
    )

    monkeypatch.setattr(
        "intrader.__main__.SQLiteStore",
        lambda *_args: DummyStore(),
    )
    monkeypatch.setattr(
        "intrader.__main__.build_stored_options_intelligence",
        lambda *_args, **_kwargs: snapshot,
    )

    def forbidden_auth(*_args, **_kwargs):
        raise AssertionError("options diagnostic must not authenticate")

    monkeypatch.setattr("intrader.__main__.authenticate", forbidden_auth)

    exit_code = main(["options-intelligence", "2026-09-28", "12:00"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "OPTIONS INTELLIGENCE OK" in output
    assert "OI PCR: 1.2" in output
    assert "Volume PCR: 1.1" in output
    assert "23150 CE" in output
    assert "23150 PE" in output
    assert "BUY" not in output
    assert "SELL" not in output
    assert "BULLISH" not in output
    assert "BEARISH" not in output


def test_options_cli_rejects_bad_time_without_opening_storage(monkeypatch, capsys) -> None:
    opened = False

    def forbidden_store(*_args):
        nonlocal opened
        opened = True
        raise AssertionError

    monkeypatch.setattr("intrader.__main__.SQLiteStore", forbidden_store)

    exit_code = main(["options-intelligence", "2026-09-28", "bad"])

    assert exit_code == 1
    assert not opened
    assert capsys.readouterr().out.strip() == "OPTIONS INTELLIGENCE UNAVAILABLE"
