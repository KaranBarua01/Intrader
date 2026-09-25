# Intrader Phase 1 Checkpoint 3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task by task. Steps use checkbox syntax for tracking.

**Goal:** Stream read-only NIFTY spot, India VIX, the nearest future, and ATM ±4 option pairs, reconnect safely, and force NO TRADE whenever critical data is disconnected or stale.

**Architecture:** Intrader uses `websocket-client` directly with TLS verification and in-memory login tokens. A small binary decoder converts SmartAPI V2 frames to typed ticks; a lifecycle controller subscribes after every connection, bounds reconnect delay, and forwards ticks to a separate health gate. Nothing in this checkpoint emits trade signals or broker orders.

**Tech Stack:** Python 3.11, websocket-client, struct, pytest, SmartAPI WebSocket V2.

**Spec:** `docs/superpowers/specs/2026-09-25-intrader-design.md`

## Global Constraints

- Windows-only, NIFTY analysis only, all orders manual on the phone.
- No order, modification, cancellation, or GTT endpoint.
- No credential, JWT, refresh token, feed token, or raw WebSocket error text in files or console output.
- TLS certificate verification stays enabled.
- A disconnected, uninitialized, malformed, or stale critical stream produces NO TRADE.
- The option window is the resolved ATM ±4 CE/PE set, never hard-coded tokens.

## Review Focus

- Truncated or malformed binary packet: discard it and remain NO TRADE, never crash the feed loop.
- Wrong exchange/token or duplicate sequence: do not refresh the expected instrument's health.
- Reconnect: clear prior freshness, resubscribe all groups, and require new ticks before READY.
- Socket error or close: clear readiness immediately; never keep a prior signal alive.
- Out-of-hours: connection alone must never imply fresh market data.

---

**Status:** Implementation complete; the market-hours live freshness verification remains pending.

### Task 1: Protocol and subscription contract

**Files:** Create `src/intrader/stream_protocol.py`, `tests/test_stream_protocol.py`.

**Interfaces:** `decode_tick(frame: bytes, received_at: datetime) -> MarketTick`; `subscription_messages(instruments: NiftyInstruments) -> tuple[dict, dict]` returns one LTP subscription for NSE spot/VIX and one SNAP_QUOTE subscription for NFO future/options. `MarketTick` contains exchange, token, mode, sequence, exchange timestamp, received timestamp, LTP and optional OI. Prices use the SDK's 1/100 scale; OI percentage fields are ignored.

- [x] Write tests for actual V2 byte offsets, price scaling, OI, packet truncation, wrong modes, and the full expected subscription sets.
- [x] Run targeted tests to see the expected failure.
- [x] Implement the decoder and subscriptions from the resolved instrument bundle.
- [x] Run targeted tests and full suite.

### Task 2: Feed health gate

**Files:** Create `src/intrader/feed_health.py`, `tests/test_feed_health.py`.

**Interfaces:** `FeedHealth(instruments: NiftyInstruments, stale_tick_seconds: float, stale_option_seconds: float)` with `on_connected()`, `on_disconnected()`, `accept(MarketTick)`, and `snapshot(now: datetime) -> HealthSnapshot`. The snapshot exposes READY or NO TRADE and safe reason codes; it never emits a trading signal.

- [x] Write tests for startup, all-token readiness, missing token, stale exchange timestamp, stale reception time, duplicate sequence, wrong token, and disconnect/reconnect invalidation.
- [x] Run targeted tests to see the expected failure.
- [x] Implement per-token freshness using UTC-aware exchange and reception timestamps and strict exchange/token matching.
- [x] Run targeted tests and full suite.

### Task 3: TLS WebSocket lifecycle and read-only probe

**Files:** Create `src/intrader/live_feed.py`, `tests/test_live_feed.py`; update `src/intrader/__main__.py`, `README.md`.

**Interfaces:** `LiveFeed(session_provider: Callable[[], SmartSession], instruments: NiftyInstruments, health: FeedHealth, socket_factory=...)` connects to `wss://smartapisocket.angelone.in/smart-stream`, sends both subscription messages on open, decodes binary frames, and clears health on close/error. `run_probe(duration_seconds: int) -> HealthSnapshot` bounds an operator diagnostic; reconnection obtains a fresh in-memory login session and WebSocket object with capped backoff. Only sanitized status is printed.

- [x] Write tests for auth headers remaining in memory, TLS verification, subscribe-on-open, reconnect/resubscribe, invalid frame handling, and close/error NO TRADE.
- [x] Run targeted tests to see the expected failure.
- [x] Implement the lifecycle and bounded diagnostic CLI, with no automatic orders.
- [x] Run targeted tests and full suite; inspect diff for secrets and order endpoints.
- [ ] During market hours, run the live probe and confirm tick freshness; outside market hours, leave this live gate pending rather than claiming stream reliability.

## Source notes

- Angel One SDK V2 example: `https://github.com/angel-one/smartapi-python/blob/main/example/smartwebsocketexamplev2.py`.
- Installed Angel One SDK `SmartApi/smartWebSocketV2.py` defines V2 frame offsets, modes, and subscription format. Intrader does not use its socket wrapper because that wrapper disables TLS verification and logs raw messages.
