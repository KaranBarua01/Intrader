"""Official NIFTY 50 membership and Angel One equity-token resolution."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from io import StringIO
from typing import Protocol, Sequence

import requests

from intrader.instruments import (
    Instrument,
    InstrumentError,
    MasterTransport,
    fetch_full_instrument_master,
    resolve_nse_equities,
)


NIFTY50_CONSTITUENTS_URL = (
    "https://www.niftyindices.com/IndexConstituent/ind_nifty50list.csv"
)


class BreadthProviderError(Exception):
    """NIFTY 50 membership or token resolution is unavailable."""


class TextTransport(Protocol):
    def get_text(self, url: str, timeout: int) -> str:
        ...


class RequestsTextTransport:
    """Small public-text boundary for the official NIFTY constituent CSV."""

    def get_text(self, url: str, timeout: int) -> str:
        try:
            response = requests.get(
                url,
                timeout=timeout,
                headers={"User-Agent": "Intrader/0.1"},
            )
            response.raise_for_status()
            return response.text
        except requests.RequestException:
            raise BreadthProviderError(
                "NIFTY constituent list unavailable"
            ) from None


@dataclass(frozen=True, slots=True)
class NiftyConstituent:
    company_name: str
    industry: str
    symbol: str


@dataclass(frozen=True, slots=True)
class ResolvedBreadthMember:
    company_name: str
    industry: str
    symbol: str
    instrument: Instrument


def parse_nifty50_constituents(csv_text: str) -> tuple[NiftyConstituent, ...]:
    """Parse the official public constituent CSV with strict symbol uniqueness."""

    if not isinstance(csv_text, str) or not csv_text.strip():
        raise BreadthProviderError("NIFTY constituent list invalid")
    reader = csv.DictReader(StringIO(csv_text.lstrip("\ufeff")))
    required = {"Company Name", "Industry", "Symbol"}
    if reader.fieldnames is None or not required.issubset(set(reader.fieldnames)):
        raise BreadthProviderError("NIFTY constituent columns invalid")

    constituents: list[NiftyConstituent] = []
    seen: set[str] = set()
    for row in reader:
        company = (row.get("Company Name") or "").strip()
        industry = (row.get("Industry") or "").strip()
        symbol = (row.get("Symbol") or "").strip().upper()
        if not company or not industry or not symbol or symbol in seen:
            raise BreadthProviderError("NIFTY constituent row invalid")
        seen.add(symbol)
        constituents.append(NiftyConstituent(company, industry, symbol))

    if len(constituents) != 50:
        raise BreadthProviderError("NIFTY 50 constituent count invalid")
    return tuple(constituents)


def fetch_nifty50_constituents(
    transport: TextTransport,
) -> tuple[NiftyConstituent, ...]:
    try:
        text = transport.get_text(NIFTY50_CONSTITUENTS_URL, timeout=20)
    except BreadthProviderError:
        raise
    except Exception:
        raise BreadthProviderError(
            "NIFTY constituent list unavailable"
        ) from None
    return parse_nifty50_constituents(text)


def resolve_breadth_universe(
    text_transport: TextTransport,
    master_transport: MasterTransport,
) -> tuple[ResolvedBreadthMember, ...]:
    """Resolve all current NIFTY 50 public constituents to exact NSE -EQ tokens."""

    constituents = fetch_nifty50_constituents(text_transport)
    try:
        master = fetch_full_instrument_master(master_transport)
        equities = resolve_nse_equities(
            master,
            [member.symbol for member in constituents],
        )
    except InstrumentError:
        raise BreadthProviderError("NIFTY equity tokens unavailable") from None

    return tuple(
        ResolvedBreadthMember(
            company_name=member.company_name,
            industry=member.industry,
            symbol=member.symbol,
            instrument=equities[member.symbol],
        )
        for member in constituents
    )
