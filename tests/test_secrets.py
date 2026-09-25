from intrader.secrets import REQUIRED_SECRET_NAMES, SecretStore


class FakeSecretStore(SecretStore):
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def set(self, name: str, value: str) -> None:
        self.values[name] = value

    def get(self, name: str) -> str | None:
        return self.values.get(name)


def test_required_secret_names_are_fixed() -> None:
    assert REQUIRED_SECRET_NAMES == (
        "api_key",
        "client_code",
        "mpin",
        "totp_secret",
    )


def test_secret_store_never_requires_session_token_persistence() -> None:
    assert "jwt_token" not in REQUIRED_SECRET_NAMES
    assert "feed_token" not in REQUIRED_SECRET_NAMES
    assert "refresh_token" not in REQUIRED_SECRET_NAMES
