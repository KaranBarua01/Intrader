"""Fail-closed freshness gate for Intrader's critical live instruments."""

from dataclasses import dataclass
from datetime import datetime, timezone

from intrader.instruments import NiftyInstruments
from intrader.stream_protocol import MarketTick


@dataclass(frozen=True, slots=True)
class HealthSnapshot:
    state: str
    reasons: tuple[str, ...]
    fresh_count: int
    expected_count: int


class FeedHealth:
    def __init__(
        self, instruments: NiftyInstruments,
        stale_tick_seconds: float,
        stale_option_seconds: float,
    ) -> None:
        if stale_tick_seconds <= 0 or stale_option_seconds <= 0:
            raise ValueError("freshness thresholds must be positive")
        self._expected = {
            ("NSE", instruments.spot.token): (1, stale_tick_seconds, "STALE_TICK"),
            ("NSE", instruments.vix.token): (1, stale_tick_seconds, "STALE_TICK"),
            ("NFO", instruments.future.token): (3, stale_tick_seconds, "STALE_TICK"),
            **{
                ("NFO", instrument.token): (3, stale_option_seconds, "STALE_OPTION")
                for instrument in (*instruments.calls, *instruments.puts)
            },
        }
        expected_count = 3 + len(instruments.calls) + len(instruments.puts)
        if len(self._expected) != expected_count:
            raise ValueError("duplicate critical instrument token")
        self._connected = False
        self._latest: dict[tuple[str, str], MarketTick] = {}

    def on_connected(self) -> None:
        self._connected = True
        self._latest.clear()

    def on_disconnected(self) -> None:
        self._connected = False
        self._latest.clear()

    def accept(self, tick: MarketTick) -> None:
        key = (tick.exchange, tick.token)
        expected = self._expected.get(key)
        if not self._connected or expected is None or tick.mode != expected[0]:
            return
        previous = self._latest.get(key)
        if previous is not None:
            if tick.exchange_at < previous.exchange_at:
                return
            if (
                tick.exchange_at == previous.exchange_at
                and tick.sequence <= previous.sequence
            ):
                return
        self._latest[key] = tick

    def snapshot(self, now: datetime) -> HealthSnapshot:
        if now.tzinfo is None:
            raise ValueError("now must be timezone aware")
        if not self._connected:
            return HealthSnapshot("NO TRADE", ("DISCONNECTED",), 0, len(self._expected))
        now_utc = now.astimezone(timezone.utc)
        reasons: set[str] = set()
        fresh_count = 0
        for key, (_, threshold, stale_reason) in self._expected.items():
            tick = self._latest.get(key)
            if tick is None:
                reasons.add("MISSING_TICKS")
                continue
            reception_age = (now_utc - tick.received_at).total_seconds()
            exchange_age = (now_utc - tick.exchange_at).total_seconds()
            if (
                reception_age < -2 or exchange_age < -2
                or reception_age > threshold or exchange_age > threshold
            ):
                reasons.add(stale_reason)
            else:
                fresh_count += 1
        return HealthSnapshot(
            "NO TRADE" if reasons else "READY",
            tuple(sorted(reasons)),
            fresh_count,
            len(self._expected),
        )
