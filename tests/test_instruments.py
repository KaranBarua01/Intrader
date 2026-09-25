from datetime import date
from decimal import Decimal

import pytest

from intrader.instruments import (
    InstrumentError,
    fetch_instrument_master,
    resolve_nifty_instruments,
)


def _row(
    token: str,
    symbol: str,
    name: str,
    kind: str,
    exchange: str,
    expiry: str = "",
    strike: str = "-1.000000",
) -> dict:
    return {
        "token": token,
        "symbol": symbol,
        "name": name,
        "expiry": expiry,
        "strike": strike,
        "lotsize": "65" if exchange == "NFO" else "1",
        "instrumenttype": kind,
        "exch_seg": exchange,
    }


def _master_rows() -> list[dict]:
    rows = [
        _row("99926000", "Nifty 50", "NIFTY", "AMXIDX", "NSE", strike="0.000000"),
        _row("99926017", "India VIX", "INDIA VIX", "AMXIDX", "NSE", strike="0.000000"),
        _row("future-old", "NIFTY24SEP26FUT", "NIFTY", "FUTIDX", "NFO", "24SEP2026"),
        _row("future-near", "NIFTY29SEP26FUT", "NIFTY", "FUTIDX", "NFO", "29SEP2026"),
        _row("future-far", "NIFTY27OCT26FUT", "NIFTY", "FUTIDX", "NFO", "27OCT2026"),
    ]
    for strike in range(22950, 23400, 50):
        for side in ("CE", "PE"):
            rows.append(
                _row(
                    f"{strike}-{side}",
                    f"NIFTY29SEP26{strike}{side}",
                    "NIFTY",
                    "OPTIDX",
                    "NFO",
                    "29SEP2026",
                    f"{strike * 100}.000000",
                )
            )
    return rows


class FakeTransport:
    def __init__(self, rows: object) -> None:
        self.rows = rows
        self.requests: list[tuple[str, int]] = []

    def get_json(self, url: str, timeout: int) -> object:
        self.requests.append((url, timeout))
        return self.rows


def test_resolves_spot_vix_nearest_future_and_atm_option_window() -> None:
    transport = FakeTransport(_master_rows())
    master = fetch_instrument_master(transport)

    bundle = resolve_nifty_instruments(master, date(2026, 9, 26), Decimal("23126"))

    assert transport.requests == [
        ("https://margincalculator.angelone.in/OpenAPI_File/files/OpenAPIScripMaster.json", 30)
    ]
    assert bundle.spot.token == "99926000"
    assert bundle.vix.token == "99926017"
    assert bundle.future.token == "future-near"
    assert bundle.option_expiry == date(2026, 9, 29)
    assert bundle.atm_strike == Decimal("23150")
    assert bundle.strikes == tuple(Decimal(str(value)) for value in range(22950, 23400, 50))
    assert tuple(option.token for option in bundle.calls) == tuple(
        f"{strike}-CE" for strike in range(22950, 23400, 50)
    )
    assert tuple(option.token for option in bundle.puts) == tuple(
        f"{strike}-PE" for strike in range(22950, 23400, 50)
    )


def test_missing_option_pair_fails_closed() -> None:
    rows = [row for row in _master_rows() if row["token"] != "23150-PE"]
    master = fetch_instrument_master(FakeTransport(rows))

    with pytest.raises(InstrumentError, match="option pair incomplete"):
        resolve_nifty_instruments(master, date(2026, 9, 26), Decimal("23126"))


def test_expired_contracts_do_not_resolve() -> None:
    rows = [row for row in _master_rows() if row["expiry"] not in {"29SEP2026", "27OCT2026"}]
    master = fetch_instrument_master(FakeTransport(rows))

    with pytest.raises(InstrumentError, match="current NIFTY future missing"):
        resolve_nifty_instruments(master, date(2026, 9, 26), Decimal("23126"))


def test_malformed_expiry_is_rejected() -> None:
    rows = _master_rows()
    rows[3]["expiry"] = "wrong"

    with pytest.raises(InstrumentError, match="instrument master invalid"):
        fetch_instrument_master(FakeTransport(rows))


def test_duplicate_nifty_spot_is_rejected() -> None:
    rows = _master_rows()
    rows.append(rows[0].copy())
    master = fetch_instrument_master(FakeTransport(rows))

    with pytest.raises(InstrumentError, match="NIFTY spot ambiguous"):
        resolve_nifty_instruments(master, date(2026, 9, 26), Decimal("23126"))


def test_non_list_master_is_rejected() -> None:
    with pytest.raises(InstrumentError, match="instrument master invalid"):
        fetch_instrument_master(FakeTransport({"status": "unexpected"}))
