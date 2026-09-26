from datetime import date, datetime, timezone
from decimal import Decimal

from intrader.breadth import BreadthSnapshot
from intrader.market_brain import FamilyEvidence, MarketBrainSnapshot
from intrader.market_confirmation import (
    FuturesConfirmation,
    MarketConfirmationSnapshot,
    OrderFlowConfirmation,
    VixConfirmation,
)
from intrader.options_intelligence import OptionChainSnapshot
from intrader.price_structure import PriceStructureSnapshot
from intrader.records import build_decision_record


NOW = datetime(2026, 9, 28, 6, 30, tzinfo=timezone.utc)
DAY = date(2026, 9, 28)


def _price() -> PriceStructureSnapshot:
    return PriceStructureSnapshot(
        at=NOW,
        spot_close=Decimal("23150"),
        ema9=Decimal("23140"),
        ema20=Decimal("23120"),
        rsi14=Decimal("63"),
        atr14=Decimal("30"),
        candle_body=Decimal("8"),
        upper_wick=Decimal("2"),
        lower_wick=Decimal("2"),
        opening_range_high=Decimal("23100"),
        opening_range_low=Decimal("23020"),
        previous_session_high=Decimal("23200"),
        previous_session_low=Decimal("22800"),
        future_close=Decimal("23200"),
        future_vwap=Decimal("23160"),
        relative_volume=Decimal("1.4"),
    )


def _options() -> OptionChainSnapshot:
    return OptionChainSnapshot(
        at=NOW,
        lookback_minutes=5,
        contracts=(),
        total_call_open_interest=1000,
        total_put_open_interest=1200,
        open_interest_pcr=Decimal("1.2"),
        total_call_volume=2000,
        total_put_volume=2200,
        volume_pcr=Decimal("1.1"),
        max_call_open_interest_strike=Decimal("23200"),
        max_put_open_interest_strike=Decimal("23100"),
        max_call_open_interest_change_strike=Decimal("23200"),
        max_put_open_interest_change_strike=Decimal("23100"),
        call_open_interest_concentration=Decimal("0.3"),
        put_open_interest_concentration=Decimal("0.35"),
    )


def _market() -> MarketConfirmationSnapshot:
    return MarketConfirmationSnapshot(
        at=NOW,
        lookback_minutes=5,
        futures=FuturesConfirmation(
            ltp=Decimal("23200"),
            ltp_change=Decimal("25"),
            open_interest=100000,
            open_interest_change=5000,
            volume=200000,
            volume_change=25000,
            buildup="LONG_BUILDUP",
            basis=Decimal("50"),
            basis_change=Decimal("8"),
        ),
        vix=VixConfirmation(
            value=Decimal("12.4"),
            change=Decimal("0.1"),
            change_pct=Decimal("0.81"),
        ),
        order_flow=OrderFlowConfirmation(
            total_buy_sell_ratio=Decimal("1.4"),
            depth_buy_sell_ratio=Decimal("1.5"),
            depth_imbalance=Decimal("0.25"),
            best_bid=Decimal("23199"),
            best_ask=Decimal("23201"),
            spread=Decimal("2"),
            spread_bps=Decimal("0.86"),
        ),
    )


def _brain(state: str = "BULLISH SETUP") -> MarketBrainSnapshot:
    return MarketBrainSnapshot(
        state=state,
        direction_score=Decimal("64") if state == "BULLISH SETUP" else Decimal("-64"),
        entry_quality=Decimal("72"),
        reversal_risk=Decimal("28"),
        confidence=Decimal("76"),
        family_coverage=Decimal("100"),
        families=(
            FamilyEvidence("PRICE", Decimal("30"), Decimal("0.7")),
            FamilyEvidence("FUTURES", Decimal("25"), Decimal("0.6")),
            FamilyEvidence("OPTIONS", Decimal("20"), Decimal("0.5")),
            FamilyEvidence("BREADTH", Decimal("15"), Decimal("0.4")),
            FamilyEvidence("ORDER_FLOW", Decimal("10"), Decimal("0.3")),
        ),
        reasons=(),
    )


def _breadth() -> BreadthSnapshot:
    return BreadthSnapshot(
        at=NOW,
        total=50,
        advancing=32,
        declining=16,
        unchanged=2,
        advance_decline_ratio=Decimal("2"),
        equal_weight_breadth_pct=Decimal("32"),
        weighted_return_pct=None,
        top_positive_contributors=(),
        top_negative_contributors=(),
        sectors=(),
    )


def test_bullish_record_selects_call_and_rejects_put() -> None:
    record = build_decision_record(
        DAY, NOW, _price(), _options(), _market(), _brain(), breadth=_breadth()
    )

    assert record.action == "BUY_CALL"
    assert record.rejected_action == "BUY_PUT"
    assert record.brain_version == "brain-v0.1"
    assert record.rule_version == "rules-v0.1"
    assert record.regime == "TRENDING_UP"
    assert any(
        reason.thesis == "CHOSEN" and reason.reason_code == "PRICE_SUPPORTS_CALL"
        for reason in record.reasons
    )
    assert any(
        reason.thesis == "REJECTED"
        and reason.reason_code == "REJECT_BUY_PUT_PRICE"
        for reason in record.reasons
    )


def test_bearish_record_selects_put_and_rejects_call() -> None:
    brain = _brain("BEARISH SETUP")
    brain = MarketBrainSnapshot(
        state=brain.state,
        direction_score=brain.direction_score,
        entry_quality=brain.entry_quality,
        reversal_risk=brain.reversal_risk,
        confidence=brain.confidence,
        family_coverage=brain.family_coverage,
        families=tuple(
            FamilyEvidence(f.name, f.weight, -abs(f.value))
            for f in brain.families
        ),
        reasons=(),
    )

    record = build_decision_record(
        DAY, NOW, _price(), _options(), _market(), brain, breadth=_breadth()
    )

    assert record.action == "BUY_PUT"
    assert record.rejected_action == "BUY_CALL"
    assert any(
        reason.thesis == "REJECTED"
        and reason.reason_code == "REJECT_BUY_CALL_PRICE"
        for reason in record.reasons
    )


def test_same_inputs_produce_same_decision_id() -> None:
    first = build_decision_record(
        DAY, NOW, _price(), _options(), _market(), _brain(), breadth=_breadth()
    )
    second = build_decision_record(
        DAY, NOW, _price(), _options(), _market(), _brain(), breadth=_breadth()
    )

    assert first.decision_id == second.decision_id


def test_wait_is_recorded_without_fake_opposite_thesis() -> None:
    brain = MarketBrainSnapshot(
        state="WAIT",
        direction_score=Decimal("10"),
        entry_quality=Decimal("40"),
        reversal_risk=Decimal("20"),
        confidence=Decimal("30"),
        family_coverage=Decimal("100"),
        families=_brain().families,
        reasons=("DIRECTION_WEAK", "CONFIDENCE_LOW"),
    )

    record = build_decision_record(
        DAY, NOW, _price(), _options(), _market(), brain, breadth=_breadth()
    )

    assert record.action == "WAIT"
    assert record.rejected_action is None
    assert any(reason.reason_code == "DIRECTION_WEAK" for reason in record.reasons)
