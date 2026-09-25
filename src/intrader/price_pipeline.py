"""Load stored Phase 1 data and build one price-structure snapshot."""

from collections import defaultdict
from datetime import date, datetime, time, timedelta
from typing import Sequence
from zoneinfo import ZoneInfo

from intrader.config import AppConfig
from intrader.historical import Candle
from intrader.instruments import NiftyInstruments
from intrader.price_structure import (
    PriceStructureError,
    PriceStructureSnapshot,
    build_price_structure_snapshot,
)
from intrader.storage import SQLiteStore, StorageError


class PricePipelineError(Exception):
    """Stored data cannot produce a trustworthy price-structure snapshot."""


def _session_groups(
    candles: Sequence[Candle],
    timezone_name: str,
) -> dict[date, list[Candle]]:
    zone = ZoneInfo(timezone_name)
    grouped: dict[date, list[Candle]] = defaultdict(list)
    for candle in candles:
        grouped[candle.at.astimezone(zone).date()].append(candle)
    return dict(grouped)


def build_stored_price_structure(
    store: SQLiteStore,
    instruments: NiftyInstruments,
    session_date: date,
    at: datetime,
    config: AppConfig,
    *,
    volume_baseline_sessions: int = 5,
) -> PriceStructureSnapshot:
    """Build price structure from SQLite using resolved current instruments."""

    if at.tzinfo is None:
        raise PricePipelineError("analysis timestamp must be timezone aware")
    if volume_baseline_sessions < 0:
        raise PricePipelineError("volume baseline count invalid")

    zone = ZoneInfo(config.timezone)
    market_open = datetime.combine(session_date, time(9, 15), zone)
    at_local = at.astimezone(zone)
    if at_local.date() != session_date or at_local < market_open:
        raise PricePipelineError("analysis timestamp outside session")

    try:
        spot = store.load_candles(
            instruments.spot.exchange,
            instruments.spot.token,
            "ONE_MINUTE",
            start=market_open,
            end=at_local,
        )
        future = store.load_candles(
            instruments.future.exchange,
            instruments.future.token,
            "ONE_MINUTE",
            start=market_open,
            end=at_local,
        )

        previous_cutoff = market_open - timedelta(microseconds=1)
        prior_spot_all = store.load_candles(
            instruments.spot.exchange,
            instruments.spot.token,
            "ONE_MINUTE",
            end=previous_cutoff,
        )
        prior_spot_groups = _session_groups(prior_spot_all, config.timezone)
        previous_spot: Sequence[Candle] | None = None
        if prior_spot_groups:
            previous_date = max(prior_spot_groups)
            previous_spot = prior_spot_groups[previous_date]

        prior_future_all = store.load_candles(
            instruments.future.exchange,
            instruments.future.token,
            "ONE_MINUTE",
            end=previous_cutoff,
        )
        prior_future_groups = _session_groups(prior_future_all, config.timezone)
        baseline_dates = sorted(prior_future_groups, reverse=True)[
            :volume_baseline_sessions
        ]
        future_baselines = [
            prior_future_groups[baseline_date]
            for baseline_date in reversed(baseline_dates)
        ]

        return build_price_structure_snapshot(
            spot,
            future,
            market_open=market_open,
            at=at_local,
            previous_spot_candles=previous_spot,
            future_volume_baselines=future_baselines,
        )
    except (StorageError, PriceStructureError):
        raise PricePipelineError("stored price structure unavailable") from None
