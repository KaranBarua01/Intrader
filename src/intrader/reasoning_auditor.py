"""Post-outcome audit of immutable Phase 3 decision reasons."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from intrader.outcomes import ShadowOutcome
from intrader.records import DecisionRecord


AUDITOR_VERSION = "auditor-v0.1"


class ReasoningAuditError(Exception):
    """A reasoning audit cannot be constructed safely."""


@dataclass(frozen=True, slots=True)
class ReasonAudit:
    trade_id: str
    decision_id: str
    auditor_version: str
    thesis: str
    reason_code: str
    category: str
    expected_direction: int
    verdict: str
    trade_result: str
    adjusted_pnl: Decimal
    spot_change: Decimal | None


def _direction(value: Decimal) -> int:
    if value > 0:
        return 1
    if value < 0:
        return -1
    return 0


def build_reason_audits(
    decision: DecisionRecord,
    outcome: ShadowOutcome,
) -> tuple[ReasonAudit, ...]:
    """Grade every frozen reason against observed direction and trade outcome."""

    if outcome.trade_id == "":
        raise ReasoningAuditError("trade id unavailable")

    trade_result = (
        "PROFIT"
        if outcome.adjusted_pnl > 0
        else "LOSS"
        if outcome.adjusted_pnl < 0
        else "FLAT"
    )

    actual_direction = (
        None
        if outcome.spot_change is None
        else _direction(outcome.spot_change)
    )

    audits: list[ReasonAudit] = []
    for reason in decision.reasons:
        if reason.expected_direction == 0:
            verdict = "UNGRADED"
        elif actual_direction is None:
            verdict = "UNKNOWN"
        elif actual_direction == 0:
            verdict = "FLAT"
        elif actual_direction == reason.expected_direction:
            verdict = "SUPPORTED"
        else:
            verdict = "CONTRADICTED"

        audits.append(
            ReasonAudit(
                trade_id=outcome.trade_id,
                decision_id=decision.decision_id,
                auditor_version=AUDITOR_VERSION,
                thesis=reason.thesis,
                reason_code=reason.reason_code,
                category=reason.category,
                expected_direction=reason.expected_direction,
                verdict=verdict,
                trade_result=trade_result,
                adjusted_pnl=outcome.adjusted_pnl,
                spot_change=outcome.spot_change,
            )
        )

    return tuple(
        sorted(audits, key=lambda item: (item.thesis, item.reason_code))
    )
