"""Versioned, execution-free option shadow trades for Intrader Phase 3."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
import hashlib
from typing import Mapping

from intrader.options_intelligence import OptionChainSnapshot, OptionContractMetrics
from intrader.records import DecisionRecord


SHADOW_VERSION = "shadow-v0.1"
DEFAULT_STOP_PCT = Decimal("0.20")
DEFAULT_TARGET_PCT = Decimal("0.30")
DEFAULT_MAX_MINUTES = 30


class ShadowTradeError(Exception):
    """A safe deterministic shadow trade cannot be created."""


@dataclass(frozen=True, slots=True)
class ShadowTrade:
    trade_id: str
    decision_id: str
    shadow_version: str
    opened_at: datetime
    action: str
    token: str
    strike: Decimal
    option_type: str
    entry_price: Decimal
    quantity: int
    lot_size: int
    lots: int
    stop_price: Decimal
    target_price: Decimal
    max_minutes: int


def _money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def select_shadow_contract(
    decision: DecisionRecord,
    options: OptionChainSnapshot,
) -> OptionContractMetrics | None:
    """Select the deterministic nearest-ATM contract for an actionable thesis."""

    option_type = (
        "CE" if decision.action == "BUY_CALL"
        else "PE" if decision.action == "BUY_PUT"
        else None
    )
    if option_type is None:
        return None

    candidates = [
        contract for contract in options.contracts
        if contract.option_type == option_type
    ]
    if not candidates:
        raise ShadowTradeError("shadow option side unavailable")

    return min(
        candidates,
        key=lambda contract: (
            abs(contract.strike - decision.spot_price),
            contract.strike,
            contract.token,
        ),
    )


def _trade_id(decision_id: str, token: str) -> str:
    digest = hashlib.sha256(
        f"{decision_id}|{SHADOW_VERSION}|{token}".encode("utf-8")
    ).hexdigest()[:16]
    return f"SHD-{digest}"


def build_shadow_trade(
    decision: DecisionRecord,
    options: OptionChainSnapshot,
    lot_sizes: Mapping[str, int],
    *,
    lots: int = 1,
    stop_pct: Decimal = DEFAULT_STOP_PCT,
    target_pct: Decimal = DEFAULT_TARGET_PCT,
    max_minutes: int = DEFAULT_MAX_MINUTES,
) -> ShadowTrade | None:
    """Build an immutable simulated position; never calls a broker."""

    if lots <= 0 or max_minutes <= 0:
        raise ShadowTradeError("shadow trade configuration invalid")
    if stop_pct <= 0 or stop_pct >= 1 or target_pct <= 0:
        raise ShadowTradeError("shadow risk configuration invalid")
    if decision.decided_at.tzinfo is None:
        raise ShadowTradeError("shadow decision timestamp invalid")

    contract = select_shadow_contract(decision, options)
    if contract is None:
        return None

    lot_size = lot_sizes.get(contract.token)
    if lot_size is None or lot_size <= 0:
        raise ShadowTradeError("shadow lot size unavailable")
    if contract.current_ltp <= 0:
        raise ShadowTradeError("shadow entry price invalid")

    entry = _money(contract.current_ltp)
    stop = _money(entry * (Decimal(1) - stop_pct))
    target = _money(entry * (Decimal(1) + target_pct))

    return ShadowTrade(
        trade_id=_trade_id(decision.decision_id, contract.token),
        decision_id=decision.decision_id,
        shadow_version=SHADOW_VERSION,
        opened_at=decision.decided_at,
        action=decision.action,
        token=contract.token,
        strike=contract.strike,
        option_type=contract.option_type,
        entry_price=entry,
        quantity=lot_size * lots,
        lot_size=lot_size,
        lots=lots,
        stop_price=stop,
        target_price=target,
        max_minutes=max_minutes,
    )
