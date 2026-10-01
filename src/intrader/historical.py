"""Read-only SmartAPI historical one-minute candle downloads."""

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
import csv
import json
import time as time_module
from typing import Iterable

from intrader.auth import HTTPTransport, SmartSession, authenticate, request_headers
from intrader.checkpoint2 import INDIA_TIME, check_market_access
from intrader.instruments import Instrument, NiftyInstruments
from intrader.secrets import SecretStore


CANDLE_URL = "https://apiconnect.angelone.in/rest/secure/angelbroking/historical/v1/getCandleData"
ONE_MINUTE = "ONE_MINUTE"
MARKET_OPEN = time(9, 15)
MARKET_CLOSE = time(15, 30)


class HistoricalDownloadError(Exception):
    """A sanitized historical-data failure safe to display or log."""


@dataclass(frozen=True, slots=True)
class Candle:
    timestamp: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int


@dataclass(frozen=True, slots=True)
class InstrumentDownload:
    instrument: Instrument
    rows: int


@dataclass(frozen=True, slots=True)
class HistoricalDownloadReport:
    trading_date: str
    csv_path: Path
    manifest_path: Path
    total_rows: int
    instruments: tuple[InstrumentDownload, ...]


class HistoricalCandleClient:
    """Small read-only wrapper around SmartAPI historical candle data."""

    def __init__(self, session: SmartSession, transport: HTTPTransport) -> None:
        self._transport = transport
        try:
            public_ip = transport.public_ip()
            self._headers = request_headers(
                session.api_key, public_ip, session.jwt_token
            )
        except Exception:
            raise HistoricalDownloadError("Historical data access unavailable") from None

    def one_minute(
        self,
        instrument: Instrument,
        start: datetime,
        end: datetime,
    ) -> tuple[Candle, ...]:
        if end < start:
            raise HistoricalDownloadError("Historical candle window invalid")

        body = {
            "exchange": instrument.exchange,
            "symboltoken": instrument.token,
            "interval": ONE_MINUTE,
            "fromdate": start.strftime("%Y-%m-%d %H:%M"),
            "todate": end.strftime("%Y-%m-%d %H:%M"),
        }
        try:
            response = self._transport.post_json(
                CANDLE_URL, self._headers, body, timeout=20
            )
        except Exception:
            raise HistoricalDownloadError("Historical candle request failed") from None

        if not isinstance(response, dict) or response.get("status") is not True:
            raise HistoricalDownloadError("Historical candle request failed")

        raw_rows = response.get("data")
        if raw_rows is None:
            return ()
        if not isinstance(raw_rows, list):
            raise HistoricalDownloadError("Historical candle response invalid")

        candles: list[Candle] = []
        for row in raw_rows:
            if not isinstance(row, (list, tuple)) or len(row) < 6:
                raise HistoricalDownloadError("Historical candle response invalid")
            try:
                timestamp = str(row[0])
                values = tuple(Decimal(str(value)) for value in row[1:5])
                if any(not value.is_finite() for value in values):
                    raise InvalidOperation
                volume_decimal = Decimal(str(row[5]))
                if not volume_decimal.is_finite() or volume_decimal < 0:
                    raise InvalidOperation
                volume = int(volume_decimal)
            except (InvalidOperation, TypeError, ValueError):
                raise HistoricalDownloadError("Historical candle response invalid") from None
            candles.append(
                Candle(
                    timestamp=timestamp,
                    open=values[0],
                    high=values[1],
                    low=values[2],
                    close=values[3],
                    volume=volume,
                )
            )
        return tuple(candles)


def _selected_instruments(bundle: NiftyInstruments) -> tuple[Instrument, ...]:
    items = (
        bundle.spot,
        bundle.vix,
        bundle.future,
        *bundle.calls,
        *bundle.puts,
    )
    seen: set[tuple[str, str]] = set()
    selected: list[Instrument] = []
    for item in items:
        key = (item.exchange, item.token)
        if key not in seen:
            selected.append(item)
            seen.add(key)
    return tuple(selected)


def _today_window(now: datetime) -> tuple[datetime, datetime]:
    local_now = now
    if local_now.tzinfo is None:
        local_now = local_now.replace(tzinfo=INDIA_TIME)
    else:
        local_now = local_now.astimezone(INDIA_TIME)

    start = datetime.combine(local_now.date(), MARKET_OPEN, tzinfo=INDIA_TIME)
    close = datetime.combine(local_now.date(), MARKET_CLOSE, tzinfo=INDIA_TIME)

    if local_now < start + timedelta(minutes=1):
        raise HistoricalDownloadError("No completed market minute available today")

    if local_now > close:
        end = close
    else:
        end = local_now.replace(second=0, microsecond=0) - timedelta(minutes=1)

    if end < start:
        raise HistoricalDownloadError("No completed market minute available today")
    return start, end


def _option_type(instrument: Instrument) -> str:
    if instrument.instrument_type != "OPTIDX":
        return ""
    if instrument.symbol.endswith("CE"):
        return "CE"
    if instrument.symbol.endswith("PE"):
        return "PE"
    return ""


def _decimal_text(value: Decimal | None) -> str:
    if value is None:
        return ""
    return format(value, "f")


def _write_csv(
    path: Path,
    rows: Iterable[tuple[Instrument, Candle]],
) -> int:
    fieldnames = [
        "timestamp",
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
    count = 0
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for instrument, candle in rows:
            writer.writerow(
                {
                    "timestamp": candle.timestamp,
                    "exchange": instrument.exchange,
                    "token": instrument.token,
                    "symbol": instrument.symbol,
                    "instrument_type": instrument.instrument_type,
                    "expiry": instrument.expiry.isoformat() if instrument.expiry else "",
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
            count += 1
    return count


def download_today_candles(
    store: SecretStore,
    transport: HTTPTransport,
    *,
    output_root: Path,
    now: datetime | None = None,
    request_delay_seconds: float = 0.4,
) -> HistoricalDownloadReport:
    """Download today's completed one-minute NIFTY market candles to CSV."""

    current = now or datetime.now(INDIA_TIME)
    start, end = _today_window(current)

    try:
        access = check_market_access(
            store,
            transport,
            as_of=start.date(),
            now=current,
        )
        session = authenticate(store, transport, now=current)
    except Exception:
        raise HistoricalDownloadError("Historical data access unavailable") from None

    instruments = _selected_instruments(access.instruments)
    client = HistoricalCandleClient(session, transport)

    all_rows: list[tuple[Instrument, Candle]] = []
    downloads: list[InstrumentDownload] = []

    for index, instrument in enumerate(instruments):
        candles = client.one_minute(instrument, start, end)
        downloads.append(InstrumentDownload(instrument, len(candles)))
        all_rows.extend((instrument, candle) for candle in candles)
        if request_delay_seconds > 0 and index < len(instruments) - 1:
            time_module.sleep(request_delay_seconds)

    if not all_rows:
        raise HistoricalDownloadError("No historical candles returned for today")

    all_rows.sort(
        key=lambda item: (
            item[1].timestamp,
            item[0].exchange,
            item[0].symbol,
        )
    )

    day_dir = Path(output_root) / start.date().isoformat()
    day_dir.mkdir(parents=True, exist_ok=True)
    csv_path = day_dir / "market_1m.csv"
    manifest_path = day_dir / "manifest.json"

    total_rows = _write_csv(csv_path, all_rows)
    manifest = {
        "trading_date": start.date().isoformat(),
        "interval": ONE_MINUTE,
        "from": start.strftime("%Y-%m-%d %H:%M"),
        "to": end.strftime("%Y-%m-%d %H:%M"),
        "csv": csv_path.name,
        "selection": "NIFTY spot, India VIX, nearest NIFTY future, and current ATM +/-4 CE/PE",
        "instruments": [
            {
                "exchange": item.instrument.exchange,
                "token": item.instrument.token,
                "symbol": item.instrument.symbol,
                "instrument_type": item.instrument.instrument_type,
                "expiry": (
                    item.instrument.expiry.isoformat()
                    if item.instrument.expiry
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
        "total_rows": total_rows,
    }
    manifest_path.write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )

    return HistoricalDownloadReport(
        trading_date=start.date().isoformat(),
        csv_path=csv_path,
        manifest_path=manifest_path,
        total_rows=total_rows,
        instruments=tuple(downloads),
    )
