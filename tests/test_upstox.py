from datetime import date
from decimal import Decimal

import pytest

from intrader.upstox import (
    NIFTY_50_INSTRUMENT_KEY,
    UpstoxDataError,
    UpstoxExpiredClient,
    UpstoxNoDataError,
)


class FakeTransport:
    def __init__(self, payloads: list[object]) -> None:
        self.payloads = list(payloads)
        self.calls: list[dict[str, object]] = []

    def get_json(self, url, *, headers, params, timeout):
        self.calls.append(
            {
                "url": url,
                "headers": dict(headers),
                "params": dict(params or {}),
                "timeout": timeout,
            }
        )
        return self.payloads.pop(0)


class MemorySecrets:
    def __init__(self, token: str | None) -> None:
        self.token = token

    def get(self, name: str) -> str | None:
        if name == "upstox_analytics_token":
            return self.token
        return None

    def set(self, name: str, value: str) -> None:
        raise NotImplementedError


def test_expiries_use_bearer_auth_and_parse_dates() -> None:
    transport = FakeTransport(
        [{"status": "success", "data": ["2024-10-24", "2024-10-03"]}]
    )
    client = UpstoxExpiredClient("secret-token", transport)

    expiries = client.get_expiries()

    assert expiries == (date(2024, 10, 3), date(2024, 10, 24))
    call = transport.calls[0]
    assert call["params"] == {"instrument_key": NIFTY_50_INSTRUMENT_KEY}
    assert call["headers"]["Authorization"] == "Bearer secret-token"


def test_option_contracts_parse_ce_and_pe() -> None:
    transport = FakeTransport(
        [
            {
                "status": "success",
                "data": [
                    {
                        "trading_symbol": "NIFTY 24500 PE 24 OCT 24",
                        "strike_price": 24500.0,
                        "instrument_type": "PE",
                        "instrument_key": "NSE_FO|43727|24-10-2024",
                        "lot_size": 25,
                    },
                    {
                        "trading_symbol": "NIFTY 24500 CE 24 OCT 24",
                        "strike_price": 24500.0,
                        "instrument_type": "CE",
                        "instrument_key": "NSE_FO|43726|24-10-2024",
                        "lot_size": 25,
                    },
                ],
            }
        ]
    )
    client = UpstoxExpiredClient("secret-token", transport)

    contracts = client.get_option_contracts(date(2024, 10, 24))

    assert [item.option_type for item in contracts] == ["CE", "PE"]
    assert contracts[0].strike_price == Decimal("24500.0")
    assert contracts[0].lot_size == 25
    assert transport.calls[0]["params"]["expiry_date"] == "2024-10-24"


def test_historical_candles_are_returned_in_chronological_order() -> None:
    transport = FakeTransport(
        [
            {
                "status": "success",
                "data": {
                    "candles": [
                        [
                            "2024-10-23T09:16:00+05:30",
                            99.7,
                            106.0,
                            97.0,
                            100.7,
                            748300,
                            3024350,
                        ],
                        [
                            "2024-10-23T09:15:00+05:30",
                            99.65,
                            111.45,
                            81.0,
                            105.75,
                            1105775,
                            3024350,
                        ],
                    ]
                },
            }
        ]
    )
    client = UpstoxExpiredClient("secret-token", transport)

    candles = client.get_historical_candles(
        "NSE_FO|43726|24-10-2024",
        date(2024, 10, 23),
    )

    assert [item.at.strftime("%H:%M") for item in candles] == ["09:15", "09:16"]
    assert candles[0].open == Decimal("99.65")
    assert candles[0].close == Decimal("105.75")
    assert candles[0].volume == 1105775
    assert candles[0].open_interest == 3024350
    assert "%7C" in transport.calls[0]["url"]


def test_from_secret_store_reads_optional_upstox_token() -> None:
    transport = FakeTransport(
        [{"status": "success", "data": ["2024-10-24"]}]
    )
    client = UpstoxExpiredClient.from_secret_store(
        MemorySecrets("stored-token"),
        transport,
    )

    assert client.get_expiries() == (date(2024, 10, 24),)


def test_from_secret_store_requires_upstox_token() -> None:
    with pytest.raises(UpstoxDataError, match="token unavailable"):
        UpstoxExpiredClient.from_secret_store(MemorySecrets(None))


def test_empty_historical_candles_raise_no_data_error() -> None:
    transport = FakeTransport(
        [{"status": "success", "data": {"candles": []}}]
    )
    client = UpstoxExpiredClient("secret-token", transport)

    with pytest.raises(UpstoxNoDataError, match="No expired option candles"):
        client.get_historical_candles(
            "NSE_FO|58542|03-10-2024",
            date(2024, 9, 17),
        )
