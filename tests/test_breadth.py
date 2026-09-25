from datetime import datetime, timezone
from decimal import Decimal

import pytest

from intrader.breadth import (
    BreadthError,
    BreadthMember,
    build_breadth_snapshot,
)


NOW = datetime(2026, 9, 28, 6, 30, tzinfo=timezone.utc)


def test_breadth_counts_weighted_return_contributors_and_sectors() -> None:
    members = (
        BreadthMember(
            "A", Decimal("100"), Decimal("102"),
            Decimal("40"), "Financials",
        ),
        BreadthMember(
            "B", Decimal("100"), Decimal("99"),
            Decimal("30"), "Financials",
        ),
        BreadthMember(
            "C", Decimal("100"), Decimal("101"),
            Decimal("20"), "Technology",
        ),
        BreadthMember(
            "D", Decimal("100"), Decimal("100"),
            Decimal("10"), "Technology",
        ),
    )

    result = build_breadth_snapshot(members, NOW)

    assert result.total == 4
    assert result.advancing == 2
    assert result.declining == 1
    assert result.unchanged == 1
    assert result.advance_decline_ratio == Decimal("2")
    assert result.equal_weight_breadth_pct == Decimal("25")
    assert result.weighted_return_pct == Decimal("0.7")
    assert result.top_positive_contributors[0].symbol == "A"
    assert result.top_positive_contributors[0].weighted_contribution_pct == Decimal("0.8")
    assert result.top_negative_contributors[0].symbol == "B"
    assert result.top_negative_contributors[0].weighted_contribution_pct == Decimal("-0.3")

    sectors = {sector.sector: sector for sector in result.sectors}
    assert sectors["Financials"].equal_weight_breadth_pct == Decimal("0")
    assert sectors["Technology"].equal_weight_breadth_pct == Decimal("50")


def test_breadth_without_weights_still_produces_counts() -> None:
    result = build_breadth_snapshot(
        (
            BreadthMember("A", Decimal("100"), Decimal("101")),
            BreadthMember("B", Decimal("100"), Decimal("99")),
        ),
        NOW,
    )

    assert result.weighted_return_pct is None
    assert result.equal_weight_breadth_pct == Decimal("0")
    assert all(
        item.weighted_contribution_pct is None
        for item in (
            *result.top_positive_contributors,
            *result.top_negative_contributors,
        )
    )


def test_zero_decliners_has_unavailable_ad_ratio() -> None:
    result = build_breadth_snapshot(
        (
            BreadthMember("A", Decimal("100"), Decimal("101")),
            BreadthMember("B", Decimal("100"), Decimal("102")),
        ),
        NOW,
    )

    assert result.advance_decline_ratio is None
    assert result.equal_weight_breadth_pct == Decimal("100")


def test_duplicate_symbol_and_invalid_prices_fail_closed() -> None:
    with pytest.raises(BreadthError, match="duplicate"):
        build_breadth_snapshot(
            (
                BreadthMember("A", Decimal("100"), Decimal("101")),
                BreadthMember("A", Decimal("100"), Decimal("102")),
            ),
            NOW,
        )

    with pytest.raises(BreadthError, match="price invalid"):
        build_breadth_snapshot(
            (BreadthMember("A", Decimal("0"), Decimal("101")),),
            NOW,
        )
