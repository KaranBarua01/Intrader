"""Local readiness checks that never expose credential values."""

from dataclasses import dataclass
import importlib.util
from pathlib import Path
import sys
import tempfile

import keyring

from intrader.config import AppConfig
from intrader.credentials import credential_is_valid
from intrader.secrets import REQUIRED_SECRET_NAMES, SecretStore


_REQUIRED_MODULES = ("keyring", "pyotp", "requests", "SmartApi", "websocket")


@dataclass(frozen=True, slots=True)
class DoctorCheck:
    name: str
    ok: bool
    detail: str


@dataclass(frozen=True, slots=True)
class DoctorReport:
    checks: tuple[DoctorCheck, ...]

    @property
    def ready(self) -> bool:
        return all(check.ok for check in self.checks)

    def format(self) -> str:
        lines = [f"Intrader doctor: {'READY' if self.ready else 'NOT READY'}"]
        lines.extend(
            f"{'OK' if check.ok else 'FAIL'} {check.name}: {check.detail}"
            for check in self.checks
        )
        return "\n".join(lines)


def _writable_directory(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=path):
            pass
    except OSError:
        return False
    return True


def run_doctor(
    config: AppConfig, store: SecretStore, data_dir: Path, log_dir: Path
) -> DoctorReport:
    """Check local prerequisites without contacting SmartAPI."""

    checks: list[DoctorCheck] = []
    python_ok = tuple(sys.version_info[:2]) == (3, 11)
    checks.append(
        DoctorCheck("Python", python_ok, "Python 3.11 required")
    )

    for module in _REQUIRED_MODULES:
        present = importlib.util.find_spec(module) is not None
        checks.append(
            DoctorCheck(f"package {module}", present, "installed" if present else "missing")
        )

    try:
        backend = keyring.get_keyring()
        keyring_ok = (
            type(backend).__module__ == "keyring.backends.Windows"
            and type(backend).__name__ == "WinVaultKeyring"
        )
    except Exception:
        keyring_ok = False
    checks.append(
        DoctorCheck("Windows keyring", keyring_ok, "available" if keyring_ok else "unavailable")
    )

    config_ok = (
        config.underlying == "NIFTY"
        and config.warmup_minutes > 0
        and config.trading_duration_minutes > 0
        and config.option_strikes_each_side > 0
        and config.timezone == "Asia/Kolkata"
        and config.stale_tick_seconds > 0
        and config.stale_option_seconds > 0
    )
    checks.append(
        DoctorCheck("config", config_ok, "valid" if config_ok else "invalid")
    )

    for name, path in (("data directory", data_dir), ("log directory", log_dir)):
        writable = _writable_directory(path)
        checks.append(
            DoctorCheck(name, writable, "writable" if writable else "unavailable")
        )

    for name in REQUIRED_SECRET_NAMES:
        try:
            value = store.get(name)
        except Exception:
            value = None
        present = bool(value)
        valid = credential_is_valid(name, value)
        checks.append(
            DoctorCheck(name, valid, "present" if valid else "invalid" if present else "missing")
        )

    return DoctorReport(tuple(checks))
