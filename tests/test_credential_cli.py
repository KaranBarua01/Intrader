from intrader.__main__ import main


class MemorySecrets:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def set(self, name: str, value: str) -> None:
        self.values[name] = value


def test_credential_cli_stores_secret_without_printing_it(monkeypatch, capsys) -> None:
    store = MemorySecrets()
    monkeypatch.setattr("intrader.__main__.CredentialStore", lambda: store)
    monkeypatch.setattr("getpass.getpass", lambda prompt: "dummy-value")

    exit_code = main(["credentials", "set", "api_key"])

    assert exit_code == 0
    assert store.values == {"api_key": "dummy-value"}
    output = capsys.readouterr().out
    assert "api_key: stored" in output
    assert "dummy-value" not in output


def test_credential_cli_rejects_session_token_names(monkeypatch, capsys) -> None:
    store = MemorySecrets()
    monkeypatch.setattr("intrader.__main__.CredentialStore", lambda: store)

    exit_code = main(["credentials", "set", "jwt_token"])

    assert exit_code == 2
    assert store.values == {}
    assert "jwt_token" not in capsys.readouterr().out


def test_credential_cli_rejects_one_character_api_key(monkeypatch, capsys) -> None:
    store = MemorySecrets()
    monkeypatch.setattr("intrader.__main__.CredentialStore", lambda: store)
    monkeypatch.setattr("getpass.getpass", lambda prompt: "x")

    assert main(["credentials", "set", "api_key"]) == 1
    assert store.values == {}
    assert "api_key: not stored" in capsys.readouterr().out


def test_credential_cli_rejects_invalid_totp_seed(monkeypatch, capsys) -> None:
    store = MemorySecrets()
    monkeypatch.setattr("intrader.__main__.CredentialStore", lambda: store)
    monkeypatch.setattr("getpass.getpass", lambda prompt: "x")

    assert main(["credentials", "set", "totp_secret"]) == 1
    assert store.values == {}
    assert "totp_secret: not stored" in capsys.readouterr().out
