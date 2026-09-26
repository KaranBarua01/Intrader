from datetime import date, datetime, timezone
from decimal import Decimal

from intrader.records import DecisionRecord
from intrader.records_pipeline import RecordDecisionResult
from intrader.shadow import ShadowTrade
from intrader.shadow_pipeline import ShadowStepResult


NOW = datetime(2026, 9, 28, 6, 30, tzinfo=timezone.utc)


def test_shadow_step_result_can_record_wait_without_trade() -> None:
    record = DecisionRecord(
        decision_id="DEC-WAIT",
        decided_at=NOW,
        session_date=date(2026, 9, 28),
        brain_version="brain-v0.1",
        rule_version="rules-v0.1",
        brain_state="WAIT",
        action="WAIT",
        rejected_action=None,
        direction_score=Decimal("10"),
        entry_quality=Decimal("40"),
        reversal_risk=Decimal("20"),
        confidence=Decimal("30"),
        family_coverage=Decimal("100"),
        regime="RANGE",
        spot_price=Decimal("23150"),
        future_price=Decimal("23200"),
        vix=Decimal("12"),
        ema9=Decimal("23140"),
        ema20=Decimal("23140"),
        rsi14=Decimal("50"),
        atr14=Decimal("30"),
        opening_range_high=Decimal("23200"),
        opening_range_low=Decimal("23100"),
        future_oi=100000,
        future_oi_change=0,
        future_volume_change=10000,
        basis=Decimal("50"),
        basis_change=Decimal("0"),
        oi_pcr=Decimal("1"),
        volume_pcr=Decimal("1"),
        breadth_pct=Decimal("0"),
        depth_imbalance=Decimal("0"),
        high_impact_event_active=False,
        families=(),
        reasons=(),
    )

    result = ShadowStepResult(
        RecordDecisionResult(record, True),
        None,
        False,
    )

    assert result.decision.record.action == "WAIT"
    assert result.trade is None
    assert result.trade_inserted is False
