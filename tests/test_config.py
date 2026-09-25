from datetime import time

from intrader.config import AppConfig, load_config


def test_default_config_is_nifty_and_30_minute_warmup(monkeypatch) -> None:
    monkeypatch.delenv("INTRADER_TRADING_START", raising=False)

    config = load_config()

    assert config.underlying == "NIFTY"
    assert config.warmup_minutes == 30
    assert config.trading_start == time(12, 0)
    assert config.trading_duration_minutes == 30
    assert config.option_strikes_each_side == 4
    assert config.timezone == "Asia/Kolkata"


def test_trading_start_can_be_overridden(monkeypatch) -> None:
    monkeypatch.setenv("INTRADER_TRADING_START", "13:15")

    assert load_config().trading_start == time(13, 15)

def test_default_data_health_thresholds() -> None:
    config = AppConfig()

    assert config.stale_tick_seconds == 5.0
    assert config.stale_option_seconds == 8.0
    assert config.warmup_start_grace_seconds == 120
