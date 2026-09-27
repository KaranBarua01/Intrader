"""Timestamp-causal historical Shadow Trader replay.

Version 1 is an Angel-One candle proxy. It deliberately avoids pretending that
expired option premiums exist when they are unavailable. The engine selects a
candle strategy on the development segment and evaluates the frozen choice on
the blind segment.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime
from decimal import Decimal
from typing import Sequence

from intrader.historical import Candle, INDIA_TIME
from intrader.shadow_lab import development_blind_split, replay_mode
from intrader.strategy_lab import (
    StrategyLabSnapshot,
    StrategyPerformance,
    analyze_strategies,
)


D = Decimal


@dataclass(frozen=True, slots=True)
class ReplayMetrics:
    sessions: int
    signals: int
    evaluable_signals: int
    wins: int
    losses: int
    flats: int
    win_rate_pct: Decimal | None
    average_return_30m_pct: Decimal | None
    total_signed_return_30m_pct: Decimal
    average_mfe_30m_pct: Decimal | None
    average_mae_30m_pct: Decimal | None


@dataclass(frozen=True, slots=True)
class ReplayCandidate:
    strategy_id: str
    strategy_name: str
    signals: int
    hit_rate_30m_pct: Decimal | None
    average_return_30m_pct: Decimal | None
    sample_label: str


@dataclass(frozen=True, slots=True)
class ShadowReplayReport:
    schema: str
    mode: str
    requested_touchpoints: int
    requested_sessions: int
    actual_sessions: int
    development_sessions: int
    blind_sessions: int
    selected_strategy_id: str | None
    selected_strategy_name: str | None
    development: ReplayMetrics
    blind: ReplayMetrics
    candidates: tuple[ReplayCandidate, ...]
    first_session: str | None
    last_session: str | None
    notes: tuple[str, ...]


def _average(values: Sequence[Decimal]) -> Decimal | None:
    if not values:
        return None
    return sum(values, D(0)) / D(len(values))


def _metrics(performance: StrategyPerformance | None, sessions: int) -> ReplayMetrics:
    if performance is None:
        return ReplayMetrics(
            sessions=sessions,
            signals=0,
            evaluable_signals=0,
            wins=0,
            losses=0,
            flats=0,
            win_rate_pct=None,
            average_return_30m_pct=None,
            total_signed_return_30m_pct=D(0),
            average_mfe_30m_pct=None,
            average_mae_30m_pct=None,
        )

    returns = [
        item.return_30m for item in performance.occurrences
        if item.return_30m is not None
    ]
    mfes = [
        item.mfe_30m for item in performance.occurrences
        if item.mfe_30m is not None
    ]
    maes = [
        item.mae_30m for item in performance.occurrences
        if item.mae_30m is not None
    ]
    wins = sum(1 for value in returns if value > 0)
    losses = sum(1 for value in returns if value < 0)
    flats = sum(1 for value in returns if value == 0)
    return ReplayMetrics(
        sessions=sessions,
        signals=performance.signals,
        evaluable_signals=len(returns),
        wins=wins,
        losses=losses,
        flats=flats,
        win_rate_pct=(
            None
            if not returns
            else D(wins) / D(len(returns)) * D(100)
        ),
        average_return_30m_pct=_average(returns),
        total_signed_return_30m_pct=sum(returns, D(0)),
        average_mfe_30m_pct=_average(mfes),
        average_mae_30m_pct=_average(maes),
    )


def _candidate(performance: StrategyPerformance) -> ReplayCandidate:
    return ReplayCandidate(
        strategy_id=performance.definition.strategy_id,
        strategy_name=performance.definition.name,
        signals=performance.signals,
        hit_rate_30m_pct=performance.hit_rate_30m,
        average_return_30m_pct=performance.avg_return_30m,
        sample_label=performance.sample_label,
    )


def _pick_strategy(
    snapshot: StrategyLabSnapshot,
    development_sessions: int,
) -> StrategyPerformance | None:
    minimum_signals = max(5, development_sessions // 4)
    eligible = [
        item
        for item in snapshot.strategies
        if item.definition.direction_scope != "PROCESS"
        and item.avg_return_30m is not None
        and item.signals >= minimum_signals
    ]
    if not eligible:
        eligible = [
            item
            for item in snapshot.strategies
            if item.definition.direction_scope != "PROCESS"
            and item.avg_return_30m is not None
            and item.signals > 0
        ]
    if not eligible:
        return None
    return max(
        eligible,
        key=lambda item: (
            item.avg_return_30m,
            item.hit_rate_30m if item.hit_rate_30m is not None else D("-999"),
            item.signals,
            item.definition.strategy_id,
        ),
    )


def _performance_by_id(
    snapshot: StrategyLabSnapshot,
    strategy_id: str | None,
) -> StrategyPerformance | None:
    if strategy_id is None:
        return None
    for item in snapshot.strategies:
        if item.definition.strategy_id == strategy_id:
            return item
    return None


def _slice_sessions(
    candles: Sequence[Candle],
    requested_sessions: int,
) -> tuple[tuple[Candle, ...], tuple]:
    ordered = tuple(sorted(candles, key=lambda candle: candle.at))
    dates = sorted({
        candle.at.astimezone(INDIA_TIME).date()
        for candle in ordered
    })
    selected_dates = dates[-requested_sessions:]
    selected_set = set(selected_dates)
    selected = tuple(
        candle
        for candle in ordered
        if candle.at.astimezone(INDIA_TIME).date() in selected_set
    )
    return selected, tuple(selected_dates)


def run_candle_proxy_replay(
    candles: Sequence[Candle],
    *,
    sessions: int,
    mode_key: str,
) -> ShadowReplayReport:
    """Run a development/blind replay without future leakage.

    Strategy rules only consume current/past candles. Forward returns are used
    exclusively by the evaluator after a signal has been generated.
    """

    mode = replay_mode(mode_key)
    development_target, blind_target = development_blind_split(sessions)
    selected, dates = _slice_sessions(candles, sessions)
    actual_sessions = len(dates)
    if actual_sessions < sessions:
        raise ValueError(
            f"only {actual_sessions} complete historical sessions are available; "
            f"{sessions} were requested"
        )

    development_dates = dates[:development_target]
    blind_dates = dates[development_target:]
    if len(blind_dates) != blind_target:
        raise ValueError("historical replay split unavailable")

    development_set = set(development_dates)
    blind_set = set(blind_dates)
    development_candles = tuple(
        candle for candle in selected
        if candle.at.astimezone(INDIA_TIME).date() in development_set
    )
    blind_candles = tuple(
        candle for candle in selected
        if candle.at.astimezone(INDIA_TIME).date() in blind_set
    )
    if not development_candles or not blind_candles:
        raise ValueError("historical replay candles unavailable")

    development_snapshot = analyze_strategies(
        development_candles,
        (),
        development_candles[0].at,
        development_candles[-1].at,
    )
    selected_strategy = _pick_strategy(
        development_snapshot,
        development_target,
    )

    blind_snapshot = analyze_strategies(
        blind_candles,
        (),
        blind_candles[0].at,
        blind_candles[-1].at,
    )
    strategy_id = (
        None
        if selected_strategy is None
        else selected_strategy.definition.strategy_id
    )
    blind_performance = _performance_by_id(blind_snapshot, strategy_id)

    candidates = tuple(
        _candidate(item)
        for item in development_snapshot.strategies
        if item.definition.direction_scope != "PROCESS"
    )

    return ShadowReplayReport(
        schema="intrader-shadow-replay-v1-candle-proxy",
        mode=mode.key,
        requested_touchpoints=mode.feature_count,
        requested_sessions=sessions,
        actual_sessions=actual_sessions,
        development_sessions=development_target,
        blind_sessions=blind_target,
        selected_strategy_id=strategy_id,
        selected_strategy_name=(
            None
            if selected_strategy is None
            else selected_strategy.definition.name
        ),
        development=_metrics(selected_strategy, development_target),
        blind=_metrics(blind_performance, blind_target),
        candidates=candidates,
        first_session=dates[0].isoformat() if dates else None,
        last_session=dates[-1].isoformat() if dates else None,
        notes=(
            "Version 1 is a NIFTY candle-direction proxy, not exact historical option P&L.",
            "The selected strategy is chosen only from the development segment and frozen for the blind segment.",
            "Forward 30-minute returns are evaluation outputs and are never available to the strategy at decision time.",
            "Replay mode records the requested touchpoint profile. Extra market families are added as their historical feeds are integrated.",
            "Expired NIFTY option premiums remain unavailable until a supported historical source is connected.",
        ),
    )
