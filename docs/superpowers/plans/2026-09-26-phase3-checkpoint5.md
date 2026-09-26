# Phase 3 Checkpoint 5 — Records Manager and Performance Analytics

**Status:** IN PROGRESS.

## Goal

Summarize the immutable decision/trade/outcome/audit history into an operator-facing record of whether Intrader is making money and where its reasoning works or fails.

## Overall metrics

- decisions recorded
- WAIT / NO_TRADE / BUY_CALL / BUY_PUT counts
- completed shadow trades
- wins / losses / flats
- win rate
- gross P&L
- estimated-friction adjusted P&L
- current shadow equity from configurable starting capital
- average winner / loser
- expectancy per trade
- profit factor
- maximum drawdown and drawdown %
- max winning / losing streak

## Breakdowns

- CALL vs PUT
- regime
- entry hour
- Brain version
- reason-code association

Reason-code statistics report association/support, not causality.

## Command

`python -m intrader records-manager`
