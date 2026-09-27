"""Parallel paper-trader tournament for Shadow Trader historical replay.

This module stays deliberately separate from broker execution. It compares
1m/5m/10m/15m signal engines against the same chronological market history,
with independent proxy paper accounts and no look-ahead.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Sequence

from intrader.historical import Candle, INDIA_TIME
from intrader.shadow_lab import ShadowReplayConfig, validate_replay_config
from intrader.shadow_replay import ShadowReplayReport, run_candle_proxy_replay


D = Decimal


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
    strategy_name: str
    phase: str
    at: str
    direction: str
    entry_underlying: Decimal
    approx_exit_underlying_30m: Decimal | None
    gross_return_30m_pct: Decimal | None
    net_return_30m_pct: Decimal | None
    paper_pnl: Decimal | None
    paper_balance_after: Decimal | None
    result: str
    regime: str | None


@dataclass(frozen=True, slots=True)
class RejectedArenaSignal:
    timeframe_minutes: int
    trader_label: str
    phase: str
    at: str
    direction: str
    reason: str


@dataclass(frozen=True, slots=True)
class ArenaTraderReport:
    timeframe_minutes: int
    trader_label: str
    selected_strategy_id: str | None
    selected_strategy_name: str | None
    development_metrics: ArenaMetrics
    blind_metrics: ArenaMetrics
    development_paper: PaperAccountSummary
    blind_paper: PaperAccountSummary
    trades: tuple[ArenaTrade, ...]
    rejected_signals: tuple[RejectedArenaSignal, ...]


@dataclass(frozen=True, slots=True)
class ShadowArenaReport:
    schema: str
    config: ShadowReplayConfig
    total_sessions: int
    actual_sessions: int
    first_session: str | None
    last_session: str | None
    trader_reports: tuple[ArenaTraderReport, ...]
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
                at=first.at,
                open=first.open,
                high=max(item.high for item in bucket),
                low=min(item.low for item in bucket),
                close=last.close,
                volume=sum(int(item.volume or 0) for item in bucket),
            )
        )
    return tuple(rows)


def _select_non_overlapping(
    report: ShadowReplayReport,
    timeframe_minutes: int,
) -> tuple[tuple[object, ...], tuple[RejectedArenaSignal, ...]]:
    accepted: list[object] = []
    rejected: list[RejectedArenaSignal] = []
    blocked_until: dict[str, datetime] = {}

    for trade in sorted(report.trades, key=lambda item: datetime.fromisoformat(item.at)):
        opened_at = datetime.fromisoformat(trade.at)
        phase = trade.phase
        until = blocked_until.get(phase)
        if until is not None and opened_at < until:
            rejected.append(
                RejectedArenaSignal(
                    timeframe_minutes=timeframe_minutes,
                    trader_label=TRADER_LABELS[timeframe_minutes],
                    phase=phase,
                    at=trade.at,
                    direction=trade.direction,
                    reason="position already open in this timeframe trader",
                )
            )
            continue
        accepted.append(trade)
        blocked_until[phase] = opened_at + timedelta(minutes=30)

    return tuple(accepted), tuple(rejected)


def _metrics(trades: Sequence[ArenaTrade], sessions: int) -> ArenaMetrics:
    values = [
        trade.net_return_30m_pct
        for trade in trades
        if trade.net_return_30m_pct is not None
    ]
    wins = sum(1 for value in values if value > 0)
    losses = sum(1 for value in values if value < 0)
    flats = sum(1 for value in values if value == 0)
    positives = [value for value in values if value > 0]
    negatives = [value for value in values if value < 0]
    gross_positive = sum(positives, D(0))
    gross_negative = abs(sum(negatives, D(0)))

    streak = longest = 0
    for value in values:
        if value < 0:
            streak += 1
            longest = max(longest, streak)
        else:
            streak = 0

    return ArenaMetrics(
        sessions=sessions,
        trades=len(values),
        wins=wins,
        losses=losses,
        flats=flats,
        win_rate_pct=(
            None if not values else D(wins) / D(len(values)) * D(100)
        ),
        average_return_pct=(
            None if not values else sum(values, D(0)) / D(len(values))
        ),
        profit_factor=(
            None if gross_negative == 0 else gross_positive / gross_negative
        ),
        max_losing_streak=longest,
    )


def _paperize_phase(
    raw_trades: Sequence[object],
    *,
    timeframe_minutes: int,
    strategy_name: str,
    config: ShadowReplayConfig,
) -> tuple[tuple[ArenaTrade, ...], PaperAccountSummary]:
    balance = config.starting_capital
    peak = balance
    max_drawdown = D(0)
    max_drawdown_pct = D(0)
    rows: list[ArenaTrade] = []
    wins = losses = flats = 0

    for trade in raw_trades:
        gross = trade.return_30m_pct
        if gross is None:
            net = None
            pnl = None
            after = balance
            result = "UNEVALUATED"
        else:
            friction_pct = config.friction_bps / D(100)
            net = gross - friction_pct
            allocated = balance * config.allocation_pct / D(100)
            pnl = allocated * net / D(100)
            balance += pnl
            after = balance
            if net > 0:
                wins += 1
                result = "WIN"
            elif net < 0:
                losses += 1
                result = "LOSS"
            else:
                flats += 1
                result = "FLAT"
            peak = max(peak, balance)
            drawdown = peak - balance
            max_drawdown = max(max_drawdown, drawdown)
            if peak > 0:
                max_drawdown_pct = max(
                    max_drawdown_pct,
                    drawdown / peak * D(100),
                )

        rows.append(
            ArenaTrade(
                timeframe_minutes=timeframe_minutes,
                trader_label=TRADER_LABELS[timeframe_minutes],
                strategy_name=strategy_name,
                phase=trade.phase,
                at=trade.at,
                direction=trade.direction,
                entry_underlying=trade.entry_underlying,
                approx_exit_underlying_30m=trade.approx_exit_underlying_30m,
                gross_return_30m_pct=gross,
                net_return_30m_pct=net,
                paper_pnl=pnl,
                paper_balance_after=after,
                result=result,
                regime=trade.regime,
            )
        )

    net_pnl = balance - config.starting_capital
    return_pct = net_pnl / config.starting_capital * D(100)
    max_dd_pct = max_drawdown_pct
    summary = PaperAccountSummary(
        starting_capital=config.starting_capital,
        ending_capital=balance,
        net_pnl=net_pnl,
        return_pct=return_pct,
        max_drawdown=max_drawdown,
        max_drawdown_pct=max_dd_pct,
        trades=wins + losses + flats,
        wins=wins,
        losses=losses,
        flats=flats,
    )
    return tuple(rows), summary


def _build_trader(
    candles: Sequence[Candle],
    *,
    timeframe_minutes: int,
    config: ShadowReplayConfig,
) -> ArenaTraderReport:
    aggregated = _aggregate_candles(candles, timeframe_minutes)
    base = run_candle_proxy_replay(
        aggregated,
        development_sessions=config.development_sessions,
        blind_sessions=config.blind_sessions,
        mode_key=config.mode_key,
    )
    accepted, rejected = _select_non_overlapping(base, timeframe_minutes)
    development_raw = tuple(item for item in accepted if item.phase == "DEVELOPMENT")
    blind_raw = tuple(item for item in accepted if item.phase == "BLIND")
    strategy_name = base.selected_strategy_name or "No qualifying strategy"

    development_trades, development_paper = _paperize_phase(
        development_raw,
        timeframe_minutes=timeframe_minutes,
        strategy_name=strategy_name,
        config=config,
    )
    blind_trades, blind_paper = _paperize_phase(
        blind_raw,
        timeframe_minutes=timeframe_minutes,
        strategy_name=strategy_name,
        config=config,
    )
    return ArenaTraderReport(
        timeframe_minutes=timeframe_minutes,
        trader_label=TRADER_LABELS[timeframe_minutes],
        selected_strategy_id=base.selected_strategy_id,
        selected_strategy_name=base.selected_strategy_name,
        development_metrics=_metrics(
            development_trades, config.development_sessions
        ),
        blind_metrics=_metrics(blind_trades, config.blind_sessions),
        development_paper=development_paper,
        blind_paper=blind_paper,
        trades=development_trades + blind_trades,
        rejected_signals=rejected,
    )


def run_shadow_arena(
    candles: Sequence[Candle],
    config: ShadowReplayConfig,
) -> ShadowArenaReport:
    config = validate_replay_config(config)
    ordered = tuple(sorted(candles, key=lambda item: item.at))
    dates = sorted({item.at.astimezone(INDIA_TIME).date() for item in ordered})
    selected_dates = dates[-config.total_sessions:]
    if len(selected_dates) < config.total_sessions:
        raise ValueError(
            f"only {len(selected_dates)} complete historical sessions are available; "
            f"{config.total_sessions} were requested"
        )
    selected_set = set(selected_dates)
    selected = tuple(
        item
        for item in ordered
        if item.at.astimezone(INDIA_TIME).date() in selected_set
    )

    trader_reports = tuple(
        _build_trader(
            selected,
            timeframe_minutes=timeframe,
            config=config,
        )
        for timeframe in config.trader_timeframes
    )
    return ShadowArenaReport(
        schema="intrader-shadow-arena-v1",
        config=config,
        total_sessions=config.total_sessions,
        actual_sessions=len(selected_dates),
        first_session=selected_dates[0].isoformat(),
        last_session=selected_dates[-1].isoformat(),
        trader_reports=trader_reports,
        notes=(
            "Each timeframe trader selects its strategy only from the development block, then freezes it for blind testing.",
            "The four paper accounts are independent and reset to the same starting capital at the beginning of the blind phase.",
            "Only one 30-minute proxy position may be open per timeframe trader; overlapping signals are recorded as rejected.",
            "Paper P&L is a NIFTY directional proxy with user-configured friction, not exact historical option premium P&L.",
            "No broker order path is present in Shadow Arena.",
        ),
    )
