# Intrader Phase 2 Checkpoint 1 — Price Structure Engine

**Status:** IN PROGRESS.

**Goal:** Convert stored one-minute NIFTY spot and nearest-future candles into deterministic price-structure metrics. This checkpoint produces measurements only; it does not emit BUY/SELL instructions or a final direction score.

## Data roles

Use NIFTY spot candles for:

- EMA 9
- EMA 20
- RSI 14
- ATR 14
- candle body / upper wick / lower wick
- opening-range high / low
- previous-session high / low

Use nearest NIFTY future candles for:

- session VWAP
- cumulative relative volume

Reason: index spot volume may be zero or non-tradable metadata. A futures VWAP must never be compared directly to spot price as if the two instruments were identical; it is exposed as a separate futures metric.

## Definitions

- EMA: standard alpha `2 / (period + 1)`, seeded by the SMA of the first period closes.
- RSI 14: Wilder smoothing, seeded from the first 14 close-to-close changes.
- ATR 14: Wilder smoothing of true range.
- Candle body: `close - open`.
- Upper wick: `high - max(open, close)`.
- Lower wick: `min(open, close) - low`.
- Opening range: first 15 market minutes by default.
- Previous-session high/low: max/min of the supplied prior session spot candles.
- Futures VWAP: cumulative typical price `(H+L+C)/3` weighted by future volume.
- Relative volume: current future cumulative volume through the current minute divided by the mean cumulative volume through the same minute-of-day across supplied prior sessions.

## Safety / quality rules

- All candles must be timezone-aware and strictly increasing.
- OHLC must remain internally valid.
- Calculations fail closed on insufficient data rather than inventing values.
- VWAP is unavailable when total futures volume is zero.
- Relative volume is unavailable when no usable prior-session baseline exists.
- Missing prior-day data remains explicitly unavailable; it is not substituted with current-day values.
- No correlated metrics are converted into a combined score in this checkpoint.

## Deliverables

1. `src/intrader/price_structure.py`
2. deterministic indicator tests
3. SQLite candle read API
4. analysis snapshot dataclass containing raw measurements
5. later integration command using stored candles once baseline history is present

## Acceptance

- EMA 9/20 verified against hand-computed fixtures.
- RSI 14 and ATR 14 verified against independent fixtures.
- Opening range and previous-day levels correct.
- Futures VWAP rejects zero-volume data.
- Relative volume aligns by minute-of-day, not list position.
- Invalid/unsorted candles fail closed.
- Existing Phase 1 tests remain green.
