"""Read-only Upstox expired-instrument market-data provider."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Protocol
from urllib.parse import quote

import requests

from intrader.secrets import SecretStore


UPSTOX_API_BASE = "https://api.upstox.com/v2"
NIFTY_50_INSTRUMENT_KEY = "NSE_INDEX|Nifty 50"


class UpstoxDataError(Exception):
    """Upstox expired-instrument data is unavailable or invalid."""


class UpstoxJsonTransport(Protocol):
    def get_json(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        params: Mapping[str, str] | None,
        timeout: int,
    ) -> object:
        ...


class RequestsUpstoxTransport:
    """Requests boundary that never exposes bearer-token values in errors."""

    def get_json(
        self,
        url: str,
        *,
        headers: Mapping[str, str],
        params: Mapping[str, str] | None,
        timeout: int,
    ) -> object:
        try:
            response = requests.get(
                url,
                headers=dict(headers),
                params=dict(params or {}),
                timeout=timeout,
            )
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError):
            raise UpstoxDataError("Upstox data unavailable") from None


@dataclass(frozen=True, slots=True)
class ExpiredOptionContract:
    trading_symbol: str
    strike_price: Decimal
    option_type: str
    instrument_key: str
    lot_size: int
    expiry: date


@dataclass(frozen=True, slots=True)
class ExpiredOptionCandle:
    at: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    open_interest: int


class UpstoxExpiredClient:
    """Read-only client for Upstox expired NIFTY option history."""

    def __init__(
        self,
        token: str,
        transport: UpstoxJsonTransport | None = None,
        *,
        timeout: int = 20,
    ) -> None:
        clean_token = token.strip() if isinstance(token, str) else ""
        if len(clean_token) < 4:
            raise UpstoxDataError("Upstox analytics token unavailable")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self._token = clean_token
        self._transport = transport or RequestsUpstoxTransport()
        self._timeout = timeout

    @classmethod
    def from_secret_store(
        cls,
        store: SecretStore,
        transport: UpstoxJsonTransport | None = None,
        *,
        timeout: int = 20,
    ) -> "UpstoxExpiredClient":
        try:
            token = store.get("upstox_analytics_token")
        except Exception:
            token = None
        if not token:
            raise UpstoxDataError("Upstox analytics token unavailable")
        return cls(token, transport, timeout=timeout)

    def _get(
        self,
        path: str,
        *,
        params: Mapping[str, str] | None = None,
    ) -> object:
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/json",
        }
        try:
            payload = self._transport.get_json(
                f"{UPSTOX_API_BASE}{path}",
                headers=headers,
                params=params,
                timeout=self._timeout,
            )
        except UpstoxDataError:
            raise
        except Exception:
            raise UpstoxDataError("Upstox data unavailable") from None

        if not isinstance(payload, dict) or payload.get("status") != "success":
            raise UpstoxDataError("Upstox response invalid")
        if "data" not in payload:
            raise UpstoxDataError("Upstox response invalid")
        return payload["data"]

    def get_expiries(
        self,
        instrument_key: str = NIFTY_50_INSTRUMENT_KEY,
    ) -> tuple[date, ...]:
        data = self._get(
            "/expired-instruments/expiries",
            params={"instrument_key": instrument_key},
        )
        if not isinstance(data, list):
            raise UpstoxDataError("Upstox expiry response invalid")
        try:
            expiries = tuple(date.fromisoformat(str(item)) for item in data)
        except ValueError:
            raise UpstoxDataError("Upstox expiry response invalid") from None
        return tuple(sorted(set(expiries)))

    def get_option_contracts(
        self,
        expiry: date,
        instrument_key: str = NIFTY_50_INSTRUMENT_KEY,
    ) -> tuple[ExpiredOptionContract, ...]:
        data = self._get(
            "/expired-instruments/option/contract",
            params={
                "instrument_key": instrument_key,
                "expiry_date": expiry.isoformat(),
            },
        )
        if not isinstance(data, list):
            raise UpstoxDataError("Upstox option-contract response invalid")

        contracts: list[ExpiredOptionContract] = []
        try:
            for item in data:
                if not isinstance(item, dict):
                    raise UpstoxDataError("Upstox option-contract response invalid")
                option_type = str(item.get("instrument_type") or "").upper()
                if option_type not in {"CE", "PE"}:
                    continue
                trading_symbol = str(item.get("trading_symbol") or "").strip()
                instrument = str(item.get("instrument_key") or "").strip()
                if not trading_symbol or not instrument:
                    raise UpstoxDataError("Upstox option-contract response invalid")
                contracts.append(
                    ExpiredOptionContract(
                        trading_symbol=trading_symbol,
                        strike_price=Decimal(str(item["strike_price"])),
                        option_type=option_type,
                        instrument_key=instrument,
                        lot_size=int(item["lot_size"]),
                        expiry=expiry,
                    )
                )
        except (KeyError, TypeError, ValueError, InvalidOperation):
            raise UpstoxDataError("Upstox option-contract response invalid") from None

        if not contracts:
            raise UpstoxDataError("No expired option contracts returned")
        return tuple(
            sorted(
                contracts,
                key=lambda item: (item.strike_price, item.option_type),
            )
        )

    def get_historical_candles(
        self,
        instrument_key: str,
        from_date: date,
        to_date: date | None = None,
    ) -> tuple[ExpiredOptionCandle, ...]:
        end = to_date or from_date
        if from_date > end:
            raise ValueError("from_date must be on or before to_date")
        encoded_key = quote(instrument_key, safe="")
        data = self._get(
            f"/expired-instruments/historical-candle/{encoded_key}/1minute/"
            f"{end.isoformat()}/{from_date.isoformat()}"
        )
        if not isinstance(data, dict) or not isinstance(data.get("candles"), list):
            raise UpstoxDataError("Upstox candle response invalid")

        candles: list[ExpiredOptionCandle] = []
        try:
            for row in data["candles"]:
                if not isinstance(row, (list, tuple)) or len(row) < 7:
                    raise UpstoxDataError("Upstox candle response invalid")
                at = datetime.fromisoformat(str(row[0]).replace("Z", "+00:00"))
                if at.tzinfo is None:
                    raise UpstoxDataError("Upstox candle timestamp invalid")
                candles.append(
                    ExpiredOptionCandle(
                        at=at,
                        open=Decimal(str(row[1])),
                        high=Decimal(str(row[2])),
                        low=Decimal(str(row[3])),
                        close=Decimal(str(row[4])),
                        volume=int(row[5]),
                        open_interest=int(row[6]),
                    )
                )
        except (TypeError, ValueError, InvalidOperation):
            raise UpstoxDataError("Upstox candle response invalid") from None

        if not candles:
            raise UpstoxDataError("No expired option candles returned")
        return tuple(sorted(candles, key=lambda candle: candle.at))
