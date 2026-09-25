from datetime import datetime, timezone
from decimal import Decimal

from intrader.breadth import BreadthSnapshot
from intrader.context import ContextSnapshot, ScheduledEvent
from intrader.feed_health import HealthSnapshot
from intrader.market_brain import build_market_brain
from intrader.market_confirmation import (
    FuturesConfirmation,
    MarketConfirmationSnapshot,
    OrderFlowConfirmation,
    VixConfirmation,
)
from intrader.options_intelligence import (
    OptionChainSnapshot,
    OptionContractMetrics,
)
from intrader.price_structure import PriceStructureSnapshot


NOW = datetime(2026, 9, 28, 6, 30, tzinfo=timezone.utc)


def _price(
    *,
    close: str = "120",
    ema9: str = "115",
    ema20: str = "110",
    rsi: str = "65",
    atr: str = "10",
    body: str = "3",
) -> PriceStructureSnapshot:
    return PriceStructureSnapshot(
        at=NOW,
        spot_close=Decimal(close),
        ema9=Decimal(ema9),
        ema20=Decimal(ema20),
        rsi14=Decimal(rsi),
        atr14=Decimal(atr),
        candle_body=Decimal(body),
        upper_wick=Decimal("1"),
        lower_wick=Decimal("1"),
        opening_range_high=Decimal("115"),
        opening_range_low=Decimal("95"),
        previous_session_high=Decimal("116"),
        previous_session_low=Decimal("90"),
        future_close=Decimal("125"),
        future_vwap=Decimal("115"),
        relative_volume=Decimal("1.5"),
    )


def _contract(
    token: str,
    option_type: str,
    buildup: str,
    oi_change: int,
) -> OptionContractMetrics:
    return OptionContractMetrics(
        token=token,
        strike=Decimal("100"),
        option_type=option_type,
        current_ltp=Decimal("10"),
        ltp_change=Decimal("1"),
        ltp_change_pct=Decimal("10"),
        current_open_interest=1000,
        open_interest_change=oi_change,
        open_interest_change_pct=Decimal("10"),
        current_volume=2000,
        volume_change=100,
        buildup=buildup,
    )


def _options(bullish: bool = True) -> OptionChainSnapshot:
    if bullish:
        contracts = (
            _contract("CE", "CE", "LONG_BUILDUP", 100),
            _contract("PE", "PE", "SHORT_BUILDUP", 100),
        )
    else:
        contracts = (
            _contract("CE", "CE", "SHORT_BUILDUP", 100),
            _contract("PE", "PE", "LONG_BUILDUP", 100),
        )
    return OptionChainSnapshot(
        at=NOW,
        lookback_minutes=5,
        contracts=contracts,
        total_call_open_interest=1000,
        total_put_open_interest=1000,
        open_interest_pcr=Decimal("1"),
        total_call_volume=2000,
        total_put_volume=2000,
        volume_pcr=Decimal("1"),
        max_call_open_interest_strike=Decimal("100"),
        max_put_open_interest_strike=Decimal("100"),
        max_call_open_interest_change_strike=Decimal("100"),
        max_put_open_interest_change_strike=Decimal("100"),
        call_open_interest_concentration=Decimal("1"),
        put_open_interest_concentration=Decimal("1"),
    )


def _market(bullish: bool = True, vix_change: str = "0") -> MarketConfirmationSnapshot:
    sign = Decimal("1") if bullish else Decimal("-1")
    return MarketConfirmationSnapshot(
        at=NOW,
        lookback_minutes=5,
        futures=FuturesConfirmation(
            ltp=Decimal("125"),
            ltp_change=Decimal("8") * sign,
            open_interest=1200,
            open_interest_change=200,
            volume=6000,
            volume_change=1000,
            buildup="LONG_BUILDUP" if bullish else "SHORT_BUILDUP",
            basis=Decimal("5"),
            basis_change=Decimal("5") * sign,
        ),
        vix=VixConfirmation(
            value=Decimal("12"),
            change=Decimal(vix_change),
            change_pct=Decimal(vix_change),
        ),
        order_flow=OrderFlowConfirmation(
            total_buy_sell_ratio=Decimal("2") if bullish else Decimal("0.5"),
            depth_buy_sell_ratio=Decimal("2") if bullish else Decimal("0.5"),
            depth_imbalance=Decimal("0.5") if bullish else Decimal("-0.5"),
            best_bid=Decimal("124.9"),
            best_ask=Decimal("125.0"),
            spread=Decimal("0.1"),
            spread_bps=Decimal("0.8"),
        ),
    )


def _breadth(value: str = "60") -> BreadthSnapshot:
    return BreadthSnapshot(
        at=NOW,
        total=50,
        advancing=40 if Decimal(value) > 0 else 10,
        declining=10 if Decimal(value) > 0 else 40,
        unchanged=0,
        advance_decline_ratio=Decimal("4") if Decimal(value) > 0 else Decimal("0.25"),
        equal_weight_breadth_pct=Decimal(value),
        weighted_return_pct=None,
        top_positive_contributors=(),
        top_negative_contributors=(),
        sectors=(),
    )


def _health(ready: bool = True) -> HealthSnapshot:
    return HealthSnapshot(
        "READY" if ready else "NO TRADE",
        () if ready else ("STALE_OPTION",),
        21 if ready else 20,
        21,
    )


def _empty_context() -> ContextSnapshot:
    return ContextSnapshot(NOW, (), (), (), None, ())


def test_aligned_families_can_produce_bullish_setup() -> None:
    result = build_market_brain(
        _price(),
        _options(True),
        _market(True),
        _health(True),
        breadth=_breadth("60"),
        context=_empty_context(),
    )

    assert result.state == "BULLISH SETUP"
    assert result.direction_score >= Decimal("35")
    assert result.confidence >= Decimal("60")
    assert result.entry_quality >= Decimal("55")
    assert result.reversal_risk <= Decimal("70")
    assert len(result.families) == 5


def test_stale_core_health_is_no_trade_regardless_of_direction() -> None:
    result = build_market_brain(
        _price(),
        _options(True),
        _market(True),
        _health(False),
        breadth=_breadth("60"),
        context=_empty_context(),
    )

    assert result.state == "NO TRADE"
    assert "CORE_DATA_UNHEALTHY" in result.reasons


def test_high_impact_event_window_is_no_trade() -> None:
    event = ScheduledEvent(
        "FED", "FOMC policy decision", NOW, "FOMC", "HIGH"
    )
    context = ContextSnapshot(
        NOW, (), (event,), (event,), 0.0, ("FED",)
    )

    result = build_market_brain(
        _price(),
        _options(True),
        _market(True),
        _health(True),
        breadth=_breadth("60"),
        context=context,
    )

    assert result.state == "NO TRADE"
    assert "HIGH_IMPACT_EVENT_WINDOW" in result.reasons


def test_conflicting_families_reduce_direction_and_confidence() -> None:
    aligned = build_market_brain(
        _price(),
        _options(True),
        _market(True),
        _health(True),
        breadth=_breadth("60"),
    )
    conflicted = build_market_brain(
        _price(),
        _options(False),
        _market(False),
        _health(True),
        breadth=_breadth("60"),
    )

    assert abs(conflicted.direction_score) < abs(aligned.direction_score)
    assert conflicted.confidence < aligned.confidence


def test_missing_breadth_reduces_coverage_without_inverting_core_direction() -> None:
    with_breadth = build_market_brain(
        _price(),
        _options(True),
        _market(True),
        _health(True),
        breadth=_breadth("60"),
    )
    without_breadth = build_market_brain(
        _price(),
        _options(True),
        _market(True),
        _health(True),
    )

    assert with_breadth.direction_score > 0
    assert without_breadth.direction_score > 0
    assert without_breadth.family_coverage == Decimal("85")
    assert without_breadth.family_coverage < with_breadth.family_coverage


def test_extreme_extension_raises_risk_but_does_not_reverse_direction() -> None:
    result = build_market_brain(
        _price(close="150", ema9="130", ema20="110", rsi="85", body="15"),
        _options(True),
        _market(True, vix_change="5"),
        _health(True),
        breadth=_breadth("60"),
    )

    assert result.direction_score > 0
    assert result.reversal_risk > Decimal("70")
    assert result.state == "WAIT"
    assert "REVERSAL_RISK_HIGH" in result.reasons
