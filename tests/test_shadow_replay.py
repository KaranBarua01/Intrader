"""Tests for the timestamp-causal historical Shadow Trader replay."""

from datetime import date, datetime, time, timedelta
from decimal import Decimal

from intrader.historical import Candle, INDIA_TIME
from intrader.shadow_replay import run_candle_proxy_replay


def _synthetic_sessions(count: int) -> tuple[Candle, ...]:
    candles = []
    day = date(2026, 1, 5)
    built = 0
    base = Decimal("24000")
    while built < count:
        if day.weekday() < 5:
            start = datetime.combine(day, time(9, 15), INDIA_TIME)
            session_base = base + Decimal(built * 20)
            for minute in range(40):
                open_ = session_base + Decimal(minute)
                close = open_ + Decimal("0.8")
                candles.append(
                    Candle(
                        at=start + timedelta(minutes=minute),
                        open=open_,
                        high=close + Decimal("0.3"),
                        low=open_ - Decimal("0.3"),
                        close=close,
                        volume=1000 + minute,
                    )
                )
            built += 1
        day += timedelta(days=1)
    return tuple(candles)


def test_candle_proxy_replay_uses_development_then_blind() -> None:
    report = run_candle_proxy_replay(
        _synthetic_sessions(30),
        sessions=30,
        mode_key="LOW",
    )

    assert report.schema == "intrader-shadow-replay-v1-candle-proxy"
    assert report.requested_sessions == 30
    assert report.actual_sessions == 30
    assert report.development_sessions == 20
    assert report.blind_sessions == 10
    assert report.mode == "LOW"
    assert report.requested_touchpoints == 15
    assert report.first_session < report.last_session


def test_replay_never_needs_future_session_to_form_report() -> None:
    candles = _synthetic_sessions(31)
    report_30 = run_candle_proxy_replay(
        candles[:-40],
        sessions=30,
        mode_key="MEDIUM",
    )
    report_with_future_present = run_candle_proxy_replay(
        candles,
        sessions=30,
        mode_key="MEDIUM",
    )

    # The runner always selects the most recent requested sessions. Presence of
    # an additional later session changes the tested period rather than leaking
    # that future session into the earlier replay.
    assert report_30.last_session != report_with_future_present.last_session
    assert report_30.requested_touchpoints == 30
    assert report_with_future_present.requested_touchpoints == 30
