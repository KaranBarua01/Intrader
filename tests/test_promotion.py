from datetime import datetime, timezone
from decimal import Decimal

from intrader.calibration import CalibrationReport, ThresholdSet
from intrader.performance import PerformanceMetrics
from intrader.promotion import PromotionCriteria, evaluate_promotion


NOW = datetime(2026, 9, 28, 6, 30, tzinfo=timezone.utc)


def _metrics(
    *,
    trades: int,
    expectancy: str,
    profit_factor: str,
    drawdown_pct: str,
) -> PerformanceMetrics:
    wins = trades
    return PerformanceMetrics(
        trades=trades,
        wins=wins,
        losses=0,
        flats=0,
        win_rate=Decimal("100"),
        gross_pnl=Decimal(expectancy) * Decimal(trades),
        adjusted_pnl=Decimal(expectancy) * Decimal(trades),
        average_winner=Decimal(expectancy),
        average_loser=None,
        expectancy=Decimal(expectancy),
        profit_factor=Decimal(profit_factor),
        max_drawdown=Decimal("0"),
        max_drawdown_pct=Decimal(drawdown_pct),
        max_winning_streak=trades,
        max_losing_streak=0,
    )


def _report(test_metrics: PerformanceMetrics) -> CalibrationReport:
    good = _metrics(
        trades=10, expectancy="100", profit_factor="2", drawdown_pct="2"
    )
    return CalibrationReport(
        report_id="CAL-1",
        calibration_version="calibration-v0.1",
        created_at=NOW,
        source_brain_version="brain-v0.1",
        source_rule_version="rules-v0.1",
        total_trades=30,
        train_trades=18,
        validation_trades=6,
        test_trades=6,
        candidate=ThresholdSet(
            Decimal("45"), Decimal("65"), Decimal("60"), Decimal("60")
        ),
        train_metrics=good,
        validation_metrics=good,
        test_metrics=test_metrics,
        limitation="test",
    )


def test_good_untouched_metrics_pass_promotion_gate() -> None:
    report = _report(
        _metrics(
            trades=6,
            expectancy="100",
            profit_factor="1.8",
            drawdown_pct="4",
        )
    )

    result = evaluate_promotion(report, created_at=NOW)

    assert result.status == "PASS"
    assert result.reasons == ()


def test_bad_test_expectancy_profit_factor_and_sample_reject() -> None:
    report = _report(
        _metrics(
            trades=2,
            expectancy="-10",
            profit_factor="0.8",
            drawdown_pct="12",
        )
    )

    result = evaluate_promotion(
        report,
        criteria=PromotionCriteria(minimum_test_trades=5),
        created_at=NOW,
    )

    assert result.status == "REJECT"
    assert "TEST_SAMPLE_TOO_SMALL" in result.reasons
    assert "TEST_EXPECTANCY_NOT_POSITIVE" in result.reasons
    assert "TEST_PROFIT_FACTOR_TOO_LOW" in result.reasons
    assert "TEST_DRAWDOWN_TOO_HIGH" in result.reasons
