# Strategy Lab — Phase 4 Research Mode

**Status:** IMPLEMENTED; live integration intentionally disabled.

## Purpose

Strategy Lab is a fourth desktop mode for testing external/book-inspired trading
hypotheses against the same historical NIFTY candle data used by Time Travel.

It is deliberately separated from Intrader Mode.

## Isolation contract

Strategy Lab may:

- read/backfill historical NIFTY candles;
- read recorded Market Brain decisions to annotate regime context;
- measure forward 5m / 15m / 30m directional outcomes;
- measure 30-minute MFE / MAE;
- drill an occurrence into Time Travel.

Strategy Lab may **not**:

- alter Market Brain family weights;
- change live thresholds;
- create or modify DecisionRecord rows;
- create shadow trades;
- settle shadow trades;
- modify reasoning audits;
- modify calibration or promotion results;
- call broker order/modify/cancel/GTT APIs.

## Initial research catalog

These are **book-inspired hypotheses**, not claimed verbatim rules. Exact
edition-specific extraction would require the source PDFs.

### Steve Nison / Candlestick

- Bullish Engulfing
- Bearish Engulfing
- Hammer after decline
- Shooting Star after rise

### Ashwani Gujral / Intraday

- simplified 9/20 EMA trend pullback
- 15-minute Opening Range Breakout
- classic Pivot R1/S1 breakout

### John Carter / Mastering the Trade

- simplified Bollinger/Keltner volatility squeeze release

### Mark Douglas / Trading Psychology

- Process Discipline is listed as process-only research.
- It generates no candle prediction.
- Future testing requires manual override / discipline / decision-process logs.

## Metrics

For each price strategy:

- occurrence count
- bullish / bearish occurrences
- 5-minute directional hit rate
- 15-minute directional hit rate
- 30-minute directional hit rate
- average signed 5/15/30-minute move
- average 30-minute MFE
- average 30-minute MAE
- sample-size label

Sample labels:

- NO SIGNALS
- TINY SAMPLE (<10)
- EARLY (<30)
- DEVELOPING (<100)
- BROADER SAMPLE (>=100)

## Promotion philosophy

Strategy Lab is observational research only.

A strategy is not eligible for Intrader merely because it has a high in-sample
hit rate. A future promotion process should require:

1. adequate sample size;
2. regime/time stability;
3. realistic transaction-cost analysis;
4. chronological train/validation/test;
5. ablation against the existing Market Brain;
6. human approval.

Until then, the UI remains marked:

**LAB ONLY — NOT USED BY INTRADER MODE**
