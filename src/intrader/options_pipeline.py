"""Build option-chain intelligence from locally stored Phase 1 snapshots."""

from collections import defaultdict
from datetime import date, datetime, time
from typing import Sequence
from zoneinfo import ZoneInfo

from intrader.config import AppConfig
from intrader.options_intelligence import (
    OptionChainSnapshot,
    OptionSnapshot,
    OptionsIntelligenceError,
    build_options_intelligence,
)
from intrader.storage import SQLiteStore, StorageError


class OptionsPipelineError(Exception):
    """Stored data cannot produce a trustworthy option-chain snapshot."""


def _group_by_token(
    snapshots: Sequence[OptionSnapshot],
) -> dict[str, list[OptionSnapshot]]:
    grouped: dict[str, list[OptionSnapshot]] = defaultdict(list)
    for snapshot in snapshots:
        grouped[snapshot.token].append(snapshot)
    return dict(grouped)


def build_stored_options_intelligence(
    store: SQLiteStore,
    session_date: date,
    at: datetime,
    config: AppConfig,
    *,
    lookback_minutes: int = 5,
    baseline_max_age_seconds: float = 30.0,
) -> OptionChainSnapshot:
    """Build the active stored ATM-window option intelligence snapshot."""

    if at.tzinfo is None:
        raise OptionsPipelineError("analysis timestamp must be timezone aware")
    if lookback_minutes <= 0:
        raise OptionsPipelineError("option lookback invalid")

    zone = ZoneInfo(config.timezone)
    at_local = at.astimezone(zone)
    market_open = datetime.combine(session_date, time(9, 15), zone)
    if at_local.date() != session_date or at_local < market_open:
        raise OptionsPipelineError("analysis timestamp outside session")

    try:
        snapshots = store.load_option_snapshots(
            start=market_open,
            end=at_local,
        )
    except StorageError:
        raise OptionsPipelineError("stored options unavailable") from None

    eligible_expiries = sorted(
        {
            snapshot.expiry
            for snapshot in snapshots
            if snapshot.expiry >= session_date
        }
    )
    if not eligible_expiries:
        raise OptionsPipelineError("stored option expiry unavailable")
    expiry = eligible_expiries[0]
    expiry_snapshots = [
        snapshot for snapshot in snapshots if snapshot.expiry == expiry
    ]
    histories = _group_by_token(expiry_snapshots)

    fresh_tokens: list[str] = []
    for token, history in histories.items():
        latest = history[-1]
        age = (at_local - latest.exchange_at.astimezone(zone)).total_seconds()
        if -2 <= age <= config.stale_option_seconds:
            fresh_tokens.append(token)

    expected_contract_count = 2 * ((2 * config.option_strikes_each_side) + 1)
    if len(fresh_tokens) != expected_contract_count:
        raise OptionsPipelineError("active option chain incomplete")

    try:
        return build_options_intelligence(
            histories,
            at_local,
            expected_tokens=tuple(sorted(fresh_tokens)),
            lookback_minutes=lookback_minutes,
            current_max_age_seconds=config.stale_option_seconds,
            baseline_max_age_seconds=baseline_max_age_seconds,
        )
    except OptionsIntelligenceError:
        raise OptionsPipelineError("stored options intelligence unavailable") from None
