# Intrader — System Design

Date: 2026-09-25

## Goal
Build a Windows-only NIFTY intraday analysis assistant that runs on the user's laptop, displays analysis on an external monitor, and never places orders. All buy/sell execution happens manually on the user's phone.

The user chooses a trading start time, e.g. 12:00. The system begins a 30-minute warm-up at 11:30, backfills the current session, connects all live feeds, calculates market state, validates feed health, and reaches either READY or NO TRADE by 12:00. During the live session it provides advisory states only: BULLISH SETUP, BEARISH SETUP, WAIT, or NO TRADE.

## Hard Safety / Scope Rules
- No API order placement.
- No broker credentials used for execution.
- Phone is the only execution device.
- Any stale or missing critical data forces NO TRADE.
- No signal is allowed to persist from stale data.
- Live analysis must not depend on Cloudflare.
- Phase 1 and Phase 2 target cost: zero.

## Runtime Architecture
Angel One SmartAPI -> Local Windows data collector -> Local analysis engines -> Local SQLite -> PySide6/PyQtGraph dashboard.

Optional Cloudflare services may be added later only for non-critical tasks such as lightweight news relay, configuration sync, or remote summaries.

## Data Sources
Primary:
- Angel One SmartAPI live WebSocket / quotes
- Angel One historical candles
- Angel One current OI / market depth / Greeks / IV where available

Secondary:
- Official RSS / scheduled macro-event sources
- Free public news sources for context only

## Instruments
- NIFTY spot
- Nearest relevant NIFTY futures contract
- India VIX
- NIFTY option strikes centered on ATM, default ATM +/- 4 strikes
- Selected NIFTY sector / constituent data for breadth and confirmation

## Signal Families
1. Price structure: VWAP, EMA 9/20, RSI 14, ATR 14, candle body/wicks, opening range, previous-day high/low, relative volume.
2. Futures confirmation: futures price, OI, change in OI calculated locally, spot-futures basis and basis change.
3. Options: CE/PE LTP, LTP change, volume, OI, locally calculated change in OI, local PCR, buildup classification.
4. Volatility/Greeks: IV, IV change/skew, Delta, Gamma, Theta, Vega, time-to-expiry, gamma concentration.
5. Breadth/leadership: advances/declines, weighted breadth, heavyweight contribution, selected sector confirmation.
6. Order flow/liquidity: bid/ask spread, five-level depth, persistent order-book imbalance.
7. Volatility/regime: India VIX and change, ATR percentile, realized volatility, time-of-day normalization.
8. Catalysts/risk: news, scheduled events, data health.

## Output Engines
- Direction score
- Entry Quality score
- Reversal / Chase Risk score
- Confidence / evidence agreement
- NO TRADE gate
- Trade Guardian after manual trade entry

The system must avoid double-counting correlated indicators. Each signal family contributes independently.

## Data Health Gate
Critical feeds must have freshness thresholds. If any required feed exceeds its stale threshold, signal output is disabled and the UI shows NO TRADE with the reason.

The application calculates OI change itself from consecutive OI values rather than trusting any documented dummy/garbage percentage-change field.

## Session State Machine
CONFIGURED -> PREPARING -> SYNCING -> ANALYSING -> VALIDATING -> READY or NO TRADE -> LIVE -> ENDED.

Example:
- 11:30 PREPARING
- Immediate backfill from 09:15 to 11:30 plus historical baselines
- 11:35 onward live accumulation and regime building
- 11:55 stability/data-health checks
- 12:00 READY or NO TRADE
- 12:00-12:30 LIVE advisory window

## Persistence
SQLite stores:
- one-minute market state snapshots
- live option snapshots
- OI observations
- futures state
- breadth and VIX state
- news/event metadata
- generated signals
- future outcomes at 5m/10m/15m/30m
- manual trade annotations and Trade Guardian metrics

Historical outcomes are used for research and calibration, not treated as guaranteed probabilities.

## UI
External monitor:
- NIFTY chart area
- Market Brain panel: state, direction, entry quality, reversal risk, data health, concise reasons

Laptop screen:
- detailed diagnostics, option/futures/breadth/news details, logs

Primary live states:
- BULLISH SETUP
- BEARISH SETUP
- WAIT
- NO TRADE

## Development Stack
- Python 3.11
- PySide6
- PyQtGraph
- SQLite
- pandas / numpy
- pytest
- Git
- PyInstaller for final Windows executable

Sensitive secrets are stored locally only, preferably Windows Credential Manager / encrypted OS-backed storage. They are never committed to Git.

## 3 Phases x 5 Checkpoints

### Phase 1 — Data Foundation
1. Development environment, project structure, logging, config, secure secrets.
2. SmartAPI authentication, instruments, expiry and ATM detection.
3. Live market feed and reconnect/stale-data handling.
4. SQLite, historical backfill, local option snapshot collection.
5. 30-minute warm-up/session preparation engine.

Each checkpoint must pass its bug gate before moving on.

### Phase 2 — Market Brain
1. Price structure engine.
2. Options intelligence engine.
3. Futures, breadth, VIX, order-flow confirmation.
4. News and scheduled event context.
5. Direction / Entry Quality / Reversal / Confidence / NO TRADE engine.

### Phase 3 — Live Trading Assistant
1. Final dashboard.
2. Session controller and configurable warm-up/live window.
3. Manual-position Trade Guardian.
4. Shadow/paper mode and outcome tracking.
5. Packaging, recovery, diagnostics, backup, production release.

## Initial SmartAPI Setup Requirements
Before coding:
- TOTP must be configured in the user's authenticator app.
- The previously exposed TOTP seed must be rotated/reset before use.
- Create a SmartAPI app/key for market-data use.
- Do not share API key, secret, PIN/password, TOTP seed, or current TOTP code in chat.
- We will not use order endpoints.
- Static IP requirements for order execution are intentionally outside this project scope.

## Acceptance Criteria for Phase 1
- Fresh install launches successfully.
- SmartAPI authentication works without secrets hard-coded in source.
- NIFTY, futures, ATM option strikes and India VIX stream reliably.
- Disconnect/reconnect handling works.
- Stale data forces NO TRADE.
- Historical data backfill completes.
- SQLite restart produces no duplicate/corrupt core records.
- Warm-up session reaches READY/NO TRADE predictably.

## Non-Goals for V1
- Automated order placement
- Broker account execution integration
- Paid AI dependency
- Cloud-dependent live calculations
- Prediction guarantees
