from datetime import date
from decimal import Decimal

from intrader.__main__ import main
from intrader.backfill import BackfillReport
from intrader.checkpoint2 import Checkpoint2Report
from intrader.instruments import Instrument, NiftyInstruments


def _instrument(token: str, exchange: str, kind: str) -> Instrument:
    return Instrument(
        token, token, "NIFTY", kind, exchange,
        date(2026, 9, 29), Decimal("23150"), 65,
    )


def _bundle() -> NiftyInstruments:
    return NiftyInstruments(
        _instrument("spot", "NSE", "AMXIDX"),
        _instrument("vix", "NSE", "AMXIDX"),
        _instrument("future", "NFO", "FUTIDX"),
        date(2026, 9, 29),
        Decimal("23150"),
        (Decimal("23150"),),
        (_instrument("call", "NFO", "OPTIDX"),),
        (_instrument("put", "NFO", "OPTIDX"),),
    )


def test_init_storage_creates_database(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)

    exit_code = main(["init-storage"])

    assert exit_code == 0
    assert (tmp_path / "data" / "intrader.db").exists()
    assert capsys.readouterr().out.strip() == "STORAGE READY"


def test_backfill_cli_prints_counts_only(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    dummy_session = object()

    monkeypatch.setattr("intrader.__main__.CredentialStore", lambda: object())
    monkeypatch.setattr("intrader.__main__.RequestsTransport", lambda: object())
    monkeypatch.setattr("intrader.__main__.authenticate", lambda *_args: dummy_session)
    monkeypatch.setattr(
        "intrader.__main__.check_market_access",
        lambda *_args, **_kwargs: Checkpoint2Report(Decimal("23150"), _bundle()),
    )
    monkeypatch.setattr(
        "intrader.__main__.backfill_core_market",
        lambda *_args, **_kwargs: BackfillReport(300, 100, 3),
    )

    exit_code = main(
        ["backfill-session", "2026-09-25", "09:15", "2026-09-25", "11:30"]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "BACKFILL OK" in output
    assert "Candle rows processed: 300" in output
    assert "OI rows processed: 100" in output
    assert "dummy" not in output


def test_backfill_cli_rejects_bad_time_without_network(monkeypatch, capsys) -> None:
    called = False

    def should_not_authenticate(*_args):
        nonlocal called
        called = True
        raise AssertionError

    monkeypatch.setattr("intrader.__main__.authenticate", should_not_authenticate)

    exit_code = main(
        ["backfill-session", "not-a-date", "09:15", "2026-09-25", "11:30"]
    )

    assert exit_code == 1
    assert not called
    assert capsys.readouterr().out.strip() == "BACKFILL UNAVAILABLE"
