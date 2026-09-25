from datetime import date, datetime, timezone
from decimal import Decimal

from intrader.__main__ import main
from intrader.checkpoint2 import Checkpoint2Report
from intrader.instruments import Instrument, NiftyInstruments
from intrader.market_confirmation import (
    FuturesConfirmation,
    MarketConfirmationSnapshot,
    OrderFlowConfirmation,
    VixConfirmation,
)


class DummyStore:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None


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


def test_market_confirmation_cli_prints_raw_measurements(monkeypatch, capsys) -> None:
    snapshot = MarketConfirmationSnapshot(
        at=datetime(2026, 9, 28, 6, 30, tzinfo=timezone.utc),
        lookback_minutes=5,
        futures=FuturesConfirmation(
            ltp=Decimal("23180"),
            ltp_change=Decimal("30"),
            open_interest=1200,
            open_interest_change=200,
            volume=6000,
            volume_change=1000,
            buildup="LONG_BUILDUP",
            basis=Decimal("60"),
            basis_change=Decimal("10"),
        ),
        vix=VixConfirmation(
            value=Decimal("12.6"),
            change=Decimal("0.6"),
            change_pct=Decimal("5"),
        ),
        order_flow=OrderFlowConfirmation(
            total_buy_sell_ratio=Decimal("1.5"),
            depth_buy_sell_ratio=Decimal("1.5"),
            depth_imbalance=Decimal("0.2"),
            best_bid=Decimal("23179"),
            best_ask=Decimal("23181"),
            spread=Decimal("2"),
            spread_bps=Decimal("0.8628"),
        ),
    )

    monkeypatch.setattr("intrader.__main__.CredentialStore", lambda: object())
    monkeypatch.setattr("intrader.__main__.RequestsTransport", lambda: object())
    monkeypatch.setattr("intrader.__main__.authenticate", lambda *_args: object())
    monkeypatch.setattr(
        "intrader.__main__.check_market_access",
        lambda *_args, **_kwargs: Checkpoint2Report(
            Decimal("23120"), _bundle()
        ),
    )
    monkeypatch.setattr(
        "intrader.__main__.SQLiteStore",
        lambda *_args: DummyStore(),
    )
    monkeypatch.setattr(
        "intrader.__main__.build_stored_market_confirmation",
        lambda *_args, **_kwargs: snapshot,
    )

    exit_code = main(["market-confirmation", "2026-09-28", "12:00"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "MARKET CONFIRMATION OK" in output
    assert "Future dOI: 200" in output
    assert "Basis change: 10" in output
    assert "VIX change %: 5" in output
    assert "Depth imbalance: 0.2" in output
    assert "BUY" not in output
    assert "SELL" not in output
    assert "BULLISH" not in output
    assert "BEARISH" not in output
