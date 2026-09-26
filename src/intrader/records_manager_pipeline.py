"""Build the operator-facing Records Manager snapshot from immutable SQLite history."""

from decimal import Decimal

from intrader.performance import RecordsManagerSnapshot, build_records_manager_snapshot
from intrader.reasoning_auditor import AUDITOR_VERSION
from intrader.storage import SQLiteStore, StorageError


class RecordsManagerError(Exception):
    """Records Manager history cannot be summarized safely."""


def build_records_manager(
    store: SQLiteStore,
    *,
    starting_capital: Decimal = Decimal("100000"),
) -> RecordsManagerSnapshot:
    try:
        decisions = store.load_decision_records()
        completed = store.load_completed_shadow_bundles()
        audits = store.load_reason_audits(auditor_version=AUDITOR_VERSION)
        return build_records_manager_snapshot(
            decisions,
            completed,
            audits,
            starting_capital=starting_capital,
        )
    except (StorageError, ValueError, Exception):
        raise RecordsManagerError("records manager unavailable") from None
