"""Download real historical NIFTY option candles from Upstox.

The downloader uses Angel One only for the historical NIFTY spot range that
defines which strikes must be acquired. Replay/strategy logic must remain
causal and must not receive future spot-range information from this module.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal
import json
from pathlib import Path
import time as time_module
from typing import Callable, Sequence

from intrader.auth import HTTPTransport, SmartSession
from intrader.historical import Candle, INDIA_TIME, HistoricalDataError, fetch_candles
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
