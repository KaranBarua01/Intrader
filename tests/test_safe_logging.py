import logging

from intrader.safe_logging import configure_logging


class MemorySecrets:
    def get(self, name: str) -> str | None:
        return {"api_key": "alpha-dummy", "mpin": "beta-dummy"}.get(name)

    def set(self, name: str, value: str) -> None:
        raise NotImplementedError


def test_logging_redacts_nested_credentials_and_exception_text(tmp_path) -> None:
    log_path = tmp_path / "logs" / "intrader.log"
    logger = configure_logging(log_path, secret_store=MemorySecrets())

    logger.info("credentials=%s", {"api_key": "alpha-dummy", "nested": {"mpin": "beta-dummy"}})
    try:
        raise ValueError("alpha-dummy leaked in exception")
    except ValueError:
        logger.exception("login failed with beta-dummy")

    content = log_path.read_text(encoding="utf-8")
    assert "alpha-dummy" not in content
    assert "beta-dummy" not in content
    assert "[REDACTED]" in content
    assert "login failed" in content


def test_logging_redacts_session_tokens_without_store(tmp_path) -> None:
    log_path = tmp_path / "intrader.log"
    logger = configure_logging(log_path)

    logger.info("session=%s", {"jwt_token": "temporary-dummy"})
    logger.info("feed_token=another-dummy")

    content = log_path.read_text(encoding="utf-8")
    assert "temporary-dummy" not in content
    assert "another-dummy" not in content
    assert content.count("[REDACTED]") == 2


def test_reconfiguration_does_not_duplicate_messages(tmp_path) -> None:
    log_path = tmp_path / "intrader.log"
    configure_logging(log_path)
    logger = configure_logging(log_path)

    logger.log(logging.INFO, "one event")

    assert log_path.read_text(encoding="utf-8").count("one event") == 1
