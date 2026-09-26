"""Settle immutable shadow trades from locally stored market observations."""

from dataclasses import dataclass
from datetime import datetime, timedelta

from intrader.instruments import NiftyInstruments
from intrader.outcomes import OutcomeError, OutcomePending, ShadowOutcome, evaluate_shadow_trade
from intrader.storage import SQLiteStore, StorageError


class OutcomePipelineError(Exception):
    """A stored shadow trade cannot be settled safely."""


class OutcomePipelinePending(OutcomePipelineError):
    """The trade is not yet ready for terminal settlement."""


@dataclass(frozen=True, slots=True)
class SettleShadowResult:
    outcome: ShadowOutcome
    inserted: bool


def settle_shadow_trade(
    store: SQLiteStore,
    instruments: NiftyInstruments,
    trade_id: str,
    as_of: datetime,
) -> SettleShadowResult:
    """Settle one trade once; repeated calls return the immutable outcome."""

    if as_of.tzinfo is None:
        raise OutcomePipelineError("settlement timestamp must be timezone aware")

    try:
        existing = store.load_shadow_outcome(trade_id)
        if existing is not None:
            return SettleShadowResult(existing, False)

        trade = store.load_shadow_trade(trade_id)
        if trade is None:
            raise OutcomePipelineError("shadow trade unavailable")
        decision = store.load_decision_record(trade.decision_id)
        if decision is None:
            raise OutcomePipelineError("shadow decision unavailable")

        timeout_at = trade.opened_at + timedelta(minutes=trade.max_minutes)
        end = min(as_of, timeout_at)
        option_rows = store.load_option_snapshots(
            start=trade.opened_at,
            end=end,
        )
        spot_rows = store.load_index_snapshots(
            instruments.spot.token,
            start=trade.opened_at,
            end=end,
        )
        outcome = evaluate_shadow_trade(
            trade,
            option_rows,
            spot_rows,
            decision.spot_price,
            as_of,
        )
        inserted = store.store_shadow_outcome(outcome)
        if not inserted:
            persisted = store.load_shadow_outcome(trade_id)
            if persisted is not None:
                outcome = persisted
        return SettleShadowResult(outcome, inserted)
    except OutcomePending as exc:
        raise OutcomePipelinePending(str(exc)) from None
    except OutcomePipelineError:
        raise
    except (OutcomeError, StorageError, Exception):
        raise OutcomePipelineError("shadow settlement unavailable") from None
