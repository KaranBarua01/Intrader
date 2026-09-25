from datetime import date, datetime, timezone
from decimal import Decimal

from intrader.__main__ import main
from intrader.checkpoint2 import Checkpoint2Report
from intrader.instruments import Instrument, NiftyInstruments
from intrader.price_structure import PriceStructureSnapshot


def _instrument(token: str, exchange: str, kind: str) -> Instrument:
    return Instrument(
        token,
        token,
        "NIFTY",
        kind,
        exchange,
        date(2026, 9, 29),
        Decimal("23150"),
        65,
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


class DummyStore:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None


def test_price_structure_cli_prints_measurements_without_signal_language(
    monkeypatch, capsys
) -> None:
    snapshot = PriceStructureSnapshot(
        at=datetime(2026, 9, 28, 6, 30, tzinfo=timezone.utc),
        spot_close=Decimal("23150"),
        ema9=Decimal("23140"),
        ema20=Decimal("23120"),
        rsi14=Decimal("62.5"),
        atr14=Decimal("28.4"),
        candle_body=Decimal("12"),
        upper_wick=Decimal("5"),
        lower_wick=Decimal("3"),
        opening_range_high=Decimal("23080"),
        opening_range_low=Decimal("22990"),
        previous_session_high=Decimal("23210"),
        previous_session_low=Decimal("22850"),
        future_close=Decimal("23200"),
        future_vwap=Decimal("23170"),
        relative_volume=Decimal("1.35"),
    )

    monkeypatch.setattr("intrader.__main__.CredentialStore", lambda: object())
    monkeypatch.setattr("intrader.__main__.RequestsTransport", lambda: object())
    monkeypatch.setattr("intrader.__main__.authenticate", lambda *_args: object())
    monkeypatch.setattr(
        "intrader.__main__.check_market_access",
        lambda *_args, **_kwargs: Checkpoint2Report(
            Decimal("23150"),
            _bundle(),
        ),
    )
    monkeypatch.setattr(
        "intrader.__main__.SQLiteStore",
        lambda *_args: DummyStore(),
    )
    monkeypatch.setattr(
        "intrader.__main__.build_stored_price_structure",
        lambda *_args, **_kwargs: snapshot,
    )

    exit_code = main(["price-structure", "2026-09-28", "12:00"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "PRICE STRUCTURE OK" in output
    assert "EMA 9: 23140" in output
    assert "RSI 14: 62.5" in output
    assert "Future VWAP: 23170" in output
    assert "Relative volume: 1.35" in output
    assert "BUY" not in output
    assert "SELL" not in output


def test_price_structure_cli_rejects_bad_time_before_network(monkeypatch, capsys) -> None:
    called = False

    def forbidden_auth(*_args):
        nonlocal called
        called = True
        raise AssertionError

    monkeypatch.setattr("intrader.__main__.authenticate", forbidden_auth)

    exit_code = main(["price-structure", "2026-09-28", "bad"])

    assert exit_code == 1
    assert not called
    assert capsys.readouterr().out.strip() == "PRICE STRUCTURE UNAVAILABLE"
