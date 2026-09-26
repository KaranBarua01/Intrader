# Phase 3 Checkpoint 2 — Shadow Trader

**Status:** IMPLEMENTATION COMPLETE. Local Python 3.11 regression verification remains pending.

## Goal

Translate actionable immutable decisions into simulated option positions without any broker execution.

## Initial shadow-v0.1 rules

- BULLISH SETUP / BUY_CALL -> nearest-ATM CE
- BEARISH SETUP / BUY_PUT -> nearest-ATM PE
- WAIT / NO_TRADE -> no position
- one simulated lot
- stop: 20% below option entry
- target: 30% above option entry
- maximum lifetime: 30 minutes

These are engineering defaults for outcome collection. They are not optimized and are versioned so later calibration can compare them fairly.

## Integrity

The shadow trade plan is immutable. Entry contract, premium, quantity, stop, target and timeout cannot be rewritten after the fact. Exit/outcome data is stored separately in Checkpoint 3.3.

## Command

`python -m intrader shadow-step YYYY-MM-DD HH:MM`

The command:
1. reconstructs and records the immutable decision;
2. if actionable, opens one simulated shadow trade;
3. if WAIT/NO_TRADE, records the decision and opens nothing.

No broker order endpoint exists.
