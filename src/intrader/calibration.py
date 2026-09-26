"""Chronological threshold calibration without auto-deployment."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
from itertools import product
from typing import Sequence

from intrader.outcomes import ShadowOutcome
from intrader.performance import PerformanceMetrics, summarize_performance
from intrader.records import DecisionRecord
from intrader.shadow import ShadowTrade


CALIBRATION_VERSION = "calibration-v0.1"


class CalibrationError(Exception):
    """The shadow history is insufficient or invalid for calibration."""


@dataclass(frozen=True, slots=True)
class ThresholdSet:
    direction_min: Decimal
    confidence_min: Decimal
    entry_quality_min: Decimal
    reversal_risk_max: Decimal


@dataclass(frozen=True, slots=True)
class CalibrationReport:
    report_id: str
    calibration_version: str
    created_at: datetime
    source_brain_version: str
    source_rule_version: str
    total_trades: int
    train_trades: int
    validation_trades: int
    test_trades: int
    candidate: ThresholdSet
    train_metrics: PerformanceMetrics
    validation_metrics: PerformanceMetrics
    test_metrics: PerformanceMetrics
    limitation: str


BASELINE_THRESHOLDS = ThresholdSet(
    Decimal("35"), Decimal("60"), Decimal("55"), Decimal("70")
)


def _passes(decision: DecisionRecord, thresholds: ThresholdSet) -> bool:
    return (
        abs(decision.direction_score) >= thresholds.direction_min
        and decision.confidence >= thresholds.confidence_min
        and decision.entry_quality >= thresholds.entry_quality_min
        and decision.reversal_risk <= thresholds.reversal_risk_max
    )


def _filter(rows, thresholds: ThresholdSet):
    return tuple(row for row in rows if _passes(row[0], thresholds))


def _split(rows):
    ordered = tuple(sorted(rows, key=lambda item: item[1].opened_at))
    n = len(ordered)
    if n < 5:
        raise CalibrationError("at least five completed shadow trades required")
    train_end = max(1, int(n * 0.60))
    validation_end = max(train_end + 1, int(n * 0.80))
    validation_end = min(validation_end, n - 1)
    return (
        ordered[:train_end],
        ordered[train_end:validation_end],
        ordered[validation_end:],
    )


def _candidate_grid() -> tuple[ThresholdSet, ...]:
    return tuple(
        ThresholdSet(
            Decimal(direction),
            Decimal(confidence),
            Decimal(entry),
            Decimal(risk),
        )
        for direction, confidence, entry, risk in product(
            (35, 40, 45, 50, 55, 60),
            (60, 65, 70, 75, 80),
            (55, 60, 65, 70, 75),
            (50, 60, 70),
        )
    )


def _metric_score(metrics: PerformanceMetrics):
    expectancy = metrics.expectancy if metrics.expectancy is not None else Decimal("-Infinity")
    profit_factor = (
        metrics.profit_factor
        if metrics.profit_factor is not None
        else Decimal("999999")
        if metrics.losses == 0 and metrics.wins > 0
        else Decimal(0)
    )
    return (expectancy, metrics.trades, profit_factor)


def _report_id(rows, candidate: ThresholdSet) -> str:
    payload = "|".join(
        [
            CALIBRATION_VERSION,
            *(row[1].trade_id for row in sorted(rows, key=lambda item: item[1].opened_at)),
            str(candidate.direction_min),
            str(candidate.confidence_min),
            str(candidate.entry_quality_min),
            str(candidate.reversal_risk_max),
        ]
    )
    return "CAL-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def calibrate_thresholds(
    rows: Sequence[tuple[DecisionRecord, ShadowTrade, ShadowOutcome]],
    *,
    minimum_train_trades: int = 3,
    starting_capital: Decimal = Decimal("100000"),
    created_at: datetime | None = None,
) -> CalibrationReport:
    """Select thresholds on TRAIN and report untouched VALIDATION/TEST results."""

    if minimum_train_trades <= 0:
        raise CalibrationError("minimum training sample invalid")
    train, validation, test = _split(rows)

    versions = {(row[0].brain_version, row[0].rule_version) for row in rows}
    if len(versions) != 1:
        raise CalibrationError("mixed Brain/rule versions require separate calibration")
    brain_version, rule_version = next(iter(versions))

    eligible = []
    for candidate in _candidate_grid():
        selected = _filter(train, candidate)
        if len(selected) < minimum_train_trades:
            continue
        metrics = summarize_performance(selected, starting_capital=starting_capital)
        if metrics.expectancy is None or metrics.expectancy <= 0:
            continue
        eligible.append((candidate, metrics))

    if not eligible:
        candidate = BASELINE_THRESHOLDS
        train_selected = _filter(train, candidate)
        if not train_selected:
            raise CalibrationError("no viable calibration candidate")
        train_metrics = summarize_performance(
            train_selected, starting_capital=starting_capital
        )
    else:
        candidate, train_metrics = max(
            eligible,
            key=lambda item: _metric_score(item[1]),
        )

    validation_selected = _filter(validation, candidate)
    test_selected = _filter(test, candidate)
    validation_metrics = summarize_performance(
        validation_selected, starting_capital=starting_capital
    )
    test_metrics = summarize_performance(
        test_selected, starting_capital=starting_capital
    )

    if created_at is None:
        created_at = datetime.now(timezone.utc)
    if created_at.tzinfo is None:
        raise CalibrationError("calibration timestamp must be timezone aware")

    return CalibrationReport(
        report_id=_report_id(rows, candidate),
        calibration_version=CALIBRATION_VERSION,
        created_at=created_at,
        source_brain_version=brain_version,
        source_rule_version=rule_version,
        total_trades=len(rows),
        train_trades=len(train),
        validation_trades=len(validation),
        test_trades=len(test),
        candidate=candidate,
        train_metrics=train_metrics,
        validation_metrics=validation_metrics,
        test_metrics=test_metrics,
        limitation=(
            "calibration-v0.1 can test only baseline-or-stricter thresholds "
            "because completed shadow trades exist only for baseline-qualified setups"
        ),
    )
