from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from intrader.market_confirmation import (
    FutureSnapshot,
    IndexSnapshot,
    MarketConfirmationError,
    build_market_confirmation,
)


NOW = datetime(2026, 9, 28, 6, 30, tzinfo=timezone.utc)


def _index(token: str, minutes_ago: int, value: str, sequence: int) -> IndexSnapshot:
    at = NOW - timedelta(minutes=minutes_ago)
    return IndexSnapshot(token, at, at, sequence, Decimal(value))


def _future(
    minutes_ago: int,
    *,
    ltp: str,
    oi: int,
    volume: int,
    total_buy: str,
    total_sell: str,
    bid: str | None,
    ask: str | None,
    depth_buy: int,
    depth_sell: int,
    sequence: int,
) -> FutureSnapshot:
    at = NOW - timedelta(minutes=minutes_ago)
    return FutureSnapshot(
        token="future",
        exchange_at=at,
        received_at=at,
        sequence=sequence,
        ltp=Decimal(ltp),
        open_interest=oi,
        volume=volume,
        total_buy_quantity=Decimal(total_buy),
        total_sell_quantity=Decimal(total_sell),
        best_bid_price=None if bid is None else Decimal(bid),
        best_bid_quantity=1000,
        best_ask_price=None if ask is None else Decimal(ask),
        best_ask_quantity=900,
        depth_buy_quantity=depth_buy,
        depth_sell_quantity=depth_sell,
    )


def test_confirmation_calculates_futures_basis_vix_and_order_flow() -> None:
    spot = (
        _index("spot", 5, "23100", 1),
        _index("spot", 0, "23120", 2),
    )
    vix = (
        _index("vix", 5, "12", 1),
        _index("vix", 0, "12.6", 2),
    )
    future = (
        _future(
            5,
            ltp="23150",
            oi=1000,
            volume=5000,
            total_buy="10000",
            total_sell="10000",
            bid="23149",
            ask="23151",
            depth_buy=5000,
            depth_sell=5000,
            sequence=1,
        ),
        _future(
            0,
            ltp="23180",
            oi=1200,
            volume=6000,
            total_buy="15000",
            total_sell="10000",
            bid="23179",
            ask="23181",
            depth_buy=6000,
            depth_sell=4000,
            sequence=2,
        ),
    )

    result = build_market_confirmation(spot, vix, future, NOW)

    assert result.futures.ltp == Decimal("23180")
    assert result.futures.ltp_change == Decimal("30")
    assert result.futures.open_interest_change == 200
    assert result.futures.volume_change == 1000
    assert result.futures.buildup == "LONG_BUILDUP"
    assert result.futures.basis == Decimal("60")
    assert result.futures.basis_change == Decimal("10")

    assert result.vix.value == Decimal("12.6")
    assert result.vix.change == Decimal("0.6")
    assert result.vix.change_pct == Decimal("5.00")

    assert result.order_flow.total_buy_sell_ratio == Decimal("1.5")
    assert result.order_flow.depth_buy_sell_ratio == Decimal("1.5")
    assert result.order_flow.depth_imbalance == Decimal("0.2")
    assert result.order_flow.best_bid == Decimal("23179")
    assert result.order_flow.best_ask == Decimal("23181")
    assert result.order_flow.spread == Decimal("2")
    assert result.order_flow.spread_bps == (
        Decimal("2") / Decimal("23180") * Decimal("10000")
    )


def test_zero_sell_quantities_return_unavailable_ratios() -> None:
    spot = (_index("spot", 5, "23100", 1), _index("spot", 0, "23120", 2))
    vix = (_index("vix", 5, "12", 1), _index("vix", 0, "12", 2))
    future = (
        _future(
            5, ltp="23150", oi=1000, volume=5000,
            total_buy="0", total_sell="0", bid=None, ask=None,
            depth_buy=0, depth_sell=0, sequence=1,
        ),
        _future(
            0, ltp="23150", oi=1000, volume=5000,
            total_buy="1000", total_sell="0", bid=None, ask=None,
            depth_buy=1000, depth_sell=0, sequence=2,
        ),
    )

    result = build_market_confirmation(spot, vix, future, NOW)

    assert result.order_flow.total_buy_sell_ratio is None
    assert result.order_flow.depth_buy_sell_ratio is None
    assert result.order_flow.depth_imbalance == Decimal("1")
    assert result.order_flow.spread is None


def test_future_volume_reset_and_crossed_book_fail_closed() -> None:
    spot = (_index("spot", 5, "23100", 1), _index("spot", 0, "23120", 2))
    vix = (_index("vix", 5, "12", 1), _index("vix", 0, "12", 2))

    reset = (
        _future(
            5, ltp="23150", oi=1000, volume=6000,
            total_buy="1000", total_sell="1000", bid="23149", ask="23151",
            depth_buy=1000, depth_sell=1000, sequence=1,
        ),
        _future(
            0, ltp="23160", oi=1100, volume=5000,
            total_buy="1000", total_sell="1000", bid="23159", ask="23161",
            depth_buy=1000, depth_sell=1000, sequence=2,
        ),
    )
    with pytest.raises(MarketConfirmationError, match="volume reset"):
        build_market_confirmation(spot, vix, reset, NOW)

    crossed = (
        _future(
            5, ltp="23150", oi=1000, volume=5000,
            total_buy="1000", total_sell="1000", bid="23149", ask="23151",
            depth_buy=1000, depth_sell=1000, sequence=1,
        ),
        _future(
            0, ltp="23160", oi=1100, volume=6000,
            total_buy="1000", total_sell="1000", bid="23162", ask="23161",
            depth_buy=1000, depth_sell=1000, sequence=2,
        ),
    )
    with pytest.raises(MarketConfirmationError, match="crossed"):
        build_market_confirmation(spot, vix, crossed, NOW)
