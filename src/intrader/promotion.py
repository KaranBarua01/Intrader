"""Human-controlled version promotion gate for Intrader Phase 3."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import hashlib

from intrader.calibration import CalibrationReport


PROMOTION_VERSION = "promotion-v0.1"


@dataclass(frozen=True, slots=True)
class PromotionCriteria:
    minimum_test_trades: int = 5
    minimum_profit_factor: Decimal = Decimal("1.20")
    maximum_drawdown_pct: Decimal = Decimal("10")


@dataclass(frozen=True, slots=True)
class PromotionReport:
    promotion_id: str
    promotion_version: str
    created_at: datetime
    calibration_report_id: str
    status: str
    reasons: tuple[str, ...]


class PromotionError(Exception):
    """A promotion report cannot be evaluated safely."""


def _promotion_id(report: CalibrationReport, criteria: PromotionCriteria) -> str:
    payload = "|".join(
        (
            PROMOTION_VERSION,
            report.report_id,
            str(criteria.minimum_test_trades),
            str(criteria.minimum_profit_factor),
            str(criteria.maximum_drawdown_pct),
        )
    )
    return "PRO-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def evaluate_promotion(
    report: CalibrationReport,
    *,
    criteria: PromotionCriteria = PromotionCriteria(),
    created_at: datetime | None = None,
) -> PromotionReport:
    """Return a non-deploying PASS/REJECT gate from untouched evaluation slices."""

    if criteria.minimum_test_trades <= 0:
        raise PromotionError("promotion sample requirement invalid")

    reasons: list[str] = []
    validation = report.validation_metrics
    test = report.test_metrics

    if test.trades < criteria.minimum_test_trades:
        reasons.append("TEST_SAMPLE_TOO_SMALL")
    if validation.expectancy is None or validation.expectancy <= 0:
        reasons.append("VALIDATION_EXPECTANCY_NOT_POSITIVE")
    if test.expectancy is None or test.expectancy <= 0:
        reasons.append("TEST_EXPECTANCY_NOT_POSITIVE")
    if (
        test.profit_factor is None
        or test.profit_factor < criteria.minimum_profit_factor
    ):
        reasons.append("TEST_PROFIT_FACTOR_TOO_LOW")
    if test.max_drawdown_pct > criteria.maximum_drawdown_pct:
        reasons.append("TEST_DRAWDOWN_TOO_HIGH")

    if created_at is None:
        created_at = datetime.now(timezone.utc)
    if created_at.tzinfo is None:
        raise PromotionError("promotion timestamp must be timezone aware")

    return PromotionReport(
        promotion_id=_promotion_id(report, criteria),
        promotion_version=PROMOTION_VERSION,
        created_at=created_at,
        calibration_report_id=report.report_id,
        status="PASS" if not reasons else "REJECT",
        reasons=tuple(reasons),
    )
