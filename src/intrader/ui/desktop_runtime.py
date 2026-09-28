"""Automatic desktop live-session supervisor for Intrader.

The desktop runtime is intentionally separate from the historical Shadow Arena.
It recovers the current NSE session when the app starts late, keeps the read-only
market feed recording until 15:30 IST, refreshes core one-minute history, builds
live Market Brain snapshots, and only permits shadow entries inside the
configured live-trading window.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
import threading

from intrader.auth import RequestsTransport, authenticate
from intrader.backfill import backfill_core_market
from intrader.brain_pipeline import build_stored_market_brain
from intrader.breadth_provider import (
    RequestsTextTransport,
    fetch_nifty50_constituents,
    resolve_breadth_members,
)
from intrader.checkpoint2 import check_market_access
from intrader.config import load_config
from intrader.context_pipeline import refresh_context
from intrader.context_sources import RequestsContextTransport
from intrader.feed_health import FeedHealth, HealthSnapshot
from intrader.global_news import fetch_global_market_news
from intrader.historical import INDIA_TIME
from intrader.live_feed import LiveFeed
from intrader.market_brain import MarketBrainSnapshot
from intrader.outcome_pipeline import OutcomePipelinePending, settle_shadow_trade
from intrader.shadow_pipeline import run_shadow_step
from intrader.storage import MarketSnapshotSink, SQLiteStore


MARKET_OPEN = time(9, 15)
MARKET_CLOSE = time(15, 30)


@dataclass(frozen=True, slots=True)
class DesktopRuntimeStatus:
    phase: str
    message: str
    feed_state: str
    fresh_count: int
    expected_count: int
    next_transition: datetime | None
    last_backfill_at: datetime | None
    recovered_late: bool


class DesktopLiveRuntime:
    """Own one background market-data/session lifecycle for the desktop app."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._feed_thread: threading.Thread | None = None
        self._feed: LiveFeed | None = None
        self._health: FeedHealth | None = None
        self._lock = threading.Lock()
        self._instruments = None
        self._latest_brain: MarketBrainSnapshot | None = None
        self._message = "Desktop live runtime not started."
        self._last_backfill_at: datetime | None = None
        self._recovered_late = False
        self._last_context_refresh: datetime | None = None
        self._last_news_refresh: datetime | None = None
        self._last_decision_minute: datetime | None = None
        self._last_settlement_check: datetime | None = None

    @property
    def instruments(self):
        with self._lock:
            return self._instruments

    @property
    def latest_brain(self) -> MarketBrainSnapshot | None:
        with self._lock:
            return self._latest_brain

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._supervise,
            name="IntraderDesktopRuntime",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        feed = self._feed
        if feed is not None:
            try:
                feed.stop()
            except Exception:
                pass
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=3)

    @staticmethod
    def _session_times(now: datetime):
        day = now.astimezone(INDIA_TIME).date()
        config = load_config()
        market_open = datetime.combine(day, MARKET_OPEN, INDIA_TIME)
        warmup_start = datetime.combine(
            day,
            config.trading_start,
            INDIA_TIME,
        ) - timedelta(minutes=config.warmup_minutes)
        live_start = datetime.combine(day, config.trading_start, INDIA_TIME)
        live_end = live_start + timedelta(
            minutes=config.trading_duration_minutes
        )
        market_close = datetime.combine(day, MARKET_CLOSE, INDIA_TIME)
        return config, market_open, warmup_start, live_start, live_end, market_close

    @classmethod
    def phase_at(cls, now: datetime) -> tuple[str, datetime | None]:
        local = now.astimezone(INDIA_TIME)
        if local.weekday() >= 5:
            return "WEEKEND", None
        _, market_open, warmup_start, live_start, live_end, market_close = (
            cls._session_times(local)
        )
        if local < market_open:
            return "PRE_MARKET", market_open
        if local < warmup_start:
            return "OBSERVATION", warmup_start
        if local < live_start:
            return "WARM_UP", live_start
        if local < live_end:
            return "LIVE", live_end
        if local < market_close:
            return "POST_TRADE", market_close
        return "CLOSED", None

    def status(self, now: datetime | None = None) -> DesktopRuntimeStatus:
        now = now or datetime.now(INDIA_TIME)
        phase, next_transition = self.phase_at(now)
        health = self._health
        if health is None:
            snapshot = HealthSnapshot("NO TRADE", ("NOT_CONNECTED",), 0, 0)
        else:
            try:
                snapshot = health.snapshot(now)
            except Exception:
                snapshot = HealthSnapshot("NO TRADE", ("HEALTH_UNAVAILABLE",), 0, 0)
        with self._lock:
            message = self._message
            last_backfill = self._last_backfill_at
            recovered_late = self._recovered_late
        return DesktopRuntimeStatus(
            phase=phase,
            message=message,
            feed_state=snapshot.state,
            fresh_count=snapshot.fresh_count,
            expected_count=snapshot.expected_count,
            next_transition=next_transition,
            last_backfill_at=last_backfill,
            recovered_late=recovered_late,
        )

    def _set_message(self, message: str) -> None:
        with self._lock:
            self._message = message

    def _optional_breadth_members(self, market_report):
        if not market_report.master:
            return ()
        try:
            constituents = fetch_nifty50_constituents(RequestsTextTransport())
            return resolve_breadth_members(constituents, market_report.master)
        except Exception:
            return ()

    def _start_feed(self, credential_store, transport, market, breadth_members) -> None:
        if self._feed_thread is not None and self._feed_thread.is_alive():
            return
        config = load_config()
        health = FeedHealth(
            market.instruments,
            config.stale_tick_seconds,
            config.stale_option_seconds,
        )
        self._health = health

        def worker() -> None:
            with SQLiteStore(self.database_path) as store:
                store.initialize()

                def session_provider():
                    return authenticate(credential_store, transport)

                feed = LiveFeed(
                    session_provider,
                    market.instruments,
                    health,
                    tick_sink=MarketSnapshotSink(
                        store,
                        market.instruments,
                        breadth_members,
                    ),
                    breadth_tokens=tuple(
                        member.instrument.token for member in breadth_members
                    ),
                )
                self._feed = feed
                try:
                    feed.run()
                finally:
                    self._feed = None

        self._feed_thread = threading.Thread(
            target=worker,
            name="IntraderLiveFeed",
            daemon=True,
        )
        self._feed_thread.start()

    def _backfill(
        self,
        session,
        transport,
        instruments,
        start: datetime,
        end: datetime,
    ) -> None:
        if end <= start:
            return
        with SQLiteStore(self.database_path) as store:
            store.initialize()
            backfill_core_market(
                store,
                session,
                transport,
                instruments,
                start,
                end,
            )
        with self._lock:
            self._last_backfill_at = end

    def _refresh_context(self, now: datetime) -> None:
        if (
            self._last_context_refresh is not None
            and now - self._last_context_refresh < timedelta(minutes=10)
        ):
            return
        try:
            with SQLiteStore(self.database_path) as store:
                refresh_context(
                    store,
                    RequestsContextTransport(),
                    now,
                )
            self._last_context_refresh = now
        except Exception:
            pass

    def _refresh_news(self, now: datetime) -> None:
        if (
            self._last_news_refresh is not None
            and now - self._last_news_refresh < timedelta(minutes=5)
        ):
            return
        try:
            items = fetch_global_market_news(
                now - timedelta(hours=24),
                now,
                max_records=75,
            )
            if items:
                with SQLiteStore(self.database_path) as store:
                    store.store_news_items(items)
            self._last_news_refresh = now
        except Exception:
            pass

    def _update_brain_and_shadow(self, now: datetime, instruments, config) -> None:
        at = now.replace(second=0, microsecond=0)
        try:
            with SQLiteStore(self.database_path) as store:
                brain = build_stored_market_brain(
                    store,
                    instruments,
                    at.date(),
                    at,
                    config,
                )
                with self._lock:
                    self._latest_brain = brain

                live_start = datetime.combine(
                    at.date(), config.trading_start, INDIA_TIME
                )
                live_end = live_start + timedelta(
                    minutes=config.trading_duration_minutes
                )
                if (
                    live_start <= at < live_end
                    and self._last_decision_minute != at
                ):
                    run_shadow_step(
                        store,
                        instruments,
                        at.date(),
                        at,
                        config,
                    )
                    self._last_decision_minute = at
        except Exception:
            # The UI still receives feed/session health while data families warm up.
            pass

    def _settle_shadow(self, now: datetime, instruments) -> None:
        if (
            self._last_settlement_check is not None
            and now - self._last_settlement_check < timedelta(seconds=10)
        ):
            return
        self._last_settlement_check = now
        try:
            with SQLiteStore(self.database_path) as store:
                for trade in store.load_unsettled_shadow_trades():
                    try:
                        settle_shadow_trade(
                            store,
                            instruments,
                            trade.trade_id,
                            now,
                        )
                    except OutcomePipelinePending:
                        continue
                    except Exception:
                        continue
        except Exception:
            pass

    def _supervise(self) -> None:
        credential_store = None
        transport = None
        session = None
        market = None
        active_day: date | None = None

        while not self._stop.is_set():
            now = datetime.now(INDIA_TIME)
            phase, _ = self.phase_at(now)
            config, market_open, warmup_start, live_start, live_end, market_close = (
                self._session_times(now)
            )

            if phase in {"WEEKEND", "PRE_MARKET", "CLOSED"}:
                if phase == "PRE_MARKET":
                    self._set_message(
                        f"PRE-MARKET — recorder starts automatically at {market_open:%H:%M} IST."
                    )
                elif phase == "CLOSED":
                    self._set_message(
                        "MARKET CLOSED — live recorder stopped; historical data remains available."
                    )
                else:
                    self._set_message("WEEKEND — no NSE live session.")
                if self._feed is not None:
                    self._feed.stop()
                self._stop.wait(5)
                continue

            try:
                if active_day != now.date() or market is None:
                    from intrader.credentials import CredentialStore

                    credential_store = CredentialStore()
                    transport = RequestsTransport()
                    session = authenticate(credential_store, transport)
                    market = check_market_access(
                        credential_store,
                        transport,
                        as_of=now.date(),
                        session=session,
                    )
                    breadth_members = self._optional_breadth_members(market)
                    with self._lock:
                        self._instruments = market.instruments
                    active_day = now.date()

                    cutoff = min(
                        now.replace(second=0, microsecond=0),
                        market_close,
                    )
                    if cutoff > market_open:
                        self._set_message(
                            f"RECOVERING — backfilling {market_open:%H:%M} → {cutoff:%H:%M} IST."
                        )
                        self._backfill(
                            session,
                            transport,
                            market.instruments,
                            market_open,
                            cutoff,
                        )
                        self._recovered_late = cutoff > market_open + timedelta(minutes=2)

                    self._start_feed(
                        credential_store,
                        transport,
                        market,
                        breadth_members,
                    )
                    self._refresh_context(now)
                    self._refresh_news(now)

                # Keep core one-minute candles/OI current without using future data.
                cutoff = min(
                    now.replace(second=0, microsecond=0),
                    market_close,
                )
                last = self._last_backfill_at or market_open
                if cutoff - last >= timedelta(minutes=2):
                    try:
                        self._backfill(
                            session,
                            transport,
                            market.instruments,
                            last,
                            cutoff,
                        )
                    except Exception:
                        # Refresh auth once and retry on the next supervisor cycle.
                        session = authenticate(credential_store, transport)

                self._refresh_context(now)
                self._refresh_news(now)
                self._update_brain_and_shadow(
                    now,
                    market.instruments,
                    config,
                )
                self._settle_shadow(now, market.instruments)

                health = self._health
                health_snapshot = (
                    None if health is None else health.snapshot(now)
                )
                feed_text = (
                    "connecting"
                    if health_snapshot is None
                    else f"{health_snapshot.fresh_count}/{health_snapshot.expected_count} fresh"
                )
                if phase == "OBSERVATION":
                    self._set_message(
                        f"OBSERVATION — recording market data • feed {feed_text} • "
                        f"warm-up starts {warmup_start:%H:%M}."
                    )
                elif phase == "WARM_UP":
                    remaining = max(
                        0,
                        int((live_start - now).total_seconds() // 60),
                    )
                    self._set_message(
                        f"WARM-UP — {remaining} min to live window • feed {feed_text}."
                    )
                elif phase == "LIVE":
                    self._set_message(
                        f"LIVE PAPER WINDOW — Market Brain may qualify shadow entries • feed {feed_text}."
                    )
                else:
                    self._set_message(
                        f"POST-TRADE OBSERVATION — no new entries • recording until {market_close:%H:%M}."
                    )
            except Exception as exc:
                detail = str(exc).strip() or exc.__class__.__name__
                self._set_message(f"RECOVERY RETRY — {detail}")
                market = None
                session = None
                self._stop.wait(5)
                continue

            self._stop.wait(2)
