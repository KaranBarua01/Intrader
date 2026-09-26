from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from intrader.outcome_pipeline import SettleShadowResult
from intrader.outcomes import ShadowOutcome


NOW = datetime(2026, 9, 28, 7, 0, tzinfo=timezone.utc)


def test_settlement_result_preserves_idempotency_status() -> None:
    outcome = ShadowOutcome(
        trade_id="SHD-1",
        evaluated_at=NOW,
        exit_at=NOW,
        exit_reason="TARGET",
        exit_price=Decimal("130"),
        gross_pnl=Decimal("1950"),
        estimated_friction=Decimal("7.5"),
        adjusted_pnl=Decimal("1942.5"),
        gross_return_pct=Decimal("30"),
        adjusted_return_pct=Decimal("29.88"),
        mfe_price=Decimal("31"),
        mae_price=Decimal("-5"),
        mfe_amount=Decimal("2015"),
        mae_amount=Decimal("-325"),
        spot_exit=Decimal("23200"),
        spot_change=Decimal("50"),
        directional_spot_change=Decimal("50"),
        forward_returns=((1, Decimal("2")), (3, Decimal("5")), (5, Decimal("10")), (10, None), (15, None), (30, None)),
    )

    result = SettleShadowResult(outcome, True)

    assert result.inserted is True
    assert result.outcome.exit_reason == "TARGET"
    assert result.outcome.adjusted_pnl < result.outcome.gross_pnl
