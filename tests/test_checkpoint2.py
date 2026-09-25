from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from intrader.checkpoint2 import MarketAccessError, check_market_access
from intrader.__main__ import main


class MemorySecrets:
    def get(self, name: str) -> str | None:
        return {
            "api_key": "dummy-api-key",
            "client_code": "dummy-client-code",
            "mpin": "0000",
            "totp_secret": "AAAAAAAAAAAAAAAA",
        }.get(name)

    def set(self, name: str, value: str) -> None:
        raise NotImplementedError


def _row(token: str, symbol: str, name: str, kind: str, exchange: str, expiry: str = "", strike: str = "0") -> dict:
    return {
        "token": token, "symbol": symbol, "name": name,
        "instrumenttype": kind, "exch_seg": exchange,
        "expiry": expiry, "strike": strike, "lotsize": "65",
    }


def _master() -> list[dict]:
    rows = [
        _row("99926000", "Nifty 50", "NIFTY", "AMXIDX", "NSE"),
        _row("99926017", "India VIX", "INDIA VIX", "AMXIDX", "NSE"),
        _row("future", "NIFTY29SEP26FUT", "NIFTY", "FUTIDX", "NFO", "29SEP2026"),
    ]
    for strike in range(22950, 23400, 50):
        for side in ("CE", "PE"):
            rows.append(
                _row(f"{strike}-{side}", f"NIFTY29SEP26{strike}{side}", "NIFTY",
                     "OPTIDX", "NFO", "29SEP2026", str(strike * 100))
            )
    return rows


class FakeTransport:
    def __init__(self, quote: dict) -> None:
        self.quote = quote
        self.urls: list[str] = []

    def public_ip(self) -> str:
        return "203.0.113.7"

    def get_json(self, url: str, timeout: int) -> object:
        self.urls.append(url)
        return _master()

    def post_json(self, url: str, headers: dict, body: dict, timeout: int) -> dict:
        self.urls.append(url)
        if url.endswith("loginByPassword"):
            return {
                "status": True,
                "data": {"jwtToken": "dummy-jwt", "refreshToken": "dummy-refresh", "feedToken": "dummy-feed"},
            }
        assert headers["Authorization"] == "Bearer dummy-jwt"
        assert body == {"mode": "LTP", "exchangeTokens": {"NSE": ["99926000"]}}
        return self.quote


def _quote(ltp: object = 23126.5) -> dict:
    return {
        "status": True,
        "data": {"fetched": [{"exchange": "NSE", "symbolToken": "99926000", "ltp": ltp}], "unfetched": []},
    }


def test_market_access_uses_only_login_master_and_quote_endpoints() -> None:
    transport = FakeTransport(_quote())

    report = check_market_access(
        MemorySecrets(), transport,
        as_of=date(2026, 9, 26), now=datetime(2026, 9, 26, 6, 30, tzinfo=timezone.utc),
    )

    assert report.spot_ltp == Decimal("23126.5")
    assert report.instruments.future.token == "future"
    assert report.instruments.atm_strike == Decimal("23150")
    assert len(report.instruments.calls) == 9
    assert [url.rsplit("/", 1)[-1] for url in transport.urls] == [
        "OpenAPIScripMaster.json", "loginByPassword", "quote"
    ]
    assert "dummy-" not in repr(report)


@pytest.mark.parametrize("quote", [_quote(None), {"status": False, "message": "dummy-jwt"}, {"status": True, "data": {"fetched": []}}])
def test_missing_or_invalid_quote_fails_closed(quote: dict) -> None:
    with pytest.raises(MarketAccessError) as error:
        check_market_access(MemorySecrets(), FakeTransport(quote), as_of=date(2026, 9, 26))

    assert "dummy-" not in str(error.value)


def test_cli_market_access_reports_only_public_instrument_details(monkeypatch, capsys) -> None:
    monkeypatch.setattr("intrader.__main__.CredentialStore", MemorySecrets)
    monkeypatch.setattr("intrader.__main__.RequestsTransport", lambda: FakeTransport(_quote()), raising=False)
    monkeypatch.setattr(
        "intrader.__main__.check_market_access",
        lambda store, transport: check_market_access(
            store, transport, as_of=date(2026, 9, 26),
            now=datetime(2026, 9, 26, 6, 30, tzinfo=timezone.utc),
        ),
    )

    exit_code = main(["check-market-access"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "MARKET ACCESS OK" in output
    assert "NIFTY spot token: 99926000" in output
    assert "dummy-" not in output
