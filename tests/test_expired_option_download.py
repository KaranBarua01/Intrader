from datetime import date, datetime, timezone
from decimal import Decimal
import json

import pytest

from intrader.expired_option_download import (
    ExpiredOptionDownloadError,
    download_expired_options_1m,
    nearest_available_expiry,
    select_required_contracts,
)
from intrader.historical import Candle
from intrader.instruments import Instrument
from intrader.upstox import ExpiredOptionCandle, ExpiredOptionContract


def _spot() -> Instrument:
    return Instrument(
        token="99926000",
        symbol="Nifty 50",
        name="NIFTY",
        instrument_type="AMXIDX",
        exchange="NSE",
        expiry=None,
        strike=Decimal("0"),
        lot_size=1,
    )


def _spot_candles() -> tuple[Candle, ...]:
    return (
        Candle(
            datetime(2024, 10, 23, 3, 45, tzinfo=timezone.utc),
            Decimal("24500"),
            Decimal("24510"),
            Decimal("24490"),
            Decimal("24505"),
            0,
        ),
    )


def _contracts() -> tuple[ExpiredOptionContract, ...]:
    values = []
    expiry = date(2024, 10, 24)
    for strike in range(24100, 24950, 50):
        for side in ("CE", "PE"):
            values.append(
                ExpiredOptionContract(
                    trading_symbol=f"NIFTY {strike} {side} 24 OCT 24",
                    strike_price=Decimal(str(strike)),
                    option_type=side,
                    instrument_key=f"NSE_FO|{strike}-{side}|24-10-2024",
                    lot_size=25,
                    expiry=expiry,
                )
            )
    return tuple(values)


class FakeUpstox:
    def __init__(self) -> None:
        self.candle_calls: list[str] = []

    def get_expiries(self):
        return (date(2024, 10, 17), date(2024, 10, 24), date(2024, 10, 31))

    def get_option_contracts(self, expiry):
        assert expiry == date(2024, 10, 24)
        return _contracts()

    def get_historical_candles(self, instrument_key, from_date, to_date=None):
        self.candle_calls.append(instrument_key)
        assert from_date == date(2024, 10, 23)
        return (
            ExpiredOptionCandle(
                at=datetime(2024, 10, 23, 3, 45, tzinfo=timezone.utc),
                open=Decimal("100"),
                high=Decimal("110"),
                low=Decimal("95"),
                close=Decimal("105"),
                volume=1000,
                open_interest=2000,
            ),
        )


def test_nearest_available_expiry_uses_first_expiry_on_or_after_day() -> None:
    assert nearest_available_expiry(
        [date(2024, 10, 17), date(2024, 10, 24), date(2024, 10, 31)],
        date(2024, 10, 23),
    ) == date(2024, 10, 24)


def test_nearest_available_expiry_fails_when_history_does_not_cover_day() -> None:
    with pytest.raises(ExpiredOptionDownloadError, match="covers"):
        nearest_available_expiry([date(2024, 10, 17)], date(2024, 10, 23))


def test_required_contracts_cover_atm_plus_minus_four() -> None:
    selected, strikes, low, high = select_required_contracts(
        _contracts(),
        _spot_candles(),
    )

    assert strikes == tuple(Decimal(str(value)) for value in range(24300, 24750, 50))
    assert len(selected) == 18
    assert {item.option_type for item in selected} == {"CE", "PE"}
    assert low == Decimal("24490")
    assert high == Decimal("24510")


def test_required_contracts_fail_closed_when_pair_missing() -> None:
    contracts = tuple(
        item
        for item in _contracts()
        if not (item.strike_price == Decimal("24500") and item.option_type == "PE")
    )
    with pytest.raises(ExpiredOptionDownloadError, match="window incomplete"):
        select_required_contracts(
            contracts,
            (
                Candle(
                    datetime(2024, 10, 23, 3, 45, tzinfo=timezone.utc),
                    Decimal("24110"),
                    Decimal("24120"),
                    Decimal("24100"),
                    Decimal("24110"),
                    0,
                ),
            ),
        )


def test_download_writes_real_option_schema(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "intrader.expired_option_download.fetch_candles",
        lambda *_args, **_kwargs: _spot_candles(),
    )
    upstox = FakeUpstox()

    report = download_expired_options_1m(
        object(),
        object(),
        upstox,
        _spot(),
        date(2024, 10, 23),
        output_root=tmp_path,
        request_delay=0,
    )

    assert report.expiry == date(2024, 10, 24)
    assert report.contract_count == 18
    assert report.total_rows == 18
    assert len(upstox.candle_calls) == 18
    csv_text = report.csv_path.read_text(encoding="utf-8")
    assert "timestamp_ist,expiry,trading_symbol,instrument_key,strike" in csv_text
    assert "open_interest" in csv_text
    assert "24500,CE,25,100,110,95,105,1000,2000" in csv_text

    manifest = json.loads(report.manifest_path.read_text(encoding="utf-8"))
    assert manifest["trading_date"] == "2024-10-23"
    assert manifest["expiry"] == "2024-10-24"
    assert manifest["contract_count"] == 18
    assert manifest["selected_strikes"][4] == "24500"
    assert "no-lookahead" in manifest["selection_note"]
