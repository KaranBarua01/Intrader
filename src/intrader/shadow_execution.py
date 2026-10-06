"""Execution adapters for Shadow Trader research.

PROXY evaluates directional NIFTY movement. OPTION_PREMIUM evaluates a long
historical CE/PE premium using real entry/exit prices and discrete contract lots.
Neither adapter can place broker orders.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol


D = Decimal


class ShadowExecutionError(Exception):
    """Historical execution cannot be represented honestly."""


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    gross_return_pct: Decimal
    net_return_pct: Decimal
    paper_pnl: Decimal
    quantity: int | None = None
    capital_used: Decimal | None = None


class ExecutionAdapter(Protocol):
    mode: str

    def evaluate(
        self,
        *,
        entry_price: Decimal,
        exit_price: Decimal,
        direction: int,
        allocated_capital: Decimal,
        friction_bps: Decimal,
        lot_size: int | None = None,
    ) -> ExecutionResult:
        ...


class ProxyExecutionAdapter:
    """Directional NIFTY proxy execution."""

    mode = "PROXY"

    def evaluate(
        self,
        *,
        entry_price: Decimal,
        exit_price: Decimal,
        direction: int,
        allocated_capital: Decimal,
        friction_bps: Decimal,
        lot_size: int | None = None,
    ) -> ExecutionResult:
        del lot_size
        if entry_price <= 0 or exit_price <= 0:
            raise ShadowExecutionError("proxy execution price invalid")
        if direction not in {-1, 1}:
            raise ShadowExecutionError("proxy execution direction invalid")
        gross = (
            (exit_price - entry_price)
            / entry_price
            * D(100)
            * D(direction)
        )
        net = gross - friction_bps / D(100)
        return ExecutionResult(
            gross_return_pct=gross,
            net_return_pct=net,
            paper_pnl=allocated_capital * net / D(100),
        )


class HistoricalOptionExecutionAdapter:
    """Long CE/PE execution from real historical option premium candles."""

    mode = "OPTION_PREMIUM"

    def evaluate(
        self,
        *,
        entry_price: Decimal,
        exit_price: Decimal,
        direction: int,
        allocated_capital: Decimal,
        friction_bps: Decimal,
        lot_size: int | None = None,
    ) -> ExecutionResult:
        if entry_price <= 0 or exit_price <= 0:
            raise ShadowExecutionError("historical option premium invalid")
        if direction not in {-1, 1}:
            raise ShadowExecutionError("historical option direction invalid")
        if lot_size is None or int(lot_size) <= 0:
            raise ShadowExecutionError("historical option lot size unavailable")
        if allocated_capital <= 0:
            raise ShadowExecutionError("allocated capital invalid")

        lot = int(lot_size)
        lot_cost = entry_price * D(lot)
        lots = int(allocated_capital // lot_cost)
        if lots < 1:
            raise ShadowExecutionError(
                "allocated capital cannot fund one historical option lot"
            )
        quantity = lots * lot
        capital_used = entry_price * D(quantity)

        gross = (exit_price - entry_price) / entry_price * D(100)
        net = gross - friction_bps / D(100)
        return ExecutionResult(
            gross_return_pct=gross,
            net_return_pct=net,
            paper_pnl=capital_used * net / D(100),
            quantity=quantity,
            capital_used=capital_used,
        )


def execution_adapter(mode: str) -> ExecutionAdapter:
    normalized = str(mode).strip().upper()
    if normalized == "PROXY":
        return ProxyExecutionAdapter()
    if normalized == "OPTION_PREMIUM":
        return HistoricalOptionExecutionAdapter()
    raise ShadowExecutionError(f"unsupported Shadow execution mode: {mode}")
