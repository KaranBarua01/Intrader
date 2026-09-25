"""Read-only SmartAPI market access check for Phase 1 Checkpoint 2."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from intrader.auth import HTTPTransport, authenticate, request_headers
from intrader.instruments import (
    InstrumentError,
    NiftyInstruments,
    fetch_instrument_master,
    resolve_nifty_instruments,
)
from intrader.secrets import SecretStore


QUOTE_URL = "https://apiconnect.angelone.in/rest/secure/angelbroking/market/v1/quote"
INDIA_TIME = timezone(timedelta(hours=5, minutes=30))


class MarketAccessError(Exception):
    """Market access is unavailable; the message never includes API payloads."""


@dataclass(frozen=True, slots=True)
class Checkpoint2Report:
    spot_ltp: Decimal
    instruments: NiftyInstruments


def check_market_access(
    store: SecretStore,
    transport: HTTPTransport,
    *,
    as_of: date | None = None,
    now: datetime | None = None,
) -> Checkpoint2Report:
    """Verify authentication and one NIFTY spot quote, then resolve contracts."""

    current_date = as_of or datetime.now(INDIA_TIME).date()
    try:
        master = fetch_instrument_master(transport)
    except InstrumentError:
        raise MarketAccessError("Instrument master unavailable") from None
    spots = [
        item for item in master
        if item.name == "NIFTY" and item.symbol.upper() == "NIFTY 50"
        and item.instrument_type == "AMXIDX" and item.exchange == "NSE"
    ]
    if len(spots) != 1:
        raise MarketAccessError("NIFTY spot token unavailable")
    spot = spots[0]

    try:
        session = authenticate(store, transport, now=now)
        headers = request_headers(session.api_key, transport.public_ip(), session.jwt_token)
        quote = transport.post_json(
            QUOTE_URL,
            headers,
            {"mode": "LTP", "exchangeTokens": {"NSE": [spot.token]}},
            timeout=10,
        )
    except Exception:
        raise MarketAccessError("SmartAPI market quote unavailable") from None

    if not isinstance(quote, dict) or quote.get("status") is not True:
        raise MarketAccessError("SmartAPI market quote unavailable")
    data = quote.get("data")
    if not isinstance(data, dict) or data.get("unfetched") or not isinstance(data.get("fetched"), list):
        raise MarketAccessError("SmartAPI market quote incomplete")
    matching = [
        item for item in data["fetched"]
        if isinstance(item, dict) and item.get("exchange") == "NSE"
        and str(item.get("symbolToken")) == spot.token
    ]
    if len(matching) != 1:
        raise MarketAccessError("SmartAPI market quote incomplete")
    try:
        ltp = Decimal(str(matching[0]["ltp"]))
        if not ltp.is_finite() or ltp <= 0:
            raise InvalidOperation
    except (KeyError, TypeError, InvalidOperation):
        raise MarketAccessError("SmartAPI market quote incomplete") from None
    try:
        bundle = resolve_nifty_instruments(master, current_date, ltp)
    except InstrumentError:
        raise MarketAccessError("NIFTY instrument resolution unavailable") from None
    return Checkpoint2Report(ltp, bundle)
