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
from intrader.historical_intelligence import analyze_historical_range, build_opening_possibilities
from intrader.historical_reanalysis import reanalyze_stored_decision
from intrader.historical import Candle, INDIA_TIME, fetch_candles
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

    def refresh_global_news(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> int:
        """Fetch global market headlines and cache them locally."""

        end = end or datetime.now(INDIA_TIME)
        start = start or (end - timedelta(hours=24))
        items = fetch_global_market_news(start, end)
        if not items:
            return 0
        with SQLiteStore(self.database_path) as store:
            return store.store_news_items(items)

    def news_for_window(self, start: datetime, end: datetime) -> tuple:
        if start.tzinfo is None or end.tzinfo is None or start >= end:
            return ()
        with SQLiteStore(self.database_path) as store:
            return store.load_news_items(start=start, end=end)

    def records_manager(self):
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

    def refresh_global_news_range(self, start: datetime, end: datetime) -> int:
        """Refresh worldwide market headlines in bounded chunks for Time Travel."""

        if start.tzinfo is None or end.tzinfo is None or start >= end:
            return 0
        if end - start > timedelta(days=30, minutes=1):
            raise ValueError("global news range is limited to 30 days")

        inserted = 0
        cursor = start
        while cursor < end:
            chunk_end = min(cursor + timedelta(days=3), end)
            try:
                items = fetch_global_market_news(
                    cursor, chunk_end, max_records=250
                )
                if items:
                    with SQLiteStore(self.database_path) as store:
                        inserted += store.store_news_items(items)
            except Exception:
                pass
            cursor = chunk_end
        return inserted

    @staticmethod
    def _previous_weekday(day: date) -> date:
        candidate = day
        while candidate.weekday() >= 5:
            candidate -= timedelta(days=1)
        return candidate

    def load_nifty_candle_range(
        self,
        start: datetime,
        end: datetime,
        *,
        backfill_missing: bool = True,
    ) -> tuple[Candle, ...]:
        """Load/backfill up to 30 calendar days of NIFTY one-minute candles."""

        if start.tzinfo is None or end.tzinfo is None or start >= end:
            raise ValueError("candle range invalid")
        if end - start > timedelta(days=30, minutes=1):
            raise ValueError("candle range is limited to 30 days")

        credential_store = CredentialStore()
        transport = RequestsTransport()
        session = authenticate(credential_store, transport)
        reference_day = self._previous_weekday(end.astimezone(INDIA_TIME).date())
        market = check_market_access(
            credential_store,
            transport,
            as_of=reference_day,
            session=session,
        )
        spot = market.instruments.spot

        with SQLiteStore(self.database_path) as store:
            existing = store.load_candles(
                spot.exchange,
                spot.token,
                "ONE_MINUTE",
                start=start,
                end=end,
            )
            if not backfill_missing:
                return existing

            existing_days = {
                candle.at.astimezone(INDIA_TIME).date()
                for candle in existing
            }
            day = start.astimezone(INDIA_TIME).date()
            last_day = end.astimezone(INDIA_TIME).date()
            while day <= last_day:
                if day.weekday() < 5 and day not in existing_days:
                    session_start = datetime.combine(
                        day, time(9, 15), INDIA_TIME
                    )
                    session_end = datetime.combine(
                        day, time(15, 30), INDIA_TIME
                    )
                    fetch_start = max(start.astimezone(INDIA_TIME), session_start)
                    fetch_end = min(end.astimezone(INDIA_TIME), session_end)
                    if fetch_start < fetch_end:
                        try:
                            rows = fetch_candles(
                                session,
                                transport,
                                spot,
                                fetch_start,
                                fetch_end,
                                "ONE_MINUTE",
                            )
                            if rows:
                                store.store_candles(spot, "ONE_MINUTE", rows)
                        except Exception:
                            # Holidays/source gaps remain explicitly unavailable.
                            pass
                day += timedelta(days=1)

            return store.load_candles(
                spot.exchange,
                spot.token,
                "ONE_MINUTE",
                start=start,
                end=end,
            )

    def analyze_time_range(self, start: datetime, end: datetime):
        """Build range intelligence plus a pre-open scenario snapshot."""

        candles = self.load_nifty_candle_range(start, end, backfill_missing=True)
        self.refresh_global_news_range(start, end)

        with SQLiteStore(self.database_path) as store:
            decisions = tuple(
                d for d in store.load_decision_records()
                if start <= d.decided_at.astimezone(start.tzinfo) <= end
            )
            bundles = tuple(
                b for b in store.load_completed_shadow_bundles()
                if start <= b[1].opened_at.astimezone(start.tzinfo) <= end
            )
            news = store.load_news_items(start=start, end=end)
            events = store.load_scheduled_events(start=start, end=end)

        analysis = analyze_historical_range(
            candles, decisions, bundles, news, events, start, end
        )

        reference_close = (
            candles[-1].at.astimezone(INDIA_TIME)
            if candles
            else end.astimezone(INDIA_TIME)
        )
        next_day = reference_close.date() + timedelta(days=1)
        while next_day.weekday() >= 5:
            next_day += timedelta(days=1)
        pre_open = datetime.combine(next_day, time(9, 0), INDIA_TIME)
        now = datetime.now(INDIA_TIME)
        opening_as_of = min(now, pre_open)
        if opening_as_of < reference_close:
            opening_as_of = reference_close

        try:
            self.refresh_global_news_range(reference_close, opening_as_of)
        except Exception:
            pass

        with SQLiteStore(self.database_path) as store:
            post_close_news = store.load_news_items(
                start=reference_close,
                end=opening_as_of,
            )
            upcoming_events = store.load_scheduled_events(
                start=reference_close,
                end=pre_open + timedelta(hours=8),
            )

        opening = build_opening_possibilities(
            analysis,
            decisions,
            candles,
            post_close_news,
            upcoming_events,
            as_of=opening_as_of,
        )
        return analysis, opening, candles, news, events

    def reanalyze_timestamp(self, at: datetime):
        """Run the current Brain against stored historical data without writes."""

        if at.tzinfo is None:
            raise ValueError("reanalysis timestamp must be timezone aware")
        day = at.astimezone(INDIA_TIME).date()
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
        with SQLiteStore(self.database_path) as store:
            before = store.count("decision_records")
            record = reanalyze_stored_decision(
                store,
                market.instruments,
                day,
                at,
                config,
            )
            after = store.count("decision_records")
        if after != before:
            raise RuntimeError("historical reanalysis mutated immutable history")
        return record

    def calibration_report(self):
        from intrader.calibration_pipeline import run_calibration
        with SQLiteStore(self.database_path) as store:
            return run_calibration(store)

    def promotion_report(self):
        from intrader.calibration_pipeline import run_promotion_gate
        with SQLiteStore(self.database_path) as store:
            return run_promotion_gate(store)
