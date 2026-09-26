# Phase 3 Checkpoint 1 — Records Manager + Decision Ledger

**Status:** IMPLEMENTATION COMPLETE. Local Python 3.11 regression verification remains pending.

## Goal

Capture exactly what Intrader knew and believed at a decision timestamp before any subsequent outcome is known.

## Decision actions

- BULLISH SETUP -> BUY_CALL
- BEARISH SETUP -> BUY_PUT
- WAIT -> WAIT
- NO TRADE -> NO_TRADE

For actionable setup states, also record the rejected opposite thesis.

## Immutable record

Each decision stores:

- deterministic decision ID
- UTC decision timestamp and session date
- brain state
- chosen action
- rejected action
- brain/rule version
- Direction
- Entry Quality
- Reversal Risk
- Confidence
- Family Coverage
- each family value/weight
- spot/future/VIX
- EMA9/EMA20/RSI14/ATR14
- opening range
- futures OI / dOI / dVolume
- basis / basis change
- OI PCR / volume PCR
- breadth
- depth imbalance
- high-impact-event flag
- deterministic regime label

## Reason journal

Reasons are stored in a child table:

- CHOSEN thesis
- REJECTED thesis
- GATE reason

Each reason has:

- machine-readable reason code
- category/family
- evidence value
- expected direction (-1, 0, +1)
- human-readable explanation

Reason rows are immutable with the parent record.

## Hindsight protection

SQLite triggers reject UPDATE and DELETE against decision records and decision reasons.

Outcomes, audits and annotations must live in separate tables added by later checkpoints.

## Command

`python -m intrader record-decision YYYY-MM-DD HH:MM`

The command reconstructs the Phase 2 measurements from SQLite, writes one immutable decision and prints its chosen/rejected thesis and reason codes.

## Acceptance

- repeated construction from the same inputs produces the same ID;
- BULLISH maps to BUY_CALL and rejects BUY_PUT;
- BEARISH maps to BUY_PUT and rejects BUY_CALL;
- WAIT/NO_TRADE are recorded;
- database UPDATE/DELETE attempts fail;
- storing the same decision twice is idempotent;
- no order API is introduced.
