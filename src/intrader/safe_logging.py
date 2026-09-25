"""Application logging that removes known broker credentials and tokens."""

from collections.abc import Mapping
import logging
from pathlib import Path
import re

from intrader.secrets import REQUIRED_SECRET_NAMES, SecretStore


_SENSITIVE_NAMES = frozenset(
    (*REQUIRED_SECRET_NAMES, "jwt_token", "refresh_token", "feed_token", "totp_code")
)
_KEY_VALUE = re.compile(
    r"(?i)(\b(?:api_key|client_code|mpin|totp_secret|totp_code|"
    r"jwt_token|refresh_token|feed_token)\b['\"]?\s*[:=]\s*['\"]?)"
    r"([^'\"\s,}\]]+)"
)


class _RedactSecrets(logging.Filter):
    def __init__(self, values: set[str]) -> None:
        super().__init__()
        self._values = tuple(sorted((value for value in values if value), key=len, reverse=True))

    def _redact(self, value: object) -> object:
        if isinstance(value, Mapping):
            return {
                key: "[REDACTED]" if str(key).lower() in _SENSITIVE_NAMES else self._redact(item)
                for key, item in value.items()
            }
        if isinstance(value, tuple):
            return tuple(self._redact(item) for item in value)
        if isinstance(value, list):
            return [self._redact(item) for item in value]
        if isinstance(value, str):
            for secret in self._values:
                value = value.replace(secret, "[REDACTED]")
            return _KEY_VALUE.sub(r"\1[REDACTED]", value)
        return value

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = self._redact(record.msg)
        record.args = self._redact(record.args)
        rendered = record.getMessage()
        record.msg = self._redact(rendered)
        record.args = ()
        record.exc_info = None
        record.exc_text = None
        record.stack_info = None
        return True


def configure_logging(
    log_path: Path, *, secret_store: SecretStore | None = None
) -> logging.Logger:
    """Configure the application file logger with broker-secret redaction."""

    values: set[str] = set()
    if secret_store is not None:
        for name in REQUIRED_SECRET_NAMES:
            try:
                value = secret_store.get(name)
            except Exception:
                continue
            if value:
                values.add(value)

    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("intrader")
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        handler.close()
    for filter_ in logger.filters[:]:
        logger.removeFilter(filter_)

    redactor = _RedactSecrets(values)
    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    handler.addFilter(redactor)
    logger.addFilter(redactor)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger
