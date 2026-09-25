"""Provider-independent market breadth measurements for Intrader Phase 2."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol, Sequence


class BreadthError(Exception):
    """Breadth inputs are incomplete or internally invalid."""


@dataclass(frozen=True, slots=True)
class BreadthMember:
    symbol: str
    previous_close: Decimal
    current_price: Decimal
    weight: Decimal | None = None
    sector: str | None = None


@dataclass(frozen=True, slots=True)
class BreadthContribution:
    symbol: str
    change_pct: Decimal
    weighted_contribution_pct: Decimal | None


@dataclass(frozen=True, slots=True)
class SectorBreadth:
    sector: str
    advancing: int
    declining: int
    unchanged: int
    equal_weight_breadth_pct: Decimal


@dataclass(frozen=True, slots=True)
class BreadthSnapshot:
    at: datetime
    total: int
    advancing: int
    declining: int
    unchanged: int
    advance_decline_ratio: Decimal | None
    equal_weight_breadth_pct: Decimal
    weighted_return_pct: Decimal | None
    top_positive_contributors: tuple[BreadthContribution, ...]
    top_negative_contributors: tuple[BreadthContribution, ...]
    sectors: tuple[SectorBreadth, ...]


class BreadthProvider(Protocol):
    """Boundary for a cached constituent-price source."""

    def load(self, at: datetime) -> Sequence[BreadthMember]:
        ...


def _change_pct(member: BreadthMember) -> Decimal:
    if not member.symbol:
        raise BreadthError("breadth symbol unavailable")
    if (
        member.previous_close <= 0
        or member.current_price <= 0
        or not member.previous_close.is_finite()
        or not member.current_price.is_finite()
    ):
        raise BreadthError("breadth price invalid")
    if member.weight is not None and (
        member.weight < 0 or not member.weight.is_finite()
    ):
        raise BreadthError("breadth weight invalid")
    return (
        (member.current_price - member.previous_close)
        / member.previous_close
        * Decimal(100)
    )


def _classification(change_pct: Decimal) -> int:
    if change_pct > 0:
        return 1
    if change_pct < 0:
        return -1
    return 0


def build_breadth_snapshot(
    members: Sequence[BreadthMember],
    at: datetime,
    *,
    top_n: int = 5,
) -> BreadthSnapshot:
    """Build raw advance/decline and weighted leadership measurements."""

    if at.tzinfo is None:
        raise BreadthError("breadth timestamp must be timezone aware")
    if not members:
        raise BreadthError("breadth members unavailable")
    if top_n <= 0:
        raise BreadthError("breadth top_n invalid")

    seen: set[str] = set()
    changes: list[tuple[BreadthMember, Decimal]] = []
    for member in members:
        if member.symbol in seen:
            raise BreadthError("duplicate breadth symbol")
        seen.add(member.symbol)
        changes.append((member, _change_pct(member)))

    advancing = sum(1 for _, change in changes if change > 0)
    declining = sum(1 for _, change in changes if change < 0)
    unchanged = len(changes) - advancing - declining
    equal_weight = (
        Decimal(advancing - declining)
        / Decimal(len(changes))
        * Decimal(100)
    )
    ad_ratio = (
        None
        if declining == 0
        else Decimal(advancing) / Decimal(declining)
    )

    weighted_return: Decimal | None = None
    contributions: list[BreadthContribution] = []
    if all(member.weight is not None for member, _ in changes):
        total_weight = sum(
            (member.weight or Decimal(0) for member, _ in changes),
            Decimal(0),
        )
        if total_weight > 0:
            weighted_return = sum(
                (
                    (member.weight or Decimal(0)) * change
                    for member, change in changes
                ),
                Decimal(0),
            ) / total_weight
            for member, change in changes:
                contribution = (
                    (member.weight or Decimal(0))
                    / total_weight
                    * change
                )
                contributions.append(
                    BreadthContribution(
                        member.symbol,
                        change,
                        contribution,
                    )
                )
    if not contributions:
        contributions = [
            BreadthContribution(member.symbol, change, None)
            for member, change in changes
        ]

    positives = tuple(
        sorted(
            (item for item in contributions if item.change_pct > 0),
            key=lambda item: (
                item.weighted_contribution_pct
                if item.weighted_contribution_pct is not None
                else item.change_pct
            ),
            reverse=True,
        )[:top_n]
    )
    negatives = tuple(
        sorted(
            (item for item in contributions if item.change_pct < 0),
            key=lambda item: (
                item.weighted_contribution_pct
                if item.weighted_contribution_pct is not None
                else item.change_pct
            ),
        )[:top_n]
    )

    sector_names = sorted(
        {member.sector for member, _ in changes if member.sector}
    )
    sectors: list[SectorBreadth] = []
    for sector in sector_names:
        sector_changes = [
            change
            for member, change in changes
            if member.sector == sector
        ]
        sector_advancing = sum(1 for change in sector_changes if change > 0)
        sector_declining = sum(1 for change in sector_changes if change < 0)
        sector_unchanged = (
            len(sector_changes) - sector_advancing - sector_declining
        )
        sector_score = (
            Decimal(sector_advancing - sector_declining)
            / Decimal(len(sector_changes))
            * Decimal(100)
        )
        sectors.append(
            SectorBreadth(
                sector=sector,
                advancing=sector_advancing,
                declining=sector_declining,
                unchanged=sector_unchanged,
                equal_weight_breadth_pct=sector_score,
            )
        )

    return BreadthSnapshot(
        at=at,
        total=len(changes),
        advancing=advancing,
        declining=declining,
        unchanged=unchanged,
        advance_decline_ratio=ad_ratio,
        equal_weight_breadth_pct=equal_weight,
        weighted_return_pct=weighted_return,
        top_positive_contributors=positives,
        top_negative_contributors=negatives,
        sectors=tuple(sectors),
    )
