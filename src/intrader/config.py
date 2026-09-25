"""Application configuration for Intrader."""

from dataclasses import dataclass
from datetime import time
import os


@dataclass(frozen=True, slots=True)
class AppConfig:
    """Runtime settings used by the Intrader application."""

    underlying: str = "NIFTY"
    warmup_minutes: int = 30
    trading_start: time = time(12, 0)
    trading_duration_minutes: int = 30
    option_strikes_each_side: int = 4
    timezone: str = "Asia/Kolkata"
    stale_tick_seconds: float = 5.0
    stale_option_seconds: float = 8.0
    warmup_start_grace_seconds: int = 120


def _parse_time(value: str) -> time:
    hour, minute = value.split(":", maxsplit=1)
    return time(int(hour), int(minute))


def load_config() -> AppConfig:
    """Load Intrader configuration from safe local environment settings."""

    trading_start = _parse_time(
        os.getenv("INTRADER_TRADING_START", "12:00")
    )

    return AppConfig(trading_start=trading_start)
