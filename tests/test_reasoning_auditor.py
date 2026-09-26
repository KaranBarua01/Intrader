from datetime import date, datetime, timezone
from decimal import Decimal

from intrader.market_brain import FamilyEvidence
from intrader.outcomes import ShadowOutcome
from intrader.reasoning_auditor import AUDITOR_VERSION, build_reason_audits
from intrader.records import DecisionReason, DecisionRecord


NOW = datetime(2026, 9, 28, 6, 30, tzinfo=timezone.utc)


def _decision() -> DecisionRecord:
    return DecisionRecord(
        decision_id="DEC-1",
        decided_at=NOW,
        session_date=date(2026, 9, 28),
        brain_version="brain-v0.1",
        rule_version="rules-v0.1",
        brain_state="BULLISH SETUP",
        action="BUY_CALL",
        rejected_action="BUY_PUT",
        direction_score=Decimal("60"),
        entry_quality=Decimal("70"),
        reversal_risk=Decimal("30"),
        confidence=Decimal("75"),
        family_coverage=Decimal("100"),
        regime="TRENDING_UP",
        spot_price=Decimal("23150"),
        future_price=Decimal("23200"),
        vix=Decimal("12"),
        ema9=Decimal("23140"),
        ema20=Decimal("23120"),
        rsi14=Decimal("62"),
        atr14=Decimal("30"),
        opening_range_high=Decimal("23100"),
        opening_range_low=Decimal("23000"),
        future_oi=100000,
        future_oi_change=5000,
        future_volume_change=20000,
        basis=Decimal("50"),
        basis_change=Decimal("5"),
        oi_pcr=Decimal("1"),
        volume_pcr=Decimal("1"),
        breadth_pct=Decimal("30"),
        depth_imbalance=Decimal("0.2"),
        high_impact_event_active=False,
        families=(FamilyEvidence("PRICE", Decimal("30"), Decimal("0.7")),),
        reasons=(
            DecisionReason(
                "CHOSEN", "PRICE_SUPPORTS_CALL", "PRICE",
                Decimal("0.7"), 1, "Price supports call."
            ),
            DecisionReason(
                "REJECTED", "REJECT_BUY_PUT_PRICE", "PRICE",
                Decimal("0.7"), 1, "Price rejects put."
            ),
            DecisionReason(
                "GATE", "VIX_STABLE", "RISK",
                Decimal("0.5"), 0, "VIX stable."
            ),
        ),
    )


def _outcome(spot_change: Decimal | None, pnl: str) -> ShadowOutcome:
    return ShadowOutcome(
        trade_id="SHD-1",
        evaluated_at=NOW,
        exit_at=NOW,
        exit_reason="TARGET",
        exit_price=Decimal("130"),
        gross_pnl=Decimal(pnl),
        estimated_friction=Decimal("5"),
        adjusted_pnl=Decimal(pnl),
        gross_return_pct=Decimal("30"),
        adjusted_return_pct=Decimal("30"),
        mfe_price=Decimal("30"),
        mae_price=Decimal("-5"),
        mfe_amount=Decimal("1950"),
        mae_amount=Decimal("-325"),
        spot_exit=None,
        spot_change=spot_change,
        directional_spot_change=spot_change,
        forward_returns=(),
    )


def test_directional_reasons_can_be_supported_while_gates_are_ungraded() -> None:
    audits = build_reason_audits(_decision(), _outcome(Decimal("40"), "1000"))

    by_code = {audit.reason_code: audit for audit in audits}
    assert by_code["PRICE_SUPPORTS_CALL"].verdict == "SUPPORTED"
    assert by_code["REJECT_BUY_PUT_PRICE"].verdict == "SUPPORTED"
    assert by_code["VIX_STABLE"].verdict == "UNGRADED"
    assert all(audit.trade_result == "PROFIT" for audit in audits)
    assert all(audit.auditor_version == AUDITOR_VERSION for audit in audits)


def test_reason_can_be_contradicted_even_when_trade_result_is_recorded_separately() -> None:
    audits = build_reason_audits(_decision(), _outcome(Decimal("-20"), "250"))

    price = next(
        audit for audit in audits if audit.reason_code == "PRICE_SUPPORTS_CALL"
    )
    assert price.verdict == "CONTRADICTED"
    assert price.trade_result == "PROFIT"


def test_missing_underlying_move_is_unknown_for_directional_reasons() -> None:
    audits = build_reason_audits(_decision(), _outcome(None, "-100"))

    price = next(
        audit for audit in audits if audit.reason_code == "PRICE_SUPPORTS_CALL"
    )
    assert price.verdict == "UNKNOWN"
    assert price.trade_result == "LOSS"
