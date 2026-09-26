# Phase 3 Checkpoint 6 — Calibration Engine

**Status:** IN PROGRESS.

## Goal

Replace arbitrary threshold assumptions with evidence while preventing the calibration process from grading itself on the same data it optimized.

## Baseline thresholds

Current rules-v0.1:
- |Direction| >= 35
- Confidence >= 60
- Entry Quality >= 55
- Reversal Risk <= 70

## First calibration scope

The initial shadow dataset only contains trades that passed the baseline gates. Therefore calibration-v0.1 searches **equal or stricter** thresholds only.

It must not claim that lower thresholds are better/worse until counterfactual WAIT outcomes are available.

## Split

Chronological:
- first 60%: TRAIN
- next 20%: VALIDATION
- final 20%: TEST

Candidate selection uses TRAIN only.

VALIDATION and TEST are evaluation-only.

## Candidate objective

Among candidates meeting the minimum training sample:
1. prefer positive expectancy;
2. maximize training expectancy;
3. break ties using larger sample size and profit factor.

The report always exposes validation/test performance separately.

## No auto-deployment

Calibration produces a candidate report only. It does not rewrite Market Brain thresholds.
