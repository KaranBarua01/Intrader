"""Build futures/VIX/order-flow confirmation from stored live snapshots."""

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from intrader.config import AppConfig
from intrader.instruments import NiftyInstruments
from intrader.market_confirmation import (
    MarketConfirmationError,
    MarketConfirmationSnapshot,
    build_market_confirmation,
)
from intrader.storage import SQLiteStore, StorageError


class MarketConfirmationPipelineError(Exception):
    """Stored market data cannot produce a trustworthy confirmation snapshot."""


def build_stored_market_confirmation(
    store: SQLiteStore,
    instruments: NiftyInstruments,
    session_date: date,
    at: datetime,
    config: AppConfig,
    *,
    lookback_minutes: int = 5,
) -> MarketConfirmationSnapshot:
    """Load aligned spot/VIX/future histories and build confirmation metrics."""

    if at.tzinfo is None:
        raise MarketConfirmationPipelineError(
            "analysis timestamp must be timezone aware"
        )
    zone = ZoneInfo(config.timezone)
    at_local = at.astimezone(zone)
    market_open = datetime.combine(session_date, time(9, 15), zone)
    if at_local.date() != session_date or at_local < market_open:
        raise MarketConfirmationPipelineError("analysis timestamp outside session")

    try:
        spot = store.load_index_snapshots(
            instruments.spot.token,
            start=market_open,
            end=at_local,
        )
        vix = store.load_index_snapshots(
            instruments.vix.token,
            start=market_open,
            end=at_local,
        )
        future = store.load_future_snapshots(
            instruments.future.token,
            start=market_open,
            end=at_local,
        )
        return build_market_confirmation(
            spot,
            vix,
            future,
            at_local,
            lookback_minutes=lookback_minutes,
            current_max_age_seconds=config.stale_tick_seconds,
            baseline_max_age_seconds=30.0,
        )
    except (StorageError, MarketConfirmationError):
        raise MarketConfirmationPipelineError(
            "stored market confirmation unavailable"
        ) from None
