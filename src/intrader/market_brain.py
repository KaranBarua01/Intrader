"""Deterministic family-weighted Market Brain for Intrader Phase 2."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Sequence

from intrader.breadth import BreadthSnapshot
from intrader.context import ContextSnapshot
from intrader.feed_health import HealthSnapshot
from intrader.market_confirmation import MarketConfirmationSnapshot
from intrader.options_intelligence import OptionChainSnapshot
from intrader.price_structure import PriceStructureSnapshot


class MarketBrainError(Exception):
    """Market Brain inputs are internally invalid."""


@dataclass(frozen=True, slots=True)
class FamilyEvidence:
    name: str
    weight: Decimal
    value: Decimal


@dataclass(frozen=True, slots=True)
class MarketBrainSnapshot:
    state: str
    direction_score: Decimal
    entry_quality: Decimal
    reversal_risk: Decimal
    confidence: Decimal
    family_coverage: Decimal
    families: tuple[FamilyEvidence, ...]
    reasons: tuple[str, ...]


_FAMILY_WEIGHTS = {
    "PRICE": Decimal("30"),
    "FUTURES": Decimal("25"),
    "OPTIONS": Decimal("20"),
    "BREADTH": Decimal("15"),
    "ORDER_FLOW": Decimal("10"),
}

_FUTURE_BUILDUP = {
    "LONG_BUILDUP": Decimal("1"),
    "SHORT_BUILDUP": Decimal("-1"),
    "SHORT_COVERING": Decimal("0.5"),
    "LONG_UNWINDING": Decimal("-0.5"),
    "NEUTRAL": Decimal("0"),
}

_OPTION_BUILDUP = {
    "CE": {
        "LONG_BUILDUP": Decimal("1"),
        "SHORT_BUILDUP": Decimal("-1"),
        "SHORT_COVERING": Decimal("0.5"),
        "LONG_UNWINDING": Decimal("-0.5"),
        "NEUTRAL": Decimal("0"),
    },
    "PE": {
        "LONG_BUILDUP": Decimal("-1"),
        "SHORT_BUILDUP": Decimal("1"),
        "SHORT_COVERING": Decimal("-0.5"),
        "LONG_UNWINDING": Decimal("0.5"),
        "NEUTRAL": Decimal("0"),
    },
}


def _clamp(value: Decimal, low: Decimal, high: Decimal) -> Decimal:
    return min(max(value, low), high)


def _family_price(price: PriceStructureSnapshot) -> Decimal:
    if price.atr14 <= 0:
        raise MarketBrainError("ATR unavailable")
    opening_width = price.opening_range_high - price.opening_range_low
    if opening_width <= 0:
        raise MarketBrainError("opening range invalid")

    ema_component = _clamp(
        ((price.ema9 - price.ema20) / price.atr14) * Decimal(2),
        Decimal("-1"),
        Decimal("1"),
    )
    opening_mid = (
        price.opening_range_high + price.opening_range_low
    ) / Decimal(2)
    location_component = _clamp(
        (price.spot_close - opening_mid) / (opening_width / Decimal(2)),
        Decimal("-1"),
        Decimal("1"),
    )
    rsi_component = _clamp(
        (price.rsi14 - Decimal(50)) / Decimal(20),
        Decimal("-1"),
        Decimal("1"),
    )
    return (
        ema_component + location_component + rsi_component
    ) / Decimal(3)


def _family_futures(
    price: PriceStructureSnapshot,
    market: MarketConfirmationSnapshot,
) -> Decimal:
    if price.atr14 <= 0:
        raise MarketBrainError("ATR unavailable")
    buildup = _FUTURE_BUILDUP.get(market.futures.buildup)
    if buildup is None:
        raise MarketBrainError("future buildup invalid")

    price_change = _clamp(
        market.futures.ltp_change / price.atr14,
        Decimal("-1"),
        Decimal("1"),
    )
    basis_change = _clamp(
        market.futures.basis_change / price.atr14,
        Decimal("-1"),
        Decimal("1"),
    )
    return (buildup + price_change + basis_change) / Decimal(3)


def _family_options(options: OptionChainSnapshot) -> Decimal:
    numerator = Decimal(0)
    denominator = Decimal(0)
    for contract in options.contracts:
        mapping = _OPTION_BUILDUP.get(contract.option_type)
        if mapping is None or contract.buildup not in mapping:
            raise MarketBrainError("option buildup invalid")
        vote = mapping[contract.buildup]
        weight = Decimal(abs(contract.open_interest_change))
        if weight == 0:
            continue
        numerator += vote * weight
        denominator += weight

    if denominator == 0:
        return Decimal(0)
    return _clamp(
        numerator / denominator,
        Decimal("-1"),
        Decimal("1"),
    )


def _family_breadth(breadth: BreadthSnapshot) -> Decimal:
    return _clamp(
        breadth.equal_weight_breadth_pct / Decimal(50),
        Decimal("-1"),
        Decimal("1"),
    )


def _pressure_ratio(ratio: Decimal | None) -> Decimal | None:
    if ratio is None or ratio < 0:
        return None
    denominator = ratio + Decimal(1)
    if denominator == 0:
        return None
    return _clamp(
        (ratio - Decimal(1)) / denominator,
        Decimal("-1"),
        Decimal("1"),
    )


def _family_order_flow(market: MarketConfirmationSnapshot) -> Decimal:
    components: list[Decimal] = []
    if market.order_flow.depth_imbalance is not None:
        components.append(
            _clamp(
                market.order_flow.depth_imbalance,
                Decimal("-1"),
                Decimal("1"),
            )
        )
    total_pressure = _pressure_ratio(
        market.order_flow.total_buy_sell_ratio
    )
    if total_pressure is not None:
        components.append(total_pressure)
    depth_pressure = _pressure_ratio(
        market.order_flow.depth_buy_sell_ratio
    )
    if depth_pressure is not None:
        components.append(depth_pressure)
    if not components:
        return Decimal(0)
    return sum(components, Decimal(0)) / Decimal(len(components))


def _agreement(families: Sequence[FamilyEvidence]) -> Decimal:
    signed = sum(
        (family.weight * family.value for family in families),
        Decimal(0),
    )
    absolute = sum(
        (family.weight * abs(family.value) for family in families),
        Decimal(0),
    )
    if absolute == 0:
        return Decimal(0)
    return _clamp(
        abs(signed) / absolute * Decimal(100),
        Decimal(0),
        Decimal(100),
    )


def _participation(relative_volume: Decimal | None) -> Decimal:
    if relative_volume is None or relative_volume < 0:
        return Decimal(50)
    return _clamp(
        relative_volume / Decimal("1.5") * Decimal(100),
        Decimal(0),
        Decimal(100),
    )


def _liquidity(spread_bps: Decimal | None) -> Decimal:
    if spread_bps is None or spread_bps < 0:
        return Decimal(50)
    return _clamp(
        Decimal(100) - (spread_bps * Decimal(10)),
        Decimal(0),
        Decimal(100),
    )


def _reversal_risk(
    price: PriceStructureSnapshot,
    market: MarketConfirmationSnapshot,
    context: ContextSnapshot | None,
) -> Decimal:
    if price.atr14 <= 0:
        raise MarketBrainError("ATR unavailable")

    extension = _clamp(
        abs(price.spot_close - price.ema20)
        / price.atr14
        / Decimal(2)
        * Decimal(100),
        Decimal(0),
        Decimal(100),
    )
    rsi_extreme = _clamp(
        (
            max(
                Decimal(0),
                abs(price.rsi14 - Decimal(50)) - Decimal(15),
            )
            / Decimal(20)
            * Decimal(100)
        ),
        Decimal(0),
        Decimal(100),
    )
    candle_extension = _clamp(
        abs(price.candle_body)
        / price.atr14
        / Decimal(2)
        * Decimal(100),
        Decimal(0),
        Decimal(100),
    )
    vix_shock = Decimal(0)
    if market.vix.change_pct is not None:
        vix_shock = _clamp(
            abs(market.vix.change_pct) / Decimal(5) * Decimal(100),
            Decimal(0),
            Decimal(100),
        )

    risk = (
        extension * Decimal("0.40")
        + rsi_extreme * Decimal("0.25")
        + candle_extension * Decimal("0.20")
        + vix_shock * Decimal("0.15")
    )

    if context is not None:
        if any(
            event.impact == "HIGH"
            for event in context.active_event_windows
        ):
            risk = Decimal(100)
        elif any(
            event.impact == "MEDIUM"
            for event in context.active_event_windows
        ):
            risk = max(risk, Decimal(65))

    return _clamp(risk, Decimal(0), Decimal(100))


def build_market_brain(
    price: PriceStructureSnapshot,
    options: OptionChainSnapshot,
    market: MarketConfirmationSnapshot,
    health: HealthSnapshot,
    *,
    breadth: BreadthSnapshot | None = None,
    context: ContextSnapshot | None = None,
) -> MarketBrainSnapshot:
    """Combine independent evidence families into one advisory state."""

    family_values = [
        FamilyEvidence(
            "PRICE",
            _FAMILY_WEIGHTS["PRICE"],
            _family_price(price),
        ),
        FamilyEvidence(
            "FUTURES",
            _FAMILY_WEIGHTS["FUTURES"],
            _family_futures(price, market),
        ),
        FamilyEvidence(
            "OPTIONS",
            _FAMILY_WEIGHTS["OPTIONS"],
            _family_options(options),
        ),
        FamilyEvidence(
            "ORDER_FLOW",
            _FAMILY_WEIGHTS["ORDER_FLOW"],
            _family_order_flow(market),
        ),
    ]
    if breadth is not None:
        family_values.append(
            FamilyEvidence(
                "BREADTH",
                _FAMILY_WEIGHTS["BREADTH"],
                _family_breadth(breadth),
            )
        )

    available_weight = sum(
        (family.weight for family in family_values),
        Decimal(0),
    )
    if available_weight <= 0:
        raise MarketBrainError("direction evidence unavailable")

    weighted_direction = sum(
        (family.weight * family.value for family in family_values),
        Decimal(0),
    )
    direction = _clamp(
        weighted_direction / available_weight * Decimal(100),
        Decimal("-100"),
        Decimal(100),
    )
    coverage = _clamp(
        available_weight
        / sum(_FAMILY_WEIGHTS.values(), Decimal(0))
        * Decimal(100),
        Decimal(0),
        Decimal(100),
    )

    agreement = _agreement(family_values)
    entry_quality = (
        agreement * Decimal("0.45")
        + _participation(price.relative_volume) * Decimal("0.30")
        + _liquidity(market.order_flow.spread_bps) * Decimal("0.25")
    )
    entry_quality = _clamp(
        entry_quality, Decimal(0), Decimal(100)
    )

    reversal_risk = _reversal_risk(price, market, context)

    health_quality = Decimal(0)
    if health.expected_count > 0:
        health_quality = _clamp(
            Decimal(health.fresh_count)
            / Decimal(health.expected_count)
            * Decimal(100),
            Decimal(0),
            Decimal(100),
        )

    confidence = (
        abs(direction) * Decimal("0.60")
        + coverage * Decimal("0.25")
        + health_quality * Decimal("0.15")
    )
    confidence = _clamp(confidence, Decimal(0), Decimal(100))

    hard_reasons: list[str] = []
    if (
        health.state != "READY"
        or health.expected_count <= 0
        or health.fresh_count != health.expected_count
        or health.reasons
    ):
        hard_reasons.append("CORE_DATA_UNHEALTHY")
    if context is not None and any(
        event.impact == "HIGH"
        for event in context.active_event_windows
    ):
        hard_reasons.append("HIGH_IMPACT_EVENT_WINDOW")

    if hard_reasons:
        state = "NO TRADE"
        reasons = tuple(hard_reasons)
    else:
        reasons_list: list[str] = []
        if abs(direction) < Decimal(35):
            reasons_list.append("DIRECTION_WEAK")
        if confidence < Decimal(60):
            reasons_list.append("CONFIDENCE_LOW")
        if entry_quality < Decimal(55):
            reasons_list.append("ENTRY_QUALITY_LOW")
        if reversal_risk > Decimal(70):
            reasons_list.append("REVERSAL_RISK_HIGH")

        if reasons_list:
            state = "WAIT"
            reasons = tuple(reasons_list)
        else:
            state = (
                "BULLISH SETUP"
                if direction > 0
                else "BEARISH SETUP"
            )
            reasons = ()

    return MarketBrainSnapshot(
        state=state,
        direction_score=direction,
        entry_quality=entry_quality,
        reversal_risk=reversal_risk,
        confidence=confidence,
        family_coverage=coverage,
        families=tuple(
            sorted(family_values, key=lambda family: family.name)
        ),
        reasons=reasons,
    )
