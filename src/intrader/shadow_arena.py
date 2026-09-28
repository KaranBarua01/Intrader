"""Parallel frozen-engine Shadow Arena for Intrader 0.5.0.

Development candles may be inspected by the trainer. Blind candles are consumed
by causal frozen engines one minute at a time. The module also produces
ablation, regime/time-of-day and optional walk-forward diagnostics.

No broker order path exists here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import hashlib
from typing import Sequence

from intrader.historical import Candle, INDIA_TIME
from intrader.shadow_lab import (
    FEATURE_FAMILIES,
    ShadowReplayConfig,
    TRADER_HOLD_MINUTES,
    replay_mode,
    validate_replay_config,
)
from intrader.shadow_replay import FrozenStrategySelection, train_frozen_strategy
from intrader.shadow_stream_engine import (
    FrozenEngineSpec,
    HistoricalFeatureTimeline,
    SliceStat,
    StreamAccountSummary,
    StreamEngineReport,
    StreamRejectedSignal,
    StreamTrade,
    run_stream_engine,
)


D = Decimal
_HOLD = dict(TRADER_HOLD_MINUTES)


TRADER_LABELS = {
    1: "1M SCALPER",
    5: "5M FAST",
    10: "10M MOMENTUM",
    15: "15M TREND",
}


@dataclass(frozen=True, slots=True)
class ArenaMetrics:
    sessions: int
    trades: int
    wins: int
    losses: int
    flats: int
    win_rate_pct: Decimal | None
    average_return_pct: Decimal | None
    profit_factor: Decimal | None
    max_losing_streak: int


@dataclass(frozen=True, slots=True)
class PaperAccountSummary:
    starting_capital: Decimal
    ending_capital: Decimal
    net_pnl: Decimal
    return_pct: Decimal
    max_drawdown: Decimal
    max_drawdown_pct: Decimal
    trades: int
    wins: int
    losses: int
    flats: int


@dataclass(frozen=True, slots=True)
class ArenaTrade:
    timeframe_minutes: int
    trader_label: str
    engine_id: str
    strategy_name: str
    phase: str
    opened_at: str
    closed_at: str
    hold_minutes: int
    direction: str
    entry_underlying: Decimal
    exit_underlying: Decimal
    gross_return_pct: Decimal
    net_return_pct: Decimal
    paper_pnl: Decimal
    paper_balance_after: Decimal
    mfe_pct: Decimal
    mae_pct: Decimal
    regime: str
    time_bucket: str
    feature_scores: tuple[tuple[str, Decimal], ...]
    exit_reason: str
    result: str


@dataclass(frozen=True, slots=True)
class RejectedArenaSignal:
    timeframe_minutes: int
    trader_label: str
    engine_id: str
    phase: str
    at: str
    direction: str
    reason: str
    hypothetical_return_pct: Decimal | None
    hypothetical_pnl: Decimal | None
    classification: str


@dataclass(frozen=True, slots=True)
class FeatureCoverageAudit:
    requested_touchpoints: int
    available_touchpoints: int
    decision_used_touchpoints: int
    requested_families: tuple[str, ...]
    available_families: tuple[str, ...]
    decision_used_families: tuple[str, ...]
    missing_families: tuple[str, ...]
    stored_rows: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class AblationResult:
    timeframe_minutes: int
    trader_label: str
    label: str
    families: tuple[str, ...]
    trades: int
    net_pnl: Decimal
    return_pct: Decimal
    profit_factor: Decimal | None
    max_drawdown_pct: Decimal


@dataclass(frozen=True, slots=True)
class WalkForwardResult:
    timeframe_minutes: int
    trader_label: str
    window_index: int
    training_start: str
    training_end: str
    test_start: str
    test_end: str
    engine_id: str
    trades: int
    net_pnl: Decimal
    return_pct: Decimal
    profit_factor: Decimal | None
    max_drawdown_pct: Decimal


@dataclass(frozen=True, slots=True)
class ArenaTraderReport:
    timeframe_minutes: int
    trader_label: str
    engine_id: str
    hold_minutes: int
    training_start: str
    training_end: str
    selected_strategy_id: str | None
    selected_strategy_name: str | None
    development_metrics: ArenaMetrics
    blind_metrics: ArenaMetrics
    development_paper: PaperAccountSummary
    blind_paper: PaperAccountSummary
    trades: tuple[ArenaTrade, ...]
    rejected_signals: tuple[RejectedArenaSignal, ...]
    regime_stats: tuple[SliceStat, ...]
    time_stats: tuple[SliceStat, ...]
    equity_curve: tuple[tuple[str, Decimal], ...]


@dataclass(frozen=True, slots=True)
class ShadowArenaReport:
    schema: str
    config: ShadowReplayConfig
    total_sessions: int
    actual_sessions: int
    first_session: str | None
    last_session: str | None
    blind_start: str
    blind_end: str
    blind_window_id: str
    blind_previously_reviewed: bool
    feature_coverage: FeatureCoverageAudit
    trader_reports: tuple[ArenaTraderReport, ...]
    ablation_results: tuple[AblationResult, ...]
    walk_forward_results: tuple[WalkForwardResult, ...]
    notes: tuple[str, ...]

    def trader(self, timeframe_minutes: int) -> ArenaTraderReport | None:
        for item in self.trader_reports:
            if item.timeframe_minutes == timeframe_minutes:
                return item
        return None


def _aggregate_candles(
    candles: Sequence[Candle],
    minutes: int,
) -> tuple[Candle, ...]:
    if minutes <= 1:
        return tuple(sorted(candles, key=lambda item: item.at))
    groups: dict[tuple[object, int], list[Candle]] = {}
    session_anchor = 9 * 60 + 15
    for candle in sorted(candles, key=lambda item: item.at):
        local = candle.at.astimezone(INDIA_TIME)
        minute_index = local.hour * 60 + local.minute
        bucket_minute = (
            ((minute_index - session_anchor) // minutes) * minutes
            + session_anchor
        )
        groups.setdefault((local.date(), bucket_minute), []).append(candle)
    rows: list[Candle] = []
    for key in sorted(groups):
        bucket = groups[key]
        first = bucket[0]
        last = bucket[-1]
        rows.append(
            Candle(
                at=last.at,
                open=first.open,
                high=max(item.high for item in bucket),
                low=min(item.low for item in bucket),
                close=last.close,
                volume=sum(int(item.volume or 0) for item in bucket),
            )
        )
    return tuple(rows)


def _dates(candles: Sequence[Candle]) -> tuple:
    return tuple(sorted({
        item.at.astimezone(INDIA_TIME).date()
        for item in candles
    }))


def _filter_days(candles: Sequence[Candle], days: Sequence) -> tuple[Candle, ...]:
    selected = set(days)
    return tuple(
        item for item in sorted(candles, key=lambda row: row.at)
        if item.at.astimezone(INDIA_TIME).date() in selected
    )


def _arena_metrics_from_stream(
    report: StreamEngineReport,
    sessions: int,
) -> ArenaMetrics:
    account = report.account
    return ArenaMetrics(
        sessions=sessions,
        trades=account.trades,
        wins=account.wins,
        losses=account.losses,
        flats=account.flats,
        win_rate_pct=(
            None
            if account.trades == 0
            else D(account.wins) / D(account.trades) * D(100)
        ),
        average_return_pct=account.average_return_pct,
        profit_factor=account.profit_factor,
        max_losing_streak=account.max_losing_streak,
    )


def _paper_from_stream(account: StreamAccountSummary) -> PaperAccountSummary:
    return PaperAccountSummary(
        starting_capital=account.starting_capital,
        ending_capital=account.ending_capital,
        net_pnl=account.net_pnl,
        return_pct=account.return_pct,
        max_drawdown=account.max_drawdown,
        max_drawdown_pct=account.max_drawdown_pct,
        trades=account.trades,
        wins=account.wins,
        losses=account.losses,
        flats=account.flats,
    )


def _paperize_development(
    selection: FrozenStrategySelection,
    config: ShadowReplayConfig,
) -> PaperAccountSummary:
    balance = config.starting_capital
    peak = balance
    max_drawdown = D(0)
    max_drawdown_pct = D(0)
    wins = losses = flats = 0
    for gross in selection.gross_horizon_returns:
        if gross is None:
            continue
        net = gross - config.friction_bps / D(100)
        allocated = balance * config.allocation_pct / D(100)
        balance += allocated * net / D(100)
        peak = max(peak, balance)
        drawdown = peak - balance
        max_drawdown = max(max_drawdown, drawdown)
        if peak > 0:
            max_drawdown_pct = max(
                max_drawdown_pct,
                drawdown / peak * D(100),
            )
        if net > 0:
            wins += 1
        elif net < 0:
            losses += 1
        else:
            flats += 1
    net_pnl = balance - config.starting_capital
    return PaperAccountSummary(
        starting_capital=config.starting_capital,
        ending_capital=balance,
        net_pnl=net_pnl,
        return_pct=net_pnl / config.starting_capital * D(100),
        max_drawdown=max_drawdown,
        max_drawdown_pct=max_drawdown_pct,
        trades=wins + losses + flats,
        wins=wins,
        losses=losses,
        flats=flats,
    )


def _development_metrics(selection: FrozenStrategySelection) -> ArenaMetrics:
    metrics = selection.development
    return ArenaMetrics(
        sessions=selection.development_sessions,
        trades=metrics.evaluable_signals,
        wins=metrics.wins,
        losses=metrics.losses,
        flats=metrics.flats,
        win_rate_pct=metrics.win_rate_pct,
        average_return_pct=metrics.average_return_30m_pct,
        profit_factor=metrics.profit_factor,
        max_losing_streak=metrics.max_losing_streak,
    )


def _engine_id(
    timeframe_minutes: int,
    selection: FrozenStrategySelection,
    config: ShadowReplayConfig,
    families: Sequence[str],
) -> str:
    signature = "|".join(
        (
            "0.5.0",
            str(timeframe_minutes),
            selection.strategy_id or "NONE",
            selection.training_start or "NONE",
            selection.training_end or "NONE",
            config.mode_key,
            ",".join(families),
        )
    )
    return hashlib.sha256(signature.encode("utf-8")).hexdigest()[:16]


def _convert_trade(
    item: StreamTrade,
    *,
    trader_label: str,
    phase: str,
) -> ArenaTrade:
    return ArenaTrade(
        timeframe_minutes=item.timeframe_minutes,
        trader_label=trader_label,
        engine_id=item.engine_id,
        strategy_name=item.strategy_name,
        phase=phase,
        opened_at=item.opened_at,
        closed_at=item.closed_at,
        hold_minutes=_HOLD[item.timeframe_minutes],
        direction=item.direction,
        entry_underlying=item.entry_underlying,
        exit_underlying=item.exit_underlying,
        gross_return_pct=item.gross_return_pct,
        net_return_pct=item.net_return_pct,
        paper_pnl=item.paper_pnl,
        paper_balance_after=item.balance_after,
        mfe_pct=item.mfe_pct,
        mae_pct=item.mae_pct,
        regime=item.regime,
        time_bucket=item.time_bucket,
        feature_scores=item.feature_scores,
        exit_reason=item.exit_reason,
        result=item.result,
    )


def _convert_rejected(
    item: StreamRejectedSignal,
    *,
    trader_label: str,
    phase: str,
) -> RejectedArenaSignal:
    return RejectedArenaSignal(
        timeframe_minutes=item.timeframe_minutes,
        trader_label=trader_label,
        engine_id=item.engine_id,
        phase=phase,
        at=item.at,
        direction=item.direction,
        reason=item.reason,
        hypothetical_return_pct=item.hypothetical_return_pct,
        hypothetical_pnl=item.hypothetical_pnl,
        classification=item.classification,
    )


def _empty_stream_report(spec: FrozenEngineSpec, config: ShadowReplayConfig) -> StreamEngineReport:
    account = StreamAccountSummary(
        starting_capital=config.starting_capital,
        ending_capital=config.starting_capital,
        net_pnl=D(0),
        return_pct=D(0),
        max_drawdown=D(0),
        max_drawdown_pct=D(0),
        trades=0,
        wins=0,
        losses=0,
        flats=0,
        profit_factor=None,
        average_return_pct=None,
        max_losing_streak=0,
    )
    return StreamEngineReport(
        spec=spec,
        account=account,
        trades=(),
        rejected_signals=(),
        regime_stats=(),
        time_stats=(),
        equity_curve=(),
    )


def _run_one_frozen_engine(
    *,
    development_one_minute: Sequence[Candle],
    blind_one_minute: Sequence[Candle],
    timeframe_minutes: int,
    config: ShadowReplayConfig,
    timeline: HistoricalFeatureTimeline,
    enabled_families: Sequence[str],
    selection: FrozenStrategySelection | None = None,
) -> tuple[FrozenStrategySelection, FrozenEngineSpec, StreamEngineReport]:
    if selection is None:
        development_aggregated = _aggregate_candles(
            development_one_minute,
            timeframe_minutes,
        )
        selection = train_frozen_strategy(
            development_aggregated,
            development_sessions=config.development_sessions,
            hold_minutes=_HOLD[timeframe_minutes],
            friction_bps=config.friction_bps,
        )
    engine_id = _engine_id(
        timeframe_minutes,
        selection,
        config,
        enabled_families,
    )
    spec = FrozenEngineSpec(
        timeframe_minutes=timeframe_minutes,
        strategy_id=selection.strategy_id or "",
        strategy_name=selection.strategy_name or "No qualifying strategy",
        engine_id=engine_id,
        hold_minutes=_HOLD[timeframe_minutes],
        enabled_families=tuple(enabled_families),
        training_start=selection.training_start or "",
        training_end=selection.training_end or "",
    )
    if selection.strategy_id is None:
        return selection, spec, _empty_stream_report(spec, config)
    stream = run_stream_engine(
        blind_candles=blind_one_minute,
        development_seed_candles=development_one_minute,
        spec=spec,
        config=config,
        timeline=timeline,
    )
    return selection, spec, stream


def _build_trader(
    *,
    development_one_minute: Sequence[Candle],
    blind_one_minute: Sequence[Candle],
    timeframe_minutes: int,
    config: ShadowReplayConfig,
    timeline: HistoricalFeatureTimeline,
    enabled_families: Sequence[str],
    selection: FrozenStrategySelection | None = None,
) -> ArenaTraderReport:
    selection, spec, stream = _run_one_frozen_engine(
        development_one_minute=development_one_minute,
        blind_one_minute=blind_one_minute,
        timeframe_minutes=timeframe_minutes,
        config=config,
        timeline=timeline,
        enabled_families=enabled_families,
        selection=selection,
    )
    label = TRADER_LABELS[timeframe_minutes]
    blind_trades = tuple(
        _convert_trade(item, trader_label=label, phase="BLIND")
        for item in stream.trades
    )
    rejected = tuple(
        _convert_rejected(item, trader_label=label, phase="BLIND")
        for item in stream.rejected_signals
    )
    return ArenaTraderReport(
        timeframe_minutes=timeframe_minutes,
        trader_label=label,
        engine_id=spec.engine_id,
        hold_minutes=spec.hold_minutes,
        training_start=spec.training_start,
        training_end=spec.training_end,
        selected_strategy_id=selection.strategy_id,
        selected_strategy_name=selection.strategy_name,
        development_metrics=_development_metrics(selection),
        blind_metrics=_arena_metrics_from_stream(
            stream,
            config.blind_sessions,
        ),
        development_paper=_paperize_development(selection, config),
        blind_paper=_paper_from_stream(stream.account),
        trades=blind_trades,
        rejected_signals=rejected,
        regime_stats=stream.regime_stats,
        time_stats=stream.time_stats,
        equity_curve=stream.equity_curve,
    )


def _ablation_family_sets(
    coverage: FeatureCoverageAudit,
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    used = list(coverage.decision_used_families)
    steps: list[tuple[str, tuple[str, ...]]] = [("BASE_STRATEGY", ())]
    current: list[str] = []
    for family in used:
        current.append(family)
        steps.append((f"+ {family}", tuple(current)))
    return tuple(steps)


def _run_ablations(
    *,
    development: Sequence[Candle],
    blind: Sequence[Candle],
    config: ShadowReplayConfig,
    timeline: HistoricalFeatureTimeline,
    coverage: FeatureCoverageAudit,
    selections: dict[int, FrozenStrategySelection],
) -> tuple[AblationResult, ...]:
    rows: list[AblationResult] = []
    for timeframe in config.trader_timeframes:
        label = TRADER_LABELS[timeframe]
        for step_label, families in _ablation_family_sets(coverage):
            _selection, _spec, stream = _run_one_frozen_engine(
                development_one_minute=development,
                blind_one_minute=blind,
                timeframe_minutes=timeframe,
                config=config,
                timeline=timeline,
                enabled_families=families,
                selection=selections[timeframe],
            )
            account = stream.account
            rows.append(
                AblationResult(
                    timeframe_minutes=timeframe,
                    trader_label=label,
                    label=step_label,
                    families=families,
                    trades=account.trades,
                    net_pnl=account.net_pnl,
                    return_pct=account.return_pct,
                    profit_factor=account.profit_factor,
                    max_drawdown_pct=account.max_drawdown_pct,
                )
            )
    return tuple(rows)


def _run_walk_forward(
    *,
    candles: Sequence[Candle],
    config: ShadowReplayConfig,
    timeline: HistoricalFeatureTimeline,
    enabled_families: Sequence[str],
) -> tuple[WalkForwardResult, ...]:
    if config.validation_mode != "WALK_FORWARD":
        return ()
    dates = list(_dates(candles))
    required = config.walk_required_sessions
    if len(dates) < required:
        return ()
    dates = dates[-required:]
    rows: list[WalkForwardResult] = []
    for window_index in range(config.walk_windows):
        train_start = window_index * config.walk_step_sessions
        train_end = train_start + config.walk_train_sessions
        test_end = train_end + config.walk_test_sessions
        if test_end > len(dates):
            break
        train_days = dates[train_start:train_end]
        test_days = dates[train_end:test_end]
        train_candles = _filter_days(candles, train_days)
        test_candles = _filter_days(candles, test_days)
        window_config = ShadowReplayConfig(
            development_sessions=len(train_days),
            blind_sessions=len(test_days),
            mode_key=config.mode_key,
            validation_mode="STANDARD",
            walk_train_sessions=config.walk_train_sessions,
            walk_test_sessions=config.walk_test_sessions,
            walk_step_sessions=config.walk_step_sessions,
            walk_windows=config.walk_windows,
            execution_mode=config.execution_mode,
            starting_capital=config.starting_capital,
            allocation_pct=config.allocation_pct,
            friction_bps=config.friction_bps,
            trader_timeframes=config.trader_timeframes,
        )
        for timeframe in config.trader_timeframes:
            _selection, spec, stream = _run_one_frozen_engine(
                development_one_minute=train_candles,
                blind_one_minute=test_candles,
                timeframe_minutes=timeframe,
                config=window_config,
                timeline=timeline,
                enabled_families=enabled_families,
            )
            rows.append(
                WalkForwardResult(
                    timeframe_minutes=timeframe,
                    trader_label=TRADER_LABELS[timeframe],
                    window_index=window_index + 1,
                    training_start=train_days[0].isoformat(),
                    training_end=train_days[-1].isoformat(),
                    test_start=test_days[0].isoformat(),
                    test_end=test_days[-1].isoformat(),
                    engine_id=spec.engine_id,
                    trades=stream.account.trades,
                    net_pnl=stream.account.net_pnl,
                    return_pct=stream.account.return_pct,
                    profit_factor=stream.account.profit_factor,
                    max_drawdown_pct=stream.account.max_drawdown_pct,
                )
            )
    return tuple(rows)


def run_shadow_arena(
    candles: Sequence[Candle],
    config: ShadowReplayConfig,
    *,
    blind_previously_reviewed: bool = False,
    feature_coverage: FeatureCoverageAudit | None = None,
    timeline: HistoricalFeatureTimeline | None = None,
) -> ShadowArenaReport:
    config = validate_replay_config(config)
    timeline = timeline or HistoricalFeatureTimeline()
    ordered = tuple(sorted(candles, key=lambda item: item.at))
    all_dates = list(_dates(ordered))
    if len(all_dates) < config.required_sessions:
        raise ValueError(
            f"only {len(all_dates)} complete historical sessions are available; "
            f"{config.required_sessions} required"
        )

    standard_dates = all_dates[-config.total_sessions:]
    development_dates = standard_dates[:config.development_sessions]
    blind_dates = standard_dates[config.development_sessions:]
    development = _filter_days(ordered, development_dates)
    blind = _filter_days(ordered, blind_dates)

    if feature_coverage is None:
        mode = replay_mode(config.mode_key)
        feature_sizes = {family: len(features) for family, features in FEATURE_FAMILIES}
        feature_coverage = FeatureCoverageAudit(
            requested_touchpoints=mode.feature_count,
            available_touchpoints=10,
            decision_used_touchpoints=10,
            requested_families=mode.families,
            available_families=tuple(
                family
                for family in mode.families
                if family in {"NIFTY price / structure", "Momentum / volatility"}
            ),
            decision_used_families=tuple(
                family
                for family in mode.families
                if family in {"NIFTY price / structure", "Momentum / volatility"}
            ),
            missing_families=tuple(
                family
                for family in mode.families
                if family not in {"NIFTY price / structure", "Momentum / volatility"}
            ),
            stored_rows=(),
        )

    enabled_families = feature_coverage.decision_used_families
    selections: dict[int, FrozenStrategySelection] = {}
    for timeframe in config.trader_timeframes:
        development_aggregated = _aggregate_candles(
            development,
            timeframe,
        )
        selections[timeframe] = train_frozen_strategy(
            development_aggregated,
            development_sessions=config.development_sessions,
            hold_minutes=_HOLD[timeframe],
            friction_bps=config.friction_bps,
        )

    trader_reports = tuple(
        _build_trader(
            development_one_minute=development,
            blind_one_minute=blind,
            timeframe_minutes=timeframe,
            config=config,
            timeline=timeline,
            enabled_families=enabled_families,
            selection=selections[timeframe],
        )
        for timeframe in config.trader_timeframes
    )

    ablations = _run_ablations(
        development=development,
        blind=blind,
        config=config,
        timeline=timeline,
        coverage=feature_coverage,
        selections=selections,
    )
    walk_forward = _run_walk_forward(
        candles=ordered,
        config=config,
        timeline=timeline,
        enabled_families=enabled_families,
    )

    blind_start = blind_dates[0].isoformat()
    blind_end = blind_dates[-1].isoformat()
    blind_window_id = hashlib.sha256(
        f"{blind_start}|{blind_end}".encode("utf-8")
    ).hexdigest()[:16]

    return ShadowArenaReport(
        schema="intrader-shadow-arena-v3-event-driven",
        config=config,
        total_sessions=config.total_sessions,
        actual_sessions=len(standard_dates),
        first_session=standard_dates[0].isoformat(),
        last_session=standard_dates[-1].isoformat(),
        blind_start=blind_start,
        blind_end=blind_end,
        blind_window_id=blind_window_id,
        blind_previously_reviewed=blind_previously_reviewed,
        feature_coverage=feature_coverage,
        trader_reports=trader_reports,
        ablation_results=ablations,
        walk_forward_results=walk_forward,
        notes=(
            "Development selects each timeframe strategy using that engine's actual hold horizon and net returns after configured friction; no qualifying net edge means no frozen strategy.",
            "Blind execution is event-driven: one-minute candles are consumed chronologically and future candles are not available to the engine.",
            "1m/5m/10m/15m engines use independent paper accounts and holding horizons.",
            "Historical feature families affect decisions only when they are both requested and causally available.",
            "Ablation compares the same blind dates while progressively enabling genuinely wired feature families.",
            "Walk-forward is produced only when WALK_FORWARD validation is selected.",
            "Paper P&L remains a NIFTY directional proxy until exact historical option-premium data is available.",
            "Reused blind windows are diagnostic only, not fresh validation.",
            "No broker order path is present in Shadow Arena.",
        ),
    )
