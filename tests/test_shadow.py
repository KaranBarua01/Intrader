from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal

from intrader.market_brain import FamilyEvidence
from intrader.options_intelligence import OptionChainSnapshot, OptionContractMetrics
from intrader.records import DecisionRecord
from intrader.shadow import SHADOW_VERSION, build_shadow_trade


NOW = datetime(2026, 9, 28, 6, 30, tzinfo=timezone.utc)


def _decision(action: str) -> DecisionRecord:
    return DecisionRecord(
        decision_id=f"DEC-{action}",
        decided_at=NOW,
        session_date=date(2026, 9, 28),
        brain_version="brain-v0.1",
        rule_version="rules-v0.1",
        brain_state=(
            "BULLISH SETUP" if action == "BUY_CALL"
            else "BEARISH SETUP" if action == "BUY_PUT"
            else "WAIT"
        ),
        action=action,
        rejected_action=(
            "BUY_PUT" if action == "BUY_CALL"
            else "BUY_CALL" if action == "BUY_PUT"
            else None
        ),
        direction_score=Decimal("60"),
        entry_quality=Decimal("70"),
        reversal_risk=Decimal("30"),
        confidence=Decimal("75"),
        family_coverage=Decimal("100"),
        regime="TRENDING_UP",
        spot_price=Decimal("23155"),
        future_price=Decimal("23200"),
        vix=Decimal("12"),
        ema9=Decimal("23140"),
        ema20=Decimal("23120"),
        rsi14=Decimal("62"),
        atr14=Decimal("30"),
        opening_range_high=Decimal("23100"),
        opening_range_low=Decimal("23020"),
        future_oi=100000,
        future_oi_change=5000,
        future_volume_change=20000,
        basis=Decimal("45"),
        basis_change=Decimal("5"),
        oi_pcr=Decimal("1.1"),
        volume_pcr=Decimal("1"),
        breadth_pct=Decimal("25"),
        depth_imbalance=Decimal("0.2"),
        high_impact_event_active=False,
        families=(FamilyEvidence("PRICE", Decimal("30"), Decimal("0.7")),),
        reasons=(),
    )


def _contract(token: str, strike: str, option_type: str, ltp: str) -> OptionContractMetrics:
    return OptionContractMetrics(
        token=token,
        strike=Decimal(strike),
        option_type=option_type,
        current_ltp=Decimal(ltp),
        ltp_change=Decimal("1"),
        ltp_change_pct=Decimal("1"),
        current_open_interest=1000,
        open_interest_change=100,
        open_interest_change_pct=Decimal("10"),
        current_volume=2000,
        volume_change=200,
        buildup="LONG_BUILDUP",
    )


def _options() -> OptionChainSnapshot:
    contracts = (
        _contract("23100CE", "23100", "CE", "120"),
        _contract("23150CE", "23150", "CE", "100"),
        _contract("23200CE", "23200", "CE", "80"),
        _contract("23100PE", "23100", "PE", "75"),
        _contract("23150PE", "23150", "PE", "95"),
        _contract("23200PE", "23200", "PE", "115"),
    )
    return OptionChainSnapshot(
        at=NOW,
        lookback_minutes=5,
        contracts=contracts,
        total_call_open_interest=3000,
        total_put_open_interest=3000,
        open_interest_pcr=Decimal("1"),
        total_call_volume=6000,
        total_put_volume=6000,
        volume_pcr=Decimal("1"),
        max_call_open_interest_strike=Decimal("23150"),
        max_put_open_interest_strike=Decimal("23150"),
        max_call_open_interest_change_strike=Decimal("23150"),
        max_put_open_interest_change_strike=Decimal("23150"),
        call_open_interest_concentration=Decimal("0.34"),
        put_open_interest_concentration=Decimal("0.34"),
    )


def test_call_uses_nearest_atm_ce_and_one_lot() -> None:
    trade = build_shadow_trade(
        _decision("BUY_CALL"),
        _options(),
        {"23100CE": 65, "23150CE": 65, "23200CE": 65},
    )

    assert trade is not None
    assert trade.shadow_version == SHADOW_VERSION
    assert trade.token == "23150CE"
    assert trade.entry_price == Decimal("100.00")
    assert trade.quantity == 65
    assert trade.stop_price == Decimal("80.00")
    assert trade.target_price == Decimal("130.00")
    assert trade.max_minutes == 30


def test_put_uses_nearest_atm_pe() -> None:
    trade = build_shadow_trade(
        _decision("BUY_PUT"),
        _options(),
        {"23100PE": 65, "23150PE": 65, "23200PE": 65},
    )

    assert trade is not None
    assert trade.token == "23150PE"
    assert trade.option_type == "PE"


def test_wait_opens_no_shadow_position() -> None:
    assert build_shadow_trade(_decision("WAIT"), _options(), {}) is None


def test_trade_id_is_deterministic() -> None:
    one = build_shadow_trade(
        _decision("BUY_CALL"), _options(), {"23150CE": 65}
    )
    two = build_shadow_trade(
        _decision("BUY_CALL"), _options(), {"23150CE": 65}
    )

    assert one is not None and two is not None
    assert one.trade_id == two.trade_id
