"""Read-only desktop data facade over Intrader backend services."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path

from intrader.auth import RequestsTransport, authenticate
from intrader.checkpoint2 import check_market_access
from intrader.config import load_config
from intrader.credentials import CredentialStore
from intrader.global_news import fetch_global_market_news, market_relevance_score
from intrader.context_pipeline import refresh_context
from intrader.context_sources import RequestsContextTransport
from intrader.historical_intelligence import analyze_historical_range, build_opening_possibilities
from intrader.historical_reanalysis import reanalyze_stored_decision
from intrader.historical import Candle, INDIA_TIME, fetch_candles
from intrader.records import DecisionRecord
from intrader.shadow import ShadowTrade
from intrader.shadow_lab import REPLAY_SESSION_OPTIONS
from intrader.shadow_replay import ShadowReplayReport, run_candle_proxy_replay
from intrader.storage import SQLiteStore
from intrader.strategy_lab import analyze_strategies
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
            news = tuple(
                item
                for item in store.load_news_items(
                    start=now - timedelta(hours=24), end=now
                )
                if market_relevance_score(item.title, item.source) >= 3
            )
            events = store.load_scheduled_events(
                start=now - timedelta(minutes=15),
                end=now + timedelta(hours=24),
            )
            counts = []
            for table in (
                "candles", "oi_observations", "option_snapshots", "index_snapshots",
                "future_snapshots", "breadth_snapshots", "news_items",
                "scheduled_events", "decision_records", "shadow_trades",
                "shadow_outcomes", "reason_audits",
            ):
                try:
                    counts.append((table, store.count(table)))
                except Exception:
                    counts.append((table, -1))
            counts.append(
                (
                    "order_flow_context",
                    sum(1 for d in decisions if d.depth_imbalance is not None),
                )
            )
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
        with SQLiteStore(self.database_path, read_only=True) as store:
            return tuple(
                item
                for item in store.load_news_items(start=start, end=end)
                if market_relevance_score(item.title, item.source) >= 3
            )

    def records_manager(self):
        from intrader.records_manager_pipeline import build_records_manager
        with SQLiteStore(self.database_path) as store:
            return build_records_manager(store)

    def decisions_for_day(self, day: date) -> tuple[DecisionRecord, ...]:
        with SQLiteStore(self.database_path, read_only=True) as store:
            return tuple(
                decision for decision in store.load_decision_records()
                if decision.session_date == day
            )

    def completed_for_day(self, day: date) -> tuple:
        with SQLiteStore(self.database_path, read_only=True) as store:
            return tuple(
                bundle for bundle in store.load_completed_shadow_bundles()
                if bundle[0].session_date == day
            )

    def reason_audits(self) -> tuple:
        with SQLiteStore(self.database_path, read_only=True) as store:
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
        backfill_missing: bool = False,
    ) -> tuple[Candle, ...]:
        """Load NIFTY candles locally; network backfill is explicit opt-in."""

        if start.tzinfo is None or end.tzinfo is None or start >= end:
            raise ValueError("candle range invalid")
        if end - start > timedelta(days=30, minutes=1):
            raise ValueError("candle range is limited to 30 days")

        with SQLiteStore(self.database_path, read_only=True) as store:
            existing = store.load_primary_index_candles(
                "ONE_MINUTE",
                start=start,
                end=end,
            )
        if not backfill_missing:
            return existing

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

    @staticmethod
    def _last_completed_market_day(now: datetime) -> date:
        local = now.astimezone(INDIA_TIME)
        candidate = local.date()
        if candidate.weekday() >= 5 or local.time() < time(15, 30):
            candidate -= timedelta(days=1)
        while candidate.weekday() >= 5:
            candidate -= timedelta(days=1)
        return candidate

    def load_shadow_replay_candles(
        self,
        sessions: int,
        *,
        now: datetime | None = None,
    ) -> tuple[Candle, ...]:
        """Fetch enough complete NIFTY history for a 30/60/90-session replay."""

        if sessions not in REPLAY_SESSION_OPTIONS:
            raise ValueError("unsupported Shadow Trader replay range")
        now = now or datetime.now(INDIA_TIME)
        end_day = self._last_completed_market_day(now)
        end = datetime.combine(end_day, time(15, 30), INDIA_TIME)

        # Generous calendar lookback covers weekends and exchange holidays while
        # keeping each Angel request inside the 30-day one-minute limit.
        start_day = end_day - timedelta(days=sessions * 2 + 35)
        start = datetime.combine(start_day, time(9, 15), INDIA_TIME)

        merged: dict[datetime, Candle] = {}
        cursor = start
        while cursor < end:
            chunk_end = min(cursor + timedelta(days=27), end)
            rows = self.load_nifty_candle_range(
                cursor,
                chunk_end,
                backfill_missing=True,
            )
            for candle in rows:
                merged[candle.at] = candle
            cursor = chunk_end

        ordered = tuple(sorted(merged.values(), key=lambda item: item.at))
        session_dates = {
            candle.at.astimezone(INDIA_TIME).date()
            for candle in ordered
        }
        if len(session_dates) < sessions:
            raise ValueError(
                f"only {len(session_dates)} historical NIFTY sessions are available; "
                f"{sessions} were requested"
            )
        return ordered

    def run_shadow_replay(
        self,
        sessions: int,
        mode_key: str,
    ) -> ShadowReplayReport:
        """Run the current safe historical candle-proxy replay."""

        candles = self.load_shadow_replay_candles(sessions)
        return run_candle_proxy_replay(
            candles,
            sessions=sessions,
            mode_key=mode_key,
        )

    def analyze_time_range(
        self,
        start: datetime,
        end: datetime,
        *,
        enrich_missing: bool = False,
    ):
        """Build range intelligence from the full selected window.

        When enrichment is enabled, candles, global news and authoritative
        macro context are refreshed on a best-effort basis before analysis.
        Unsupported historical families remain explicitly unavailable instead
        of being fabricated.
        """

        if enrich_missing:
            try:
                candles = self.load_nifty_candle_range(
                    start,
                    end,
                    backfill_missing=True,
                )
            except Exception:
                candles = self.load_nifty_candle_range(
                    start,
                    end,
                    backfill_missing=False,
                )
            try:
                self.refresh_global_news_range(start, end)
            except Exception:
                pass
            try:
                with SQLiteStore(self.database_path) as store:
                    refresh_context(
                        store,
                        RequestsContextTransport(),
                        end,
                        recent_hours=max(
                            24,
                            min(
                                24 * 31,
                                int((end - start).total_seconds() // 3600) + 24,
                            ),
                        ),
                        lookahead_hours=24,
                    )
            except Exception:
                pass
        else:
            candles = self.load_nifty_candle_range(
                start,
                end,
                backfill_missing=False,
            )

        with SQLiteStore(self.database_path, read_only=True) as store:
            decisions = tuple(
                d for d in store.load_decision_records()
                if start <= d.decided_at.astimezone(start.tzinfo) <= end
            )
            bundles = tuple(
                b for b in store.load_completed_shadow_bundles()
                if start <= b[1].opened_at.astimezone(start.tzinfo) <= end
            )
            news = tuple(
                item
                for item in store.load_news_items(start=start, end=end)
                if market_relevance_score(item.title, item.source) >= 3
            )
            events = store.load_scheduled_events(start=start, end=end)
            coverage_counts = {
                "Candles": len(candles),
                "Options": store.count_time_range_rows(
                    "option_snapshots", start=start, end=end
                ),
                "Futures": store.count_time_range_rows(
                    "future_snapshots", start=start, end=end
                ),
                "VIX / Index": store.count_time_range_rows(
                    "index_snapshots", start=start, end=end
                ),
                "Breadth": store.count_time_range_rows(
                    "breadth_snapshots", start=start, end=end
                ),
                "Order flow": sum(
                    1 for d in decisions if d.depth_imbalance is not None
                ),
                "Recorded decisions": len(decisions),
                "Shadow outcomes": len(bundles),
                "Global/news context": len(news),
                "Scheduled events": len(events),
            }

        analysis = analyze_historical_range(
            candles, decisions, bundles, news, events, start, end,
            coverage_counts=coverage_counts,
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

        with SQLiteStore(self.database_path, read_only=True) as store:
            post_close_news = tuple(
                item
                for item in store.load_news_items(
                    start=reference_close,
                    end=opening_as_of,
                )
                if market_relevance_score(item.title, item.source) >= 3
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

    def analyze_session_to_now(
        self,
        at: datetime | None = None,
    ):
        """Analyze the complete current or most-recent session up to a timestamp.

        The advisory action comes only from an immutable Market Brain decision
        recorded inside that session. Candle-only evidence never fabricates a
        CALL/PUT recommendation.
        """

        at = (at or datetime.now(INDIA_TIME)).astimezone(INDIA_TIME)
        session_day = at.date()

        if session_day.weekday() >= 5 or at.time() < time(9, 15):
            session_day -= timedelta(days=1)
            while session_day.weekday() >= 5:
                session_day -= timedelta(days=1)
            session_end = datetime.combine(
                session_day,
                time(15, 30),
                INDIA_TIME,
            )
        else:
            market_close = datetime.combine(
                session_day,
                time(15, 30),
                INDIA_TIME,
            )
            session_end = min(at, market_close)

        session_start = datetime.combine(
            session_day,
            time(9, 15),
            INDIA_TIME,
        )
        analysis, opening, candles, news, events = self.analyze_time_range(
            session_start,
            session_end,
            enrich_missing=True,
        )
        with SQLiteStore(self.database_path, read_only=True) as store:
            decisions = tuple(
                decision
                for decision in store.load_decision_records()
                if session_start
                <= decision.decided_at.astimezone(INDIA_TIME)
                <= session_end
            )
        latest = decisions[-1] if decisions else None
        return (
            analysis,
            opening,
            candles,
            news,
            events,
            latest,
            session_start,
            session_end,
        )

    def enrich_time_range(self, start: datetime, end: datetime) -> tuple[int, int]:
        """Explicitly fetch missing candles/news for a historical range."""

        before = self.load_nifty_candle_range(start, end, backfill_missing=False)
        after = self.load_nifty_candle_range(start, end, backfill_missing=True)
        inserted_news = self.refresh_global_news_range(start, end)
        return max(0, len(after) - len(before)), inserted_news

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
        with SQLiteStore(self.database_path, read_only=True) as store:
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

    def analyze_strategy_range(self, start: datetime, end: datetime):
        """Run Strategy Lab on the same historical candle range used by Time Travel."""

        candles = self.load_nifty_candle_range(
            start,
            end,
            backfill_missing=False,
        )
        with SQLiteStore(self.database_path, read_only=True) as store:
            decisions = tuple(
                decision
                for decision in store.load_decision_records()
                if start
                <= decision.decided_at.astimezone(start.tzinfo)
                <= end
            )
        snapshot = analyze_strategies(
            candles,
            decisions,
            start,
            end,
        )
        return snapshot

    def calibration_report(self):
        from intrader.calibration_pipeline import run_calibration
        with SQLiteStore(self.database_path) as store:
            return run_calibration(store)

    def promotion_report(self):
        from intrader.calibration_pipeline import run_promotion_gate
        with SQLiteStore(self.database_path) as store:
            return run_promotion_gate(store)
