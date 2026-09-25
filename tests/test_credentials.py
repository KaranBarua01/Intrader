import pytest

from intrader.credentials import CredentialStore
from intrader.secrets import SecretStore


class MemoryKeyring:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}

    def set_password(self, service: str, username: str, password: str) -> None:
        self.values[(service, username)] = password

    def get_password(self, service: str, username: str) -> str | None:
        return self.values.get((service, username))

    def delete_password(self, service: str, username: str) -> None:
        self.values.pop((service, username), None)


def test_store_round_trip() -> None:
    backend = MemoryKeyring()
    store = CredentialStore(backend=backend)

    store.set("api_key", "dummy-value-0000")

    assert store.get("api_key") == "dummy-value-0000"
    assert backend.values[("Intrader", "api_key")] == "dummy-value-0000"


def test_credential_store_implements_secret_store_contract() -> None:
    backend = MemoryKeyring()
    store: SecretStore = CredentialStore(backend=backend)

    assert isinstance(store, SecretStore)
    store.set("api_key", "dummy-value-0000")
    assert store.get("api_key") == "dummy-value-0000"


def test_store_rejects_unknown_credential_names() -> None:
    store = CredentialStore(backend=MemoryKeyring())

    with pytest.raises(ValueError, match="Unsupported credential"):
        store.set("random_secret", "value")


def test_delete_removes_stored_credential() -> None:
    store = CredentialStore(backend=MemoryKeyring())
    store.set("client_code", "ABC123")

    store.delete("client_code")

    assert store.get("client_code") is None
