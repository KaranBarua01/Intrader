"""Build and persist one immutable Phase 3 decision from stored Phase 2 data."""

from dataclasses import dataclass
from datetime import date, datetime

from intrader.breadth_pipeline import BreadthPipelineError, build_stored_breadth
from intrader.config import AppConfig
from intrader.context_pipeline import ContextPipelineError, load_cached_context
from intrader.feed_health import HealthSnapshot
from intrader.instruments import NiftyInstruments
from intrader.market_brain import MarketBrainError, build_market_brain
from intrader.market_confirmation_pipeline import build_stored_market_confirmation
from intrader.options_pipeline import build_stored_options_intelligence
from intrader.price_pipeline import build_stored_price_structure
from intrader.records import DecisionRecord, RecordsError, build_decision_record
from intrader.storage import SQLiteStore, StorageError


class RecordsPipelineError(Exception):
    """Stored data cannot produce or persist an immutable decision record."""


@dataclass(frozen=True, slots=True)
class RecordDecisionResult:
    record: DecisionRecord
    inserted: bool


def record_stored_decision(
    store: SQLiteStore,
    instruments: NiftyInstruments,
    session_date: date,
    at: datetime,
    config: AppConfig,
) -> RecordDecisionResult:
    """Reconstruct Phase 2 inputs, freeze reasoning, and persist it once."""

    try:
        price = build_stored_price_structure(
            store, instruments, session_date, at, config
        )
        options = build_stored_options_intelligence(
            store, session_date, at, config
        )
        market = build_stored_market_confirmation(
            store, instruments, session_date, at, config
        )
    except Exception:
        raise RecordsPipelineError("decision core data unavailable") from None

    breadth = None
    try:
        breadth = build_stored_breadth(store, session_date, at, config)
    except BreadthPipelineError:
        pass

    context = None
    try:
        context = load_cached_context(store, at)
    except ContextPipelineError:
        pass

    health = HealthSnapshot("READY", (), 21, 21)
    try:
        brain = build_market_brain(
            price,
            options,
            market,
            health,
            breadth=breadth,
            context=context,
        )
        record = build_decision_record(
            session_date,
            at,
            price,
            options,
            market,
            brain,
            breadth=breadth,
            context=context,
        )
        inserted = store.store_decision_record(record)
    except (MarketBrainError, RecordsError, StorageError):
        raise RecordsPipelineError("decision record unavailable") from None

    return RecordDecisionResult(record=record, inserted=inserted)
