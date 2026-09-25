"""Core market historical backfill for Intrader warm-up."""

from dataclasses import dataclass
from datetime import datetime
import time
from typing import Callable

from intrader.auth import HTTPTransport, SmartSession
from intrader.historical import HistoricalDataError, fetch_candles, fetch_oi
from intrader.instruments import NiftyInstruments
from intrader.storage import SQLiteStore, StorageError


class BackfillError(Exception):
    """The warm-up historical backfill gate failed."""


@dataclass(frozen=True, slots=True)
class BackfillReport:
    candle_rows: int
    oi_rows: int
    candle_instruments: int


def backfill_core_market(
    store: SQLiteStore,
    session: SmartSession,
    transport: HTTPTransport,
    instruments: NiftyInstruments,
    start: datetime,
    end: datetime,
    *,
    request_delay: float = 0.35,
    sleeper: Callable[[float], None] = time.sleep,
) -> BackfillReport:
    """Fetch core one-minute history first, then commit it atomically."""

    if request_delay < 0:
        raise BackfillError("backfill request delay invalid")

    candle_batches = []
    try:
        core = (instruments.spot, instruments.vix, instruments.future)
        for index, instrument in enumerate(core):
            candles = fetch_candles(
                session, transport, instrument, start, end, "ONE_MINUTE"
            )
            candle_batches.append((instrument, "ONE_MINUTE", candles))
            if index < len(core) - 1 or request_delay:
                sleeper(request_delay)
        future_oi = fetch_oi(
            session, transport, instruments.future, start, end, "ONE_MINUTE"
        )
        candle_rows, oi_rows = store.store_backfill(
            candle_batches,
            [(instruments.future, "ONE_MINUTE", future_oi)],
        )
    except (HistoricalDataError, StorageError):
        raise BackfillError("session backfill unavailable") from None

    return BackfillReport(candle_rows, oi_rows, len(candle_batches))
