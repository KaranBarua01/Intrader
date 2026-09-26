"""Historical current-Brain reanalysis without mutating immutable records."""

from __future__ import annotations

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
from intrader.storage import SQLiteStore


class HistoricalReanalysisError(Exception):
    """Historical core data cannot support a current-Brain replay."""


def reanalyze_stored_decision(
    store: SQLiteStore,
    instruments: NiftyInstruments,
    session_date: date,
    at: datetime,
    config: AppConfig,
) -> DecisionRecord:
    """Rebuild a decision at one timestamp without storing or rewriting history."""

    if at.tzinfo is None:
        raise HistoricalReanalysisError("reanalysis timestamp must be timezone aware")

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
        raise HistoricalReanalysisError(
            "full historical core data unavailable at this timestamp"
        ) from None

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
        return build_decision_record(
            session_date,
            at,
            price,
            options,
            market,
            brain,
            breadth=breadth,
            context=context,
        )
    except (MarketBrainError, RecordsError):
        raise HistoricalReanalysisError(
            "historical decision reconstruction unavailable"
        ) from None
