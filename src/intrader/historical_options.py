"""Strict local reader for downloaded historical NIFTY option candles.

This module is deliberately file-local and causal-friendly. It does not perform
network requests and it does not choose strategies. The caller decides when a
candle becomes visible to a replay clock.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable


REQUIRED_COLUMNS = frozenset(
    {
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
    }
)


class HistoricalOptionDataError(Exception):
    """Downloaded historical option data is missing or invalid."""


@dataclass(frozen=True, slots=True)
class HistoricalOptionCandle:
    at: datetime
    expiry: date
    trading_symbol: str
    instrument_key: str
    strike: Decimal
    option_type: str
    lot_size: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    open_interest: int


@dataclass(frozen=True, slots=True)
class HistoricalOptionSummary:
    trading_date: date
    rows: int
    contracts: int
    strikes: int
    complete_pair_strikes: int
    first_candle: datetime
    last_candle: datetime


class HistoricalOptionDataset:
    """One trading day's immutable historical option-candle dataset."""

    def __init__(self, rows: Iterable[HistoricalOptionCandle]) -> None:
        ordered = tuple(sorted(rows, key=lambda item: (item.at, item.strike, item.option_type)))
        if not ordered:
            raise HistoricalOptionDataError("historical option dataset is empty")

        days = {row.at.date() for row in ordered}
        if len(days) != 1:
            raise HistoricalOptionDataError("historical option dataset must contain one trading date")
        self._trading_date = next(iter(days))

        by_contract: dict[tuple[Decimal, str], list[HistoricalOptionCandle]] = {}
        seen_rows: set[tuple[str, datetime]] = set()
        contract_keys: dict[tuple[Decimal, str], str] = {}

        for row in ordered:
            if row.option_type not in {"CE", "PE"}:
                raise HistoricalOptionDataError("historical option type invalid")
            if row.at.tzinfo is None:
                raise HistoricalOptionDataError("historical option timestamp must be timezone aware")
            if row.at.date() != self._trading_date:
                raise HistoricalOptionDataError("historical option row date mismatch")
            if row.expiry < self._trading_date:
                raise HistoricalOptionDataError("historical option expiry predates trading date")
            if row.lot_size <= 0 or row.volume < 0 or row.open_interest < 0:
                raise HistoricalOptionDataError("historical option quantity field invalid")
            if row.strike <= 0:
                raise HistoricalOptionDataError("historical option strike invalid")
            prices = (row.open, row.high, row.low, row.close)
            if any(not price.is_finite() or price <= 0 for price in prices):
                raise HistoricalOptionDataError("historical option price invalid")
            if row.high < max(row.open, row.close, row.low):
                raise HistoricalOptionDataError("historical option OHLC invalid")
            if row.low > min(row.open, row.close, row.high):
                raise HistoricalOptionDataError("historical option OHLC invalid")

            identity = (row.instrument_key, row.at)
            if identity in seen_rows:
                raise HistoricalOptionDataError("duplicate historical option candle")
            seen_rows.add(identity)

            key = (row.strike, row.option_type)
            previous_key = contract_keys.get(key)
            if previous_key is not None and previous_key != row.instrument_key:
                raise HistoricalOptionDataError("multiple contracts for same strike and side")
            contract_keys[key] = row.instrument_key
            by_contract.setdefault(key, []).append(row)

        self._rows = ordered
        self._by_contract = {
            key: tuple(values)
            for key, values in by_contract.items()
        }

    @property
    def trading_date(self) -> date:
        return self._trading_date

    @property
    def rows(self) -> tuple[HistoricalOptionCandle, ...]:
        return self._rows

    @property
    def strikes(self) -> tuple[Decimal, ...]:
        return tuple(sorted({row.strike for row in self._rows}))

    @property
    def complete_pair_strikes(self) -> tuple[Decimal, ...]:
        sides: dict[Decimal, set[str]] = {}
        for strike, option_type in self._by_contract:
            sides.setdefault(strike, set()).add(option_type)
        return tuple(
            strike
            for strike in sorted(sides)
            if sides[strike] == {"CE", "PE"}
        )

    def summary(self) -> HistoricalOptionSummary:
        return HistoricalOptionSummary(
            trading_date=self._trading_date,
            rows=len(self._rows),
            contracts=len(self._by_contract),
            strikes=len(self.strikes),
            complete_pair_strikes=len(self.complete_pair_strikes),
            first_candle=self._rows[0].at,
            last_candle=self._rows[-1].at,
        )

    def nearest_complete_strike(self, underlying_price: Decimal) -> Decimal:
        """Choose ATM from strikes that have both CE and PE data."""

        strikes = self.complete_pair_strikes
        if not strikes:
            raise HistoricalOptionDataError("no complete CE/PE strike pairs available")
        if not underlying_price.is_finite() or underlying_price <= 0:
            raise HistoricalOptionDataError("underlying price invalid")
        return min(strikes, key=lambda strike: (abs(strike - underlying_price), strike))

    def candles(
        self,
        strike: Decimal,
        option_type: str,
    ) -> tuple[HistoricalOptionCandle, ...]:
        side = option_type.upper()
        rows = self._by_contract.get((strike, side))
        if rows is None:
            raise HistoricalOptionDataError(
                f"historical option contract unavailable: {strike} {side}"
            )
        return rows

    def visible_at(
        self,
        strike: Decimal,
        option_type: str,
        as_of: datetime,
    ) -> tuple[HistoricalOptionCandle, ...]:
        """Return only candles whose timestamps are not later than the replay clock."""

        if as_of.tzinfo is None:
            raise HistoricalOptionDataError("replay clock must be timezone aware")
        return tuple(
            row
            for row in self.candles(strike, option_type)
            if row.at <= as_of
        )

    def first_candle_after(
        self,
        strike: Decimal,
        option_type: str,
        signal_at: datetime,
        *,
        max_wait_minutes: int = 2,
    ) -> HistoricalOptionCandle | None:
        """Return the first strictly later candle for causal next-bar entry.

        A signal formed on a completed minute cannot enter at that same minute's
        already-known OHLC. Entry therefore starts on the first later option bar.
        """

        if signal_at.tzinfo is None or max_wait_minutes < 1:
            raise HistoricalOptionDataError("causal entry request invalid")
        deadline = signal_at + timedelta(minutes=max_wait_minutes)
        for row in self.candles(strike, option_type):
            if row.at <= signal_at:
                continue
            if row.at <= deadline:
                return row
            return None
        return None

    def first_candle_at_or_after(
        self,
        strike: Decimal,
        option_type: str,
        target_at: datetime,
        *,
        max_wait_minutes: int = 2,
    ) -> HistoricalOptionCandle | None:
        """Evaluator helper for a planned exit timestamp."""

        if target_at.tzinfo is None or max_wait_minutes < 0:
            raise HistoricalOptionDataError("historical exit request invalid")
        deadline = target_at + timedelta(minutes=max_wait_minutes)
        for row in self.candles(strike, option_type):
            if row.at < target_at:
                continue
            if row.at <= deadline:
                return row
            return None
        return None


def _decimal(value: object, field: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise HistoricalOptionDataError(
            f"historical option {field} invalid"
        ) from None
    if not parsed.is_finite():
        raise HistoricalOptionDataError(
            f"historical option {field} invalid"
        )
    return parsed


def load_historical_option_csv(path: Path) -> HistoricalOptionDataset:
    """Load and strictly validate one downloaded options_1m.csv file."""

    path = Path(path)
    if not path.is_file():
        raise HistoricalOptionDataError(f"historical option file missing: {path}")

    try:
        with path.open("r", newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            columns = set(reader.fieldnames or ())
            if not REQUIRED_COLUMNS.issubset(columns):
                raise HistoricalOptionDataError(
                    "historical option CSV columns invalid"
                )

            rows: list[HistoricalOptionCandle] = []
            for raw in reader:
                try:
                    at = datetime.fromisoformat(
                        str(raw["timestamp_ist"]).replace("Z", "+00:00")
                    )
                    expiry = date.fromisoformat(str(raw["expiry"]))
                    trading_symbol = str(raw["trading_symbol"]).strip()
                    instrument_key = str(raw["instrument_key"]).strip()
                    option_type = str(raw["option_type"]).strip().upper()
                    lot_size = int(str(raw["lot_size"]))
                    volume = int(str(raw["volume"]))
                    open_interest = int(str(raw["open_interest"]))
                except (KeyError, TypeError, ValueError):
                    raise HistoricalOptionDataError(
                        "historical option CSV row invalid"
                    ) from None
                if not trading_symbol or not instrument_key:
                    raise HistoricalOptionDataError(
                        "historical option contract identity invalid"
                    )
                rows.append(
                    HistoricalOptionCandle(
                        at=at,
                        expiry=expiry,
                        trading_symbol=trading_symbol,
                        instrument_key=instrument_key,
                        strike=_decimal(raw["strike"], "strike"),
                        option_type=option_type,
                        lot_size=lot_size,
                        open=_decimal(raw["open"], "open"),
                        high=_decimal(raw["high"], "high"),
                        low=_decimal(raw["low"], "low"),
                        close=_decimal(raw["close"], "close"),
                        volume=volume,
                        open_interest=open_interest,
                    )
                )
    except OSError:
        raise HistoricalOptionDataError(
            "historical option file unreadable"
        ) from None

    return HistoricalOptionDataset(rows)
