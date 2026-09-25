# Intrader Phase 2 Checkpoint 3 — Futures, VIX, Breadth and Order Flow

**Status:** IMPLEMENTATION COMPLETE. Full SNAP_QUOTE order flow, futures/VIX confirmation, additive SQLite persistence, official NIFTY 50 membership resolution, optional breadth QUOTE collection, equal-weight/industry breadth, pipelines, diagnostics, and tests are committed. Local Python 3.11 regression verification remains pending.

**Goal:** Add independent confirmation measurements from NIFTY futures, India VIX, market breadth and five-level order flow. This checkpoint remains descriptive and does not produce the final Direction/Entry/Reversal scores.

## Verified SmartAPI SNAP_QUOTE contract

Current SmartAPI WebSocket V2 SNAP_QUOTE packets are 379 bytes and include:

- LTP
- last traded quantity
- average traded price
- day volume
- total buy quantity
- total sell quantity
- day OHLC
- last traded timestamp
- open interest
- five buy/sell depth levels
- circuit/52-week fields

Intrader continues to ignore the broker-provided OI percentage-change field and calculates OI change locally.

The documented best-five flag is:

- 1 = buy
- 0 = sell

## Phase 2 CP3 measurements

### Futures confirmation

From the nearest NIFTY future:

- current LTP
- 5-minute LTP change
- current OI
- 5-minute OI change
- 5-minute volume change
- contract buildup label
- spot/future basis
- 5-minute basis change

### VIX

From India VIX:

- current VIX
- 5-minute absolute change
- 5-minute percentage change

### Order flow

From nearest-future SNAP_QUOTE:

- total-buy / total-sell quantity ratio
- five-level buy / sell quantity ratio
- depth imbalance = (buy qty - sell qty) / (buy qty + sell qty)
- best bid
- best ask
- spread
- spread in basis points

These are liquidity/pressure measurements only, not direct trade signals.

### Breadth / leadership

Breadth is kept independent from futures/order flow:

- advancing constituent count
- declining constituent count
- unchanged count
- advance/decline ratio
- equal-weight breadth percentage
- selected sector/index confirmation

Constituent membership/data acquisition will be isolated behind a provider/cache boundary so a failure cannot disable core SmartAPI futures/VIX measurements.

## Persistence

Add local storage for:

- NIFTY spot live snapshots
- India VIX live snapshots
- nearest-future LTP/OI/volume/order-flow snapshots

SQLite persistence failures remain fail-closed for live readiness.

## Quality gates

- mode-3 packet shorter than 379 bytes is invalid;
- malformed depth levels are discarded/fail closed;
- buy/sell flags follow the documented protocol, not the currently confusing SDK variable names;
- future and spot basis use time-aligned snapshots;
- negative cumulative-volume delta fails closed;
- zero denominators return unavailable ratios;
- stale current data cannot produce a confirmation snapshot;
- no BUY/SELL/BULLISH/BEARISH verdict in this checkpoint.
