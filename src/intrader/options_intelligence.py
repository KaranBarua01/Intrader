"""Deterministic NIFTY option-chain measurements for Intrader Phase 2."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Mapping, Sequence


class OptionsIntelligenceError(Exception):
    """Option-chain inputs are incomplete, stale, or internally inconsistent."""


@dataclass(frozen=True, slots=True)
class OptionSnapshot:
    token: str
    exchange_at: datetime
    received_at: datetime
    sequence: int
    expiry: date
    strike: Decimal
    option_type: str
    ltp: Decimal
    open_interest: int
    volume: int


@dataclass(frozen=True, slots=True)
class OptionContractMetrics:
    token: str
    strike: Decimal
    option_type: str
    current_ltp: Decimal
    ltp_change: Decimal
    ltp_change_pct: Decimal | None
    current_open_interest: int
    open_interest_change: int
    open_interest_change_pct: Decimal | None
    current_volume: int
    volume_change: int
    buildup: str


@dataclass(frozen=True, slots=True)
class OptionChainSnapshot:
    at: datetime
    lookback_minutes: int
    contracts: tuple[OptionContractMetrics, ...]
    total_call_open_interest: int
    total_put_open_interest: int
    open_interest_pcr: Decimal | None
    total_call_volume: int
    total_put_volume: int
    volume_pcr: Decimal | None
    max_call_open_interest_strike: Decimal
    max_put_open_interest_strike: Decimal
    max_call_open_interest_change_strike: Decimal | None
    max_put_open_interest_change_strike: Decimal | None
    call_open_interest_concentration: Decimal | None
    put_open_interest_concentration: Decimal | None


def _validate_snapshot(snapshot: OptionSnapshot) -> None:
    if not snapshot.token:
        raise OptionsIntelligenceError("option token unavailable")
    if snapshot.exchange_at.tzinfo is None or snapshot.received_at.tzinfo is None:
        raise OptionsIntelligenceError("option timestamp must be timezone aware")
    if snapshot.sequence < 0:
        raise OptionsIntelligenceError("option sequence invalid")
    if snapshot.option_type not in {"CE", "PE"}:
        raise OptionsIntelligenceError("option type invalid")
    if snapshot.strike <= 0 or not snapshot.strike.is_finite():
        raise OptionsIntelligenceError("option strike invalid")
    if snapshot.ltp <= 0 or not snapshot.ltp.is_finite():
        raise OptionsIntelligenceError("option LTP invalid")
    if snapshot.open_interest < 0 or snapshot.volume < 0:
        raise OptionsIntelligenceError("option OI/volume invalid")


def _validate_history(history: Sequence[OptionSnapshot]) -> None:
    if not history:
        raise OptionsIntelligenceError("option history unavailable")
    previous: OptionSnapshot | None = None
    for snapshot in history:
        _validate_snapshot(snapshot)
        if previous is not None:
            if snapshot.token != previous.token:
                raise OptionsIntelligenceError("mixed option token history")
            if snapshot.exchange_at < previous.exchange_at:
                raise OptionsIntelligenceError("option history not ordered")
            if (
                snapshot.exchange_at == previous.exchange_at
                and snapshot.sequence <= previous.sequence
            ):
                raise OptionsIntelligenceError("duplicate option sequence")
            if (
                snapshot.expiry != previous.expiry
                or snapshot.strike != previous.strike
                or snapshot.option_type != previous.option_type
            ):
                raise OptionsIntelligenceError("option contract metadata changed")
        previous = snapshot


def classify_buildup(
    ltp_change: Decimal,
    open_interest_change: int,
) -> str:
    """Return the classic price/OI buildup label for one option contract."""

    if ltp_change > 0 and open_interest_change > 0:
        return "LONG_BUILDUP"
    if ltp_change < 0 and open_interest_change > 0:
        return "SHORT_BUILDUP"
    if ltp_change > 0 and open_interest_change < 0:
        return "SHORT_COVERING"
    if ltp_change < 0 and open_interest_change < 0:
        return "LONG_UNWINDING"
    return "NEUTRAL"


def _percent_change(current: Decimal, previous: Decimal) -> Decimal | None:
    if previous == 0:
        return None
    return ((current - previous) / previous) * Decimal(100)


def _percent_change_int(current: int, previous: int) -> Decimal | None:
    if previous == 0:
        return None
    return (
        Decimal(current - previous) / Decimal(previous)
    ) * Decimal(100)


def _select_pair(
    history: Sequence[OptionSnapshot],
    at: datetime,
    baseline_target: datetime,
    *,
    current_max_age_seconds: float,
    baseline_max_age_seconds: float,
) -> tuple[OptionSnapshot, OptionSnapshot]:
    _validate_history(history)

    eligible_current = [
        snapshot for snapshot in history if snapshot.exchange_at <= at
    ]
    if not eligible_current:
        raise OptionsIntelligenceError("current option snapshot unavailable")
    current = eligible_current[-1]
    current_age = (at - current.exchange_at).total_seconds()
    if current_age < -2 or current_age > current_max_age_seconds:
        raise OptionsIntelligenceError("current option snapshot stale")

    eligible_baseline = [
        snapshot
        for snapshot in history
        if snapshot.exchange_at <= baseline_target
    ]
    if not eligible_baseline:
        raise OptionsIntelligenceError("option lookback unavailable")
    baseline = eligible_baseline[-1]
    baseline_age = (baseline_target - baseline.exchange_at).total_seconds()
    if baseline_age < -2 or baseline_age > baseline_max_age_seconds:
        raise OptionsIntelligenceError("option lookback stale")
    if baseline.expiry != current.expiry:
        raise OptionsIntelligenceError("option expiry changed")
    if baseline.volume > current.volume:
        raise OptionsIntelligenceError("option volume reset detected")

    return current, baseline


def _contract_metrics(
    current: OptionSnapshot,
    baseline: OptionSnapshot,
) -> OptionContractMetrics:
    ltp_change = current.ltp - baseline.ltp
    oi_change = current.open_interest - baseline.open_interest
    volume_change = current.volume - baseline.volume
    if volume_change < 0:
        raise OptionsIntelligenceError("option volume change invalid")

    return OptionContractMetrics(
        token=current.token,
        strike=current.strike,
        option_type=current.option_type,
        current_ltp=current.ltp,
        ltp_change=ltp_change,
        ltp_change_pct=_percent_change(current.ltp, baseline.ltp),
        current_open_interest=current.open_interest,
        open_interest_change=oi_change,
        open_interest_change_pct=_percent_change_int(
            current.open_interest,
            baseline.open_interest,
        ),
        current_volume=current.volume,
        volume_change=volume_change,
        buildup=classify_buildup(ltp_change, oi_change),
    )


def _ratio(numerator: int, denominator: int) -> Decimal | None:
    if denominator == 0:
        return None
    return Decimal(numerator) / Decimal(denominator)


def _max_oi_contract(
    contracts: Sequence[OptionContractMetrics],
) -> OptionContractMetrics:
    if not contracts:
        raise OptionsIntelligenceError("option side unavailable")
    return max(
        contracts,
        key=lambda contract: (
            contract.current_open_interest,
            -contract.strike,
        ),
    )


def _max_positive_oi_change_strike(
    contracts: Sequence[OptionContractMetrics],
) -> Decimal | None:
    positive = [
        contract
        for contract in contracts
        if contract.open_interest_change > 0
    ]
    if not positive:
        return None
    return max(
        positive,
        key=lambda contract: (
            contract.open_interest_change,
            -contract.strike,
        ),
    ).strike


def build_options_intelligence(
    histories: Mapping[str, Sequence[OptionSnapshot]],
    at: datetime,
    *,
    expected_tokens: Sequence[str],
    lookback_minutes: int = 5,
    current_max_age_seconds: float = 10.0,
    baseline_max_age_seconds: float = 30.0,
) -> OptionChainSnapshot:
    """Build raw chain measurements from complete resolved option histories."""

    if at.tzinfo is None:
        raise OptionsIntelligenceError("analysis timestamp must be timezone aware")
    if lookback_minutes <= 0:
        raise OptionsIntelligenceError("option lookback invalid")
    if current_max_age_seconds <= 0 or baseline_max_age_seconds <= 0:
        raise OptionsIntelligenceError("option freshness limit invalid")

    expected = tuple(expected_tokens)
    if not expected or len(set(expected)) != len(expected):
        raise OptionsIntelligenceError("expected option tokens invalid")

    baseline_target = at - timedelta(minutes=lookback_minutes)
    metrics: list[OptionContractMetrics] = []
    expiry: date | None = None

    for token in expected:
        history = histories.get(token)
        if history is None:
            raise OptionsIntelligenceError("option chain incomplete")
        current, baseline = _select_pair(
            history,
            at,
            baseline_target,
            current_max_age_seconds=current_max_age_seconds,
            baseline_max_age_seconds=baseline_max_age_seconds,
        )
        if current.token != token:
            raise OptionsIntelligenceError("option token mismatch")
        if expiry is None:
            expiry = current.expiry
        elif current.expiry != expiry:
            raise OptionsIntelligenceError("mixed option expiries")
        metrics.append(_contract_metrics(current, baseline))

    calls = [metric for metric in metrics if metric.option_type == "CE"]
    puts = [metric for metric in metrics if metric.option_type == "PE"]
    call_strikes = {metric.strike for metric in calls}
    put_strikes = {metric.strike for metric in puts}
    if not calls or not puts or call_strikes != put_strikes:
        raise OptionsIntelligenceError("option strike pairs incomplete")

    total_call_oi = sum(metric.current_open_interest for metric in calls)
    total_put_oi = sum(metric.current_open_interest for metric in puts)
    total_call_volume = sum(metric.current_volume for metric in calls)
    total_put_volume = sum(metric.current_volume for metric in puts)

    max_call = _max_oi_contract(calls)
    max_put = _max_oi_contract(puts)

    sorted_metrics = tuple(
        sorted(
            metrics,
            key=lambda metric: (
                metric.strike,
                0 if metric.option_type == "CE" else 1,
            ),
        )
    )

    return OptionChainSnapshot(
        at=at,
        lookback_minutes=lookback_minutes,
        contracts=sorted_metrics,
        total_call_open_interest=total_call_oi,
        total_put_open_interest=total_put_oi,
        open_interest_pcr=_ratio(total_put_oi, total_call_oi),
        total_call_volume=total_call_volume,
        total_put_volume=total_put_volume,
        volume_pcr=_ratio(total_put_volume, total_call_volume),
        max_call_open_interest_strike=max_call.strike,
        max_put_open_interest_strike=max_put.strike,
        max_call_open_interest_change_strike=_max_positive_oi_change_strike(
            calls
        ),
        max_put_open_interest_change_strike=_max_positive_oi_change_strike(
            puts
        ),
        call_open_interest_concentration=_ratio(
            max_call.current_open_interest,
            total_call_oi,
        ),
        put_open_interest_concentration=_ratio(
            max_put.current_open_interest,
            total_put_oi,
        ),
    )
