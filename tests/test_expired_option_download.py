from datetime import date, datetime, timezone
from decimal import Decimal
import json

import pytest

from intrader.expired_option_download import (
    ExpiredOptionDownloadError,
    ExpiredOptionDownloadReport,
    download_expired_option_sessions,
    download_expired_options_1m,
    nearest_available_expiry,
    select_required_contracts,
)
from intrader.historical import Candle
from intrader.instruments import Instrument
from intrader.upstox import (
    ExpiredOptionCandle,
    ExpiredOptionContract,
    UpstoxNoDataError,
)


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



def test_batch_downloads_previous_sessions_and_skips_holiday(
    tmp_path, monkeypatch
) -> None:
    attempted = []
    holiday = date(2024, 10, 21)

    def fake_download(
        _session,
        _transport,
        _upstox,
        _spot_instrument,
        trading_date,
        *,
        output_root,
        **_kwargs,
    ):
        attempted.append(trading_date)
        if trading_date == holiday:
            raise ExpiredOptionDownloadError(
                "No NIFTY spot candles returned for requested date"
            )
        day_dir = output_root / trading_date.isoformat()
        return ExpiredOptionDownloadReport(
            trading_date=trading_date,
            expiry=date(2024, 10, 24),
            spot_low=Decimal("24400"),
            spot_high=Decimal("24600"),
            selected_strikes=(Decimal("24500"),),
            contract_count=2,
            total_rows=750,
            csv_path=day_dir / "options_1m.csv",
            manifest_path=day_dir / "options_manifest.json",
        )

    monkeypatch.setattr(
        "intrader.expired_option_download.download_expired_options_1m",
        fake_download,
    )

    report = download_expired_option_sessions(
        object(),
        object(),
        object(),
        _spot(),
        date(2024, 10, 23),
        3,
        output_root=tmp_path,
        request_delay=0,
        session_delay=0,
    )

    assert report.completed_dates == (
        date(2024, 10, 18),
        date(2024, 10, 22),
        date(2024, 10, 23),
    )
    assert report.skipped_non_sessions == (holiday,)
    assert report.total_rows == 2250
    assert attempted == [
        date(2024, 10, 23),
        date(2024, 10, 22),
        date(2024, 10, 21),
        date(2024, 10, 18),
    ]
    payload = json.loads(report.summary_path.read_text(encoding="utf-8"))
    assert payload["completed_sessions"] == 3
    assert payload["first_session"] == "2024-10-18"


def test_batch_reuses_valid_cached_session(tmp_path, monkeypatch) -> None:
    cached_day = date(2024, 10, 23)
    cached_path = tmp_path / cached_day.isoformat() / "options_1m.csv"
    cached_path.parent.mkdir(parents=True)
    cached_path.write_text("placeholder", encoding="utf-8")

    class CachedDataset:
        def summary(self):
            class Summary:
                trading_date = cached_day
                rows = 9750
            return Summary()

    monkeypatch.setattr(
        "intrader.expired_option_download.load_historical_option_csv",
        lambda _path: CachedDataset(),
    )

    downloaded = []

    def fake_download(
        _session,
        _transport,
        _upstox,
        _spot_instrument,
        trading_date,
        *,
        output_root,
        **_kwargs,
    ):
        downloaded.append(trading_date)
        day_dir = output_root / trading_date.isoformat()
        return ExpiredOptionDownloadReport(
            trading_date=trading_date,
            expiry=date(2024, 10, 24),
            spot_low=Decimal("24400"),
            spot_high=Decimal("24600"),
            selected_strikes=(Decimal("24500"),),
            contract_count=2,
            total_rows=9000,
            csv_path=day_dir / "options_1m.csv",
            manifest_path=day_dir / "options_manifest.json",
        )

    monkeypatch.setattr(
        "intrader.expired_option_download.download_expired_options_1m",
        fake_download,
    )

    report = download_expired_option_sessions(
        object(),
        object(),
        object(),
        _spot(),
        cached_day,
        2,
        output_root=tmp_path,
        request_delay=0,
        session_delay=0,
    )

    assert report.cached_dates == (cached_day,)
    assert downloaded == [date(2024, 10, 22)]
    assert report.total_rows == 18750



def test_download_tolerates_empty_outer_buffer_contract(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "intrader.expired_option_download.fetch_candles",
        lambda *_args, **_kwargs: _spot_candles(),
    )

    class MissingOuterBufferUpstox(FakeUpstox):
        def get_historical_candles(
            self, instrument_key, from_date, to_date=None
        ):
            self.candle_calls.append(instrument_key)
            assert from_date == date(2024, 10, 23)
            if instrument_key == "NSE_FO|24700-PE|24-10-2024":
                raise UpstoxNoDataError(
                    "No expired option candles returned"
                )
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

    report = download_expired_options_1m(
        object(),
        object(),
        MissingOuterBufferUpstox(),
        _spot(),
        date(2024, 10, 23),
        output_root=tmp_path,
        request_delay=0,
    )

    assert report.contract_count == 17
    manifest = json.loads(report.manifest_path.read_text(encoding="utf-8"))
    assert manifest["requested_contract_count"] == 18
    assert manifest["contract_count"] == 17
    assert manifest["coverage_state"] == "DEGRADED_BUFFER_ONLY"
    assert manifest["missing_contracts"] == [
        {
            "trading_symbol": "NIFTY 24700 PE 24 OCT 24",
            "instrument_key": "NSE_FO|24700-PE|24-10-2024",
            "strike": "24700",
            "option_type": "PE",
            "reason": "UPSTOX_EMPTY_CANDLES",
        }
    ]



def test_download_fails_closed_when_empty_contract_breaks_atm_coverage(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setattr(
        "intrader.expired_option_download.fetch_candles",
        lambda *_args, **_kwargs: _spot_candles(),
    )

    class MissingAtmUpstox(FakeUpstox):
        def get_historical_candles(
            self, instrument_key, from_date, to_date=None
        ):
            self.candle_calls.append(instrument_key)
            assert from_date == date(2024, 10, 23)
            if instrument_key == "NSE_FO|24500-PE|24-10-2024":
                raise UpstoxNoDataError(
                    "No expired option candles returned"
                )
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

    with pytest.raises(
        ExpiredOptionDownloadError,
        match="ATM coverage incomplete",
    ):
        download_expired_options_1m(
            object(),
            object(),
            MissingAtmUpstox(),
            _spot(),
            date(2024, 10, 23),
            output_root=tmp_path,
            request_delay=0,
        )
