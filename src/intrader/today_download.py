"""Export today's completed one-minute NIFTY market candles to CSV."""

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
import csv
import json
import time as time_module
from typing import Callable

from intrader.auth import HTTPTransport, SmartSession
from intrader.historical import INDIA_TIME, HistoricalDataError, fetch_candles
from intrader.instruments import Instrument, NiftyInstruments


MARKET_OPEN = time(9, 15)
MARKET_CLOSE = time(15, 30)


class TodayDownloadError(Exception):
    """Today's one-minute export is unavailable."""


@dataclass(frozen=True, slots=True)
class InstrumentDownload:
    instrument: Instrument
    rows: int


@dataclass(frozen=True, slots=True)
class TodayDownloadReport:
    trading_date: str
    csv_path: Path
    manifest_path: Path
    total_rows: int
    instruments: tuple[InstrumentDownload, ...]


def completed_market_window(now: datetime) -> tuple[datetime, datetime]:
    """Return today's market-open through last completed minute in India time."""

    local_now = now
    if local_now.tzinfo is None:
        local_now = local_now.replace(tzinfo=INDIA_TIME)
    else:
        local_now = local_now.astimezone(INDIA_TIME)

    start = datetime.combine(local_now.date(), MARKET_OPEN, tzinfo=INDIA_TIME)
    close = datetime.combine(local_now.date(), MARKET_CLOSE, tzinfo=INDIA_TIME)

    if local_now < start + timedelta(minutes=1):
        raise TodayDownloadError("No completed market minute available today")

    if local_now >= close:
        end = close
    else:
        end = local_now.replace(second=0, microsecond=0) - timedelta(minutes=1)

    if end <= start:
        raise TodayDownloadError("No completed market minute available today")
    return start, end


def selected_instruments(bundle: NiftyInstruments) -> tuple[Instrument, ...]:
    """Return NIFTY spot, VIX, nearest future, and ATM +/-4 CE/PE once each."""

    items = (
        bundle.spot,
        bundle.vix,
        bundle.future,
        *bundle.calls,
        *bundle.puts,
    )
    seen: set[tuple[str, str]] = set()
    result: list[Instrument] = []
    for instrument in items:
        key = (instrument.exchange, instrument.token)
        if key in seen:
            continue
        seen.add(key)
        result.append(instrument)
    return tuple(result)


def _decimal_text(value: Decimal | None) -> str:
    return "" if value is None else format(value, "f")


def _option_type(instrument: Instrument) -> str:
    if instrument.instrument_type != "OPTIDX":
        return ""
    if instrument.symbol.endswith("CE"):
        return "CE"
    if instrument.symbol.endswith("PE"):
        return "PE"
    return ""


def download_today_1m(
    session: SmartSession,
    transport: HTTPTransport,
    instruments: NiftyInstruments,
    *,
    output_root: Path,
    now: datetime | None = None,
    request_delay: float = 0.35,
    sleeper: Callable[[float], None] = time_module.sleep,
) -> TodayDownloadReport:
    """Download today's completed one-minute candles for the resolved NIFTY set."""

    if request_delay < 0:
        raise TodayDownloadError("request delay invalid")

    current = now or datetime.now(INDIA_TIME)
    start, end = completed_market_window(current)
    targets = selected_instruments(instruments)

    rows: list[tuple[Instrument, object]] = []
    downloads: list[InstrumentDownload] = []

    try:
        for index, instrument in enumerate(targets):
            candles = fetch_candles(
                session,
                transport,
                instrument,
                start,
                end,
                "ONE_MINUTE",
            )
            downloads.append(InstrumentDownload(instrument, len(candles)))
            rows.extend((instrument, candle) for candle in candles)
            if request_delay > 0 and index < len(targets) - 1:
                sleeper(request_delay)
    except HistoricalDataError:
        raise TodayDownloadError("Historical candle download unavailable") from None

    if not rows:
        raise TodayDownloadError("No one-minute candles returned for today")

    rows.sort(
        key=lambda item: (
            item[1].at,
            item[0].exchange,
            item[0].symbol,
        )
    )

    day_dir = Path(output_root) / start.date().isoformat()
    day_dir.mkdir(parents=True, exist_ok=True)
    csv_path = day_dir / "market_1m.csv"
    manifest_path = day_dir / "manifest.json"

    fieldnames = [
        "timestamp_ist",
        "exchange",
        "token",
        "symbol",
        "instrument_type",
        "expiry",
        "strike",
        "option_type",
        "open",
        "high",
        "low",
        "close",
        "volume",
    ]

    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for instrument, candle in rows:
            writer.writerow(
                {
                    "timestamp_ist": candle.at.astimezone(INDIA_TIME).isoformat(),
                    "exchange": instrument.exchange,
                    "token": instrument.token,
                    "symbol": instrument.symbol,
                    "instrument_type": instrument.instrument_type,
                    "expiry": (
                        instrument.expiry.isoformat()
                        if instrument.expiry is not None
                        else ""
                    ),
                    "strike": (
                        _decimal_text(instrument.strike)
                        if instrument.instrument_type == "OPTIDX"
                        else ""
                    ),
                    "option_type": _option_type(instrument),
                    "open": _decimal_text(candle.open),
                    "high": _decimal_text(candle.high),
                    "low": _decimal_text(candle.low),
                    "close": _decimal_text(candle.close),
                    "volume": candle.volume,
                }
            )

    manifest = {
        "trading_date": start.date().isoformat(),
        "interval": "ONE_MINUTE",
        "from_ist": start.isoformat(),
        "to_ist": end.isoformat(),
        "selection": (
            "NIFTY spot, India VIX, nearest NIFTY future, "
            "and nearest-expiry ATM +/-4 CE/PE"
        ),
        "csv": csv_path.name,
        "total_rows": len(rows),
        "instruments": [
            {
                "exchange": item.instrument.exchange,
                "token": item.instrument.token,
                "symbol": item.instrument.symbol,
                "instrument_type": item.instrument.instrument_type,
                "expiry": (
                    item.instrument.expiry.isoformat()
                    if item.instrument.expiry is not None
                    else None
                ),
                "strike": (
                    _decimal_text(item.instrument.strike)
                    if item.instrument.instrument_type == "OPTIDX"
                    else None
                ),
                "option_type": _option_type(item.instrument) or None,
                "rows": item.rows,
            }
            for item in downloads
        ],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    return TodayDownloadReport(
        trading_date=start.date().isoformat(),
        csv_path=csv_path,
        manifest_path=manifest_path,
        total_rows=len(rows),
        instruments=tuple(downloads),
    )
