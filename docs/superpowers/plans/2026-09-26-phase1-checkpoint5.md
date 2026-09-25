# Intrader Phase 1 Checkpoint 5 Implementation Plan

**Status:** Offline implementation complete. Targeted Checkpoint 5 tests pass; full regression passes except the expected Python-version readiness test in the verifier, which runs Python 3.13 while Intrader requires Python 3.11. Real market-hours warm-up verification remains pending.

**Goal:** Coordinate the 30-minute warm-up so Intrader predictably reaches READY or NO TRADE at the user-selected start time.

## Schedule

For each trading date:

- market open: 09:15 IST
- selected live start: `AppConfig.trading_start`
- warm-up start: live start minus `warmup_minutes` (default 30)
- live end: live start plus `trading_duration_minutes` (default 30)

The selected start must leave a valid historical window after market open.

## State machine

`CONFIGURED -> PREPARING -> SYNCING -> ANALYSING -> VALIDATING -> READY | NO TRADE -> LIVE -> ENDED`

Safety rules:

- Backfill failure => NO TRADE.
- Storage failure => NO TRADE.
- Missing/stale/disconnected critical feed => NO TRADE.
- READY is never inferred from connection alone.
- After the live window ends => ENDED.
- No state transition can place, modify, cancel, or suggest a broker order.

## Warm-up sequence

1. PREPARING
   - calculate schedule;
   - reject invalid/out-of-window timing;
   - initialize SQLite.
2. SYNCING
   - authenticate once;
   - resolve current NIFTY instruments;
   - backfill NIFTY spot, VIX, nearest future candles and future OI from 09:15 to warm-up start/current preparation time.
3. ANALYSING
   - start the read-only WebSocket;
   - persist ATM ±4 CE/PE option LTP/OI/volume during the remaining warm-up.
4. SYNCING
   - at selected start, perform an incremental core backfill for the warm-up interval so candles/OI are complete.
5. VALIDATING
   - evaluate the final live feed-health snapshot;
   - all critical instruments fresh => READY;
   - otherwise => NO TRADE.
6. LIVE
   - only after the selected start and a READY gate.
7. ENDED
   - at selected start + configured live duration.

## Commands

- `python -m intrader session-plan YYYY-MM-DD`
- `python -m intrader prepare-session YYYY-MM-DD`

`prepare-session` may remain active for the warm-up duration. It prints only state/status/count information and never credentials, tokens, raw market packets, or trade instructions.

## Tests

- schedule math across boundaries;
- invalid start before usable market window;
- deterministic state transitions;
- backfill failure => NO TRADE;
- stale/missing feed => NO TRADE;
- fresh complete feed => READY then LIVE;
- live-end => ENDED;
- warm-up runner performs initial backfill, live collection, incremental backfill and final validation;
- CLI never starts network work before warm-up start.
