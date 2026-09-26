"""Read-only desktop data facade over Intrader backend services."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path

from intrader.auth import RequestsTransport, authenticate
from intrader.checkpoint2 import check_market_access
from intrader.config import load_config
from intrader.credentials import CredentialStore
from intrader.global_news import fetch_global_market_news
from intrader.historical import Candle, INDIA_TIME
from intrader.records import DecisionRecord
from intrader.shadow import ShadowTrade
from intrader.storage import SQLiteStore
from intrader.ui.paths import database_path as default_database_path


@dataclass(frozen=True, slots=True)
class DesktopSnapshot:
    latest_decision: DecisionRecord | None
    active_shadow_trade: ShadowTrade | None
    completed_bundles: tuple
    recent_news: tuple
    upcoming_events: tuple
    database_counts: tuple[tuple[str, int], ...]


class DesktopDataService:
    def __init__(self, database_path: Path | None = None) -> None:
        self.database_path = database_path or default_database_path()

    def snapshot(self, now: datetime | None = None) -> DesktopSnapshot:
        now = now or datetime.now(INDIA_TIME)
        with SQLiteStore(self.database_path) as store:
            decisions = store.load_decision_records()
            unsettled = store.load_unsettled_shadow_trades()
            completed = store.load_completed_shadow_bundles()
            news = store.load_news_items(start=now - timedelta(hours=24), end=now)
            events = store.load_scheduled_events(
                start=now - timedelta(minutes=15),
                end=now + timedelta(hours=24),
            )
            counts = []
            for table in (
                "candles", "option_snapshots", "index_snapshots",
                "future_snapshots", "breadth_snapshots", "decision_records",
                "shadow_trades", "shadow_outcomes", "reason_audits",
            ):
                try:
                    counts.append((table, store.count(table)))
                except Exception:
                    counts.append((table, -1))
        return DesktopSnapshot(
            latest_decision=None if not decisions else decisions[-1],
            active_shadow_trade=None if not unsettled else unsettled[-1],
            completed_bundles=completed,
            recent_news=news,
            upcoming_events=events,
            database_counts=tuple(counts),
        )

    def refresh_global_news(\n        self,\n        start: datetime | None = None,\n        end: datetime | None = None,\n    ) -> int:\n        """Fetch global market headlines and cache them locally."""\n\n        end = end or datetime.now(INDIA_TIME)\n        start = start or (end - timedelta(hours=24))\n        items = fetch_global_market_news(start, end)\n        if not items:\n            return 0\n        with SQLiteStore(self.database_path) as store:\n            return store.store_news_items(items)\n\n    def news_for_window(self, start: datetime, end: datetime) -> tuple:\n        if start.tzinfo is None or end.tzinfo is None or start >= end:\n            return ()\n        with SQLiteStore(self.database_path) as store:\n            return store.load_news_items(start=start, end=end)\n    def records_manager(self):
        from intrader.records_manager_pipeline import build_records_manager
        with SQLiteStore(self.database_path) as store:
            return build_records_manager(store)

    def decisions_for_day(self, day: date) -> tuple[DecisionRecord, ...]:
        with SQLiteStore(self.database_path) as store:
            return tuple(
                decision for decision in store.load_decision_records()
                if decision.session_date == day
            )

    def completed_for_day(self, day: date) -> tuple:
        with SQLiteStore(self.database_path) as store:
            return tuple(
                bundle for bundle in store.load_completed_shadow_bundles()
                if bundle[0].session_date == day
            )

    def reason_audits(self) -> tuple:
        with SQLiteStore(self.database_path) as store:
            return store.load_reason_audits()

    def load_nifty_candles(self, day: date) -> tuple[Candle, ...]:
        """Resolve NIFTY through the existing read-only market-access layer."""
        config = load_config()
        credential_store = CredentialStore()
        transport = RequestsTransport()
        session = authenticate(credential_store, transport)
        market = check_market_access(
            credential_store,
            transport,
            as_of=day,
            session=session,
        )
        start = datetime.combine(day, time(9, 15), INDIA_TIME)
        end = datetime.combine(day, time(15, 30), INDIA_TIME)
        with SQLiteStore(self.database_path) as store:
            return store.load_candles(
                market.instruments.spot.exchange,
                market.instruments.spot.token,
                "ONE_MINUTE",
                start=start,
                end=end,
            )

    def calibration_report(self):
        from intrader.calibration_pipeline import run_calibration
        with SQLiteStore(self.database_path) as store:
            return run_calibration(store)

    def promotion_report(self):
        from intrader.calibration_pipeline import run_promotion_gate
        with SQLiteStore(self.database_path) as store:
            return run_promotion_gate(store)
