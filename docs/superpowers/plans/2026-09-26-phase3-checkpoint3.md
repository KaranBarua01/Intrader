# Phase 3 Checkpoint 3 — Outcome Engine

**Status:** IN PROGRESS.

## Goal

Attach objective post-decision market outcomes to immutable shadow entries without rewriting the original reasoning.

## Exit model

For BUY_CALL / BUY_PUT long-option shadow trades:

- first observed option LTP >= target -> TARGET
- first observed option LTP <= stop -> STOP
- otherwise at max lifetime -> TIMEOUT

The engine uses observed stored option LTP snapshots only. It does not invent intrabar highs/lows.

## Metrics

- exit timestamp / option premium
- gross P&L
- estimated-friction P&L
- gross / adjusted return %
- MFE / MAE in premium and currency terms
- underlying NIFTY change through exit when available
- direction-adjusted underlying move
- 1/3/5/10/15/30 minute option forward returns

## Friction

shadow-v0.1 applies a simple 5 bps-per-side slippage estimate to premium turnover. It is explicitly an engineering estimate, not a claim about actual Angel One fees/taxes.

Gross P&L is always retained separately.

## Integrity

Outcomes are stored in a separate immutable table. Decision and entry rows remain untouched.

## Command

`python -m intrader settle-shadow TRADE_ID YYYY-MM-DD HH:MM`

If the trade has not hit target/stop and its timeout has not elapsed, settlement remains pending rather than fabricating an exit.
