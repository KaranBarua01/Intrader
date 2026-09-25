"""Read-only SmartAPI login with no credential or token logging."""

from dataclasses import dataclass
from datetime import datetime, timezone
import ipaddress
import socket
from typing import Protocol
import uuid

import pyotp
import requests

from intrader.secrets import REQUIRED_SECRET_NAMES, SecretStore


LOGIN_URL = "https://apiconnect.angelone.in/rest/auth/angelbroking/user/v1/loginByPassword"
PUBLIC_IP_URL = "https://api.ipify.org"


class SmartAPIError(Exception):
    """A sanitized SmartAPI failure safe to display or log."""


class HTTPTransport(Protocol):
    def public_ip(self) -> str:
        ...

    def post_json(self, url: str, headers: dict, body: dict, timeout: int) -> dict:
        ...

    def get_json(self, url: str, timeout: int) -> object:
        ...


class RequestsTransport:
    """Small HTTP boundary that never logs requests or response bodies."""

    def public_ip(self) -> str:
        try:
            response = requests.get(PUBLIC_IP_URL, timeout=5)
            response.raise_for_status()
            address = response.text.strip()
            ipaddress.IPv4Address(address)
            return address
        except (requests.RequestException, ValueError, ipaddress.AddressValueError):
            raise SmartAPIError("Public IP lookup unavailable") from None

    def post_json(self, url: str, headers: dict, body: dict, timeout: int) -> dict:
        try:
            response = requests.post(url, headers=headers, json=body, timeout=timeout)
            response.raise_for_status()
            value = response.json()
        except (requests.RequestException, ValueError):
            raise SmartAPIError("SmartAPI network request failed") from None
        if not isinstance(value, dict):
            raise SmartAPIError("SmartAPI response invalid")
        return value

    def get_json(self, url: str, timeout: int) -> object:
        try:
            response = requests.get(url, timeout=timeout)
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError):
            raise SmartAPIError("SmartAPI network request failed") from None


@dataclass(frozen=True, slots=True, repr=False)
class SmartSession:
    api_key: str
    client_code: str
    jwt_token: str
    refresh_token: str
    feed_token: str

    def __repr__(self) -> str:
        return "SmartSession([REDACTED])"


def _local_ip() -> str:
    try:
        return socket.gethostbyname(socket.gethostname())
    except OSError:
        return "127.0.0.1"


def request_headers(api_key: str, public_ip: str, jwt_token: str | None = None) -> dict[str, str]:
    """Build SmartAPI headers without logging their sensitive fields."""

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "X-UserType": "USER",
        "X-SourceID": "WEB",
        "X-ClientLocalIP": _local_ip(),
        "X-ClientPublicIP": public_ip,
        "X-MACAddress": ":".join(f"{uuid.getnode():012x}"[i : i + 2] for i in range(0, 12, 2)),
        "X-PrivateKey": api_key,
    }
    if jwt_token:
        headers["Authorization"] = f"Bearer {jwt_token}"
    return headers


def authenticate(
    store: SecretStore, transport: HTTPTransport, *, now: datetime | None = None
) -> SmartSession:
    """Create an in-memory session using the documented login endpoint only."""

    credentials: dict[str, str] = {}
    for name in REQUIRED_SECRET_NAMES:
        try:
            value = store.get(name)
        except Exception:
            raise SmartAPIError("SmartAPI credential unavailable") from None
        if not value:
            raise SmartAPIError("Missing SmartAPI credential")
        credentials[name] = value

    try:
        totp = pyotp.TOTP(credentials["totp_secret"]).at(
            now or datetime.now(timezone.utc)
        )
    except Exception:
        raise SmartAPIError("TOTP configuration invalid") from None

    try:
        address = transport.public_ip()
        ipaddress.IPv4Address(address)
    except Exception:
        raise SmartAPIError("Public IP lookup unavailable") from None

    headers = request_headers(credentials["api_key"], address)
    body = {
        "clientcode": credentials["client_code"],
        "password": credentials["mpin"],
        "totp": totp,
    }
    try:
        response = transport.post_json(LOGIN_URL, headers, body, timeout=10)
    except Exception:
        raise SmartAPIError("SmartAPI login unavailable") from None

    if not isinstance(response, dict) or response.get("status") is not True:
        raise SmartAPIError("SmartAPI login rejected")
    data = response.get("data")
    if not isinstance(data, dict):
        raise SmartAPIError("SmartAPI login response incomplete")
    tokens = (data.get("jwtToken"), data.get("refreshToken"), data.get("feedToken"))
    if not all(isinstance(token, str) and token for token in tokens):
        raise SmartAPIError("SmartAPI login response incomplete")
    return SmartSession(
        api_key=credentials["api_key"],
        client_code=credentials["client_code"],
        jwt_token=tokens[0],
        refresh_token=tokens[1],
        feed_token=tokens[2],
    )
