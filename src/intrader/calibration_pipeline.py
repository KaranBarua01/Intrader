"""Run calibration and promotion from immutable completed shadow history."""

from dataclasses import dataclass
from datetime import datetime, timezone

from intrader.calibration import CalibrationError, CalibrationReport, calibrate_thresholds
from intrader.promotion import PromotionReport, evaluate_promotion
from intrader.storage import SQLiteStore, StorageError


class CalibrationPipelineError(Exception):
    """Stored shadow history is not yet suitable for calibration."""


def run_calibration(
    store: SQLiteStore,
    *,
    created_at: datetime | None = None,
) -> CalibrationReport:
    try:
        rows = store.load_completed_shadow_bundles()
        return calibrate_thresholds(
            rows,
            created_at=created_at or datetime.now(timezone.utc),
        )
    except (CalibrationError, StorageError, Exception):
        raise CalibrationPipelineError("calibration pending or unavailable") from None


def run_promotion_gate(
    store: SQLiteStore,
    *,
    created_at: datetime | None = None,
) -> tuple[CalibrationReport, PromotionReport]:
    report = run_calibration(store, created_at=created_at)
    promotion = evaluate_promotion(
        report,
        created_at=created_at or datetime.now(timezone.utc),
    )
    return report, promotion
