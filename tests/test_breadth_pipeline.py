from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from intrader.breadth_pipeline import BreadthPipelineError, build_stored_breadth
from intrader.breadth_provider import ResolvedBreadthMember
from intrader.config import AppConfig
from intrader.instruments import Instrument
from intrader.storage import SQLiteStore
from intrader.stream_protocol import MarketTick


IST = ZoneInfo("Asia/Kolkata")
DAY = date(2026, 9, 28)
AT = datetime(2026, 9, 28, 12, 0, tzinfo=IST)


def _member(index: int) -> ResolvedBreadthMember:
    symbol = f"SYM{index}"
    return ResolvedBreadthMember(
        company_name=f"Company {index}",
        industry=f"Industry {index % 5}",
        symbol=symbol,
        instrument=Instrument(
            token=str(10000 + index),
            symbol=f"{symbol}-EQ",
            name=symbol,
            instrument_type="",
            exchange="NSE",
            expiry=None,
            strike=Decimal("-1"),
            lot_size=1,
        ),
    )


def _tick(member: ResolvedBreadthMember, index: int) -> MarketTick:
    return MarketTick(
        exchange="NSE",
        token=member.instrument.token,
        mode=2,
        sequence=index + 1,
        exchange_at=AT,
        received_at=AT,
        last_price=Decimal("101") if index < 30 else Decimal("99"),
        open_interest=None,
        volume=1000,
        previous_close=Decimal("100"),
    )


def test_pipeline_builds_equal_weight_breadth_from_50_fresh_members(tmp_path) -> None:
    members = tuple(_member(index) for index in range(50))

    with SQLiteStore(tmp_path / "intrader.db") as store:
        for index, member in enumerate(members):
            store.store_breadth_tick(member, _tick(member, index))

        result = build_stored_breadth(
            store,
            DAY,
            AT,
            AppConfig(),
        )

    assert result.total == 50
    assert result.advancing == 30
    assert result.declining == 20
    assert result.unchanged == 0
    assert result.advance_decline_ratio == Decimal("1.5")
    assert result.equal_weight_breadth_pct == Decimal("20")
    assert result.weighted_return_pct is None
    assert len(result.sectors) == 5


def test_pipeline_rejects_incomplete_membership(tmp_path) -> None:
    with SQLiteStore(tmp_path / "intrader.db") as store:
        for index in range(49):
            member = _member(index)
            store.store_breadth_tick(member, _tick(member, index))

        with pytest.raises(BreadthPipelineError, match="incomplete"):
            build_stored_breadth(
                store,
                DAY,
                AT,
                AppConfig(),
            )
