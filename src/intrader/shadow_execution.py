"""Execution adapters for Shadow Trader research.

The proxy adapter is available now. The option-premium adapter boundary is
defined so Upstox/another expired-option source can be attached without
rewriting the causal engine. It intentionally raises until complete timestamped
premium data is supplied.
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
    ) -> ExecutionResult:
        ...


class ProxyExecutionAdapter:
    """Directional NIFTY proxy execution used until option premiums exist."""

    mode = "PROXY"

    def evaluate(
        self,
        *,
        entry_price: Decimal,
        exit_price: Decimal,
        direction: int,
        allocated_capital: Decimal,
        friction_bps: Decimal,
    ) -> ExecutionResult:
        if entry_price <= 0 or exit_price <= 0:
            raise ShadowExecutionError("proxy execution price invalid")
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
    """Reserved boundary for exact CE/PE historical fills.

    This adapter is intentionally unavailable until a provider supplies complete
    timestamped option premiums (and preferably bid/ask) for the replay window.
    """

    mode = "OPTION_PREMIUM"

    def evaluate(self, **_kwargs) -> ExecutionResult:
        raise ShadowExecutionError(
            "exact historical option-premium execution requires complete "
            "timestamped expired-option prices; no synthetic premium is allowed"
        )


def execution_adapter(mode: str) -> ExecutionAdapter:
    normalized = str(mode).strip().upper()
    if normalized == "PROXY":
        return ProxyExecutionAdapter()
    if normalized == "OPTION_PREMIUM":
        return HistoricalOptionExecutionAdapter()
    raise ShadowExecutionError(f"unsupported Shadow execution mode: {mode}")
