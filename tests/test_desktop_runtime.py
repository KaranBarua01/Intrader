"""Desktop live-runtime session clock tests."""

from datetime import datetime

from intrader.historical import INDIA_TIME
from intrader.ui.desktop_runtime import DesktopLiveRuntime


def _at(hour: int, minute: int) -> datetime:
    # 2026-09-28 is a Monday.
    return datetime(2026, 9, 28, hour, minute, tzinfo=INDIA_TIME)


def test_desktop_runtime_phase_clock_covers_full_market_day() -> None:
    assert DesktopLiveRuntime.phase_at(_at(9, 0))[0] == "PRE_MARKET"
    assert DesktopLiveRuntime.phase_at(_at(10, 0))[0] == "OBSERVATION"
    assert DesktopLiveRuntime.phase_at(_at(11, 45))[0] == "WARM_UP"
    assert DesktopLiveRuntime.phase_at(_at(12, 10))[0] == "LIVE"
    assert DesktopLiveRuntime.phase_at(_at(13, 0))[0] == "POST_TRADE"
    assert DesktopLiveRuntime.phase_at(_at(15, 45))[0] == "CLOSED"


def test_desktop_runtime_does_not_mark_late_warmup_as_missed() -> None:
    phase, next_transition = DesktopLiveRuntime.phase_at(_at(11, 45))

    assert phase == "WARM_UP"
    assert next_transition is not None
    assert next_transition.hour == 12
    assert next_transition.minute == 0
