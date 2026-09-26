from datetime import datetime, timedelta

import pytest

from intrader.historical import Candle, INDIA_TIME
from intrader.strategy_lab import STRATEGIES, analyze_strategies


def _candle(at, open_, high, low, close, volume=1000):
    from decimal import Decimal

    return Candle(
        at,
        Decimal(str(open_)),
        Decimal(str(high)),
        Decimal(str(low)),
        Decimal(str(close)),
        volume,
    )


def _series():
    start = datetime(2026, 9, 25, 9, 15, tzinfo=INDIA_TIME)
    rows = [
        _candle(start, 100, 101, 98.5, 99),
        _candle(start + timedelta(minutes=1), 98.8, 102, 98.5, 101.5),
    ]
    price = 101.5
    for minute in range(2, 40):
        open_ = price
        price += 0.10
        rows.append(
            _candle(
                start + timedelta(minutes=minute),
                open_,
                price + 0.15,
                open_ - 0.10,
                price,
            )
        )
    return tuple(rows)


def test_strategy_lab_detects_bullish_engulfing_and_forward_result() -> None:
    candles = _series()
    result = analyze_strategies(
        candles,
        (),
        candles[0].at,
        candles[-1].at,
    )

    engulfing = next(
        strategy
        for strategy in result.strategies
        if strategy.definition.strategy_id == "NISON_BULLISH_ENGULFING"
    )

    assert engulfing.signals >= 1
    assert engulfing.bullish_signals >= 1
    assert engulfing.hit_rate_5m is not None
    assert engulfing.hit_rate_5m > 0
    assert engulfing.avg_return_30m is not None
    assert engulfing.avg_return_30m > 0


def test_douglas_is_process_only_not_candle_prediction() -> None:
    candles = _series()
    result = analyze_strategies(
        candles,
        (),
        candles[0].at,
        candles[-1].at,
    )

    douglas = next(
        strategy
        for strategy in result.strategies
        if strategy.definition.strategy_id == "DOUGLAS_PROCESS_DISCIPLINE"
    )

    assert douglas.signals == 0
    assert douglas.sample_label == "NO SIGNALS"
    assert douglas.hit_rate_30m is None


def test_catalog_contains_all_four_book_families() -> None:
    sources = {strategy.source for strategy in STRATEGIES}

    assert any("Steve Nison" in source for source in sources)
    assert any("Ashwani Gujral" in source for source in sources)
    assert any("John Carter" in source for source in sources)
    assert any("Mark Douglas" in source for source in sources)


def test_strategy_lab_rejects_more_than_30_days() -> None:
    start = datetime(2026, 8, 1, 9, 15, tzinfo=INDIA_TIME)
    end = start + timedelta(days=31)

    with pytest.raises(ValueError, match="30 days"):
        analyze_strategies((), (), start, end)
