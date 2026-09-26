from decimal import Decimal

from intrader.performance import PerformanceMetrics, RecordsManagerSnapshot
from intrader.records_manager_pipeline import build_records_manager


class FakeStore:
    def load_decision_records(self):
        return ()

    def load_completed_shadow_bundles(self):
        return ()

    def load_reason_audits(self, **_kwargs):
        return ()


def test_empty_records_manager_is_valid() -> None:
    result = build_records_manager(FakeStore(), starting_capital=Decimal("100000"))

    assert result.current_equity == Decimal("100000")
    assert result.overall.trades == 0
    assert result.decision_counts == ()
