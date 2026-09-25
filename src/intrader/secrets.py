"""Secret storage contracts for Intrader."""

from abc import ABC, abstractmethod


REQUIRED_SECRET_NAMES = (
    "api_key",
    "client_code",
    "mpin",
    "totp_secret",
)


class SecretStore(ABC):
    """Abstract interface for retrieving Intrader's long-lived secrets."""

    @abstractmethod
    def set(self, name: str, value: str) -> None:
        """Store a long-lived secret."""
        raise NotImplementedError

    @abstractmethod
    def get(self, name: str) -> str | None:
        """Return a stored secret, or None when it does not exist."""
        raise NotImplementedError
