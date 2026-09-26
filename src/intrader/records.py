"""Immutable pre-outcome decision records for Intrader Phase 3."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib

from intrader.breadth import BreadthSnapshot
from intrader.context import ContextSnapshot
from intrader.market_brain import (
    BRAIN_VERSION,
    RULE_VERSION,
    FamilyEvidence,
    MarketBrainSnapshot,
)
from intrader.market_confirmation import MarketConfirmationSnapshot
from intrader.options_intelligence import OptionChainSnapshot
from intrader.price_structure import PriceStructureSnapshot


class RecordsError(Exception):
    """A decision record cannot be built safely."""


@dataclass(frozen=True, slots=True)
class DecisionReason:
    thesis: str
    reason_code: str
    category: str
    evidence_value: Decimal | None
    expected_direction: int
    explanation: str


@dataclass(frozen=True, slots=True)
class DecisionRecord:
    decision_id: str
    decided_at: datetime
    session_date: date
    brain_version: str
    rule_version: str
    brain_state: str
    action: str
    rejected_action: str | None
    direction_score: Decimal
    entry_quality: Decimal
    reversal_risk: Decimal
    confidence: Decimal
    family_coverage: Decimal
    regime: str
    spot_price: Decimal
    future_price: Decimal | None
    vix: Decimal
    ema9: Decimal
    ema20: Decimal
    rsi14: Decimal
    atr14: Decimal
    opening_range_high: Decimal
    opening_range_low: Decimal
    future_oi: int
    future_oi_change: int
    future_volume_change: int
    basis: Decimal
    basis_change: Decimal
    oi_pcr: Decimal | None
    volume_pcr: Decimal | None
    breadth_pct: Decimal | None
    depth_imbalance: Decimal | None
    high_impact_event_active: bool
    families: tuple[FamilyEvidence, ...]
    reasons: tuple[DecisionReason, ...]


_ACTIONS = {
    "BULLISH SETUP": ("BUY_CALL", "BUY_PUT", 1),
    "BEARISH SETUP": ("BUY_PUT", "BUY_CALL", -1),
    "WAIT": ("WAIT", None, 0),
    "NO TRADE": ("NO_TRADE", None, 0),
}


def _sign(value: Decimal, threshold: Decimal = Decimal("0.15")) -> int:
    if value > threshold:
        return 1
    if value < -threshold:
        return -1
    return 0


def _family_reasons(
    families: tuple[FamilyEvidence, ...],
    chosen_direction: int,
    rejected_action: str | None,
) -> list[DecisionReason]:
    reasons: list[DecisionReason] = []
    for family in families:
        direction = _sign(family.value)
        direction_name = (
            "CALL" if direction > 0 else "PUT" if direction < 0 else "NEUTRAL"
        )
        code = f"{family.name}_SUPPORTS_{direction_name}"
        explanation = (
            f"{family.name} family value {family.value} "
            f"supports {direction_name.lower()} direction."
        )
        thesis = (
            "CHOSEN"
            if chosen_direction != 0 and direction == chosen_direction
            else "GATE"
        )
        reasons.append(
            DecisionReason(
                thesis=thesis,
                reason_code=code,
                category=family.name,
                evidence_value=family.value,
                expected_direction=direction,
                explanation=explanation,
            )
        )
        if (
            rejected_action is not None
            and chosen_direction != 0
            and direction == chosen_direction
        ):
            reasons.append(
                DecisionReason(
                    thesis="REJECTED",
                    reason_code=f"REJECT_{rejected_action}_{family.name}",
                    category=family.name,
                    evidence_value=family.value,
                    expected_direction=chosen_direction,
                    explanation=(
                        f"{family.name} evidence opposed the rejected "
                        f"{rejected_action} thesis."
                    ),
                )
            )
    return reasons


def _detail_reasons(
    price: PriceStructureSnapshot,
    market: MarketConfirmationSnapshot,
    brain: MarketBrainSnapshot,
    chosen_direction: int,
    context: ContextSnapshot | None,
) -> list[DecisionReason]:
    reasons: list[DecisionReason] = []

    ema_direction = 1 if price.ema9 > price.ema20 else -1 if price.ema9 < price.ema20 else 0
    reasons.append(
        DecisionReason(
            thesis="CHOSEN" if ema_direction == chosen_direction and chosen_direction else "GATE",
            reason_code=(
                "PRICE_EMA_CALL"
                if ema_direction > 0
                else "PRICE_EMA_PUT"
                if ema_direction < 0
                else "PRICE_EMA_FLAT"
            ),
            category="PRICE",
            evidence_value=price.ema9 - price.ema20,
            expected_direction=ema_direction,
            explanation=f"EMA9 {price.ema9} versus EMA20 {price.ema20}.",
        )
    )

    if price.spot_close > price.opening_range_high:
        or_direction = 1
        or_code = "PRICE_ABOVE_OPENING_RANGE"
    elif price.spot_close < price.opening_range_low:
        or_direction = -1
        or_code = "PRICE_BELOW_OPENING_RANGE"
    else:
        or_direction = 0
        or_code = "PRICE_INSIDE_OPENING_RANGE"
    reasons.append(
        DecisionReason(
            thesis="CHOSEN" if or_direction == chosen_direction and chosen_direction else "GATE",
            reason_code=or_code,
            category="PRICE",
            evidence_value=price.spot_close,
            expected_direction=or_direction,
            explanation=(
                f"Spot {price.spot_close}; opening range "
                f"{price.opening_range_low}-{price.opening_range_high}."
            ),
        )
    )

    rsi_direction = 1 if price.rsi14 >= 55 else -1 if price.rsi14 <= 45 else 0
    reasons.append(
        DecisionReason(
            thesis="CHOSEN" if rsi_direction == chosen_direction and chosen_direction else "GATE",
            reason_code=(
                "PRICE_RSI_CALL"
                if rsi_direction > 0
                else "PRICE_RSI_PUT"
                if rsi_direction < 0
                else "PRICE_RSI_NEUTRAL"
            ),
            category="PRICE",
            evidence_value=price.rsi14,
            expected_direction=rsi_direction,
            explanation=f"RSI14 is {price.rsi14}.",
        )
    )

    buildup_direction = {
        "LONG_BUILDUP": 1,
        "SHORT_COVERING": 1,
        "SHORT_BUILDUP": -1,
        "LONG_UNWINDING": -1,
        "NEUTRAL": 0,
    }.get(market.futures.buildup, 0)
    reasons.append(
        DecisionReason(
            thesis=(
                "CHOSEN"
                if buildup_direction == chosen_direction and chosen_direction
                else "GATE"
            ),
            reason_code=f"FUTURES_{market.futures.buildup}",
            category="FUTURES",
            evidence_value=Decimal(market.futures.open_interest_change),
            expected_direction=buildup_direction,
            explanation=(
                f"Futures {market.futures.buildup}; dLTP "
                f"{market.futures.ltp_change}; dOI "
                f"{market.futures.open_interest_change}."
            ),
        )
    )

    if market.order_flow.depth_imbalance is None:
        flow_direction = 0
        flow_code = "ORDER_FLOW_UNAVAILABLE"
    elif market.order_flow.depth_imbalance > Decimal("0.10"):
        flow_direction = 1
        flow_code = "ORDER_FLOW_BUY_PRESSURE"
    elif market.order_flow.depth_imbalance < Decimal("-0.10"):
        flow_direction = -1
        flow_code = "ORDER_FLOW_SELL_PRESSURE"
    else:
        flow_direction = 0
        flow_code = "ORDER_FLOW_BALANCED"
    reasons.append(
        DecisionReason(
            thesis="CHOSEN" if flow_direction == chosen_direction and chosen_direction else "GATE",
            reason_code=flow_code,
            category="ORDER_FLOW",
            evidence_value=market.order_flow.depth_imbalance,
            expected_direction=flow_direction,
            explanation=(
                f"Five-level depth imbalance is "
                f"{market.order_flow.depth_imbalance}."
            ),
        )
    )

    vix_change = market.vix.change_pct
    vix_code = (
        "VIX_SHOCK"
        if vix_change is not None and abs(vix_change) >= Decimal(5)
        else "VIX_STABLE"
    )
    reasons.append(
        DecisionReason(
            thesis="GATE",
            reason_code=vix_code,
            category="RISK",
            evidence_value=vix_change,
            expected_direction=0,
            explanation=f"VIX change percent is {vix_change}.",
        )
    )

    high_event = bool(
        context
        and any(event.impact == "HIGH" for event in context.active_event_windows)
    )
    reasons.append(
        DecisionReason(
            thesis="GATE",
            reason_code=(
                "HIGH_IMPACT_EVENT_ACTIVE" if high_event else "EVENT_WINDOW_CLEAR"
            ),
            category="EVENT",
            evidence_value=None,
            expected_direction=0,
            explanation=(
                "A HIGH-impact event window is active."
                if high_event
                else "No HIGH-impact event window is active."
            ),
        )
    )

    for reason in brain.reasons:
        reasons.append(
            DecisionReason(
                thesis="GATE",
                reason_code=reason,
                category="BRAIN_GATE",
                evidence_value=None,
                expected_direction=0,
                explanation=f"Market Brain gate: {reason}.",
            )
        )
    return reasons


def _regime(
    brain: MarketBrainSnapshot,
    market: MarketConfirmationSnapshot,
    context: ContextSnapshot | None,
) -> str:
    if context and any(
        event.impact == "HIGH" for event in context.active_event_windows
    ):
        return "EVENT_RISK"
    if (
        market.vix.change_pct is not None
        and abs(market.vix.change_pct) >= Decimal(5)
    ):
        return "HIGH_VOLATILITY"
    if abs(brain.direction_score) >= Decimal(50) and brain.entry_quality >= Decimal(55):
        return "TRENDING_UP" if brain.direction_score > 0 else "TRENDING_DOWN"
    if abs(brain.direction_score) < Decimal(25):
        return "RANGE"
    return "MIXED"


def _decision_id(
    at: datetime,
    brain: MarketBrainSnapshot,
    action: str,
) -> str:
    if at.tzinfo is None:
        raise RecordsError("decision timestamp must be timezone aware")
    payload = "|".join(
        (
            at.astimezone(timezone.utc).isoformat(timespec="milliseconds"),
            BRAIN_VERSION,
            RULE_VERSION,
            brain.state,
            action,
            str(brain.direction_score),
            str(brain.confidence),
        )
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return f"DEC-{at.astimezone(timezone.utc):%Y%m%dT%H%M%S}-{digest}"


def build_decision_record(
    session_date: date,
    at: datetime,
    price: PriceStructureSnapshot,
    options: OptionChainSnapshot,
    market: MarketConfirmationSnapshot,
    brain: MarketBrainSnapshot,
    *,
    breadth: BreadthSnapshot | None = None,
    context: ContextSnapshot | None = None,
) -> DecisionRecord:
    """Freeze one pre-outcome Market Brain decision and its reasoning."""

    if at.tzinfo is None:
        raise RecordsError("decision timestamp must be timezone aware")
    mapping = _ACTIONS.get(brain.state)
    if mapping is None:
        raise RecordsError("unsupported Market Brain state")
    action, rejected_action, chosen_direction = mapping

    family_reasons = _family_reasons(
        brain.families,
        chosen_direction,
        rejected_action,
    )
    detail_reasons = _detail_reasons(
        price,
        market,
        brain,
        chosen_direction,
        context,
    )

    # Keep one deterministic copy per thesis/reason code.
    deduped: dict[tuple[str, str], DecisionReason] = {}
    for reason in (*family_reasons, *detail_reasons):
        deduped[(reason.thesis, reason.reason_code)] = reason

    high_event = bool(
        context
        and any(event.impact == "HIGH" for event in context.active_event_windows)
    )

    return DecisionRecord(
        decision_id=_decision_id(at, brain, action),
        decided_at=at,
        session_date=session_date,
        brain_version=BRAIN_VERSION,
        rule_version=RULE_VERSION,
        brain_state=brain.state,
        action=action,
        rejected_action=rejected_action,
        direction_score=brain.direction_score,
        entry_quality=brain.entry_quality,
        reversal_risk=brain.reversal_risk,
        confidence=brain.confidence,
        family_coverage=brain.family_coverage,
        regime=_regime(brain, market, context),
        spot_price=price.spot_close,
        future_price=price.future_close,
        vix=market.vix.value,
        ema9=price.ema9,
        ema20=price.ema20,
        rsi14=price.rsi14,
        atr14=price.atr14,
        opening_range_high=price.opening_range_high,
        opening_range_low=price.opening_range_low,
        future_oi=market.futures.open_interest,
        future_oi_change=market.futures.open_interest_change,
        future_volume_change=market.futures.volume_change,
        basis=market.futures.basis,
        basis_change=market.futures.basis_change,
        oi_pcr=options.open_interest_pcr,
        volume_pcr=options.volume_pcr,
        breadth_pct=None if breadth is None else breadth.equal_weight_breadth_pct,
        depth_imbalance=market.order_flow.depth_imbalance,
        high_impact_event_active=high_event,
        families=brain.families,
        reasons=tuple(
            sorted(deduped.values(), key=lambda item: (item.thesis, item.reason_code))
        ),
    )
