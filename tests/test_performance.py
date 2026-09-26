from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from intrader.market_brain import FamilyEvidence
from intrader.outcomes import ShadowOutcome
from intrader.performance import build_records_manager_snapshot
from intrader.reasoning_auditor import ReasonAudit
from intrader.records import DecisionRecord
from intrader.shadow import ShadowTrade


NOW = datetime(2026, 9, 28, 6, 30, tzinfo=timezone.utc)


def _decision(index: int, action: str, regime: str) -> DecisionRecord:
    return DecisionRecord(
        decision_id=f"DEC-{index}",
        decided_at=NOW + timedelta(minutes=index),
        session_date=date(2026, 9, 28),
        brain_version="brain-v0.1",
        rule_version="rules-v0.1",
        brain_state="BULLISH SETUP" if action == "BUY_CALL" else "BEARISH SETUP",
        action=action,
        rejected_action="BUY_PUT" if action == "BUY_CALL" else "BUY_CALL",
        direction_score=Decimal("60"),
        entry_quality=Decimal("70"),
        reversal_risk=Decimal("30"),
        confidence=Decimal("75"),
        family_coverage=Decimal("100"),
        regime=regime,
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


def _trade(decision: DecisionRecord, index: int) -> ShadowTrade:
    return ShadowTrade(
        trade_id=f"SHD-{index}",
        decision_id=decision.decision_id,
        shadow_version="shadow-v0.1",
        opened_at=decision.decided_at,
        action=decision.action,
        token=f"opt-{index}",
        strike=Decimal("23150"),
        option_type="CE" if decision.action == "BUY_CALL" else "PE",
        entry_price=Decimal("100"),
        quantity=65,
        lot_size=65,
        lots=1,
        stop_price=Decimal("80"),
        target_price=Decimal("130"),
        max_minutes=30,
    )


def _outcome(trade: ShadowTrade, pnl: str) -> ShadowOutcome:
    value = Decimal(pnl)
    return ShadowOutcome(
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


def test_records_manager_tracks_pnl_expectancy_drawdown_and_groups() -> None:
    d1 = _decision(1, "BUY_CALL", "TRENDING_UP")
    d2 = _decision(2, "BUY_PUT", "TRENDING_DOWN")
    d3 = _decision(3, "BUY_CALL", "TRENDING_UP")
    t1, t2, t3 = _trade(d1, 1), _trade(d2, 2), _trade(d3, 3)
    completed = (
        (d1, t1, _outcome(t1, "1000")),
        (d2, t2, _outcome(t2, "-500")),
        (d3, t3, _outcome(t3, "250")),
    )
    audits = (
        ReasonAudit(
            t1.trade_id, d1.decision_id, "auditor-v0.1", "CHOSEN",
            "PRICE_SUPPORTS_CALL", "PRICE", 1, "SUPPORTED",
            "PROFIT", Decimal("1000"), Decimal("20")
        ),
        ReasonAudit(
            t3.trade_id, d3.decision_id, "auditor-v0.1", "CHOSEN",
            "PRICE_SUPPORTS_CALL", "PRICE", 1, "CONTRADICTED",
            "PROFIT", Decimal("250"), Decimal("-5")
        ),
    )

    result = build_records_manager_snapshot(
        (d1, d2, d3), completed, audits, starting_capital=Decimal("100000")
    )

    assert result.current_equity == Decimal("100750")
    assert result.overall.trades == 3
    assert result.overall.wins == 2
    assert result.overall.losses == 1
    assert result.overall.adjusted_pnl == Decimal("750")
    assert result.overall.expectancy == Decimal("250")
    assert result.overall.profit_factor == Decimal("2.5")
    assert result.overall.max_drawdown == Decimal("500")
    assert dict(result.decision_counts) == {"BUY_CALL": 2, "BUY_PUT": 1}
    assert dict(result.by_action)["BUY_CALL"].adjusted_pnl == Decimal("1250")
    assert result.reasons[0].reason_code == "PRICE_SUPPORTS_CALL"
    assert result.reasons[0].occurrences == 2
    assert result.reasons[0].supported == 1
    assert result.reasons[0].contradicted == 1
