# Intrader Phase 1 Checkpoint 4 Implementation Plan

**Status:** Offline implementation complete; real Windows/SmartAPI backfill verification pending.\n\n**Goal:** Add restart-safe SQLite persistence, read-only historical backfill, and local live option/OI snapshot collection.

**Architecture:** Use Python's built-in sqlite3 with WAL mode and idempotent primary keys. Historical data comes only from Angel One market-data endpoints. The backfill scope is NIFTY spot, India VIX, nearest NIFTY future candles, plus nearest-future historical OI. ATM ±4 option state is collected from the already-approved live SNAP_QUOTE stream during warm-up and live operation.

## Hard constraints

- No order, modify, cancel, position, GTT, or execution endpoints.
- No credentials/tokens written to SQLite.
- SQLite restart must not duplicate candles, OI rows, or option snapshots.
- Database writes must be transactional and recoverable.
- Historical timestamps are normalized to UTC in storage.
- Historical API failures do not produce READY.
- Live option persistence must never keep feed health READY after disconnect/staleness.
- API request pacing must stay below the documented historical-data limit.

## Task 1 — SQLite persistence

Create `src/intrader/storage.py` and `tests/test_storage.py`.

Tables:
- `candles`
- `oi_observations`
- `option_snapshots`

Acceptance:
- schema initializes twice safely;
- WAL and foreign keys are enabled;
- duplicate/replayed candle/OI/snapshot inserts are idempotent;
- transaction rollback leaves no partial batch;
- database can close/reopen without corruption.

## Task 2 — Historical market-data client

Create `src/intrader/historical.py` and `tests/test_historical.py`.

Interfaces:
- `fetch_candles(...)`
- `fetch_oi(...)`

Acceptance:
- only documented historical endpoints;
- one-minute request window max 30 days;
- strict response shape validation;
- timezone-aware input/output;
- OHLC validation and non-negative volume/OI;
- sanitized failures.

## Task 3 — Core session backfill

Create `src/intrader/backfill.py` and `tests/test_backfill.py`.

Backfill:
- NIFTY spot 1-minute candles;
- India VIX 1-minute candles;
- nearest NIFTY future 1-minute candles;
- nearest NIFTY future 1-minute OI.

Acceptance:
- pacing between network requests;
- store is idempotent across repeated runs;
- report returns inserted/available row counts;
- one failed source fails the backfill gate.

## Task 4 — Live option snapshot sink

Modify `src/intrader/live_feed.py` to accept an optional tick sink and persist only resolved CE/PE SNAP_QUOTE ticks through the store adapter.

Acceptance:
- invalid/wrong-token ticks are not stored;
- duplicate/replayed snapshots do not duplicate rows;
- persistence failure forces feed health to NO TRADE rather than silently continuing.

## Task 5 — CLI and checkpoint gate

Add:
- `python -m intrader init-storage`
- `python -m intrader backfill-session YYYY-MM-DD HH:MM YYYY-MM-DD HH:MM`

Acceptance:
- CLI output contains only counts/status;
- no credential/token values;
- complete test suite passes on Python 3.11;
- repeated backfill produces identical database row counts;
- no broker execution endpoint exists in the checkpoint diff.
