"""Read-only Angel One historical candle and OI access."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from intrader.auth import HTTPTransport, SmartSession, request_headers
from intrader.instruments import Instrument


CANDLE_URL = "https://apiconnect.angelone.in/rest/secure/angelbroking/historical/v1/getCandleData"
OI_URL = "https://apiconnect.angelone.in/rest/secure/angelbroking/historical/v1/getOIData"
INDIA_TIME = timezone(timedelta(hours=5, minutes=30))
ONE_MINUTE_MAX = timedelta(days=30)


class HistoricalDataError(Exception):
    """Historical market data is unavailable or invalid."""


@dataclass(frozen=True, slots=True)
class Candle:
    at: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int


@dataclass(frozen=True, slots=True)
class OIObservation:
    at: datetime
    oi: int


def _validate_window(start: datetime, end: datetime, interval: str) -> None:
    if start.tzinfo is None or end.tzinfo is None:
        raise HistoricalDataError("historical range must be timezone aware")
    if start >= end:
        raise HistoricalDataError("historical range invalid")
    if interval != "ONE_MINUTE":
        raise HistoricalDataError("unsupported historical interval")
    if end - start > ONE_MINUTE_MAX:
        raise HistoricalDataError("historical range exceeds interval limit")


def _body(instrument: Instrument, start: datetime, end: datetime, interval: str) -> dict:
    return {
        "exchange": instrument.exchange,
        "symboltoken": instrument.token,
        "interval": interval,
        "fromdate": start.astimezone(INDIA_TIME).strftime("%Y-%m-%d %H:%M"),
        "todate": end.astimezone(INDIA_TIME).strftime("%Y-%m-%d %H:%M"),
    }


def _headers(session: SmartSession, transport: HTTPTransport) -> dict[str, str]:
    try:
        return request_headers(
            session.api_key, transport.public_ip(), session.jwt_token
        )
    except Exception:
        raise HistoricalDataError("historical request unavailable") from None


def _timestamp(value: object) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        raise HistoricalDataError("historical timestamp invalid") from None
    if parsed.tzinfo is None:
        raise HistoricalDataError("historical timestamp invalid")
    return parsed.astimezone(timezone.utc)


def fetch_candles(
    session: SmartSession,
    transport: HTTPTransport,
    instrument: Instrument,
    start: datetime,
    end: datetime,
    interval: str = "ONE_MINUTE",
) -> tuple[Candle, ...]:
    """Fetch a validated historical candle range for one instrument."""

    _validate_window(start, end, interval)
    try:
        response = transport.post_json(
            CANDLE_URL,
            _headers(session, transport),
            _body(instrument, start, end, interval),
            timeout=15,
        )
    except HistoricalDataError:
        raise
    except Exception:
        raise HistoricalDataError("historical candle request unavailable") from None
    if not isinstance(response, dict) or response.get("status") is not True:
        raise HistoricalDataError("historical candle request rejected")
    data = response.get("data")
    if not isinstance(data, list):
        raise HistoricalDataError("historical candle response invalid")

    candles: list[Candle] = []
    for row in data:
        if not isinstance(row, list) or len(row) != 6:
            raise HistoricalDataError("historical candle response invalid")
        try:
            at = _timestamp(row[0])
            open_ = Decimal(str(row[1]))
            high = Decimal(str(row[2]))
            low = Decimal(str(row[3]))
            close = Decimal(str(row[4]))
            volume = int(row[5])
        except (InvalidOperation, TypeError, ValueError):
            raise HistoricalDataError("historical candle response invalid") from None
        prices = (open_, high, low, close)
        if (
            any(not price.is_finite() or price <= 0 for price in prices)
            or high < max(open_, close, low)
            or low > min(open_, close, high)
            or volume < 0
        ):
            raise HistoricalDataError("historical candle response invalid")
        candles.append(Candle(at, open_, high, low, close, volume))
    return tuple(candles)


def fetch_oi(
    session: SmartSession,
    transport: HTTPTransport,
    instrument: Instrument,
    start: datetime,
    end: datetime,
    interval: str = "ONE_MINUTE",
) -> tuple[OIObservation, ...]:
    """Fetch historical OI for a live NFO contract."""

    _validate_window(start, end, interval)
    if instrument.exchange != "NFO":
        raise HistoricalDataError("historical OI requires NFO instrument")
    try:
        response = transport.post_json(
            OI_URL,
            _headers(session, transport),
            _body(instrument, start, end, interval),
            timeout=15,
        )
    except HistoricalDataError:
        raise
    except Exception:
        raise HistoricalDataError("historical OI request unavailable") from None
    if not isinstance(response, dict) or response.get("status") is not True:
        raise HistoricalDataError("historical OI request rejected")
    data = response.get("data")
    if not isinstance(data, list):
        raise HistoricalDataError("historical OI response invalid")

    observations: list[OIObservation] = []
    for row in data:
        if not isinstance(row, dict) or "time" not in row or "oi" not in row:
            raise HistoricalDataError("historical OI response invalid")
        try:
            at = _timestamp(row["time"])
            oi = int(row["oi"])
        except (TypeError, ValueError):
            raise HistoricalDataError("historical OI response invalid") from None
        if oi < 0:
            raise HistoricalDataError("historical OI response invalid")
        observations.append(OIObservation(at, oi))
    return tuple(observations)
