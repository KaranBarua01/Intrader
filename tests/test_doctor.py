from intrader import doctor
from intrader.__main__ import main
from intrader.config import AppConfig


class MemorySecrets:
    def __init__(self, values: dict[str, str]) -> None:
        self.values = values

    def get(self, name: str) -> str | None:
        return self.values.get(name)

    def set(self, name: str, value: str) -> None:
        self.values[name] = value


def test_doctor_reports_ready_environment(tmp_path, monkeypatch) -> None:
    class FakeWindowsKeyring:
        pass

    FakeWindowsKeyring.__module__ = "keyring.backends.Windows"
    FakeWindowsKeyring.__name__ = "WinVaultKeyring"
    monkeypatch.setattr(doctor.keyring, "get_keyring", lambda: FakeWindowsKeyring())

    secrets = MemorySecrets(
        {
            "api_key": "dummy-api-key", "client_code": "dummy-client-code",
            "mpin": "0000", "totp_secret": "AAAAAAAAAAAAAAAA",
        }
    )

    report = doctor.run_doctor(AppConfig(), secrets, tmp_path / "data", tmp_path / "logs")

    assert report.ready
    assert all(check.ok for check in report.checks)
    assert "dummy-" not in report.format()


def test_doctor_rejects_one_character_stored_credentials(tmp_path) -> None:
    secrets = MemorySecrets(
        {
            "api_key": "x", "client_code": "dummy-client-code",
            "mpin": "0000", "totp_secret": "x",
        }
    )

    report = doctor.run_doctor(AppConfig(), secrets, tmp_path / "data", tmp_path / "logs")

    assert not report.ready
    assert "api_key: invalid" in report.format()
    assert "totp_secret: invalid" in report.format()


def test_doctor_reports_missing_secret_by_name_only(tmp_path) -> None:
    secrets = MemorySecrets({"api_key": "dummy-value"})

    report = doctor.run_doctor(AppConfig(), secrets, tmp_path / "data", tmp_path / "logs")

    assert not report.ready
    assert "totp_secret: missing" in report.format()
    assert "dummy-value" not in report.format()


def test_doctor_rejects_unsupported_python(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(doctor.sys, "version_info", (3, 13, 0))

    report = doctor.run_doctor(AppConfig(), MemorySecrets({}), tmp_path / "data", tmp_path / "logs")

    assert not report.ready
    assert "Python 3.11 required" in report.format()


def test_doctor_reports_unwritable_data_path(tmp_path) -> None:
    data_path = tmp_path / "blocked"
    data_path.write_text("a file, not a directory", encoding="utf-8")

    report = doctor.run_doctor(AppConfig(), MemorySecrets({}), data_path, tmp_path / "logs")

    assert not report.ready
    assert "data directory: unavailable" in report.format()


def test_doctor_cli_omits_credential_values(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        "intrader.__main__.CredentialStore",
        lambda: MemorySecrets({"api_key": "dummy-value"}),
        raising=False,
    )

    exit_code = main(["doctor"])

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "api_key: present" in output
    assert "dummy-value" not in output
