"""Build the Phase 2 Market Brain from synchronized stored measurements."""

from datetime import date, datetime

from intrader.breadth_pipeline import (
    BreadthPipelineError,
    build_stored_breadth,
)
from intrader.config import AppConfig
from intrader.context import ContextSnapshot
from intrader.context_pipeline import (
    ContextPipelineError,
    load_cached_context,
)
from intrader.feed_health import HealthSnapshot
from intrader.instruments import NiftyInstruments
from intrader.market_brain import (
    MarketBrainError,
    MarketBrainSnapshot,
    build_market_brain,
)
from intrader.market_confirmation_pipeline import (
    build_stored_market_confirmation,
)
from intrader.options_pipeline import build_stored_options_intelligence
from intrader.price_pipeline import build_stored_price_structure
from intrader.storage import SQLiteStore


class BrainPipelineError(Exception):
    """Stored core data cannot produce a synchronized Market Brain snapshot."""


def build_stored_market_brain(
    store: SQLiteStore,
    instruments: NiftyInstruments,
    session_date: date,
    at: datetime,
    config: AppConfig,
) -> MarketBrainSnapshot:
    """Build all required core families at one timestamp from SQLite."""

    try:
        price = build_stored_price_structure(
            store,
            instruments,
            session_date,
            at,
            config,
        )
        options = build_stored_options_intelligence(
            store,
            session_date,
            at,
            config,
        )
        market = build_stored_market_confirmation(
            store,
            instruments,
            session_date,
            at,
            config,
        )
    except Exception:
        raise BrainPipelineError("core Market Brain data unavailable") from None

    breadth = None
    try:
        breadth = build_stored_breadth(
            store,
            session_date,
            at,
            config,
        )
    except BreadthPipelineError:
        pass

    context: ContextSnapshot | None = None
    try:
        context = load_cached_context(store, at)
    except ContextPipelineError:
        pass

    # Options pipeline proves 18 fresh contracts; market confirmation proves
    # fresh spot, VIX and future snapshots. Together they reconstruct all 21
    # core feed-health requirements for a stored diagnostic timestamp.
    reconstructed_health = HealthSnapshot("READY", (), 21, 21)

    try:
        return build_market_brain(
            price,
            options,
            market,
            reconstructed_health,
            breadth=breadth,
            context=context,
        )
    except MarketBrainError:
        raise BrainPipelineError("Market Brain calculation unavailable") from None
