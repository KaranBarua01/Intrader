from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from intrader.context import NewsItem, ScheduledEvent
from intrader.historical import Candle, INDIA_TIME
from intrader.historical_intelligence import (
    HistoricalIntelligenceError,
    analyze_historical_range,
    build_opening_possibilities,
)
from intrader.market_brain import FamilyEvidence
from intrader.records import DecisionRecord


START = datetime(2026, 9, 25, 9, 15, tzinfo=INDIA_TIME)
END = datetime(2026, 9, 25, 15, 30, tzinfo=INDIA_TIME)


def _decision(at: datetime, direction: str = "60") -> DecisionRecord:
    return DecisionRecord(
        decision_id=f"DEC-{at:%H%M}",
        decided_at=at,
        session_date=at.date(),
        brain_version="brain-v0.1",
        rule_version="rules-v0.1",
        brain_state="BULLISH SETUP",
        action="BUY_CALL",
        rejected_action="BUY_PUT",
        direction_score=Decimal(direction),
        entry_quality=Decimal("70"),
        reversal_risk=Decimal("30"),
        confidence=Decimal("75"),
        family_coverage=Decimal("100"),
        regime="TRENDING_UP",
        spot_price=Decimal("23150"),
        future_price=Decimal("23200"),
        vix=Decimal("12"),
        ema9=Decimal("23140"),
        ema20=Decimal("23120"),
        rsi14=Decimal("62"),
        atr14=Decimal("30"),
        opening_range_high=Decimal("23100"),
        opening_range_low=Decimal("23000"),
        future_oi=100000,
        future_oi_change=5000,
        future_volume_change=20000,
        basis=Decimal("50"),
        basis_change=Decimal("6"),
        oi_pcr=Decimal("1.1"),
        volume_pcr=Decimal("1.0"),
        breadth_pct=Decimal("25"),
        depth_imbalance=Decimal("0.2"),
        high_impact_event_active=False,
        families=(FamilyEvidence("PRICE", Decimal("30"), Decimal("0.7")),),
        reasons=(),
    )


def _candles() -> tuple[Candle, ...]:
    return (
        Candle(START, Decimal("23100"), Decimal("23120"), Decimal("23090"), Decimal("23110"), 1000),
        Candle(START + timedelta(minutes=30), Decimal("23110"), Decimal("23180"), Decimal("23105"), Decimal("23170"), 1400),
        Candle(END, Decimal("23170"), Decimal("23220"), Decimal("23160"), Decimal("23200"), 1800),
    )


def test_range_analysis_summarizes_price_decisions_context() -> None:
    decision = _decision(END - timedelta(minutes=5))
    news = (
        NewsItem("source", "Global market headline", END - timedelta(hours=1), "https://example.test/a", "GLOBAL_MARKET_NEWS"),
    )
    events = (
        ScheduledEvent("FED", "Policy event", END - timedelta(hours=2), "FOMC", "HIGH"),
    )

    result = analyze_historical_range(
        _candles(), (decision,), (), news, events, START, END
    )

    assert result.candle_count == 3
    assert result.session_count == 1
    assert result.change_pct is not None and result.change_pct > 0
    assert dict(result.decision_counts) == {"BUY_CALL": 1}
    assert dict(result.regime_counts) == {"TRENDING_UP": 1}
    assert result.news_count == 1
    assert result.event_count == 1
    assert result.analysis_notes
    assert "NIFTY rose" in result.analysis_notes[0]
    assert any(moment.kind == "BRAIN_DECISION" for moment in result.key_moments)
    assert any(moment.kind == "NEWS_CONTEXT" for moment in result.key_moments)
    assert dict(result.coverage)["Candles"] == "AVAILABLE"


def test_range_analysis_rejects_more_than_30_days() -> None:
    with pytest.raises(HistoricalIntelligenceError, match="30 days"):
        analyze_historical_range(
            (), (), (), (), (), START, START + timedelta(days=31)
        )


def test_opening_possibilities_are_weights_not_probabilities() -> None:
    decision = _decision(END - timedelta(minutes=5), "65")
    analysis = analyze_historical_range(
        _candles(), (decision,), (), (), (), START, END
    )
    news = (
        NewsItem("source", "Overnight global headline", END + timedelta(hours=1), "https://example.test/b", "GLOBAL_MARKET_NEWS"),
    )
    events = (
        ScheduledEvent("BLS", "Jobs data", END + timedelta(hours=12), "EMPLOYMENT", "HIGH"),
    )

    result = build_opening_possibilities(
        analysis,
        (decision,),
        _candles(),
        news,
        events,
        as_of=END + timedelta(hours=13),
    )

    total = result.bullish_weight + result.balanced_weight + result.bearish_weight
    assert abs(total - Decimal(100)) < Decimal("0.0001")
    assert result.bullish_weight > result.bearish_weight
    assert result.gap_risk > 0
    assert result.evidence_coverage > 0
    assert result.next_session_candidate == date(2026, 9, 28)
    assert any("not calibrated probabilities" in item for item in result.limitations)
