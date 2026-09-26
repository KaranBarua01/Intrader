from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from intrader.calibration import calibrate_thresholds
from intrader.market_brain import FamilyEvidence
from intrader.outcomes import ShadowOutcome
from intrader.records import DecisionRecord
from intrader.shadow import ShadowTrade


NOW = datetime(2026, 9, 28, 6, 30, tzinfo=timezone.utc)


def _row(index: int, direction: str, confidence: str, entry: str, risk: str, pnl: str):
    decision = DecisionRecord(
        decision_id=f"DEC-{index}",
        decided_at=NOW + timedelta(minutes=index),
        session_date=date(2026, 9, 28),
        brain_version="brain-v0.1",
        rule_version="rules-v0.1",
        brain_state="BULLISH SETUP",
        action="BUY_CALL",
        rejected_action="BUY_PUT",
        direction_score=Decimal(direction),
        entry_quality=Decimal(entry),
        reversal_risk=Decimal(risk),
        confidence=Decimal(confidence),
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
        reasons=(),
    )
    trade = ShadowTrade(
        trade_id=f"SHD-{index}",
        decision_id=decision.decision_id,
        shadow_version="shadow-v0.1",
        opened_at=decision.decided_at,
        action="BUY_CALL",
        token=f"opt-{index}",
        strike=Decimal("23150"),
        option_type="CE",
        entry_price=Decimal("100"),
        quantity=65,
        lot_size=65,
        lots=1,
        stop_price=Decimal("80"),
        target_price=Decimal("130"),
        max_minutes=30,
    )
    value = Decimal(pnl)
    outcome = ShadowOutcome(
        trade_id=trade.trade_id,
        evaluated_at=trade.opened_at + timedelta(minutes=5),
        exit_at=trade.opened_at + timedelta(minutes=5),
        exit_reason="TARGET" if value > 0 else "STOP",
        exit_price=Decimal("130") if value > 0 else Decimal("80"),
        gross_pnl=value,
        estimated_friction=Decimal("0"),
        adjusted_pnl=value,
        gross_return_pct=Decimal("10"),
        adjusted_return_pct=Decimal("10"),
        mfe_price=Decimal("10"),
        mae_price=Decimal("-5"),
        mfe_amount=Decimal("650"),
        mae_amount=Decimal("-325"),
        spot_exit=None,
        spot_change=None,
        directional_spot_change=None,
        forward_returns=(),
    )
    return decision, trade, outcome


def test_calibration_uses_chronological_train_validation_test() -> None:
    rows = tuple(
        _row(
            index,
            direction="65" if index % 2 == 0 else "40",
            confidence="75" if index % 2 == 0 else "62",
            entry="70" if index % 2 == 0 else "56",
            risk="40" if index % 2 == 0 else "68",
            pnl="1000" if index % 2 == 0 else "-500",
        )
        for index in range(10)
    )

    report = calibrate_thresholds(
        rows,
        minimum_train_trades=2,
        created_at=NOW,
    )

    assert report.total_trades == 10
    assert report.train_trades == 6
    assert report.validation_trades == 2
    assert report.test_trades == 2
    assert report.candidate.direction_min >= Decimal("35")
    assert report.candidate.confidence_min >= Decimal("60")
    assert report.candidate.entry_quality_min >= Decimal("55")
    assert report.candidate.reversal_risk_max <= Decimal("70")
    assert report.train_metrics.expectancy is not None
    assert "baseline-or-stricter" in report.limitation
