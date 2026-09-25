from datetime import datetime, timezone

import pyotp
import pytest

from intrader.auth import SmartAPIError, authenticate


class MemorySecrets:
    def __init__(self, values: dict[str, str]) -> None:
        self.values = values

    def get(self, name: str) -> str | None:
        return self.values.get(name)

    def set(self, name: str, value: str) -> None:
        self.values[name] = value


class FakeTransport:
    def __init__(self, response: dict | None = None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.calls: list[tuple[str, dict, dict, int]] = []
        self.ip_calls = 0

    def public_ip(self) -> str:
        self.ip_calls += 1
        return "203.0.113.7"

    def post_json(self, url: str, headers: dict, body: dict, timeout: int) -> dict:
        self.calls.append((url, headers, body, timeout))
        if self.error is not None:
            raise self.error
        return self.response or {}


def _stored_credentials() -> MemorySecrets:
    return MemorySecrets(
        {
            "api_key": "dummy-api-key",
            "client_code": "dummy-client-code",
            "mpin": "0000",
            "totp_secret": "AAAAAAAAAAAAAAAA",
        }
    )


def _success_response() -> dict:
    return {
        "status": True,
        "data": {
            "jwtToken": "dummy-jwt",
            "refreshToken": "dummy-refresh",
            "feedToken": "dummy-feed",
        },
    }


def test_authentication_uses_only_login_endpoint_and_keeps_tokens_in_memory() -> None:
    transport = FakeTransport(_success_response())
    instant = datetime(2026, 9, 26, 6, 30, tzinfo=timezone.utc)

    session = authenticate(_stored_credentials(), transport, now=instant)

    assert len(transport.calls) == 1
    url, headers, body, timeout = transport.calls[0]
    assert url == "https://apiconnect.angelone.in/rest/auth/angelbroking/user/v1/loginByPassword"
    assert headers["X-PrivateKey"] == "dummy-api-key"
    assert headers["X-ClientPublicIP"] == "203.0.113.7"
    assert body == {
        "clientcode": "dummy-client-code",
        "password": "0000",
        "totp": pyotp.TOTP("AAAAAAAAAAAAAAAA").at(instant),
    }
    assert timeout == 10
    assert session.jwt_token == "dummy-jwt"
    assert session.refresh_token == "dummy-refresh"
    assert session.feed_token == "dummy-feed"
    assert "dummy-" not in repr(session)


def test_missing_credential_does_not_make_network_request() -> None:
    transport = FakeTransport(_success_response())
    credentials = _stored_credentials()
    del credentials.values["mpin"]

    with pytest.raises(SmartAPIError, match="Missing SmartAPI credential"):
        authenticate(credentials, transport)

    assert transport.calls == []
    assert transport.ip_calls == 0


def test_invalid_totp_seed_does_not_make_network_request() -> None:
    transport = FakeTransport(_success_response())
    credentials = _stored_credentials()
    credentials.values["totp_secret"] = "invalid!"

    with pytest.raises(SmartAPIError, match="TOTP configuration invalid"):
        authenticate(credentials, transport)

    assert transport.calls == []
    assert transport.ip_calls == 0


@pytest.mark.parametrize(
    "response",
    [
        {"status": False, "message": "dummy-mpin rejected"},
        {"status": True, "data": {"jwtToken": "dummy-jwt"}},
        {"status": True, "data": None},
    ],
)
def test_failed_or_incomplete_login_fails_closed_without_echoing_response(response: dict) -> None:
    transport = FakeTransport(response)

    with pytest.raises(SmartAPIError) as error:
        authenticate(_stored_credentials(), transport)

    assert "dummy-" not in str(error.value)


def test_transport_error_is_sanitized() -> None:
    transport = FakeTransport(error=RuntimeError("dummy-api-key in transport error"))

    with pytest.raises(SmartAPIError, match="SmartAPI login unavailable") as error:
        authenticate(_stored_credentials(), transport)

    assert "dummy-api-key" not in str(error.value)
