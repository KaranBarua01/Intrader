"""Records Manager performance analytics for Intrader Phase 3."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Mapping, Sequence

from intrader.outcomes import ShadowOutcome
from intrader.reasoning_auditor import ReasonAudit
from intrader.records import DecisionRecord
from intrader.shadow import ShadowTrade


@dataclass(frozen=True, slots=True)
class PerformanceMetrics:
    trades: int
    wins: int
    losses: int
    flats: int
    win_rate: Decimal | None
    gross_pnl: Decimal
    adjusted_pnl: Decimal
    average_winner: Decimal | None
    average_loser: Decimal | None
    expectancy: Decimal | None
    profit_factor: Decimal | None
    max_drawdown: Decimal
    max_drawdown_pct: Decimal
    max_winning_streak: int
    max_losing_streak: int


@dataclass(frozen=True, slots=True)
class ReasonPerformance:
    reason_code: str
    occurrences: int
    profitable: int
    losing: int
    supported: int
    contradicted: int
    average_pnl: Decimal


@dataclass(frozen=True, slots=True)
class RecordsManagerSnapshot:
    starting_capital: Decimal
    current_equity: Decimal
    decision_counts: tuple[tuple[str, int], ...]
    overall: PerformanceMetrics
    by_action: tuple[tuple[str, PerformanceMetrics], ...]
    by_regime: tuple[tuple[str, PerformanceMetrics], ...]
    by_hour: tuple[tuple[str, PerformanceMetrics], ...]
    by_brain_version: tuple[tuple[str, PerformanceMetrics], ...]
    reasons: tuple[ReasonPerformance, ...]


def _metrics(
    rows: Sequence[tuple[DecisionRecord, ShadowTrade, ShadowOutcome]],
    starting_capital: Decimal,
) -> PerformanceMetrics:
    ordered = sorted(rows, key=lambda item: item[1].opened_at)
    pnls = [item[2].adjusted_pnl for item in ordered]
    gross = sum((item[2].gross_pnl for item in ordered), Decimal(0))
    adjusted = sum(pnls, Decimal(0))
    wins = [pnl for pnl in pnls if pnl > 0]
    losses = [pnl for pnl in pnls if pnl < 0]
    flats = sum(1 for pnl in pnls if pnl == 0)
    count = len(pnls)

    win_rate = None if count == 0 else Decimal(len(wins)) / Decimal(count) * Decimal(100)
    avg_winner = None if not wins else sum(wins, Decimal(0)) / Decimal(len(wins))
    avg_loser = None if not losses else sum(losses, Decimal(0)) / Decimal(len(losses))
    expectancy = None if count == 0 else adjusted / Decimal(count)
    gross_profit = sum(wins, Decimal(0))
    gross_loss = abs(sum(losses, Decimal(0)))
    profit_factor = None if gross_loss == 0 else gross_profit / gross_loss

    equity = starting_capital
    peak = starting_capital
    max_drawdown = Decimal(0)
    win_streak = loss_streak = max_win_streak = max_loss_streak = 0
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
        if pnl > 0:
            win_streak += 1
            loss_streak = 0
            max_win_streak = max(max_win_streak, win_streak)
        elif pnl < 0:
            loss_streak += 1
            win_streak = 0
            max_loss_streak = max(max_loss_streak, loss_streak)
        else:
            win_streak = loss_streak = 0

    max_drawdown_pct = (
        Decimal(0)
        if starting_capital <= 0
        else max_drawdown / starting_capital * Decimal(100)
    )
    return PerformanceMetrics(
        trades=count,
        wins=len(wins),
        losses=len(losses),
        flats=flats,
        win_rate=win_rate,
        gross_pnl=gross,
        adjusted_pnl=adjusted,
        average_winner=avg_winner,
        average_loser=avg_loser,
        expectancy=expectancy,
        profit_factor=profit_factor,
        max_drawdown=max_drawdown,
        max_drawdown_pct=max_drawdown_pct,
        max_winning_streak=max_win_streak,
        max_losing_streak=max_loss_streak,
    )


def _group_metrics(
    rows: Sequence[tuple[DecisionRecord, ShadowTrade, ShadowOutcome]],
    key_fn,
    starting_capital: Decimal,
):
    grouped = {}
    for row in rows:
        grouped.setdefault(key_fn(row), []).append(row)
    return tuple(
        (key, _metrics(grouped[key], starting_capital))
        for key in sorted(grouped)
    )


def _reason_performance(audits: Sequence[ReasonAudit]) -> tuple[ReasonPerformance, ...]:
    grouped: dict[str, list[ReasonAudit]] = {}
    for audit in audits:
        grouped.setdefault(audit.reason_code, []).append(audit)

    results: list[ReasonPerformance] = []
    for code, rows in grouped.items():
        results.append(
            ReasonPerformance(
                reason_code=code,
                occurrences=len(rows),
                profitable=sum(1 for row in rows if row.trade_result == "PROFIT"),
                losing=sum(1 for row in rows if row.trade_result == "LOSS"),
                supported=sum(1 for row in rows if row.verdict == "SUPPORTED"),
                contradicted=sum(1 for row in rows if row.verdict == "CONTRADICTED"),
                average_pnl=(
                    sum((row.adjusted_pnl for row in rows), Decimal(0))
                    / Decimal(len(rows))
                ),
            )
        )
    return tuple(
        sorted(results, key=lambda item: (-item.occurrences, item.reason_code))
    )


def build_records_manager_snapshot(
    decisions: Sequence[DecisionRecord],
    completed: Sequence[tuple[DecisionRecord, ShadowTrade, ShadowOutcome]],
    audits: Sequence[ReasonAudit],
    *,
    starting_capital: Decimal = Decimal("100000"),
) -> RecordsManagerSnapshot:
    if starting_capital <= 0:
        raise ValueError("starting capital must be positive")

    decision_counts: dict[str, int] = {}
    for decision in decisions:
        decision_counts[decision.action] = decision_counts.get(decision.action, 0) + 1

    overall = _metrics(completed, starting_capital)
    return RecordsManagerSnapshot(
        starting_capital=starting_capital,
        current_equity=starting_capital + overall.adjusted_pnl,
        decision_counts=tuple(sorted(decision_counts.items())),
        overall=overall,
        by_action=_group_metrics(
            completed, lambda row: row[1].action, starting_capital
        ),
        by_regime=_group_metrics(
            completed, lambda row: row[0].regime, starting_capital
        ),
        by_hour=_group_metrics(
            completed,
            lambda row: row[1].opened_at.strftime("%H:00"),
            starting_capital,
        ),
        by_brain_version=_group_metrics(
            completed, lambda row: row[0].brain_version, starting_capital
        ),
        reasons=_reason_performance(audits),
    )
