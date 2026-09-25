from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from intrader.options_intelligence import (
    OptionSnapshot,
    OptionsIntelligenceError,
    build_options_intelligence,
    classify_buildup,
)


NOW = datetime(2026, 9, 28, 6, 30, tzinfo=timezone.utc)
EXPIRY = date(2026, 9, 29)


def _snapshot(
    token: str,
    strike: int,
    option_type: str,
    minutes_ago: int,
    *,
    ltp: str,
    oi: int,
    volume: int,
    sequence: int,
) -> OptionSnapshot:
    at = NOW - timedelta(minutes=minutes_ago)
    return OptionSnapshot(
        token=token,
        exchange_at=at,
        received_at=at,
        sequence=sequence,
        expiry=EXPIRY,
        strike=Decimal(str(strike)),
        option_type=option_type,
        ltp=Decimal(ltp),
        open_interest=oi,
        volume=volume,
    )


def _history(
    token: str,
    strike: int,
    option_type: str,
    *,
    old_ltp: str,
    new_ltp: str,
    old_oi: int,
    new_oi: int,
    old_volume: int,
    new_volume: int,
) -> tuple[OptionSnapshot, OptionSnapshot]:
    return (
        _snapshot(
            token,
            strike,
            option_type,
            5,
            ltp=old_ltp,
            oi=old_oi,
            volume=old_volume,
            sequence=1,
        ),
        _snapshot(
            token,
            strike,
            option_type,
            0,
            ltp=new_ltp,
            oi=new_oi,
            volume=new_volume,
            sequence=2,
        ),
    )


@pytest.mark.parametrize(
    ("ltp_change", "oi_change", "expected"),
    [
        (Decimal("1"), 1, "LONG_BUILDUP"),
        (Decimal("-1"), 1, "SHORT_BUILDUP"),
        (Decimal("1"), -1, "SHORT_COVERING"),
        (Decimal("-1"), -1, "LONG_UNWINDING"),
        (Decimal("0"), 10, "NEUTRAL"),
        (Decimal("2"), 0, "NEUTRAL"),
    ],
)
def test_buildup_classification_is_contract_level(
    ltp_change: Decimal,
    oi_change: int,
    expected: str,
) -> None:
    assert classify_buildup(ltp_change, oi_change) == expected


def test_chain_calculates_changes_pcr_concentrations_and_max_strikes() -> None:
    histories = {
        "100CE": _history(
            "100CE", 100, "CE",
            old_ltp="10", new_ltp="12",
            old_oi=100, new_oi=150,
            old_volume=1000, new_volume=1300,
        ),
        "100PE": _history(
            "100PE", 100, "PE",
            old_ltp="9", new_ltp="8",
            old_oi=200, new_oi=250,
            old_volume=1200, new_volume=1600,
        ),
        "150CE": _history(
            "150CE", 150, "CE",
            old_ltp="6", new_ltp="5",
            old_oi=300, new_oi=350,
            old_volume=800, new_volume=900,
        ),
        "150PE": _history(
            "150PE", 150, "PE",
            old_ltp="14", new_ltp="16",
            old_oi=100, new_oi=140,
            old_volume=900, new_volume=1200,
        ),
    }

    result = build_options_intelligence(
        histories,
        NOW,
        expected_tokens=("100CE", "100PE", "150CE", "150PE"),
    )

    assert result.total_call_open_interest == 500
    assert result.total_put_open_interest == 390
    assert result.open_interest_pcr == Decimal("0.78")
    assert result.total_call_volume == 2200
    assert result.total_put_volume == 2800
    assert result.volume_pcr == Decimal(2800) / Decimal(2200)
    assert result.max_call_open_interest_strike == Decimal("150")
    assert result.max_put_open_interest_strike == Decimal("100")
    assert result.max_call_open_interest_change_strike == Decimal("100")
    assert result.max_put_open_interest_change_strike == Decimal("100")
    assert result.call_open_interest_concentration == Decimal("0.7")
    assert result.put_open_interest_concentration == Decimal(250) / Decimal(390)

    by_token = {metric.token: metric for metric in result.contracts}
    assert by_token["100CE"].ltp_change == Decimal("2")
    assert by_token["100CE"].ltp_change_pct == Decimal("20")
    assert by_token["100CE"].open_interest_change == 50
    assert by_token["100CE"].open_interest_change_pct == Decimal("50")
    assert by_token["100CE"].volume_change == 300
    assert by_token["100CE"].buildup == "LONG_BUILDUP"
    assert by_token["100PE"].buildup == "SHORT_BUILDUP"
    assert by_token["150CE"].buildup == "SHORT_BUILDUP"
    assert by_token["150PE"].buildup == "LONG_BUILDUP"


def test_missing_contract_or_missing_lookback_fails_closed() -> None:
    complete = {
        "100CE": _history(
            "100CE", 100, "CE",
            old_ltp="10", new_ltp="12",
            old_oi=100, new_oi=150,
            old_volume=1000, new_volume=1300,
        ),
        "100PE": _history(
            "100PE", 100, "PE",
            old_ltp="9", new_ltp="8",
            old_oi=200, new_oi=250,
            old_volume=1200, new_volume=1600,
        ),
    }

    with pytest.raises(OptionsIntelligenceError, match="incomplete"):
        build_options_intelligence(
            {"100CE": complete["100CE"]},
            NOW,
            expected_tokens=("100CE", "100PE"),
        )

    current_only = {
        "100CE": (complete["100CE"][-1],),
        "100PE": (complete["100PE"][-1],),
    }
    with pytest.raises(OptionsIntelligenceError, match="lookback"):
        build_options_intelligence(
            current_only,
            NOW,
            expected_tokens=("100CE", "100PE"),
        )


def test_negative_volume_delta_fails_closed() -> None:
    histories = {
        "100CE": _history(
            "100CE", 100, "CE",
            old_ltp="10", new_ltp="12",
            old_oi=100, new_oi=150,
            old_volume=1500, new_volume=1300,
        ),
        "100PE": _history(
            "100PE", 100, "PE",
            old_ltp="9", new_ltp="8",
            old_oi=200, new_oi=250,
            old_volume=1200, new_volume=1600,
        ),
    }

    with pytest.raises(OptionsIntelligenceError, match="volume reset"):
        build_options_intelligence(
            histories,
            NOW,
            expected_tokens=("100CE", "100PE"),
        )


def test_zero_call_oi_or_volume_returns_unavailable_ratio() -> None:
    histories = {
        "100CE": _history(
            "100CE", 100, "CE",
            old_ltp="10", new_ltp="12",
            old_oi=0, new_oi=0,
            old_volume=0, new_volume=0,
        ),
        "100PE": _history(
            "100PE", 100, "PE",
            old_ltp="9", new_ltp="8",
            old_oi=100, new_oi=100,
            old_volume=100, new_volume=100,
        ),
    }

    result = build_options_intelligence(
        histories,
        NOW,
        expected_tokens=("100CE", "100PE"),
    )

    assert result.open_interest_pcr is None
    assert result.volume_pcr is None
    assert result.call_open_interest_concentration is None


def test_stale_current_snapshot_fails_closed() -> None:
    histories = {
        "100CE": (
            _snapshot(
                "100CE", 100, "CE", 5,
                ltp="10", oi=100, volume=1000, sequence=1,
            ),
            OptionSnapshot(
                token="100CE",
                exchange_at=NOW - timedelta(seconds=20),
                received_at=NOW - timedelta(seconds=20),
                sequence=2,
                expiry=EXPIRY,
                strike=Decimal("100"),
                option_type="CE",
                ltp=Decimal("12"),
                open_interest=150,
                volume=1300,
            ),
        ),
        "100PE": _history(
            "100PE", 100, "PE",
            old_ltp="9", new_ltp="8",
            old_oi=200, new_oi=250,
            old_volume=1200, new_volume=1600,
        ),
    }

    with pytest.raises(OptionsIntelligenceError, match="stale"):
        build_options_intelligence(
            histories,
            NOW,
            expected_tokens=("100CE", "100PE"),
        )
