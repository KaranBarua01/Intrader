"""Read-only desktop data facade over Intrader backend services."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from decimal import Decimal
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
from intrader.historical_options import (
    HistoricalOptionDataError,
    HistoricalOptionDataset,
    load_historical_option_csv,
)
from intrader.records import DecisionRecord
from intrader.shadow import ShadowTrade
from intrader.shadow_arena import FeatureCoverageAudit, ShadowArenaReport, run_shadow_arena
from intrader.shadow_lab import (
    FEATURE_FAMILIES,
    MAX_REPLAY_SESSION_INPUT,
    ShadowReplayConfig,
    replay_mode,
    validate_replay_config,
)
from intrader.shadow_replay import ShadowReplayReport, run_candle_proxy_replay
from intrader.shadow_stream_engine import (
    FeatureEvent,
    HistoricalFeatureTimeline,
    RiskWindow,
)
from intrader.storage import SQLiteStore
from intrader.strategy_lab import analyze_strategies
from intrader.ui.desktop_runtime import DesktopLiveRuntime, DesktopRuntimeStatus
from intrader.ui.paths import database_path as default_database_path


@dataclass(frozen=True, slots=True)
class DesktopSnapshot:
    latest_decision: DecisionRecord | None
    live_brain: object | None
    runtime_status: DesktopRuntimeStatus
    active_shadow_trade: ShadowTrade | None
    completed_bundles: tuple
    recent_news: tuple
    upcoming_events: tuple
    database_counts: tuple[tuple[str, int], ...]


class DesktopDataService:
    def __init__(self, database_path: Path | None = None) -> None:
        self.database_path = database_path or default_database_path()
        self.runtime = DesktopLiveRuntime(self.database_path)

    def start_live_runtime(self) -> None:
        self.runtime.start()

    def stop_live_runtime(self) -> None:
        self.runtime.stop()

    def runtime_status(self, now: datetime | None = None) -> DesktopRuntimeStatus:
        return self.runtime.status(now)

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
        session_decisions = [
            decision for decision in decisions
            if decision.session_date == now.astimezone(INDIA_TIME).date()
        ]
        return DesktopSnapshot(
            latest_decision=None if not session_decisions else session_decisions[-1],
            live_brain=self.runtime.latest_brain,
            runtime_status=self.runtime.status(now),
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
        """Load cached NIFTY candles and append live tick-derived current bars.

        Desktop rendering must not require a fresh broker login merely to read
        data already being recorded by the live runtime.
        """

        start = datetime.combine(day, time(9, 15), INDIA_TIME)
        end = datetime.combine(day, time(15, 30), INDIA_TIME)
        with SQLiteStore(self.database_path, read_only=True) as store:
            candles = list(
                store.load_primary_index_candles(
                    "ONE_MINUTE",
                    start=start,
                    end=end,
                )
            )
            instruments = self.runtime.instruments
            if instruments is None:
                return tuple(candles)
            ticks = store.load_index_snapshots(
                instruments.spot.token,
                start=start,
                end=end,
            )

        existing_minutes = {
            item.at.astimezone(INDIA_TIME).replace(second=0, microsecond=0)
            for item in candles
        }
        grouped: dict[datetime, list] = {}
        for tick in ticks:
            minute = tick.exchange_at.astimezone(INDIA_TIME).replace(
                second=0,
                microsecond=0,
            )
            if minute in existing_minutes:
                continue
            grouped.setdefault(minute, []).append(tick)

        for minute in sorted(grouped):
            rows = grouped[minute]
            prices = [row.ltp for row in rows]
            if not prices:
                continue
            candles.append(
                Candle(
                    at=minute,
                    open=prices[0],
                    high=max(prices),
                    low=min(prices),
                    close=prices[-1],
                    volume=0,
                )
            )
        return tuple(sorted(candles, key=lambda item: item.at))

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

        if sessions < 2 or sessions > MAX_REPLAY_SESSION_INPUT * 2:
            raise ValueError("Shadow Trader total replay range must be between 2 and 1000 sessions")
        now = now or datetime.now(INDIA_TIME)
        end_day = self._last_completed_market_day(now)
        end = datetime.combine(end_day, time(15, 30), INDIA_TIME)

        # Generous calendar lookback covers weekends and exchange holidays while
        # keeping each Angel request inside the 30-day one-minute limit.
        start_day = end_day - timedelta(days=sessions * 2 + 35)
        start = datetime.combine(start_day, time(9, 15), INDIA_TIME)

        def collect_cached(
            target: dict[datetime, Candle],
            *,
            backfill_missing: bool,
        ) -> None:
            cursor = start
            while cursor < end:
                chunk_end = min(cursor + timedelta(days=27), end)
                rows = self.load_nifty_candle_range(
                    cursor,
                    chunk_end,
                    backfill_missing=backfill_missing,
                )
                for candle in rows:
                    target[candle.at] = candle
                cursor = chunk_end

        # Always try the local cache first. Historical replay should keep working
        # without internet or a fresh broker login when enough candles are already
        # stored on disk.
        merged: dict[datetime, Candle] = {}
        collect_cached(merged, backfill_missing=False)
        cached_session_dates = {
            candle.at.astimezone(INDIA_TIME).date()
            for candle in merged.values()
        }
        if len(cached_session_dates) >= sessions:
            return tuple(sorted(merged.values(), key=lambda item: item.at))

        cached_count = len(cached_session_dates)
        try:
            collect_cached(merged, backfill_missing=True)
        except Exception as exc:
            detail = str(exc).strip() or exc.__class__.__name__
            raise ValueError(
                f"Shadow Trader has {cached_count}/{sessions} requested sessions cached locally. "
                f"SmartAPI could not download the missing historical candles: {detail}"
            ) from None

        ordered = tuple(sorted(merged.values(), key=lambda item: item.at))
        session_dates = {
            candle.at.astimezone(INDIA_TIME).date()
            for candle in ordered
        }
        if len(session_dates) < sessions:
            raise ValueError(
                f"only {len(session_dates)} historical NIFTY sessions are available after "
                f"SmartAPI backfill; {sessions} were requested"
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

    @staticmethod
    def _clip_score(value: Decimal) -> Decimal:
        return max(Decimal("-1"), min(Decimal("1"), value))

    def _build_shadow_feature_timeline(
        self,
        start: datetime,
        end: datetime,
        candles: tuple[Candle, ...],
        mode_key: str,
    ) -> tuple[HistoricalFeatureTimeline, FeatureCoverageAudit]:
        """Build causal historical feature events from data genuinely stored locally."""

        mode = replay_mode(mode_key)
        feature_sizes = {
            family: len(features)
            for family, features in FEATURE_FAMILIES
        }
        events: list[FeatureEvent] = []
        risk_windows: list[RiskWindow] = []

        with SQLiteStore(self.database_path, read_only=True) as store:
            counts = {
                "candles": store.count_time_range_rows(
                    "candles", start=start, end=end
                ),
                "future_snapshots": store.count_time_range_rows(
                    "future_snapshots", start=start, end=end
                ),
                "option_snapshots": store.count_time_range_rows(
                    "option_snapshots", start=start, end=end
                ),
                "index_snapshots": store.count_time_range_rows(
                    "index_snapshots", start=start, end=end
                ),
                "breadth_snapshots": store.count_time_range_rows(
                    "breadth_snapshots", start=start, end=end
                ),
                "news_items": store.count_time_range_rows(
                    "news_items", start=start, end=end
                ),
                "scheduled_events": store.count_time_range_rows(
                    "scheduled_events", start=start, end=end
                ),
            }

            # Futures: price/OI/depth confirmation. Multiple expiry tokens are
            # handled independently; only prior observations for the same token
            # are used, so expiry rollover cannot leak information.
            for token in store.distinct_snapshot_tokens(
                "future_snapshots", start=start, end=end
            ):
                rows = store.load_future_snapshots(token, start=start, end=end)
                previous = None
                for row in rows:
                    if previous is None:
                        previous = row
                        continue
                    if row.volume < previous.volume:
                        previous = row
                        continue
                    price_base = previous.ltp if previous.ltp > 0 else row.ltp
                    price_change = (
                        (row.ltp - previous.ltp) / price_base * Decimal(100)
                        if price_base > 0 else Decimal(0)
                    )
                    price_score = self._clip_score(
                        price_change / Decimal("0.15")
                    )
                    oi_change = row.open_interest - previous.open_interest
                    oi_sign = (
                        Decimal(1) if oi_change > 0
                        else Decimal("-1") if oi_change < 0
                        else Decimal(0)
                    )
                    depth_total = row.depth_buy_quantity + row.depth_sell_quantity
                    depth = (
                        Decimal(0)
                        if depth_total == 0
                        else Decimal(
                            row.depth_buy_quantity - row.depth_sell_quantity
                        ) / Decimal(depth_total)
                    )
                    # OI strengthens the current price direction but does not
                    # invent direction by itself.
                    score = self._clip_score(
                        price_score * Decimal("0.75")
                        + depth * Decimal("0.25")
                    )
                    if oi_sign < 0:
                        score *= Decimal("0.75")
                    events.append(
                        FeatureEvent(
                            at=row.exchange_at,
                            family="Futures",
                            score=score,
                            label=(
                                f"Futures price/OI/depth: Δpx={price_change:.3f}% "
                                f"ΔOI={oi_change} depth={depth:.2f}"
                            ),
                        )
                    )
                    previous = row

            # Breadth: equal-weight advance/decline state for the latest stored
            # constituent observations in each minute.
            breadth_rows = store.load_breadth_snapshots(start=start, end=end)
            breadth_by_minute: dict[datetime, list] = {}
            for row in breadth_rows:
                minute = row.exchange_at.replace(second=0, microsecond=0)
                breadth_by_minute.setdefault(minute, []).append(row)
            for at, rows in breadth_by_minute.items():
                latest: dict[str, object] = {}
                for row in rows:
                    latest[row.symbol] = row
                members = list(latest.values())
                if not members:
                    continue
                advancing = sum(
                    1 for row in members
                    if row.current_price > row.previous_close
                )
                declining = sum(
                    1 for row in members
                    if row.current_price < row.previous_close
                )
                score = Decimal(advancing - declining) / Decimal(len(members))
                events.append(
                    FeatureEvent(
                        at=at,
                        family="Breadth / constituents",
                        score=self._clip_score(score),
                        label=(
                            f"Breadth {advancing} advancing / "
                            f"{declining} declining / {len(members)} tracked"
                        ),
                    )
                )

            # Options: when historical snapshots genuinely exist, use the
            # same-timestamp put/call OI and volume balance as confirmation.
            option_rows = store.load_option_snapshots(start=start, end=end)
            options_by_minute: dict[datetime, dict[str, object]] = {}
            for row in option_rows:
                minute = row.exchange_at.replace(second=0, microsecond=0)
                options_by_minute.setdefault(minute, {})[row.token] = row
            for at, by_token in options_by_minute.items():
                rows = list(by_token.values())
                calls = [row for row in rows if row.option_type == "CE"]
                puts = [row for row in rows if row.option_type == "PE"]
                call_oi = sum(row.open_interest for row in calls)
                put_oi = sum(row.open_interest for row in puts)
                call_volume = sum(row.volume for row in calls)
                put_volume = sum(row.volume for row in puts)
                if call_oi <= 0 or put_oi <= 0:
                    continue
                oi_pcr = Decimal(put_oi) / Decimal(call_oi)
                volume_pcr = (
                    None
                    if call_volume <= 0
                    else Decimal(put_volume) / Decimal(call_volume)
                )
                oi_score = self._clip_score(
                    (oi_pcr - Decimal(1)) / Decimal("0.50")
                )
                volume_score = (
                    Decimal(0)
                    if volume_pcr is None
                    else self._clip_score(
                        (volume_pcr - Decimal(1)) / Decimal("0.50")
                    )
                )
                score = self._clip_score(
                    (oi_score + volume_score) / Decimal(2)
                )
                events.append(
                    FeatureEvent(
                        at=at,
                        family="Options",
                        score=score,
                        label=(
                            f"Option PCR OI={oi_pcr:.2f} "
                            f"VOL={'N/A' if volume_pcr is None else f'{volume_pcr:.2f}'}"
                        ),
                    )
                )
            # Scheduled event context is a risk gate, not a fabricated
            # directional prediction.
            scheduled = store.load_scheduled_events(start=start, end=end)
            impact_windows = {
                "HIGH": (30, 15),
                "MEDIUM": (15, 10),
            }
            for event in scheduled:
                window = impact_windows.get(event.impact)
                if window is None:
                    continue
                pre, post = window
                risk_windows.append(
                    RiskWindow(
                        start=event.scheduled_at - timedelta(minutes=pre),
                        end=event.scheduled_at + timedelta(minutes=post),
                        label=f"{event.impact} event: {event.name}",
                    )
                )

        timeline = HistoricalFeatureTimeline(events, risk_windows)
        event_families = set(timeline.families)

        family_features = {
            family: tuple(features)
            for family, features in FEATURE_FAMILIES
        }
        requested_features = {
            feature
            for family in mode.families
            for feature in family_features[family]
        }

        available_features: set[str] = set()
        used_features: set[str] = set()

        if counts["candles"] > 0:
            available_features.update(family_features["NIFTY price / structure"])
            available_features.update(family_features["Momentum / volatility"])
            used_features.update(("spot_return_1m", "roc5"))
        if counts["future_snapshots"] > 0:
            available_features.update(family_features["Futures"])
            used_features.update(
                ("future_oi_change", "future_order_flow_imbalance")
            )
        if counts["option_snapshots"] > 0:
            available_features.update(family_features["Options"])
            available_features.update(family_features["Options microstructure"])
            used_features.update(
                ("call_put_oi_ratio", "call_put_volume_ratio")
            )
        if counts["breadth_snapshots"] > 0:
            available_features.add("nifty_advancers_ratio")
            used_features.add("nifty_advancers_ratio")
        if counts["index_snapshots"] > 0:
            available_features.update(("india_vix_level", "india_vix_change"))
        if counts["scheduled_events"] > 0:
            available_features.add("event_proximity")
            used_features.add("event_proximity")
        if counts["news_items"] > 0:
            available_features.add("news_relevance_score")
        if counts["candles"] > 0:
            available_features.update(("market_regime", "time_of_day_bucket"))

        available_features &= requested_features
        used_features &= requested_features

        available = {
            family
            for family in mode.families
            if any(
                feature in available_features
                for feature in family_features[family]
            )
        }
        decision_used = {
            family
            for family in mode.families
            if any(
                feature in used_features
                for feature in family_features[family]
            )
        }

        # The timeline is the executable truth: do not call a family "used"
        # merely because raw rows exist. This keeps HIGH mode honest.
        decision_used.update(
            family
            for family in event_families
            if family in mode.families
            and family in {"Futures", "Options", "Breadth / constituents"}
        )
        if risk_windows and "Volatility / macro context" in mode.families:
            decision_used.add("Volatility / macro context")

        available_requested = tuple(
            family for family in mode.families if family in available
        )
        decision_used_ordered = tuple(
            family for family in mode.families if family in decision_used
        )
        missing = tuple(
            family for family in mode.families if family not in available
        )
        return timeline, FeatureCoverageAudit(
            requested_touchpoints=mode.feature_count,
            available_touchpoints=len(available_features),
            decision_used_touchpoints=len(used_features),
            requested_families=mode.families,
            available_families=available_requested,
            decision_used_families=decision_used_ordered,
            missing_families=missing,
            stored_rows=tuple(sorted(counts.items())),
        )

    def run_shadow_replay_with_visuals(
        self,
        config: ShadowReplayConfig,
    ) -> tuple[ShadowArenaReport, tuple[Candle, ...]]:
        """Run frozen-engine Shadow Arena and return selected candles for playback."""

        config = validate_replay_config(config)
        sessions = config.required_sessions
        candles = self.load_shadow_replay_candles(sessions)
        selected_dates = sorted({
            candle.at.astimezone(INDIA_TIME).date()
            for candle in candles
        })[-sessions:]
        selected_set = set(selected_dates)
        selected = tuple(
            candle
            for candle in sorted(candles, key=lambda item: item.at)
            if candle.at.astimezone(INDIA_TIME).date() in selected_set
        )
        if not selected:
            raise ValueError("Shadow Trader historical candles unavailable")

        option_datasets: dict[date, HistoricalOptionDataset] | None = None
        if config.execution_mode == "OPTION_PREMIUM":
            option_datasets = {}
            missing: list[date] = []
            historical_root = self.database_path.parent / "historical"
            for day in selected_dates:
                path = historical_root / day.isoformat() / "options_1m.csv"
                try:
                    dataset = load_historical_option_csv(path)
                    if dataset.trading_date != day:
                        raise HistoricalOptionDataError("historical option date mismatch")
                    option_datasets[day] = dataset
                except HistoricalOptionDataError:
                    missing.append(day)
            if missing:
                preview = ", ".join(day.isoformat() for day in missing[:5])
                suffix = "" if len(missing) <= 5 else f" (+{len(missing) - 5} more)"
                raise ValueError(
                    "OPTION_PREMIUM requires cached options_1m.csv for every replay "
                    f"session. Missing {len(missing)} date(s): {preview}{suffix}. "
                    "Download each missing date with: python -m intrader "
                    "download-expired-options YYYY-MM-DD"
                )

        timeline, coverage = self._build_shadow_feature_timeline(
            selected[0].at,
            selected[-1].at,
            selected,
            config.mode_key,
        )
        report = run_shadow_arena(
            selected,
            config,
            feature_coverage=coverage,
            timeline=timeline,
            option_datasets=option_datasets,
        )

        with SQLiteStore(self.database_path) as store:
            previously_reviewed = store.has_reviewed_blind_window(
                report.blind_window_id
            )
            if not previously_reviewed:
                store.mark_blind_window_reviewed(
                    report.blind_window_id,
                    report.blind_start,
                    report.blind_end,
                )
        if previously_reviewed:
            report = replace(report, blind_previously_reviewed=True)

        playback = tuple(
            candle
            for candle in selected
            if report.first_session
            <= candle.at.astimezone(INDIA_TIME).date().isoformat()
            <= report.last_session
        )
        return report, playback

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
