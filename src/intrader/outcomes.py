"""Objective post-entry shadow outcomes for Intrader Phase 3."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import Sequence

from intrader.market_confirmation import IndexSnapshot
from intrader.options_intelligence import OptionSnapshot
from intrader.shadow import ShadowTrade


FRICTION_BPS_PER_SIDE = Decimal("5")
FORWARD_MINUTES = (1, 3, 5, 10, 15, 30)


class OutcomeError(Exception):
    """A shadow outcome cannot be evaluated safely."""


class OutcomePending(OutcomeError):
    """The trade is still open or lacks enough terminal data."""


@dataclass(frozen=True, slots=True)
class ShadowOutcome:
    trade_id: str
    evaluated_at: datetime
    exit_at: datetime
    exit_reason: str
    exit_price: Decimal
    gross_pnl: Decimal
    estimated_friction: Decimal
    adjusted_pnl: Decimal
    gross_return_pct: Decimal
    adjusted_return_pct: Decimal
    mfe_price: Decimal
    mae_price: Decimal
    mfe_amount: Decimal
    mae_amount: Decimal
    spot_exit: Decimal | None
    spot_change: Decimal | None
    directional_spot_change: Decimal | None
    forward_returns: tuple[tuple[int, Decimal | None], ...]


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _pct(change: Decimal, base: Decimal) -> Decimal:
    if base <= 0:
        raise OutcomeError("outcome base price invalid")
    return change / base * Decimal(100)


def _ordered_option_history(
    trade: ShadowTrade,
    snapshots: Sequence[OptionSnapshot],
    end: datetime,
) -> list[OptionSnapshot]:
    rows = [
        snapshot
        for snapshot in snapshots
        if snapshot.token == trade.token
        and trade.opened_at <= snapshot.exchange_at <= end
    ]
    rows.sort(key=lambda item: (item.exchange_at, item.sequence))
    if not rows:
        raise OutcomePending("shadow option history unavailable")
    return rows


def _forward_price(
    rows: Sequence[OptionSnapshot],
    target: datetime,
    *,
    tolerance_seconds: int = 30,
) -> Decimal | None:
    for row in rows:
        if row.exchange_at < target:
            continue
        if (row.exchange_at - target).total_seconds() <= tolerance_seconds:
            return row.ltp
        return None
    return None


def _spot_at_or_before(
    rows: Sequence[IndexSnapshot],
    at: datetime,
    *,
    max_age_seconds: int = 10,
) -> Decimal | None:
    candidates = [row for row in rows if row.exchange_at <= at]
    if not candidates:
        return None
    latest = max(candidates, key=lambda item: item.exchange_at)
    if (at - latest.exchange_at).total_seconds() > max_age_seconds:
        return None
    return latest.ltp


def evaluate_shadow_trade(
    trade: ShadowTrade,
    option_snapshots: Sequence[OptionSnapshot],
    spot_snapshots: Sequence[IndexSnapshot],
    spot_entry: Decimal,
    as_of: datetime,
) -> ShadowOutcome:
    """Evaluate a long-option shadow trade from stored observations only."""

    if as_of.tzinfo is None or trade.opened_at.tzinfo is None:
        raise OutcomeError("outcome timestamp must be timezone aware")
    if as_of < trade.opened_at:
        raise OutcomeError("outcome evaluation precedes entry")
    if spot_entry <= 0:
        raise OutcomeError("spot entry invalid")

    timeout_at = trade.opened_at + timedelta(minutes=trade.max_minutes)
    observation_end = min(as_of, timeout_at)
    rows = _ordered_option_history(trade, option_snapshots, observation_end)

    exit_row: OptionSnapshot | None = None
    exit_reason: str | None = None
    for row in rows:
        if row.ltp >= trade.target_price:
            exit_row = row
            exit_reason = "TARGET"
            break
        if row.ltp <= trade.stop_price:
            exit_row = row
            exit_reason = "STOP"
            break

    if exit_row is None:
        if as_of < timeout_at:
            raise OutcomePending("shadow trade still open")
        terminal = [row for row in rows if row.exchange_at <= timeout_at]
        if not terminal:
            raise OutcomePending("shadow timeout data unavailable")
        exit_row = terminal[-1]
        if (timeout_at - exit_row.exchange_at).total_seconds() > 30:
            raise OutcomePending("shadow timeout snapshot stale")
        exit_reason = "TIMEOUT"

    observed_to_exit = [row for row in rows if row.exchange_at <= exit_row.exchange_at]
    high = max(row.ltp for row in observed_to_exit)
    low = min(row.ltp for row in observed_to_exit)

    premium_change = exit_row.ltp - trade.entry_price
    gross_pnl = premium_change * Decimal(trade.quantity)
    turnover = (
        trade.entry_price + exit_row.ltp
    ) * Decimal(trade.quantity)
    friction = turnover * (FRICTION_BPS_PER_SIDE / Decimal(10000))
    adjusted_pnl = gross_pnl - friction

    forward: list[tuple[int, Decimal | None]] = []
    for minutes in FORWARD_MINUTES:
        price = _forward_price(
            rows,
            trade.opened_at + timedelta(minutes=minutes),
        )
        forward.append(
            (
                minutes,
                None
                if price is None
                else _pct(price - trade.entry_price, trade.entry_price),
            )
        )

    spot_exit = _spot_at_or_before(spot_snapshots, exit_row.exchange_at)
    spot_change = None if spot_exit is None else spot_exit - spot_entry
    directional_spot_change = (
        None
        if spot_change is None
        else spot_change
        if trade.action == "BUY_CALL"
        else -spot_change
    )

    return ShadowOutcome(
        trade_id=trade.trade_id,
        evaluated_at=as_of,
        exit_at=exit_row.exchange_at,
        exit_reason=exit_reason,
        exit_price=_money(exit_row.ltp),
        gross_pnl=_money(gross_pnl),
        estimated_friction=_money(friction),
        adjusted_pnl=_money(adjusted_pnl),
        gross_return_pct=_pct(premium_change, trade.entry_price),
        adjusted_return_pct=_pct(
            adjusted_pnl / Decimal(trade.quantity),
            trade.entry_price,
        ),
        mfe_price=_money(high - trade.entry_price),
        mae_price=_money(low - trade.entry_price),
        mfe_amount=_money((high - trade.entry_price) * Decimal(trade.quantity)),
        mae_amount=_money((low - trade.entry_price) * Decimal(trade.quantity)),
        spot_exit=spot_exit,
        spot_change=spot_change,
        directional_spot_change=directional_spot_change,
        forward_returns=tuple(forward),
    )
