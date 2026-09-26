"""Historical range intelligence and opening-scenario analysis for Time Travel."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Sequence

from intrader.context import NewsItem, ScheduledEvent
from intrader.historical import Candle, INDIA_TIME
from intrader.records import DecisionRecord
from intrader.shadow import ShadowTrade
from intrader.outcomes import ShadowOutcome


class HistoricalIntelligenceError(Exception):
    """Historical range inputs are invalid or insufficient."""


@dataclass(frozen=True, slots=True)
class KeyMoment:
    at: datetime
    kind: str
    importance: Decimal
    summary: str
    detail: str


@dataclass(frozen=True, slots=True)
class RangeAnalysisSnapshot:
    start: datetime
    end: datetime
    candle_count: int
    session_count: int
    start_price: Decimal | None
    end_price: Decimal | None
    high: Decimal | None
    low: Decimal | None
    change_pct: Decimal | None
    range_pct: Decimal | None
    decision_counts: tuple[tuple[str, int], ...]
    regime_counts: tuple[tuple[str, int], ...]
    shadow_trades: int
    shadow_wins: int
    shadow_losses: int
    adjusted_pnl: Decimal
    expectancy: Decimal | None
    news_count: int
    event_count: int
    analysis_notes: tuple[str, ...]
    key_moments: tuple[KeyMoment, ...]
    coverage: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class OpeningPossibilities:
    as_of: datetime
    reference_end: datetime
    next_session_candidate: date
    bullish_weight: Decimal
    balanced_weight: Decimal
    bearish_weight: Decimal
    gap_risk: Decimal
    evidence_coverage: Decimal
    bias_score: Decimal
    drivers: tuple[str, ...]
    limitations: tuple[str, ...]


def _clamp(value: Decimal, low: Decimal, high: Decimal) -> Decimal:
    return min(max(value, low), high)


def _pct(change: Decimal, base: Decimal) -> Decimal:
    if base == 0:
        return Decimal(0)
    return change / base * Decimal(100)


def _next_weekday(day: date) -> date:
    candidate = day + timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate += timedelta(days=1)
    return candidate


def _shadow_stats(
    bundles: Sequence[tuple[DecisionRecord, ShadowTrade, ShadowOutcome]],
) -> tuple[int, int, int, Decimal, Decimal | None]:
    pnls = [bundle[2].adjusted_pnl for bundle in bundles]
    count = len(pnls)
    wins = sum(1 for pnl in pnls if pnl > 0)
    losses = sum(1 for pnl in pnls if pnl < 0)
    total = sum(pnls, Decimal(0))
    expectancy = None if count == 0 else total / Decimal(count)
    return count, wins, losses, total, expectancy


def analyze_historical_range(
    candles: Sequence[Candle],
    decisions: Sequence[DecisionRecord],
    bundles: Sequence[tuple[DecisionRecord, ShadowTrade, ShadowOutcome]],
    news: Sequence[NewsItem],
    events: Sequence[ScheduledEvent],
    start: datetime,
    end: datetime,
) -> RangeAnalysisSnapshot:
    """Summarize a historical window of at most 30 days without causal overclaiming."""

    if start.tzinfo is None or end.tzinfo is None:
        raise HistoricalIntelligenceError("range timestamps must be timezone aware")
    if start >= end:
        raise HistoricalIntelligenceError("range window invalid")
    if end - start > timedelta(days=30, minutes=1):
        raise HistoricalIntelligenceError("range analysis is limited to 30 days")

    candles_in = tuple(sorted(
        (c for c in candles if start <= c.at.astimezone(start.tzinfo) <= end),
        key=lambda c: c.at,
    ))
    decisions_in = tuple(sorted(
        (d for d in decisions if start <= d.decided_at.astimezone(start.tzinfo) <= end),
        key=lambda d: d.decided_at,
    ))
    bundles_in = tuple(
        b for b in bundles if start <= b[1].opened_at.astimezone(start.tzinfo) <= end
    )
    news_in = tuple(
        n for n in news if start <= n.published_at.astimezone(start.tzinfo) <= end
    )
    events_in = tuple(
        e for e in events if start <= e.scheduled_at.astimezone(start.tzinfo) <= end
    )

    start_price = end_price = high = low = change_pct = range_pct = None
    session_count = 0
    if candles_in:
        start_price = candles_in[0].open
        end_price = candles_in[-1].close
        high = max(c.high for c in candles_in)
        low = min(c.low for c in candles_in)
        change_pct = _pct(end_price - start_price, start_price)
        range_pct = _pct(high - low, start_price)
        session_count = len({c.at.astimezone(INDIA_TIME).date() for c in candles_in})

    decision_counts: dict[str, int] = {}
    regime_counts: dict[str, int] = {}
    for decision in decisions_in:
        decision_counts[decision.action] = decision_counts.get(decision.action, 0) + 1
        regime_counts[decision.regime] = regime_counts.get(decision.regime, 0) + 1

    trade_count, wins, losses, adjusted_pnl, expectancy = _shadow_stats(bundles_in)

    moments: list[KeyMoment] = []
    if candles_in:
        previous_close = candles_in[0].open
        ranked_candles: list[tuple[Decimal, Candle]] = []
        for candle in candles_in:
            move = abs(_pct(candle.close - previous_close, previous_close))
            ranked_candles.append((move, candle))
            previous_close = candle.close
        for move, candle in sorted(ranked_candles, key=lambda x: x[0], reverse=True)[:5]:
            moments.append(KeyMoment(
                candle.at,
                "PRICE_MOVE",
                move,
                f"Large one-minute move: {move:.3f}%",
                f"O {candle.open} H {candle.high} L {candle.low} C {candle.close}",
            ))

    for decision in sorted(
        decisions_in,
        key=lambda d: (abs(d.direction_score) + d.confidence / Decimal(4)),
        reverse=True,
    )[:5]:
        importance = abs(decision.direction_score) + decision.confidence / Decimal(4)
        moments.append(KeyMoment(
            decision.decided_at,
            "BRAIN_DECISION",
            importance,
            f"{decision.action} • Direction {decision.direction_score}",
            f"Confidence {decision.confidence}, Entry {decision.entry_quality}, Risk {decision.reversal_risk}, Regime {decision.regime}",
        ))

    for decision, trade, outcome in sorted(
        bundles_in,
        key=lambda b: abs(b[2].adjusted_pnl),
        reverse=True,
    )[:5]:
        moments.append(KeyMoment(
            trade.opened_at,
            "SHADOW_TRADE",
            abs(outcome.adjusted_pnl),
            f"{trade.action} shadow trade • P&L {outcome.adjusted_pnl}",
            f"{outcome.exit_reason}; MFE {outcome.mfe_amount}; MAE {outcome.mae_amount}",
        ))

    for event in events_in:
        importance = Decimal(100 if event.impact == "HIGH" else 60 if event.impact == "MEDIUM" else 25)
        moments.append(KeyMoment(
            event.scheduled_at,
            "EVENT",
            importance,
            f"{event.impact} event • {event.name}",
            f"Source {event.source}; category {event.category}",
        ))

    for item in sorted(news_in, key=lambda n: n.published_at, reverse=True)[:5]:
        moments.append(KeyMoment(
            item.published_at,
            "NEWS_CONTEXT",
            Decimal(20),
            item.title,
            f"Source {item.source}; context only, not treated as proven cause",
        ))

    key_moments = tuple(sorted(
        moments,
        key=lambda m: (-m.importance, m.at),
    )[:20])

    notes: list[str] = []
    if change_pct is not None:
        direction_word = "rose" if change_pct > 0 else "fell" if change_pct < 0 else "finished flat"
        notes.append(
            f"NIFTY {direction_word} {abs(change_pct):.3f}% across {session_count} observed session(s)."
        )
    if regime_counts:
        dominant_regime, dominant_count = max(
            regime_counts.items(), key=lambda item: item[1]
        )
        notes.append(
            f"Most common recorded regime: {dominant_regime} ({dominant_count} decision snapshots)."
        )
    if decision_counts:
        mix = ", ".join(
            f"{name} {count}" for name, count in sorted(decision_counts.items())
        )
        notes.append(f"Recorded decision mix: {mix}.")
    if trade_count:
        notes.append(
            f"Shadow results: {wins} profitable, {losses} losing, adjusted P&L {adjusted_pnl}, expectancy {expectancy}."
        )
    if news_in or events_in:
        notes.append(
            f"Context present: {len(news_in)} cached news item(s) and {len(events_in)} scheduled event(s); these are timestamp context, not automatically treated as causes."
        )
    if key_moments:
        notes.append(
            f"Highest-ranked moment: {key_moments[0].kind} at {key_moments[0].at.astimezone(INDIA_TIME):%Y-%m-%d %H:%M} — {key_moments[0].summary}."
        )

    coverage = (
        ("Candles", "AVAILABLE" if candles_in else "UNAVAILABLE"),
        ("Recorded decisions", "AVAILABLE" if decisions_in else "UNAVAILABLE"),
        ("Shadow outcomes", "AVAILABLE" if bundles_in else "UNAVAILABLE"),
        ("Global/news context", "AVAILABLE" if news_in else "UNAVAILABLE"),
        ("Scheduled events", "AVAILABLE" if events_in else "UNAVAILABLE"),
    )

    return RangeAnalysisSnapshot(
        start=start,
        end=end,
        candle_count=len(candles_in),
        session_count=session_count,
        start_price=start_price,
        end_price=end_price,
        high=high,
        low=low,
        change_pct=change_pct,
        range_pct=range_pct,
        decision_counts=tuple(sorted(decision_counts.items())),
        regime_counts=tuple(sorted(regime_counts.items())),
        shadow_trades=trade_count,
        shadow_wins=wins,
        shadow_losses=losses,
        adjusted_pnl=adjusted_pnl,
        expectancy=expectancy,
        news_count=len(news_in),
        event_count=len(events_in),
        analysis_notes=tuple(notes),
        key_moments=key_moments,
        coverage=coverage,
    )


def build_opening_possibilities(
    analysis: RangeAnalysisSnapshot,
    decisions: Sequence[DecisionRecord],
    candles: Sequence[Candle],
    post_close_news: Sequence[NewsItem],
    upcoming_events: Sequence[ScheduledEvent],
    *,
    as_of: datetime,
) -> OpeningPossibilities:
    """Create evidence-weighted opening scenarios, not calibrated probabilities."""

    if as_of.tzinfo is None:
        raise HistoricalIntelligenceError("opening analysis timestamp must be timezone aware")
    candles_in = tuple(sorted(
        (c for c in candles if analysis.start <= c.at.astimezone(analysis.start.tzinfo) <= analysis.end),
        key=lambda c: c.at,
    ))
    reference_end = (
        candles_in[-1].at.astimezone(analysis.end.tzinfo)
        if candles_in
        else analysis.end
    )
    if as_of < reference_end:
        raise HistoricalIntelligenceError("opening analysis cannot precede the reference market close")

    latest_decision = None
    eligible_decisions = [d for d in decisions if d.decided_at <= reference_end]
    if eligible_decisions:
        latest_decision = max(eligible_decisions, key=lambda d: d.decided_at)

    weighted_votes: list[tuple[str, Decimal, Decimal]] = []
    drivers: list[str] = []

    if latest_decision is not None:
        direction_vote = _clamp(latest_decision.direction_score / Decimal(100), Decimal("-1"), Decimal("1"))
        weighted_votes.append(("Market Brain", direction_vote, Decimal("0.40")))
        drivers.append(f"Final recorded Brain direction: {latest_decision.direction_score}")

        if latest_decision.breadth_pct is not None:
            breadth_vote = _clamp(latest_decision.breadth_pct / Decimal(50), Decimal("-1"), Decimal("1"))
            weighted_votes.append(("Breadth", breadth_vote, Decimal("0.10")))
            drivers.append(f"Final breadth: {latest_decision.breadth_pct}%")

        if latest_decision.atr14 > 0:
            basis_vote = _clamp(latest_decision.basis_change / latest_decision.atr14, Decimal("-1"), Decimal("1"))
            weighted_votes.append(("Basis", basis_vote, Decimal("0.10")))
            drivers.append(f"Final futures basis change / ATR: {basis_vote:.2f}")

    if analysis.change_pct is not None:
        session_vote = _clamp(analysis.change_pct / Decimal("1.0"), Decimal("-1"), Decimal("1"))
        weighted_votes.append(("Range return", session_vote, Decimal("0.20")))
        drivers.append(f"Selected-period NIFTY change: {analysis.change_pct:.3f}%")

    if len(candles_in) >= 2:
        last_at = candles_in[-1].at
        cutoff = last_at - timedelta(minutes=30)
        recent = [c for c in candles_in if c.at >= cutoff]
        if len(recent) >= 2:
            base = recent[0].open
            recent_pct = _pct(recent[-1].close - base, base)
            recent_vote = _clamp(recent_pct / Decimal("0.50"), Decimal("-1"), Decimal("1"))
            weighted_votes.append(("Last 30m momentum", recent_vote, Decimal("0.20")))
            drivers.append(f"Last 30-minute momentum: {recent_pct:.3f}%")

    total_weight = sum((weight for _name, _vote, weight in weighted_votes), Decimal(0))
    bias = Decimal(0)
    if total_weight > 0:
        bias = sum((vote * weight for _name, vote, weight in weighted_votes), Decimal(0)) / total_weight
        bias = _clamp(bias, Decimal("-1"), Decimal("1"))

    raw_bull = Decimal("0.25") + max(bias, Decimal(0))
    raw_bear = Decimal("0.25") + max(-bias, Decimal(0))
    raw_balanced = Decimal("0.25") + max(Decimal(0), Decimal(1) - abs(bias))
    total_raw = raw_bull + raw_bear + raw_balanced
    bullish = raw_bull / total_raw * Decimal(100)
    bearish = raw_bear / total_raw * Decimal(100)
    balanced = raw_balanced / total_raw * Decimal(100)

    high_events = [
        event for event in upcoming_events
        if event.impact == "HIGH" and reference_end <= event.scheduled_at <= as_of + timedelta(hours=24)
    ]
    usable_news = [
        item for item in post_close_news
        if reference_end < item.published_at <= as_of
    ]
    gap_risk = Decimal(0)
    if analysis.range_pct is not None:
        gap_risk += _clamp(analysis.range_pct / Decimal(2) * Decimal(35), Decimal(0), Decimal(35))
    if latest_decision is not None:
        gap_risk += _clamp(latest_decision.reversal_risk / Decimal(100) * Decimal(35), Decimal(0), Decimal(35))
    gap_risk += min(Decimal(len(usable_news) * 2), Decimal(15))
    gap_risk += min(Decimal(len(high_events) * 15), Decimal(30))
    gap_risk = _clamp(gap_risk, Decimal(0), Decimal(100))

    if usable_news:
        drivers.append(f"Post-close global headlines observed: {len(usable_news)} (not direction-scored)")
    if high_events:
        drivers.append(f"Upcoming HIGH-impact events: {len(high_events)}")

    coverage = _clamp(total_weight / Decimal("1.0") * Decimal(100), Decimal(0), Decimal(100))

    limitations = [
        "Scenario weights are heuristic evidence scores, not calibrated probabilities.",
        "Global headlines increase context/gap-risk awareness but are not direction-scored in v0.1.",
        "Exchange holidays are not yet verified by a dedicated market calendar.",
    ]
    if latest_decision is None:
        limitations.append("No recorded Market Brain decision was available at the range end.")
    if not candles_in:
        limitations.append("No stored NIFTY candles were available for the selected range.")

    return OpeningPossibilities(
        as_of=as_of,
        reference_end=reference_end,
        next_session_candidate=_next_weekday(reference_end.astimezone(INDIA_TIME).date()),
        bullish_weight=bullish,
        balanced_weight=balanced,
        bearish_weight=bearish,
        gap_risk=gap_risk,
        evidence_coverage=coverage,
        bias_score=bias * Decimal(100),
        drivers=tuple(drivers),
        limitations=tuple(limitations),
    )
