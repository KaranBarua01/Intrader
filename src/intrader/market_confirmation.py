"""Pure futures, VIX and order-flow measurements for Intrader Phase 2."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Sequence

from intrader.options_intelligence import classify_buildup


class MarketConfirmationError(Exception):
    """Confirmation inputs are stale, incomplete, or inconsistent."""


@dataclass(frozen=True, slots=True)
class IndexSnapshot:
    token: str
    exchange_at: datetime
    received_at: datetime
    sequence: int
    ltp: Decimal


@dataclass(frozen=True, slots=True)
class FutureSnapshot:
    token: str
    exchange_at: datetime
    received_at: datetime
    sequence: int
    ltp: Decimal
    open_interest: int
    volume: int
    total_buy_quantity: Decimal
    total_sell_quantity: Decimal
    best_bid_price: Decimal | None
    best_bid_quantity: int
    best_ask_price: Decimal | None
    best_ask_quantity: int
    depth_buy_quantity: int
    depth_sell_quantity: int


@dataclass(frozen=True, slots=True)
class FuturesConfirmation:
    ltp: Decimal
    ltp_change: Decimal
    open_interest: int
    open_interest_change: int
    volume: int
    volume_change: int
    buildup: str
    basis: Decimal
    basis_change: Decimal


@dataclass(frozen=True, slots=True)
class VixConfirmation:
    value: Decimal
    change: Decimal
    change_pct: Decimal | None


@dataclass(frozen=True, slots=True)
class OrderFlowConfirmation:
    total_buy_sell_ratio: Decimal | None
    depth_buy_sell_ratio: Decimal | None
    depth_imbalance: Decimal | None
    best_bid: Decimal | None
    best_ask: Decimal | None
    spread: Decimal | None
    spread_bps: Decimal | None


@dataclass(frozen=True, slots=True)
class MarketConfirmationSnapshot:
    at: datetime
    lookback_minutes: int
    futures: FuturesConfirmation
    vix: VixConfirmation
    order_flow: OrderFlowConfirmation


def _validate_index(history: Sequence[IndexSnapshot]) -> None:
    if not history:
        raise MarketConfirmationError("index history unavailable")
    previous: IndexSnapshot | None = None
    for snapshot in history:
        if not snapshot.token or snapshot.exchange_at.tzinfo is None:
            raise MarketConfirmationError("index snapshot invalid")
        if snapshot.received_at.tzinfo is None or snapshot.sequence < 0:
            raise MarketConfirmationError("index snapshot invalid")
        if snapshot.ltp <= 0 or not snapshot.ltp.is_finite():
            raise MarketConfirmationError("index snapshot invalid")
        if previous is not None:
            if snapshot.token != previous.token:
                raise MarketConfirmationError("mixed index token history")
            if snapshot.exchange_at < previous.exchange_at:
                raise MarketConfirmationError("index history not ordered")
        previous = snapshot


def _validate_future(history: Sequence[FutureSnapshot]) -> None:
    if not history:
        raise MarketConfirmationError("future history unavailable")
    previous: FutureSnapshot | None = None
    for snapshot in history:
        if not snapshot.token or snapshot.exchange_at.tzinfo is None:
            raise MarketConfirmationError("future snapshot invalid")
        if snapshot.received_at.tzinfo is None or snapshot.sequence < 0:
            raise MarketConfirmationError("future snapshot invalid")
        if snapshot.ltp <= 0 or not snapshot.ltp.is_finite():
            raise MarketConfirmationError("future snapshot invalid")
        if snapshot.open_interest < 0 or snapshot.volume < 0:
            raise MarketConfirmationError("future snapshot invalid")
        if (
            snapshot.total_buy_quantity < 0
            or snapshot.total_sell_quantity < 0
            or snapshot.best_bid_quantity < 0
            or snapshot.best_ask_quantity < 0
            or snapshot.depth_buy_quantity < 0
            or snapshot.depth_sell_quantity < 0
        ):
            raise MarketConfirmationError("future snapshot invalid")
        if previous is not None:
            if snapshot.token != previous.token:
                raise MarketConfirmationError("mixed future token history")
            if snapshot.exchange_at < previous.exchange_at:
                raise MarketConfirmationError("future history not ordered")
        previous = snapshot


def _select_pair(history, at: datetime, target: datetime, current_age: float, baseline_age: float):
    current_candidates = [row for row in history if row.exchange_at <= at]
    baseline_candidates = [row for row in history if row.exchange_at <= target]
    if not current_candidates or not baseline_candidates:
        raise MarketConfirmationError("confirmation lookback unavailable")
    current = current_candidates[-1]
    baseline = baseline_candidates[-1]
    if (at - current.exchange_at).total_seconds() > current_age:
        raise MarketConfirmationError("confirmation current snapshot stale")
    if (target - baseline.exchange_at).total_seconds() > baseline_age:
        raise MarketConfirmationError("confirmation lookback stale")
    return current, baseline


def _ratio(numerator: Decimal | int, denominator: Decimal | int) -> Decimal | None:
    den = Decimal(denominator)
    if den == 0:
        return None
    return Decimal(numerator) / den


def _pct(current: Decimal, previous: Decimal) -> Decimal | None:
    if previous == 0:
        return None
    return ((current - previous) / previous) * Decimal(100)


def build_market_confirmation(
    spot_history: Sequence[IndexSnapshot],
    vix_history: Sequence[IndexSnapshot],
    future_history: Sequence[FutureSnapshot],
    at: datetime,
    *,
    lookback_minutes: int = 5,
    current_max_age_seconds: float = 10.0,
    baseline_max_age_seconds: float = 30.0,
) -> MarketConfirmationSnapshot:
    """Build independent futures, VIX and order-flow measurements."""

    if at.tzinfo is None or lookback_minutes <= 0:
        raise MarketConfirmationError("confirmation time invalid")
    _validate_index(spot_history)
    _validate_index(vix_history)
    _validate_future(future_history)

    target = at - timedelta(minutes=lookback_minutes)
    spot, spot_base = _select_pair(
        spot_history, at, target, current_max_age_seconds, baseline_max_age_seconds
    )
    vix, vix_base = _select_pair(
        vix_history, at, target, current_max_age_seconds, baseline_max_age_seconds
    )
    future, future_base = _select_pair(
        future_history, at, target, current_max_age_seconds, baseline_max_age_seconds
    )

    if future_base.volume > future.volume:
        raise MarketConfirmationError("future volume reset detected")

    ltp_change = future.ltp - future_base.ltp
    oi_change = future.open_interest - future_base.open_interest
    basis = future.ltp - spot.ltp
    baseline_basis = future_base.ltp - spot_base.ltp

    total_ratio = _ratio(
        future.total_buy_quantity,
        future.total_sell_quantity,
    )
    depth_ratio = _ratio(
        future.depth_buy_quantity,
        future.depth_sell_quantity,
    )
    depth_total = future.depth_buy_quantity + future.depth_sell_quantity
    depth_imbalance = (
        None
        if depth_total == 0
        else Decimal(
            future.depth_buy_quantity - future.depth_sell_quantity
        ) / Decimal(depth_total)
    )

    spread = None
    spread_bps = None
    if future.best_bid_price is not None and future.best_ask_price is not None:
        spread = future.best_ask_price - future.best_bid_price
        if spread < 0:
            raise MarketConfirmationError("crossed future order book")
        mid = (future.best_ask_price + future.best_bid_price) / Decimal(2)
        if mid > 0:
            spread_bps = (spread / mid) * Decimal(10000)

    return MarketConfirmationSnapshot(
        at=at,
        lookback_minutes=lookback_minutes,
        futures=FuturesConfirmation(
            ltp=future.ltp,
            ltp_change=ltp_change,
            open_interest=future.open_interest,
            open_interest_change=oi_change,
            volume=future.volume,
            volume_change=future.volume - future_base.volume,
            buildup=classify_buildup(ltp_change, oi_change),
            basis=basis,
            basis_change=basis - baseline_basis,
        ),
        vix=VixConfirmation(
            value=vix.ltp,
            change=vix.ltp - vix_base.ltp,
            change_pct=_pct(vix.ltp, vix_base.ltp),
        ),
        order_flow=OrderFlowConfirmation(
            total_buy_sell_ratio=total_ratio,
            depth_buy_sell_ratio=depth_ratio,
            depth_imbalance=depth_imbalance,
            best_bid=future.best_bid_price,
            best_ask=future.best_ask_price,
            spread=spread,
            spread_bps=spread_bps,
        ),
    )
