"""Persist post-outcome reasoning audits for completed shadow trades."""

from dataclasses import dataclass

from intrader.reasoning_auditor import (
    AUDITOR_VERSION,
    ReasonAudit,
    ReasoningAuditError,
    build_reason_audits,
)
from intrader.storage import SQLiteStore, StorageError


class ReasoningPipelineError(Exception):
    """A completed trade cannot be audited safely."""


@dataclass(frozen=True, slots=True)
class AuditShadowResult:
    audits: tuple[ReasonAudit, ...]
    inserted_rows: int


def audit_shadow_trade(
    store: SQLiteStore,
    trade_id: str,
) -> AuditShadowResult:
    """Audit one completed shadow trade against its immutable reason journal."""

    try:
        trade = store.load_shadow_trade(trade_id)
        if trade is None:
            raise ReasoningPipelineError("shadow trade unavailable")
        decision = store.load_decision_record(trade.decision_id)
        if decision is None:
            raise ReasoningPipelineError("decision record unavailable")
        outcome = store.load_shadow_outcome(trade_id)
        if outcome is None:
            raise ReasoningPipelineError("shadow outcome unavailable")

        audits = build_reason_audits(decision, outcome)
        inserted = store.store_reason_audits(audits)
        persisted = store.load_reason_audits(
            trade_id=trade_id,
            auditor_version=AUDITOR_VERSION,
        )
        return AuditShadowResult(persisted, inserted)
    except ReasoningPipelineError:
        raise
    except (ReasoningAuditError, StorageError, Exception):
        raise ReasoningPipelineError("reasoning audit unavailable") from None
