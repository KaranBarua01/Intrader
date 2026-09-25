from datetime import date, datetime
from zoneinfo import ZoneInfo

from intrader.__main__ import main


IST = ZoneInfo("Asia/Kolkata")


def test_session_plan_prints_deterministic_schedule(monkeypatch, capsys) -> None:
    monkeypatch.delenv("INTRADER_TRADING_START", raising=False)

    exit_code = main(["session-plan", "2026-09-28"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "SESSION PLAN" in output
    assert "Warm-up start: 2026-09-28 11:30 IST" in output
    assert "Live start: 2026-09-28 12:00 IST" in output
    assert "Live end: 2026-09-28 12:30 IST" in output


def test_prepare_session_before_warmup_does_not_authenticate(monkeypatch, capsys) -> None:
    called = False

    def forbidden_auth(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("network should not start")

    monkeypatch.setattr(
        "intrader.__main__._now_india",
        lambda: datetime(2026, 9, 28, 11, 0, tzinfo=IST),
    )
    monkeypatch.setattr("intrader.__main__.authenticate", forbidden_auth)

    exit_code = main(["prepare-session", "2026-09-28"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "SESSION: CONFIGURED" in output
    assert "WARMUP_NOT_STARTED" in output
    assert not called


def test_prepare_session_started_too_late_fails_without_authentication(
    monkeypatch, capsys
) -> None:
    called = False

    def forbidden_auth(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("network should not start")

    monkeypatch.setattr(
        "intrader.__main__._now_india",
        lambda: datetime(2026, 9, 28, 11, 33, tzinfo=IST),
    )
    monkeypatch.setattr("intrader.__main__.authenticate", forbidden_auth)

    exit_code = main(["prepare-session", "2026-09-28"])

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "SESSION: NO TRADE" in output
    assert "MISSED_WARMUP" in output
    assert not called


def test_weekend_session_plan_is_rejected(capsys) -> None:
    exit_code = main(["session-plan", "2026-09-26"])

    assert exit_code == 1
    assert capsys.readouterr().out.strip() == "SESSION PLAN UNAVAILABLE"
