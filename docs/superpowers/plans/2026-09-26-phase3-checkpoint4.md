# Phase 3 Checkpoint 4 — Reasoning Auditor

**Status:** IMPLEMENTATION COMPLETE. Local Python 3.11 regression verification remains pending.

## Goal

Audit the immutable pre-trade reason journal against subsequent observed market behavior without rewriting the original reasoning.

## Auditor version

`auditor-v0.1`

Multiple auditor versions may coexist later. Old audits are not overwritten.

## Per-reason verdicts

For directional reasons:

- SUPPORTED — underlying NIFTY move matched the reason's expected direction
- CONTRADICTED — underlying move opposed it
- FLAT — underlying did not move directionally
- UNKNOWN — underlying exit observation unavailable

For non-directional risk/gate reasons:

- UNGRADED

Separately record trade association:

- PROFIT
- LOSS
- FLAT

This is association/support analysis, not a claim that a reason caused the trade outcome.

## Opposite thesis

Rejected-thesis reason rows are audited too. This lets Records Manager later ask whether evidence used to reject CALL/PUT was historically useful.

## Integrity

Audit rows are versioned and immutable.

## Command

`python -m intrader audit-shadow TRADE_ID`
