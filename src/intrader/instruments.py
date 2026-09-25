"""Resolve current NIFTY market-data instruments from Angel One's master."""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Protocol, Sequence


MASTER_URL = "https://margincalculator.angelone.in/OpenAPI_File/files/OpenAPIScripMaster.json"


class InstrumentError(Exception):
    """Instrument metadata is missing, ambiguous, or unusable."""


class MasterTransport(Protocol):
    def get_json(self, url: str, timeout: int) -> object:
        ...


@dataclass(frozen=True, slots=True)
class Instrument:
    token: str
    symbol: str
    name: str
    instrument_type: str
    exchange: str
    expiry: date | None
    strike: Decimal | None
    lot_size: int


@dataclass(frozen=True, slots=True)
class NiftyInstruments:
    spot: Instrument
    vix: Instrument
    future: Instrument
    option_expiry: date
    atm_strike: Decimal
    strikes: tuple[Decimal, ...]
    calls: tuple[Instrument, ...]
    puts: tuple[Instrument, ...]


def _parse_relevant_row(row: dict) -> Instrument:
    try:
        token = str(row["token"])
        symbol = str(row["symbol"])
        name = str(row["name"])
        kind = str(row["instrumenttype"])
        exchange = str(row["exch_seg"])
        expiry = datetime.strptime(row["expiry"], "%d%b%Y").date() if row["expiry"] else None
        raw_strike = Decimal(str(row["strike"]))
        strike = raw_strike / 100 if kind == "OPTIDX" else raw_strike
        lot_size = int(row["lotsize"])
        if not token or not symbol or lot_size <= 0 or not strike.is_finite():
            raise ValueError("incomplete instrument")
    except (KeyError, TypeError, ValueError, InvalidOperation):
        raise InstrumentError("instrument master invalid") from None
    return Instrument(token, symbol, name, kind, exchange, expiry, strike, lot_size)


def fetch_full_instrument_master(transport: MasterTransport) -> list[Instrument]:
    """Fetch the official Angel One master without filtering instrument names."""

    try:
        raw = transport.get_json(MASTER_URL, timeout=30)
    except Exception:
        raise InstrumentError("instrument master unavailable") from None
    if not isinstance(raw, list):
        raise InstrumentError("instrument master invalid")

    instruments: list[Instrument] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        try:
            instruments.append(_parse_relevant_row(row))
        except InstrumentError:
            continue
    if not instruments:
        raise InstrumentError("instrument master invalid")
    return instruments


def resolve_nse_equities(
    master: Sequence[Instrument],
    symbols: Sequence[str],
) -> dict[str, Instrument]:
    """Resolve exact NSE -EQ instruments for a requested symbol set."""

    requested = tuple(symbol.strip().upper() for symbol in symbols)
    if not requested or any(not symbol for symbol in requested):
        raise InstrumentError("equity symbols invalid")
    if len(set(requested)) != len(requested):
        raise InstrumentError("duplicate equity symbols")

    resolved: dict[str, Instrument] = {}
    for symbol in requested:
        exact_symbol = f"{symbol}-EQ"
        matches = [
            item
            for item in master
            if item.exchange == "NSE"
            and item.symbol.upper() == exact_symbol
            and item.expiry is None
        ]
        if len(matches) != 1:
            raise InstrumentError(f"NSE equity unavailable: {symbol}")
        resolved[symbol] = matches[0]
    return resolved


def fetch_instrument_master(transport: MasterTransport) -> list[Instrument]:
    """Fetch and parse only NIFTY and India VIX rows from the official master."""

    try:
        raw = transport.get_json(MASTER_URL, timeout=30)
    except Exception:
        raise InstrumentError("instrument master unavailable") from None
    if not isinstance(raw, list):
        raise InstrumentError("instrument master invalid")
    instruments: list[Instrument] = []
    for row in raw:
        if not isinstance(row, dict):
            continue
        if str(row.get("name", "")).upper() in {"NIFTY", "INDIA VIX"}:
            instruments.append(_parse_relevant_row(row))
    if not instruments:
        raise InstrumentError("instrument master invalid")
    return instruments


def _exact_one(items: list[Instrument], missing: str, ambiguous: str) -> Instrument:
    if not items:
        raise InstrumentError(missing)
    if len(items) != 1:
        raise InstrumentError(ambiguous)
    return items[0]


def resolve_nifty_instruments(
    master: Sequence[Instrument],
    as_of: date,
    spot_ltp: Decimal,
    strikes_each_side: int = 4,
) -> NiftyInstruments:
    """Choose spot, VIX, nearest future and a complete ATM option window."""

    if not spot_ltp.is_finite() or spot_ltp <= 0 or strikes_each_side < 1:
        raise InstrumentError("instrument resolution input invalid")
    spot = _exact_one(
        [
            item for item in master
            if item.name == "NIFTY" and item.symbol.upper() == "NIFTY 50"
            and item.exchange == "NSE" and item.instrument_type == "AMXIDX"
        ],
        "NIFTY spot missing",
        "NIFTY spot ambiguous",
    )
    vix = _exact_one(
        [
            item for item in master
            if item.name == "INDIA VIX" and item.exchange == "NSE"
            and item.instrument_type == "AMXIDX"
        ],
        "India VIX missing",
        "India VIX ambiguous",
    )
    futures = sorted(
        (
            item for item in master
            if item.name == "NIFTY" and item.exchange == "NFO"
            and item.instrument_type == "FUTIDX" and item.expiry is not None
            and item.expiry >= as_of
        ),
        key=lambda item: item.expiry,
    )
    if not futures:
        raise InstrumentError("current NIFTY future missing")
    future = _exact_one(
        [item for item in futures if item.expiry == futures[0].expiry],
        "current NIFTY future missing",
        "current NIFTY future ambiguous",
    )

    options = [
        item for item in master
        if item.name == "NIFTY" and item.exchange == "NFO"
        and item.instrument_type == "OPTIDX" and item.expiry is not None
        and item.expiry >= as_of and item.strike is not None
        and item.symbol.endswith(("CE", "PE"))
    ]
    if not options:
        raise InstrumentError("current NIFTY options missing")
    option_expiry = min(item.expiry for item in options if item.expiry is not None)
    nearest = [item for item in options if item.expiry == option_expiry]
    all_strikes = sorted({item.strike for item in nearest if item.strike is not None})
    atm_index = min(
        range(len(all_strikes)),
        key=lambda index: (abs(all_strikes[index] - spot_ltp), all_strikes[index]),
    )
    start = atm_index - strikes_each_side
    end = atm_index + strikes_each_side + 1
    if start < 0 or end > len(all_strikes):
        raise InstrumentError("ATM option window incomplete")
    strikes = tuple(all_strikes[start:end])
    calls: list[Instrument] = []
    puts: list[Instrument] = []
    for strike in strikes:
        calls.append(_exact_one(
            [item for item in nearest if item.strike == strike and item.symbol.endswith("CE")],
            "ATM option pair incomplete", "ATM option pair ambiguous",
        ))
        puts.append(_exact_one(
            [item for item in nearest if item.strike == strike and item.symbol.endswith("PE")],
            "ATM option pair incomplete", "ATM option pair ambiguous",
        ))
    return NiftyInstruments(
        spot, vix, future, option_expiry, all_strikes[atm_index], strikes,
        tuple(calls), tuple(puts),
    )
