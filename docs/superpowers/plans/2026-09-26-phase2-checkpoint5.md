# Intrader Phase 2 Checkpoint 5 — Market Brain

**Status:** IN PROGRESS.

**Goal:** Combine Phase 2 measurement families into deterministic Direction, Entry Quality, Reversal/Chase Risk, Confidence and final advisory state while explicitly preventing correlated indicators from being counted as independent evidence.

## Final advisory states

- BULLISH SETUP
- BEARISH SETUP
- WAIT
- NO TRADE

These are analytical states only. Intrader still has no broker order-placement path.

## Hard gates

NO TRADE when:
- core 21-instrument health is not READY/fresh;
- required price/options/futures-order-flow measurements are unavailable;
- a HIGH scheduled-event window is active.

Missing optional breadth/context lowers evidence coverage but does not fabricate data.

## Direction families

Each family produces exactly one bounded value in [-1, +1]:

1. PRICE — 30%
   - EMA9/EMA20 separation normalized by ATR
   - spot location inside/outside the opening range
   - RSI position
   - these are averaged inside the family, not separately weighted globally

2. FUTURES — 25%
   - futures buildup label
   - five-minute futures price change normalized by ATR
   - basis change normalized by ATR

3. OPTIONS — 20%
   - per-contract buildup votes aggregated across the complete ATM +/-4 chain
   - CE and PE semantics are mirrored
   - PCR/concentration remain descriptive and are not added as independent direction votes

4. BREADTH — 15%
   - equal-weight NIFTY constituent breadth
   - weighted breadth is used only when a verified weight source exists

5. ORDER FLOW — 10%
   - five-level depth imbalance
   - total buy/sell pressure transformed to a bounded ratio
   - both live inside one family to avoid double counting

Available family weights are normalized for Direction. Missing optional breadth reduces Confidence coverage.

## Entry Quality

0-100 from independent execution-quality dimensions:
- cross-family directional agreement
- futures relative volume participation
- futures spread/liquidity

It is not a second Direction score.

## Reversal / Chase Risk

0-100 from:
- spot extension from EMA20 in ATR units
- RSI extremity
- latest candle body in ATR units
- absolute VIX percentage change
- scheduled-event window escalation

## Confidence

0-100 from:
- magnitude/clarity of the net family vote
- directional-family coverage
- core feed freshness

## Initial state thresholds

Initial deterministic thresholds for shadow calibration, not claims of profitability:

- |Direction| >= 35
- Confidence >= 60
- Entry Quality >= 55
- Reversal/Chase Risk <= 70

If thresholds are not jointly satisfied => WAIT.

These thresholds must be calibrated later from shadow/outcome data; they are not optimized on historical returns in this checkpoint.

## Acceptance

- each family contributes no more than its declared family weight;
- removing breadth lowers coverage/confidence but cannot invert other family values;
- high-impact active event => NO TRADE;
- stale core health => NO TRADE;
- conflicting families => lower Direction/Confidence;
- extreme extension raises Reversal Risk without automatically reversing Direction;
- no API order endpoint is introduced.
