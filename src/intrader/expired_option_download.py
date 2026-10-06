"""Download real historical NIFTY option candles from Upstox.

The downloader uses Angel One only for the historical NIFTY spot range that
defines which strikes must be acquired. Replay/strategy logic must remain
causal and must not receive future spot-range information from this module.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
import json
from pathlib import Path
import time as time_module
from typing import Callable, Sequence

from intrader.auth import HTTPTransport, SmartSession
from intrader.historical import Candle, INDIA_TIME, HistoricalDataError, fetch_candles
from intrader.historical_options import (
    HistoricalOptionDataError,
    load_historical_option_csv,
)
from intrader.instruments import Instrument
from intrader.upstox import (
    ExpiredOptionCandle,
    ExpiredOptionContract,
    UpstoxDataError,
    UpstoxExpiredClient,
)


MARKET_OPEN = time(9, 15)
MARKET_CLOSE = time(15, 30)


class ExpiredOptionDownloadError(Exception):
    """Historical expired-option acquisition failed closed."""


@dataclass(frozen=True, slots=True)
class ExpiredOptionDownloadReport:
    trading_date: date
    expiry: date
    spot_low: Decimal
    spot_high: Decimal
    selected_strikes: tuple[Decimal, ...]
    contract_count: int
    total_rows: int
    csv_path: Path
    manifest_path: Path


@dataclass(frozen=True, slots=True)
class ExpiredOptionBatchReport:
    end_date: date
    requested_sessions: int
    completed_dates: tuple[date, ...]
    downloaded_dates: tuple[date, ...]
    cached_dates: tuple[date, ...]
    skipped_non_sessions: tuple[date, ...]
    total_rows: int
    summary_path: Path


def _market_window(trading_date: date) -> tuple[datetime, datetime]:
    return (
        datetime.combine(trading_date, MARKET_OPEN, tzinfo=INDIA_TIME),
        datetime.combine(trading_date, MARKET_CLOSE, tzinfo=INDIA_TIME),
    )


def _nearest_index(values: Sequence[Decimal], price: Decimal) -> int:
    return min(
        range(len(values)),
        key=lambda index: (abs(values[index] - price), values[index]),
    )


def nearest_available_expiry(
    expiries: Sequence[date],
    trading_date: date,
) -> date:
    """Return the first expiry on or after the requested trading date."""

    eligible = sorted({expiry for expiry in expiries if expiry >= trading_date})
    if not eligible:
        raise ExpiredOptionDownloadError(
            "No expired NIFTY option expiry covers the requested trading date"
        )
    return eligible[0]


def select_required_contracts(
    contracts: Sequence[ExpiredOptionContract],
    spot_candles: Sequence[Candle],
    *,
    strikes_each_side: int = 4,
) -> tuple[tuple[ExpiredOptionContract, ...], tuple[Decimal, ...], Decimal, Decimal]:
    """Select every CE/PE pair needed for ATM +/-N throughout the session.

    The whole-day spot range is used only to acquire a sufficiently wide raw
    dataset. Strategy/replay code must still reveal candles causally.
    """

    if strikes_each_side < 1:
        raise ExpiredOptionDownloadError("Strike-window size invalid")
    if not spot_candles:
        raise ExpiredOptionDownloadError("NIFTY spot history unavailable")

    by_strike: dict[Decimal, dict[str, ExpiredOptionContract]] = {}
    for contract in contracts:
        if contract.option_type not in {"CE", "PE"}:
            continue
        pair = by_strike.setdefault(contract.strike_price, {})
        if contract.option_type in pair:
            raise ExpiredOptionDownloadError("Duplicate expired option contract")
        pair[contract.option_type] = contract

    complete_strikes = sorted(
        strike
        for strike, pair in by_strike.items()
        if set(pair) == {"CE", "PE"}
    )
    if not complete_strikes:
        raise ExpiredOptionDownloadError("Complete expired option pairs unavailable")

    spot_low = min(candle.low for candle in spot_candles)
    spot_high = max(candle.high for candle in spot_candles)
    low_index = _nearest_index(complete_strikes, spot_low)
    high_index = _nearest_index(complete_strikes, spot_high)
    first = min(low_index, high_index) - strikes_each_side
    last = max(low_index, high_index) + strikes_each_side + 1
    if first < 0 or last > len(complete_strikes):
        raise ExpiredOptionDownloadError("Required expired option window incomplete")

    selected_strikes = tuple(complete_strikes[first:last])
    selected: list[ExpiredOptionContract] = []
    for strike in selected_strikes:
        pair = by_strike[strike]
        selected.extend((pair["CE"], pair["PE"]))

    return (
        tuple(selected),
        selected_strikes,
        spot_low,
        spot_high,
    )


def _decimal_text(value: Decimal) -> str:
    return format(value, "f")


def download_expired_options_1m(
    session: SmartSession,
    angel_transport: HTTPTransport,
    upstox: UpstoxExpiredClient,
    spot: Instrument,
    trading_date: date,
    *,
    output_root: Path,
    strikes_each_side: int = 4,
    request_delay: float = 0.10,
    sleeper: Callable[[float], None] = time_module.sleep,
) -> ExpiredOptionDownloadReport:
    """Download the real one-minute NIFTY option set needed for replay."""

    if request_delay < 0:
        raise ExpiredOptionDownloadError("Request delay invalid")

    start, end = _market_window(trading_date)
    try:
        spot_candles = fetch_candles(
            session,
            angel_transport,
            spot,
            start,
            end,
            "ONE_MINUTE",
        )
    except HistoricalDataError:
        raise ExpiredOptionDownloadError(
            "NIFTY spot history unavailable"
        ) from None
    if not spot_candles:
        raise ExpiredOptionDownloadError(
            "No NIFTY spot candles returned for requested date"
        )

    try:
        expiry = nearest_available_expiry(upstox.get_expiries(), trading_date)
        contracts = upstox.get_option_contracts(expiry)
        selected, selected_strikes, spot_low, spot_high = select_required_contracts(
            contracts,
            spot_candles,
            strikes_each_side=strikes_each_side,
        )
    except UpstoxDataError as exc:
        raise ExpiredOptionDownloadError(str(exc)) from None

    rows: list[tuple[ExpiredOptionContract, ExpiredOptionCandle]] = []
    contract_rows: list[dict[str, object]] = []
    for index, contract in enumerate(selected):
        try:
            candles = upstox.get_historical_candles(
                contract.instrument_key,
                trading_date,
            )
        except UpstoxDataError as exc:
            raise ExpiredOptionDownloadError(
                f"Expired option candles unavailable for {contract.trading_symbol}"
            ) from exc

        same_day = tuple(
            candle
            for candle in candles
            if candle.at.astimezone(INDIA_TIME).date() == trading_date
        )
        if not same_day:
            raise ExpiredOptionDownloadError(
                f"No candles returned for {contract.trading_symbol}"
            )
        rows.extend((contract, candle) for candle in same_day)
        contract_rows.append(
            {
                "trading_symbol": contract.trading_symbol,
                "instrument_key": contract.instrument_key,
                "strike": _decimal_text(contract.strike_price),
                "option_type": contract.option_type,
                "lot_size": contract.lot_size,
                "rows": len(same_day),
                "first_ist": same_day[0].at.astimezone(INDIA_TIME).isoformat(),
                "last_ist": same_day[-1].at.astimezone(INDIA_TIME).isoformat(),
            }
        )
        if request_delay > 0 and index < len(selected) - 1:
            sleeper(request_delay)

    if not rows:
        raise ExpiredOptionDownloadError("No expired option candles returned")

    rows.sort(
        key=lambda item: (
            item[1].at,
            item[0].strike_price,
            item[0].option_type,
        )
    )
    day_dir = Path(output_root) / trading_date.isoformat()
    day_dir.mkdir(parents=True, exist_ok=True)
    csv_path = day_dir / "options_1m.csv"
    manifest_path = day_dir / "options_manifest.json"

    fieldnames = [
        "timestamp_ist",
        "expiry",
        "trading_symbol",
        "instrument_key",
        "strike",
        "option_type",
        "lot_size",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "open_interest",
    ]
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for contract, candle in rows:
            writer.writerow(
                {
                    "timestamp_ist": candle.at.astimezone(INDIA_TIME).isoformat(),
                    "expiry": expiry.isoformat(),
                    "trading_symbol": contract.trading_symbol,
                    "instrument_key": contract.instrument_key,
                    "strike": _decimal_text(contract.strike_price),
                    "option_type": contract.option_type,
                    "lot_size": contract.lot_size,
                    "open": _decimal_text(candle.open),
                    "high": _decimal_text(candle.high),
                    "low": _decimal_text(candle.low),
                    "close": _decimal_text(candle.close),
                    "volume": candle.volume,
                    "open_interest": candle.open_interest,
                }
            )

    manifest = {
        "trading_date": trading_date.isoformat(),
        "option_source": "Upstox expired instruments",
        "spot_selection_source": "Angel One NIFTY 50 one-minute candles",
        "expiry": expiry.isoformat(),
        "spot_low": _decimal_text(spot_low),
        "spot_high": _decimal_text(spot_high),
        "strikes_each_side": strikes_each_side,
        "selected_strikes": [_decimal_text(value) for value in selected_strikes],
        "selection_note": (
            "Whole-day spot range is used only for raw-data acquisition. "
            "Replay logic must remain causal/no-lookahead."
        ),
        "contract_count": len(selected),
        "total_rows": len(rows),
        "csv": csv_path.name,
        "contracts": contract_rows,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    return ExpiredOptionDownloadReport(
        trading_date=trading_date,
        expiry=expiry,
        spot_low=spot_low,
        spot_high=spot_high,
        selected_strikes=selected_strikes,
        contract_count=len(selected),
        total_rows=len(rows),
        csv_path=csv_path,
        manifest_path=manifest_path,
    )



def _cached_option_rows(output_root: Path, trading_date: date) -> int | None:
    """Return validated cached row count, or None when the day must be fetched."""

    csv_path = Path(output_root) / trading_date.isoformat() / "options_1m.csv"
    if not csv_path.is_file():
        return None
    try:
        dataset = load_historical_option_csv(csv_path)
        summary = dataset.summary()
    except HistoricalOptionDataError:
        return None
    if summary.trading_date != trading_date:
        return None
    return summary.rows


def download_expired_option_sessions(
    session: SmartSession,
    angel_transport: HTTPTransport,
    upstox: UpstoxExpiredClient,
    spot: Instrument,
    end_date: date,
    sessions: int,
    *,
    output_root: Path,
    strikes_each_side: int = 4,
    request_delay: float = 0.10,
    session_delay: float = 0.25,
    sleeper: Callable[[float], None] = time_module.sleep,
    progress: Callable[[str], None] | None = None,
) -> ExpiredOptionBatchReport:
    """Download the most recent N complete option sessions ending at end_date.

    Existing validated options_1m.csv files are reused. Weekends are ignored,
    exchange holidays are detected by an empty NIFTY spot response, and any
    genuine broker/provider error stops the batch so partial progress can be
    resumed safely.
    """

    if not 1 <= sessions <= 250:
        raise ExpiredOptionDownloadError(
            "Batch session count must be between 1 and 250"
        )
    if request_delay < 0 or session_delay < 0:
        raise ExpiredOptionDownloadError("Batch delay invalid")

    output_root = Path(output_root)
    completed: list[date] = []
    downloaded: list[date] = []
    cached: list[date] = []
    skipped: list[date] = []
    total_rows = 0
    candidate = end_date
    scanned_days = 0
    max_calendar_days = sessions * 3 + 45

    while len(completed) < sessions and scanned_days < max_calendar_days:
        scanned_days += 1
        if candidate.weekday() >= 5:
            candidate -= timedelta(days=1)
            continue

        cached_rows = _cached_option_rows(output_root, candidate)
        if cached_rows is not None:
            completed.append(candidate)
            cached.append(candidate)
            total_rows += cached_rows
            if progress is not None:
                progress(
                    f"[{len(completed)}/{sessions}] {candidate.isoformat()} "
                    f"CACHED rows={cached_rows}"
                )
            candidate -= timedelta(days=1)
            continue

        try:
            report = download_expired_options_1m(
                session,
                angel_transport,
                upstox,
                spot,
                candidate,
                output_root=output_root,
                strikes_each_side=strikes_each_side,
                request_delay=request_delay,
                sleeper=sleeper,
            )
        except ExpiredOptionDownloadError as exc:
            if str(exc) == "No NIFTY spot candles returned for requested date":
                skipped.append(candidate)
                if progress is not None:
                    progress(f"[--] {candidate.isoformat()} NON-TRADING SESSION")
                candidate -= timedelta(days=1)
                continue
            raise ExpiredOptionDownloadError(
                f"Batch stopped at {candidate.isoformat()}: {exc}"
            ) from exc

        completed.append(candidate)
        downloaded.append(candidate)
        total_rows += report.total_rows
        if progress is not None:
            progress(
                f"[{len(completed)}/{sessions}] {candidate.isoformat()} "
                f"DOWNLOADED rows={report.total_rows}"
            )
        candidate -= timedelta(days=1)
        if session_delay > 0 and len(completed) < sessions:
            sleeper(session_delay)

    if len(completed) < sessions:
        raise ExpiredOptionDownloadError(
            f"Only {len(completed)}/{sessions} historical option sessions "
            "could be resolved inside the batch scan window"
        )

    completed_sorted = tuple(sorted(completed))
    downloaded_sorted = tuple(sorted(downloaded))
    cached_sorted = tuple(sorted(cached))
    skipped_sorted = tuple(sorted(skipped))
    batch_dir = output_root / "_option_batches"
    batch_dir.mkdir(parents=True, exist_ok=True)
    summary_path = batch_dir / (
        f"ending_{end_date.isoformat()}_{sessions}_sessions.json"
    )
    payload = {
        "schema": "intrader-expired-option-batch-v1",
        "end_date": end_date.isoformat(),
        "requested_sessions": sessions,
        "completed_sessions": len(completed_sorted),
        "first_session": completed_sorted[0].isoformat(),
        "last_session": completed_sorted[-1].isoformat(),
        "downloaded_dates": [item.isoformat() for item in downloaded_sorted],
        "cached_dates": [item.isoformat() for item in cached_sorted],
        "skipped_non_sessions": [item.isoformat() for item in skipped_sorted],
        "total_rows": total_rows,
        "resume_rule": (
            "Validated existing options_1m.csv files are reused; failed batches "
            "may be rerun safely."
        ),
    }
    summary_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    return ExpiredOptionBatchReport(
        end_date=end_date,
        requested_sessions=sessions,
        completed_dates=completed_sorted,
        downloaded_dates=downloaded_sorted,
        cached_dates=cached_sorted,
        skipped_non_sessions=skipped_sorted,
        total_rows=total_rows,
        summary_path=summary_path,
    )
