"""Open one immutable shadow position from a recorded Phase 3 decision."""

from dataclasses import dataclass
from datetime import date, datetime

from intrader.config import AppConfig
from intrader.instruments import NiftyInstruments
from intrader.options_pipeline import build_stored_options_intelligence
from intrader.records_pipeline import RecordDecisionResult, record_stored_decision
from intrader.shadow import ShadowTrade, ShadowTradeError, build_shadow_trade
from intrader.storage import SQLiteStore, StorageError


class ShadowPipelineError(Exception):
    """A shadow decision/trade step cannot be completed safely."""


@dataclass(frozen=True, slots=True)
class ShadowStepResult:
    decision: RecordDecisionResult
    trade: ShadowTrade | None
    trade_inserted: bool


def run_shadow_step(
    store: SQLiteStore,
    instruments: NiftyInstruments,
    session_date: date,
    at: datetime,
    config: AppConfig,
) -> ShadowStepResult:
    """Record the decision and open one versioned simulated trade when actionable."""

    try:
        decision_result = record_stored_decision(
            store, instruments, session_date, at, config
        )
    except Exception:
        raise ShadowPipelineError("shadow decision unavailable") from None

    if decision_result.record.action not in {"BUY_CALL", "BUY_PUT"}:
        return ShadowStepResult(decision_result, None, False)

    try:
        options = build_stored_options_intelligence(
            store, session_date, at, config
        )
        lot_sizes = {
            instrument.token: instrument.lot_size
            for instrument in (*instruments.calls, *instruments.puts)
        }
        trade = build_shadow_trade(
            decision_result.record,
            options,
            lot_sizes,
        )
        if trade is None:
            return ShadowStepResult(decision_result, None, False)
        inserted = store.store_shadow_trade(trade)
        if not inserted:
            existing = store.load_shadow_trade_for_decision(
                decision_result.record.decision_id
            )
            if existing is not None:
                trade = existing
    except (ShadowTradeError, StorageError, Exception):
        raise ShadowPipelineError("shadow trade unavailable") from None

    return ShadowStepResult(decision_result, trade, inserted)
