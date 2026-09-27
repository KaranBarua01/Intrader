"""Timestamp-causal historical Shadow Trader replay.

Version 2 is an Angel-One NIFTY candle proxy. It deliberately avoids pretending
that expired option premiums exist when they are unavailable. The engine chooses
a strategy using only the development segment, freezes it, and then evaluates
that unchanged strategy on the blind segment.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Sequence

from intrader.historical import Candle, INDIA_TIME
from intrader.shadow_lab import development_blind_split, replay_mode
from intrader.strategy_lab import (
    StrategyLabSnapshot,
    StrategyOccurrence,
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
    average_winner_pct: Decimal | None
    average_loser_pct: Decimal | None
    profit_factor: Decimal | None
    max_drawdown_pct_points: Decimal
    max_winning_streak: int
    max_losing_streak: int
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
class ReplayTradeResult:
    phase: str
    at: str
    direction: str
    entry_underlying: Decimal
    approx_exit_underlying_30m: Decimal | None
    return_5m_pct: Decimal | None
    return_15m_pct: Decimal | None
    return_30m_pct: Decimal | None
    mfe_30m_pct: Decimal | None
    mae_30m_pct: Decimal | None
    result: str
    regime: str | None


@dataclass(frozen=True, slots=True)
class FrozenStrategySelection:
    strategy_id: str | None
    strategy_name: str | None
    development_sessions: int
    training_start: str | None
    training_end: str | None
    development: ReplayMetrics
    candidates: tuple[ReplayCandidate, ...]
    occurrences: tuple[StrategyOccurrence, ...]


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
    trades: tuple[ReplayTradeResult, ...]
    first_session: str | None
    last_session: str | None
    notes: tuple[str, ...]


def _average(values: Sequence[Decimal]) -> Decimal | None:
    if not values:
        return None
    return sum(values, D(0)) / D(len(values))


def _streaks(values: Sequence[Decimal]) -> tuple[int, int]:
    current_win = current_loss = 0
    max_win = max_loss = 0
    for value in values:
        if value > 0:
            current_win += 1
            current_loss = 0
            max_win = max(max_win, current_win)
        elif value < 0:
            current_loss += 1
            current_win = 0
            max_loss = max(max_loss, current_loss)
        else:
            current_win = current_loss = 0
    return max_win, max_loss


def _max_drawdown(values: Sequence[Decimal]) -> Decimal:
    cumulative = D(0)
    peak = D(0)
    max_drawdown = D(0)
    for value in values:
        cumulative += value
        peak = max(peak, cumulative)
        max_drawdown = max(max_drawdown, peak - cumulative)
    return max_drawdown


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
            average_winner_pct=None,
            average_loser_pct=None,
            profit_factor=None,
            max_drawdown_pct_points=D(0),
            max_winning_streak=0,
            max_losing_streak=0,
            average_mfe_30m_pct=None,
            average_mae_30m_pct=None,
        )

    returns = [
        item.return_30m
        for item in performance.occurrences
        if item.return_30m is not None
    ]
    mfes = [
        item.mfe_30m
        for item in performance.occurrences
        if item.mfe_30m is not None
    ]
    maes = [
        item.mae_30m
        for item in performance.occurrences
        if item.mae_30m is not None
    ]
    winning_returns = [value for value in returns if value > 0]
    losing_returns = [value for value in returns if value < 0]
    wins = len(winning_returns)
    losses = len(losing_returns)
    flats = sum(1 for value in returns if value == 0)
    gross_positive = sum(winning_returns, D(0))
    gross_negative = abs(sum(losing_returns, D(0)))
    max_win_streak, max_loss_streak = _streaks(returns)
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
        average_winner_pct=_average(winning_returns),
        average_loser_pct=_average(losing_returns),
        profit_factor=(
            None if gross_negative == 0 else gross_positive / gross_negative
        ),
        max_drawdown_pct_points=_max_drawdown(returns),
        max_winning_streak=max_win_streak,
        max_losing_streak=max_loss_streak,
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


def _selection_stats(
    performance: StrategyPerformance,
) -> tuple[int, Decimal, Decimal, Decimal]:
    """Return stability, profit factor, drawdown and average return for training only."""

    returns = [
        item.return_30m
        for item in performance.occurrences
        if item.return_30m is not None
    ]
    if not returns:
        return 0, D(0), D("999"), D("-999")

    positives = sum((value for value in returns if value > 0), D(0))
    negatives = abs(sum((value for value in returns if value < 0), D(0)))
    profit_factor = (
        D("999") if negatives == 0 and positives > 0
        else D(0) if negatives == 0
        else positives / negatives
    )

    cumulative = D(0)
    peak = D(0)
    max_drawdown = D(0)
    for value in returns:
        cumulative += value
        peak = max(peak, cumulative)
        max_drawdown = max(max_drawdown, peak - cumulative)

    # Require the training edge to appear across the sample instead of winning
    # only because of one cluster. These thirds use development outcomes only.
    segment_means: list[Decimal] = []
    for part in range(3):
        start = len(returns) * part // 3
        end = len(returns) * (part + 1) // 3
        segment = returns[start:end]
        if segment:
            segment_means.append(sum(segment, D(0)) / D(len(segment)))
    positive_segments = sum(1 for value in segment_means if value > 0)
    average = sum(returns, D(0)) / D(len(returns))
    return positive_segments, profit_factor, max_drawdown, average


def _pick_strategy(
    snapshot: StrategyLabSnapshot,
    development_sessions: int,
) -> StrategyPerformance | None:
    """Choose a development-only strategy with sample/stability protection."""

    minimum_signals = max(8, development_sessions // 4)
    scored: list[
        tuple[StrategyPerformance, int, Decimal, Decimal, Decimal]
    ] = []
    for item in snapshot.strategies:
        if (
            item.definition.direction_scope == "PROCESS"
            or item.avg_return_30m is None
            or item.signals < minimum_signals
        ):
            continue
        stability, profit_factor, drawdown, average = _selection_stats(item)
        if average <= 0:
            continue
        scored.append((item, stability, profit_factor, drawdown, average))

    # First preference: positive expectancy, PF > 1 and positive results in
    # at least two thirds of the development sample.
    robust = [
        row for row in scored
        if row[1] >= 2 and row[2] > 1
    ]
    pool = robust or scored
    if not pool:
        return None

    chosen = max(
        pool,
        key=lambda row: (
            row[1],
            row[4] / (D(1) + row[3]),
            row[2],
            row[0].signals,
            row[0].definition.strategy_id,
        ),
    )
    return chosen[0]


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


def _approx_exit(occurrence: StrategyOccurrence) -> Decimal | None:
    result = occurrence.return_30m
    if result is None:
        return None
    multiplier = (
        D(1) + result / D(100)
        if occurrence.direction > 0
        else D(1) - result / D(100)
    )
    return occurrence.entry_price * multiplier


def _trade(phase: str, occurrence: StrategyOccurrence) -> ReplayTradeResult:
    result = occurrence.return_30m
    outcome = (
        "UNEVALUATED"
        if result is None
        else "WIN"
        if result > 0
        else "LOSS"
        if result < 0
        else "FLAT"
    )
    return ReplayTradeResult(
        phase=phase,
        at=occurrence.at.astimezone(INDIA_TIME).isoformat(),
        direction="CALL / LONG" if occurrence.direction > 0 else "PUT / SHORT",
        entry_underlying=occurrence.entry_price,
        approx_exit_underlying_30m=_approx_exit(occurrence),
        return_5m_pct=occurrence.return_5m,
        return_15m_pct=occurrence.return_15m,
        return_30m_pct=occurrence.return_30m,
        mfe_30m_pct=occurrence.mfe_30m,
        mae_30m_pct=occurrence.mae_30m,
        result=outcome,
        regime=occurrence.regime,
    )


def train_frozen_strategy(
    development_candles: Sequence[Candle],
    *,
    development_sessions: int,
) -> FrozenStrategySelection:
    """Train/select one strategy using development candles only.

    No blind candles are accepted by this function. The returned selection can
    be serialized/frozen and then handed to a causal streaming engine.
    """

    ordered = tuple(sorted(development_candles, key=lambda item: item.at))
    dates = sorted({
        candle.at.astimezone(INDIA_TIME).date()
        for candle in ordered
    })
    if len(dates) != development_sessions:
        raise ValueError(
            f"development candle set contains {len(dates)} sessions; "
            f"{development_sessions} required"
        )
    if not ordered:
        raise ValueError("development candles unavailable")
    max_days = max(30, (ordered[-1].at - ordered[0].at).days + 3)
    snapshot = analyze_strategies(
        ordered,
        (),
        ordered[0].at,
        ordered[-1].at,
        max_days=max_days,
    )
    selected = _pick_strategy(snapshot, development_sessions)
    return FrozenStrategySelection(
        strategy_id=None if selected is None else selected.definition.strategy_id,
        strategy_name=None if selected is None else selected.definition.name,
        development_sessions=development_sessions,
        training_start=dates[0].isoformat() if dates else None,
        training_end=dates[-1].isoformat() if dates else None,
        development=_metrics(selected, development_sessions),
        candidates=tuple(
            _candidate(item)
            for item in snapshot.strategies
            if item.definition.direction_scope != "PROCESS"
        ),
        occurrences=() if selected is None else selected.occurrences,
    )


def run_candle_proxy_replay(
    candles: Sequence[Candle],
    *,
    sessions: int | None = None,
    development_sessions: int | None = None,
    blind_sessions: int | None = None,
    mode_key: str,
) -> ShadowReplayReport:
    """Run a development/blind replay without future leakage.

    Strategy rules only consume current/past candles. Forward returns are used
    exclusively by the evaluator after a signal has been generated.
    """

    mode = replay_mode(mode_key)
    if development_sessions is not None or blind_sessions is not None:
        if development_sessions is None or blind_sessions is None:
            raise ValueError("development and blind sessions must be provided together")
        development_target = int(development_sessions)
        blind_target = int(blind_sessions)
        if development_target < 1 or blind_target < 1:
            raise ValueError("development and blind sessions must both be at least 1")
        requested_sessions = development_target + blind_target
    else:
        if sessions is None:
            raise ValueError("replay session count is required")
        requested_sessions = int(sessions)
        development_target, blind_target = development_blind_split(requested_sessions)

    selected, dates = _slice_sessions(candles, requested_sessions)
    actual_sessions = len(dates)
    if actual_sessions < requested_sessions:
        raise ValueError(
            f"only {actual_sessions} complete historical sessions are available; "
            f"{requested_sessions} were requested"
        )

    development_dates = dates[:development_target]
    blind_dates = dates[development_target:]
    if len(blind_dates) != blind_target:
        raise ValueError("historical replay split unavailable")

    development_set = set(development_dates)
    blind_set = set(blind_dates)
    development_candles = tuple(
        candle
        for candle in selected
        if candle.at.astimezone(INDIA_TIME).date() in development_set
    )
    blind_candles = tuple(
        candle
        for candle in selected
        if candle.at.astimezone(INDIA_TIME).date() in blind_set
    )
    if not development_candles or not blind_candles:
        raise ValueError("historical replay candles unavailable")

    analysis_limit_days = max(
        30,
        (selected[-1].at - selected[0].at).days + 3,
    )
    development_snapshot = analyze_strategies(
        development_candles,
        (),
        development_candles[0].at,
        development_candles[-1].at,
        max_days=analysis_limit_days,
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
        max_days=analysis_limit_days,
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
    trades = tuple(
        [_trade("DEVELOPMENT", occurrence) for occurrence in (
            () if selected_strategy is None else selected_strategy.occurrences
        )]
        + [_trade("BLIND", occurrence) for occurrence in (
            () if blind_performance is None else blind_performance.occurrences
        )]
    )

    return ShadowReplayReport(
        schema="intrader-shadow-replay-v2-results",
        mode=mode.key,
        requested_touchpoints=mode.feature_count,
        requested_sessions=requested_sessions,
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
        trades=trades,
        first_session=dates[0].isoformat() if dates else None,
        last_session=dates[-1].isoformat() if dates else None,
        notes=(
            "Version 2 is a NIFTY candle-direction proxy, not exact historical option P&L.",
            "The selected strategy is chosen only from the development segment, must pass sample/stability checks when possible, and is frozen for the blind segment.",
            "Forward 5/15/30-minute returns are evaluation outputs and are never available to the strategy at decision time.",
            "Profit factor and drawdown currently use signed underlying percentage returns, not rupee option P&L.",
            "Replay mode records the requested touchpoint profile. Extra market families are added as their historical feeds are integrated.",
            "Expired NIFTY option premiums remain unavailable until a supported historical source is connected.",
        ),
    )
