from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from intrader.market_confirmation import IndexSnapshot
from intrader.options_intelligence import OptionSnapshot
from intrader.outcomes import OutcomePending, evaluate_shadow_trade
from intrader.shadow import ShadowTrade


NOW = datetime(2026, 9, 28, 6, 30, tzinfo=timezone.utc)
EXPIRY = date(2026, 9, 29)


def _trade(action: str = "BUY_CALL") -> ShadowTrade:
    return ShadowTrade(
        trade_id="SHD-1",
        decision_id="DEC-1",
        shadow_version="shadow-v0.1",
        opened_at=NOW,
        action=action,
        token="opt",
        strike=Decimal("23150"),
        option_type="CE" if action == "BUY_CALL" else "PE",
        entry_price=Decimal("100"),
        quantity=65,
        lot_size=65,
        lots=1,
        stop_price=Decimal("80"),
        target_price=Decimal("130"),
        max_minutes=30,
    )


def _option(minute: int, price: str, sequence: int) -> OptionSnapshot:
    at = NOW + timedelta(minutes=minute)
    return OptionSnapshot(
        token="opt",
        exchange_at=at,
        received_at=at,
        sequence=sequence,
        expiry=EXPIRY,
        strike=Decimal("23150"),
        option_type="CE",
        ltp=Decimal(price),
        open_interest=1000,
        volume=2000 + sequence,
    )


def _spot(minute: int, price: str, sequence: int) -> IndexSnapshot:
    at = NOW + timedelta(minutes=minute)
    return IndexSnapshot("spot", at, at, sequence, Decimal(price))


def test_target_exit_records_profit_mfe_mae_and_underlying_move() -> None:
    option_rows = (
        _option(0, "100", 1),
        _option(1, "95", 2),
        _option(3, "110", 3),
        _option(5, "131", 4),
        _option(30, "140", 5),
    )
    spot_rows = (
        _spot(0, "23150", 1),
        _spot(5, "23190", 2),
    )

    result = evaluate_shadow_trade(
        _trade(), option_rows, spot_rows, Decimal("23150"),
        NOW + timedelta(minutes=31),
    )

    assert result.exit_reason == "TARGET"
    assert result.exit_price == Decimal("131.00")
    assert result.gross_pnl == Decimal("2015.00")
    assert result.adjusted_pnl < result.gross_pnl
    assert result.mfe_price == Decimal("31.00")
    assert result.mae_price == Decimal("-5.00")
    assert result.spot_change == Decimal("40")
    assert result.directional_spot_change == Decimal("40")


def test_put_directional_spot_change_is_inverted() -> None:
    option_rows = (
        _option(0, "100", 1),
        _option(5, "131", 2),
        _option(30, "135", 3),
    )
    spot_rows = (_spot(0, "23150", 1), _spot(5, "23110", 2))

    result = evaluate_shadow_trade(
        _trade("BUY_PUT"), option_rows, spot_rows, Decimal("23150"),
        NOW + timedelta(minutes=31),
    )

    assert result.directional_spot_change == Decimal("40")


def test_stop_exit_is_first_observed_boundary() -> None:
    rows = (
        _option(0, "100", 1),
        _option(2, "79", 2),
        _option(3, "140", 3),
        _option(30, "120", 4),
    )

    result = evaluate_shadow_trade(
        _trade(), rows, (), Decimal("23150"),
        NOW + timedelta(minutes=31),
    )

    assert result.exit_reason == "STOP"
    assert result.exit_price == Decimal("79.00")
    assert result.gross_pnl == Decimal("-1365.00")


def test_open_trade_remains_pending_before_timeout() -> None:
    rows = (_option(0, "100", 1), _option(10, "105", 2))

    with pytest.raises(OutcomePending, match="horizon incomplete"):
        evaluate_shadow_trade(
            _trade(), rows, (), Decimal("23150"),
            NOW + timedelta(minutes=10),
        )


def test_timeout_uses_fresh_terminal_snapshot() -> None:
    rows = (
        _option(0, "100", 1),
        _option(30, "108", 2),
    )

    result = evaluate_shadow_trade(
        _trade(), rows, (), Decimal("23150"),
        NOW + timedelta(minutes=31),
    )

    assert result.exit_reason == "TIMEOUT"
    assert result.exit_price == Decimal("108.00")
    assert result.gross_pnl == Decimal("520.00")
