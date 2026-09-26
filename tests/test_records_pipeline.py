from datetime import date, datetime, timezone
from decimal import Decimal

from intrader.config import AppConfig
from intrader.market_brain import FamilyEvidence, MarketBrainSnapshot
from intrader.records import DecisionRecord, DecisionReason
from intrader.records_pipeline import RecordDecisionResult


NOW = datetime(2026, 9, 28, 6, 30, tzinfo=timezone.utc)
DAY = date(2026, 9, 28)


def _record() -> DecisionRecord:
    return DecisionRecord(
        decision_id="DEC-1",
        decided_at=NOW,
        session_date=DAY,
        brain_version="brain-v0.1",
        rule_version="rules-v0.1",
        brain_state="BULLISH SETUP",
        action="BUY_CALL",
        rejected_action="BUY_PUT",
        direction_score=Decimal("62"),
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
        rsi14=Decimal("63"),
        atr14=Decimal("30"),
        opening_range_high=Decimal("23100"),
        opening_range_low=Decimal("23020"),
        future_oi=100000,
        future_oi_change=5000,
        future_volume_change=20000,
        basis=Decimal("50"),
        basis_change=Decimal("5"),
        oi_pcr=Decimal("1.2"),
        volume_pcr=Decimal("1.1"),
        breadth_pct=Decimal("30"),
        depth_imbalance=Decimal("0.2"),
        high_impact_event_active=False,
        families=(FamilyEvidence("PRICE", Decimal("30"), Decimal("0.7")),),
        reasons=(
            DecisionReason(
                "CHOSEN", "PRICE_SUPPORTS_CALL", "PRICE",
                Decimal("0.7"), 1, "Price supports call."
            ),
        ),
    )


def test_result_model_preserves_insert_status() -> None:
    result = RecordDecisionResult(_record(), True)

    assert result.inserted is True
    assert result.record.action == "BUY_CALL"
    assert result.record.rejected_action == "BUY_PUT"
