# Intrader Phase 3 — Shadow Learning System

**Status:** IN PROGRESS.

**Purpose:** Turn Phase 2 intelligence into an auditable learning loop. Phase 3 does not add broker execution.

## Version freeze

- Market Brain baseline: `brain-v0.1`
- Decision rule baseline: `rules-v0.1`
- Initial shadow execution rules: `shadow-v0.1`

These identifiers are persisted with every decision/trade so future logic cannot silently rewrite history.

## Checkpoints

1. **3.1 Records Manager + Decision Ledger**
   - immutable Market Brain decision records
   - chosen action and rejected opposite thesis
   - machine-readable reason codes
   - raw market measurements at decision time
   - brain/rule versions
   - deterministic regime label

2. **3.2 Shadow Trader**
   - BUY_CALL / BUY_PUT only for initial directional simulator
   - one-lot simulated position
   - versioned stop/target/timeout rules
   - no broker endpoint

3. **3.3 Outcome Engine**
   - gross and friction-adjusted shadow P&L
   - MFE / MAE
   - 1/3/5/10/15/30-minute forward returns
   - target/stop/timeout exit classification
   - equity curve and drawdown inputs

4. **3.4 Reasoning Auditor**
   - attach outcomes to immutable pre-trade reason codes
   - reason success/failure statistics
   - chosen thesis vs rejected thesis analysis
   - no causal claim from correlation alone

5. **3.5 Performance + Regime Analytics**
   - CALL vs PUT
   - time-of-day
   - regime
   - reason code
   - Brain version
   - win rate, expectancy, profit factor, drawdown, streaks

6. **3.6 Calibration Engine**
   - chronological train/validation/test split
   - threshold search on training only
   - untouched validation/test evaluation
   - candidate report only; never silently rewrites production thresholds

7. **3.7 Version Promotion Gate**
   - explicit PASS / REJECT report for a candidate Brain/rule version
   - sample-size, expectancy, profit factor and drawdown gates
   - promotion remains a human decision

## Non-negotiable integrity rules

- Pre-decision reasoning is immutable.
- Outcome data is stored separately from reasoning.
- WAIT and NO_TRADE decisions are recorded, not discarded.
- Opposite-thesis rejection is recorded for CALL/PUT setups.
- No Phase 3 code calls order placement, modification, cancellation or GTT endpoints.
- Calibration results never auto-deploy.
