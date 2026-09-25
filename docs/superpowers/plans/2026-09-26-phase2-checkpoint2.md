# Intrader Phase 2 Checkpoint 2 — Options Intelligence

**Status:** IMPLEMENTATION COMPLETE. Engine, SQLite reads, stored-session pipeline, CLI, and tests are committed. Branch-level pytest verification remains pending because connector-originated commits are not starting GitHub Actions in this repository.

**Goal:** Convert the stored ATM +/-4 NIFTY option snapshots into deterministic chain measurements without producing a final market-direction verdict.

## Inputs

Use only the resolved nearest-expiry ATM +/-4 CE/PE contracts already collected through the Phase 1 SNAP_QUOTE stream.

Each stored option observation contains:

- exchange timestamp
- received timestamp
- sequence
- expiry
- strike
- CE/PE type
- LTP
- open interest
- cumulative traded volume

## Lookback

Default change window: 5 minutes.

For every resolved CE/PE contract:

- current = latest snapshot at or before the requested analysis time;
- baseline = latest snapshot at or before analysis time minus 5 minutes;
- both snapshots must belong to the requested session and the same contract.

The engine fails closed when the chain is incomplete or the requested lookback is unavailable.

## Per-contract measurements

- LTP change
- LTP percentage change
- OI change
- OI percentage change
- cumulative volume
- volume change over lookback
- buildup classification

### Buildup labels

These are contract-level descriptive labels only:

- price up + OI up => LONG_BUILDUP
- price down + OI up => SHORT_BUILDUP
- price up + OI down => SHORT_COVERING
- price down + OI down => LONG_UNWINDING
- zero/ambiguous movement => NEUTRAL

A CE/PE buildup label is not itself treated as a NIFTY direction signal.

## Chain measurements

Across the selected ATM +/-4 window:

- total CE OI
- total PE OI
- OI PCR = total PE OI / total CE OI
- total CE cumulative volume
- total PE cumulative volume
- volume PCR = total PE volume / total CE volume
- strike with maximum CE OI
- strike with maximum PE OI
- strike with maximum positive CE OI change
- strike with maximum positive PE OI change
- CE OI concentration share
- PE OI concentration share

The engine exposes the concentrations and ratios as raw measurements. Direction scoring is deferred to Phase 2 Checkpoint 5.

## Quality rules

- exactly one CE and one PE contract per selected strike;
- all current snapshots must be present;
- all lookback baselines must be present;
- snapshots must be timezone-aware and strictly ordered per token;
- current OI/volume cannot be lower than zero;
- negative volume delta indicates a reset/inconsistent session and fails closed;
- division by zero returns unavailable for PCR/percentage metrics instead of inventing a value;
- no BUY/SELL/BULLISH/BEARISH verdict in this checkpoint.

## Deliverables

1. `src/intrader/options_intelligence.py`
2. SQLite option-snapshot read API
3. `src/intrader/options_pipeline.py`
4. read-only `options-intelligence YYYY-MM-DD HH:MM` diagnostic
5. deterministic tests for buildup, PCR, chain completeness, lookback alignment and storage reads
