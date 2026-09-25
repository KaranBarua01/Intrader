"""Secure credential storage for Intrader."""

from typing import Protocol

import keyring

from intrader.secrets import SecretStore


SERVICE_NAME = "Intrader"

SUPPORTED_CREDENTIALS = frozenset(
    {
        "api_key",
        "client_code",
        "mpin",
        "totp_secret",
    }
)


def credential_is_valid(name: str, value: str | None) -> bool:
    """Check basic stored-value shape without revealing the value."""

    if name not in SUPPORTED_CREDENTIALS or not isinstance(value, str):
        return False
    if name == "totp_secret":
        if len(value.strip()) < 16:
            return False
        try:
            import pyotp

            pyotp.TOTP(value).now()
        except Exception:
            return False
        return True
    return len(value.strip()) >= 4


class KeyringBackend(Protocol):
    def set_password(self, service: str, username: str, password: str) -> None:
        ...

    def get_password(self, service: str, username: str) -> str | None:
        ...

    def delete_password(self, service: str, username: str) -> None:
        ...


class CredentialStore(SecretStore):
    """Store Intrader credentials using the operating-system keyring."""

    def __init__(self, backend: KeyringBackend | None = None) -> None:
        self._backend = backend if backend is not None else keyring

    @staticmethod
    def _validate_name(name: str) -> None:
        if name not in SUPPORTED_CREDENTIALS:
            raise ValueError(f"Unsupported credential: {name}")

    def set(self, name: str, value: str) -> None:
        self._validate_name(name)
        self._backend.set_password(SERVICE_NAME, name, value)

    def get(self, name: str) -> str | None:
        self._validate_name(name)
        return self._backend.get_password(SERVICE_NAME, name)

    def delete(self, name: str) -> None:
        self._validate_name(name)
        self._backend.delete_password(SERVICE_NAME, name)
