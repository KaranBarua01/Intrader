from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from intrader.historical import INDIA_TIME
from intrader.historical_options import (
    HistoricalOptionDataError,
    load_historical_option_csv,
)


HEADER = (
    "timestamp_ist,expiry,trading_symbol,instrument_key,strike,option_type,"
    "lot_size,open,high,low,close,volume,open_interest\n"
)


def _row(
    minute: int,
    strike: int,
    side: str,
    *,
    open_: str = "100",
    high: str = "110",
    low: str = "95",
    close: str = "105",
) -> str:
    return (
        f"2024-10-23T09:{minute:02d}:00+05:30,2024-10-24,"
        f"NIFTY {strike} {side} 24 OCT 24,NSE_FO|{strike}-{side}|24-10-2024,"
        f"{strike},{side},25,{open_},{high},{low},{close},1000,2000\n"
    )


def _write_fixture(path) -> None:
    text = HEADER
    for minute in (15, 16, 17):
        for strike in (24450, 24500, 24550):
            for side in ("CE", "PE"):
                text += _row(minute, strike, side)
    path.write_text(text, encoding="utf-8")


def test_load_summary_and_complete_pairs(tmp_path) -> None:
    path = tmp_path / "options_1m.csv"
    _write_fixture(path)

    data = load_historical_option_csv(path)
    summary = data.summary()

    assert summary.trading_date.isoformat() == "2024-10-23"
    assert summary.rows == 18
    assert summary.contracts == 6
    assert summary.strikes == 3
    assert summary.complete_pair_strikes == 3
    assert data.complete_pair_strikes == (
        Decimal("24450"),
        Decimal("24500"),
        Decimal("24550"),
    )


def test_nearest_complete_strike_is_deterministic(tmp_path) -> None:
    path = tmp_path / "options_1m.csv"
    _write_fixture(path)
    data = load_historical_option_csv(path)

    assert data.nearest_complete_strike(Decimal("24524")) == Decimal("24500")
    assert data.nearest_complete_strike(Decimal("24525")) == Decimal("24500")
    assert data.nearest_complete_strike(Decimal("24526")) == Decimal("24550")


def test_visible_at_never_returns_future_candles(tmp_path) -> None:
    path = tmp_path / "options_1m.csv"
    _write_fixture(path)
    data = load_historical_option_csv(path)

    clock = datetime(2024, 10, 23, 9, 16, tzinfo=INDIA_TIME)
    visible = data.visible_at(Decimal("24500"), "CE", clock)

    assert [row.at.strftime("%H:%M") for row in visible] == ["09:15", "09:16"]


def test_entry_is_strictly_next_bar_after_signal(tmp_path) -> None:
    path = tmp_path / "options_1m.csv"
    _write_fixture(path)
    data = load_historical_option_csv(path)

    signal = datetime(2024, 10, 23, 9, 15, tzinfo=INDIA_TIME)
    entry = data.first_candle_after(Decimal("24500"), "CE", signal)

    assert entry is not None
    assert entry.at.strftime("%H:%M") == "09:16"
    assert entry.open == Decimal("100")


def test_entry_returns_none_when_gap_exceeds_limit(tmp_path) -> None:
    path = tmp_path / "options_1m.csv"
    path.write_text(
        HEADER
        + _row(15, 24500, "CE")
        + _row(15, 24500, "PE")
        + _row(19, 24500, "CE")
        + _row(19, 24500, "PE"),
        encoding="utf-8",
    )
    data = load_historical_option_csv(path)

    signal = datetime(2024, 10, 23, 9, 15, tzinfo=INDIA_TIME)
    assert data.first_candle_after(
        Decimal("24500"), "CE", signal, max_wait_minutes=2
    ) is None


def test_invalid_ohlc_fails_closed(tmp_path) -> None:
    path = tmp_path / "options_1m.csv"
    path.write_text(
        HEADER
        + _row(15, 24500, "CE", open_="100", high="99", low="95", close="105"),
        encoding="utf-8",
    )

    with pytest.raises(HistoricalOptionDataError, match="OHLC"):
        load_historical_option_csv(path)


def test_exact_candle_lookup_is_timestamp_strict(tmp_path) -> None:
    path = tmp_path / "options_1m.csv"
    _write_fixture(path)
    data = load_historical_option_csv(path)

    exact = data.candle_at(
        Decimal("24500"),
        "CE",
        datetime(2024, 10, 23, 9, 16, tzinfo=INDIA_TIME),
    )
    missing = data.candle_at(
        Decimal("24500"),
        "CE",
        datetime(2024, 10, 23, 9, 18, tzinfo=INDIA_TIME),
    )

    assert exact is not None
    assert exact.at.strftime("%H:%M") == "09:16"
    assert missing is None
