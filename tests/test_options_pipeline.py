from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from intrader.config import AppConfig
from intrader.instruments import Instrument
from intrader.options_pipeline import (
    OptionsPipelineError,
    build_stored_options_intelligence,
)
from intrader.storage import SQLiteStore
from intrader.stream_protocol import MarketTick


IST = ZoneInfo("Asia/Kolkata")
DAY = date(2026, 9, 28)
AT = datetime(2026, 9, 28, 12, 0, tzinfo=IST)
EXPIRY = date(2026, 9, 29)


def _instrument(token: str, strike: int, option_type: str) -> Instrument:
    return Instrument(
        token=token,
        symbol=f"NIFTY29SEP26{strike}{option_type}",
        name="NIFTY",
        instrument_type="OPTIDX",
        exchange="NFO",
        expiry=EXPIRY,
        strike=Decimal(str(strike)),
        lot_size=65,
    )


def _store_pair(
    store: SQLiteStore,
    instrument: Instrument,
    *,
    old_ltp: str,
    new_ltp: str,
    old_oi: int,
    new_oi: int,
    old_volume: int,
    new_volume: int,
    sequence_base: int,
) -> None:
    baseline_at = AT - timedelta(minutes=5)
    current_at = AT
    store.store_option_tick(
        instrument,
        MarketTick(
            "NFO",
            instrument.token,
            3,
            sequence_base,
            baseline_at,
            baseline_at,
            Decimal(old_ltp),
            old_oi,
            old_volume,
        ),
    )
    store.store_option_tick(
        instrument,
        MarketTick(
            "NFO",
            instrument.token,
            3,
            sequence_base + 1,
            current_at,
            current_at,
            Decimal(new_ltp),
            new_oi,
            new_volume,
        ),
    )


def test_pipeline_selects_complete_fresh_active_chain(tmp_path) -> None:
    config = AppConfig(option_strikes_each_side=1)
    with SQLiteStore(tmp_path / "intrader.db") as store:
        sequence = 1
        for strike in (23100, 23150, 23200):
            for option_type in ("CE", "PE"):
                instrument = _instrument(
                    f"{strike}{option_type}",
                    strike,
                    option_type,
                )
                _store_pair(
                    store,
                    instrument,
                    old_ltp="100",
                    new_ltp="105",
                    old_oi=1000,
                    new_oi=1100,
                    old_volume=2000,
                    new_volume=2300,
                    sequence_base=sequence,
                )
                sequence += 2

        result = build_stored_options_intelligence(
            store,
            DAY,
            AT,
            config,
        )

    assert len(result.contracts) == 6
    assert result.total_call_open_interest == 3300
    assert result.total_put_open_interest == 3300
    assert result.open_interest_pcr == Decimal("1")
    assert result.volume_pcr == Decimal("1")


def test_pipeline_rejects_incomplete_active_chain(tmp_path) -> None:
    config = AppConfig(option_strikes_each_side=1)
    with SQLiteStore(tmp_path / "intrader.db") as store:
        for sequence, (strike, option_type) in enumerate(
            (
                (23100, "CE"),
                (23100, "PE"),
                (23150, "CE"),
                (23150, "PE"),
                (23200, "CE"),
            ),
            start=1,
        ):
            _store_pair(
                store,
                _instrument(f"{strike}{option_type}", strike, option_type),
                old_ltp="100",
                new_ltp="105",
                old_oi=1000,
                new_oi=1100,
                old_volume=2000,
                new_volume=2300,
                sequence_base=sequence * 10,
            )

        with pytest.raises(OptionsPipelineError, match="incomplete"):
            build_stored_options_intelligence(
                store,
                DAY,
                AT,
                config,
            )


def test_pipeline_ignores_stale_old_atm_contracts(tmp_path) -> None:
    config = AppConfig(option_strikes_each_side=1)
    with SQLiteStore(tmp_path / "intrader.db") as store:
        sequence = 1
        for strike in (23100, 23150, 23200):
            for option_type in ("CE", "PE"):
                _store_pair(
                    store,
                    _instrument(f"{strike}{option_type}", strike, option_type),
                    old_ltp="100",
                    new_ltp="105",
                    old_oi=1000,
                    new_oi=1100,
                    old_volume=2000,
                    new_volume=2300,
                    sequence_base=sequence,
                )
                sequence += 2

        stale_instrument = _instrument("23000CE", 23000, "CE")
        stale_at = AT - timedelta(minutes=20)
        store.store_option_tick(
            stale_instrument,
            MarketTick(
                "NFO",
                stale_instrument.token,
                3,
                999,
                stale_at,
                stale_at,
                Decimal("50"),
                500,
                800,
            ),
        )

        result = build_stored_options_intelligence(
            store,
            DAY,
            AT,
            config,
        )

    assert len(result.contracts) == 6
    assert all(contract.strike != Decimal("23000") for contract in result.contracts)
