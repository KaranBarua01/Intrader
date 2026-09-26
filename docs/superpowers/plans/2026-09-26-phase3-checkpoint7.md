# Phase 3 Checkpoint 7 — Version Promotion Gate

**Status:** IMPLEMENTATION COMPLETE. Local Python 3.11 regression verification remains pending.

## Goal

Turn calibration evidence into an explicit PASS/REJECT recommendation without automatically modifying production Market Brain rules.

## promotion-v0.1 default gates

- TEST selected trades >= 5
- VALIDATION expectancy > 0
- TEST expectancy > 0
- TEST profit factor >= 1.20
- TEST maximum drawdown <= 10% of shadow starting capital

The initial sample floor is intentionally low enough for engineering/shadow validation and should be raised before any serious capital decision.

## Result

PASS or REJECT with machine-readable reasons.

A PASS means only that the candidate cleared the configured statistical engineering gate. It does not prove future profitability.

## Human control

Promotion remains a human decision. No threshold/rule file is rewritten by this checkpoint.
