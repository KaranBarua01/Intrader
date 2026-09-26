# Intrader

Intrader is a local Windows-based NIFTY intraday market-analysis assistant.

## Phase 1

Phase 1 builds the data foundation:

- Angel One SmartAPI market-data connectivity
- NIFTY instrument resolution
- live WebSocket feeds
- historical market-data backfill
- local SQLite storage
- feed-health monitoring
- 30-minute preparation state machine

Intrader does not place, modify, or cancel broker orders.

Phone execution remains completely manual.

## Local setup

Use Python 3.11 on Windows. From the project directory, create and activate a virtual environment, then install Intrader and its development tools:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e '.[dev]'
python -m pytest -v
```

If PowerShell blocks activation, you can call `.\.venv\Scripts\python.exe` directly in place of `python`.

Enter each long lived SmartAPI credential through the hidden terminal prompt. Values are stored by Windows Credential Manager and are never passed as command-line arguments:

```powershell
python -m intrader credentials set api_key
python -m intrader credentials set client_code
python -m intrader credentials set mpin
python -m intrader credentials set totp_secret
```

Use a fresh TOTP secret and API key. Earlier values were disclosed during setup and must not be reused. Do not paste credentials or current TOTP codes into chat, source files, or terminal command text.

Check local readiness:

```powershell
python -m intrader doctor
```

The doctor reports package, keyring, configuration, directory, and basic credential-format checks. `READY` means local prerequisites are available; it does not test SmartAPI login or market-data access. `NOT READY` names the missing or invalid prerequisite without printing a credential value. If a credential is invalid, run its `credentials set` command again and type the complete value at the hidden prompt. `credentials set` rejects entries that are too short or have an invalid TOTP format.

After rotating and privately storing the API key and TOTP setup key, check read-only broker access and current NIFTY contract resolution:

```powershell
python -m intrader check-market-access
```

This command fetches Angel One’s instrument master, logs in, obtains one NIFTY spot LTP quote, and resolves the nearest NIFTY future and ATM options. It prints only public instrument details. `MARKET ACCESS UNAVAILABLE` means that the live access gate remains closed.

During NSE market hours, run a bounded WebSocket health probe:

```powershell
python -m intrader check-live-feed 20
```

`READY` requires fresh NIFTY spot, India VIX, nearest future, and all selected ATM ±4 CE/PE ticks. Any missing, stale, disconnected, or malformed critical data gives `NO TRADE`. Outside market hours, `NO TRADE` is expected. The probe sends no orders and ends automatically after the requested seconds.

Intrader is currently in Phase 1, Checkpoint 3. Signals and the dashboard are not implemented yet.


## Phase 1 Checkpoint 4 — local persistence and backfill

Initialize the restart-safe local SQLite database:

```powershell
.\.venv\Scripts\python.exe -m intrader init-storage
```

The database is created at `data\intrader.db` and uses SQLite WAL mode. It stores:

- NIFTY / India VIX / nearest-future one-minute candles
- nearest-future historical OI observations
- live ATM ±4 CE/PE option snapshots with LTP, OI, volume, timestamps and sequence

Run a read-only historical backfill for a market session:

```powershell
.\.venv\Scripts\python.exe -m intrader backfill-session 2026-09-25 09:15 2026-09-25 15:30
```

Running the same backfill again is safe: candle and OI primary keys update existing rows instead of creating duplicates.

`check-live-feed` now also writes resolved option SNAP_QUOTE observations to the same SQLite database. A database write failure forces the feed to `NO TRADE`.

Checkpoint 4 code is implemented and offline-tested. The remaining checkpoint gate is one successful real historical backfill on the Windows/Python 3.11 machine.


## Phase 1 Checkpoint 5 — 30-minute session warm-up

Preview a configured session without making network requests:

```powershell
.\.venv\Scripts\python.exe -m intrader session-plan 2026-09-28
```

With the default 12:00 IST live start, the plan is:

- 09:15 IST market-open history baseline
- 11:30 IST warm-up start
- 12:00 IST readiness gate / selected live start
- 12:30 IST configured live-window end

Start the preparation engine at the warm-up start:

```powershell
.\.venv\Scripts\python.exe -m intrader prepare-session YYYY-MM-DD
```

The preparation engine:

1. backfills core NIFTY/VIX/future candles and future OI;
2. collects live ATM +/-4 option LTP/OI/volume during warm-up;
3. performs a final incremental candle/OI backfill at the selected start;
4. validates every critical live instrument;
5. returns `READY` only when the complete feed is fresh; otherwise it returns `NO TRADE`.

For data-integrity safety, starting more than 2 minutes after the configured warm-up start returns `NO TRADE: MISSED_WARMUP`, because the missing live option history cannot be reconstructed reliably.

Checkpoint 5 is offline-tested. Final completion requires one real market-hours warm-up on the Windows/Python 3.11 machine.


## Phase 2 Checkpoint 1 — Price Structure

Phase 2 development lives on the `intrader-phase2` branch so the Phase 1 live-verification branch remains stable.

The Price Structure engine currently calculates raw measurements only:

- NIFTY spot EMA 9 / EMA 20
- Wilder RSI 14
- Wilder ATR 14
- candle body and upper/lower wicks
- first-15-minute opening range
- previous stored spot-session high/low
- nearest-future VWAP
- cumulative relative futures volume versus prior stored sessions

NIFTY spot/index volume is not used for VWAP. Futures volume is used instead, and futures VWAP remains a separate futures measurement so it is never incorrectly treated as the same price series as NIFTY spot.

When sufficient stored data exists, the read-only diagnostic is:

```powershell
.\.venv\Scripts\python.exe -m intrader price-structure YYYY-MM-DD HH:MM
```

This command prints measurements only. Direction scoring and trade-state decisions are intentionally deferred to later Market Brain checkpoints.


## Phase 2 — Market Brain implementation

All five Phase 2 checkpoints are implemented on `intrader-phase2`. Full Python 3.11 regression verification must be completed locally before Phase 2 is treated as release-ready.

### Checkpoint 2 — Options Intelligence

The local options engine uses the stored nearest-expiry ATM +/-4 CE/PE snapshots and calculates:

- 5-minute LTP, OI and volume changes
- contract-level LONG_BUILDUP / SHORT_BUILDUP / SHORT_COVERING / LONG_UNWINDING labels
- OI PCR and volume PCR
- maximum CE/PE OI strikes
- maximum positive OI-change strikes
- OI concentration

Diagnostic:

```powershell
.\.venv\Scripts\python.exe -m intrader options-intelligence YYYY-MM-DD HH:MM
```

### Checkpoint 3 — Futures, VIX, Order Flow and Breadth

The SmartAPI SNAP_QUOTE decoder now uses the full 379-byte packet and captures:

- nearest-future LTP, OI and volume
- total buy/sell quantities
- five-level bid/ask depth
- best bid/ask and spread
- spot/future basis and basis change
- India VIX change
- futures buildup

NIFTY 50 breadth is optional confirmation. Membership comes from the official NIFTY Indices constituent CSV and constituents are resolved to exact Angel One NSE `-EQ` tokens. Constituent QUOTE subscriptions provide current price and previous close.

Public constituent weights are not guessed. Weighted breadth remains unavailable unless a verified official weight source is added.

Diagnostics:

```powershell
.\.venv\Scripts\python.exe -m intrader market-confirmation YYYY-MM-DD HH:MM
.\.venv\Scripts\python.exe -m intrader breadth YYYY-MM-DD HH:MM
```

### Checkpoint 4 — News and scheduled events

The context layer is non-directional and caches independent public sources in SQLite:

- RBI official press-release RSS
- BLS official release calendar
- Federal Reserve FOMC calendar

A failed source does not erase cached data from the other sources.

Diagnostic:

```powershell
.\.venv\Scripts\python.exe -m intrader context YYYY-MM-DD HH:MM
```

### Checkpoint 5 — Market Brain

The final Market Brain combines five independent directional families:

| Family | Maximum direction weight |
| --- | ---: |
| Price structure | 30 |
| Futures | 25 |
| Options | 20 |
| Breadth | 15 |
| Order flow | 10 |

Correlated indicators are combined inside their family before the family contributes to the overall Direction score.

Final outputs:

- Direction: -100 to +100
- Entry Quality: 0 to 100
- Reversal / Chase Risk: 0 to 100
- Confidence: 0 to 100
- Family Coverage: 0 to 100
- advisory state: `BULLISH SETUP`, `BEARISH SETUP`, `WAIT`, or `NO TRADE`

Initial state thresholds are intentionally uncalibrated engineering defaults for shadow testing. They are not claims of profitability and must be calibrated later from tracked outcomes.

Diagnostic:

```powershell
.\.venv\Scripts\python.exe -m intrader market-brain YYYY-MM-DD HH:MM
```

Intrader still contains no broker order-placement, order-modification, order-cancellation or GTT execution path. All actual execution remains manual on the user's phone.


## Phase 3 — Shadow Learning System

Phase 3 lives on the `intrader-phase3` branch and keeps execution fully simulated.

### Checkpoint 3.1 — Records Manager / Decision Ledger

Every Market Brain evaluation can be frozen into an immutable decision record containing:

- Brain/rule version
- BUY_CALL / BUY_PUT / WAIT / NO_TRADE action
- rejected opposite thesis
- Direction / Entry Quality / Reversal Risk / Confidence
- family evidence
- price/futures/options/breadth/order-flow measurements
- regime label
- machine-readable reason codes

Command:

```powershell
.\.venv\Scripts\python.exe -m intrader record-decision YYYY-MM-DD HH:MM
```

### Checkpoint 3.2 — Shadow Trader

Actionable decisions open one simulated nearest-ATM option position using `shadow-v0.1`:

- one lot
- 20% shadow stop
- 30% shadow target
- 30-minute maximum horizon

Command:

```powershell
.\.venv\Scripts\python.exe -m intrader shadow-step YYYY-MM-DD HH:MM
```

No broker order endpoint is used.

### Checkpoint 3.3 — Outcome Engine

After the full 30-minute observation horizon is available, Intrader records:

- first target/stop/timeout exit
- gross P&L
- friction-adjusted shadow P&L
- MFE / MAE
- NIFTY move through exit
- 1/3/5/10/15/30-minute option forward returns

Command:

```powershell
.\.venv\Scripts\python.exe -m intrader settle-shadow TRADE_ID YYYY-MM-DD HH:MM
```

### Checkpoint 3.4 — Reasoning Auditor

Each immutable reason is compared with the subsequent underlying move and trade result using `auditor-v0.1`.

Verdicts:

- SUPPORTED
- CONTRADICTED
- FLAT
- UNKNOWN
- UNGRADED

Command:

```powershell
.\.venv\Scripts\python.exe -m intrader audit-shadow TRADE_ID
```

These are associations/support checks, not causal claims.

### Checkpoint 3.5 — Records Manager analytics

```powershell
.\.venv\Scripts\python.exe -m intrader records-manager
```

The Records Manager reports:

- current shadow equity
- gross and adjusted P&L
- wins / losses / win rate
- expectancy
- profit factor
- maximum drawdown
- winning / losing streaks
- CALL vs PUT
- regime breakdown
- time-of-day breakdown
- Brain-version breakdown
- reason-code associations

### Checkpoint 3.6 — Calibration

```powershell
.\.venv\Scripts\python.exe -m intrader calibrate-shadow
```

`calibration-v0.1` uses a chronological 60/20/20 train/validation/test split and tests only baseline-or-stricter thresholds. Training selects a candidate; validation/test remain evaluation-only.

Calibration never rewrites production thresholds automatically.

### Checkpoint 3.7 — Promotion gate

```powershell
.\.venv\Scripts\python.exe -m intrader promotion-gate
```

`promotion-v0.1` returns PASS or REJECT from untouched evaluation evidence. A PASS is only an engineering gate; promotion remains a human decision.

### Integrity guarantees

- pre-decision reasoning is immutable;
- shadow entries are immutable;
- terminal outcomes are immutable;
- reasoning audits are versioned;
- WAIT and NO_TRADE decisions are retained;
- no order placement, modification, cancellation or GTT execution path exists;
- calibration and promotion never auto-deploy.


## Phase 4 — Windows Desktop App

Phase 4 lives on `intrader-phase4` and adds the executable desktop interface.

### Visual direction

The UI uses a minimalist light theme:

- warm white / off-white surfaces
- faint sand-cast texture impression through low-contrast panels
- very limited pale blue accents
- green/red reserved for market direction, P&L and health
- dense numbers and analysis without ornamental clutter

### Three operating modes

**Intrader Mode**
- current CALL / PUT / WAIT / NO TRADE decision
- Direction / Confidence / Entry Quality / Reversal Risk
- NIFTY candles
- reasoning and rejected opposite thesis
- active shadow trade
- global news and scheduled events
- Records Manager status

**Time Travel**
- 30-minute replay window
- play / pause / step controls
- synchronized stored candles
- immutable historical decision at the selected timestamp
- original reasoning and rejected thesis
- target/stop/timeout result
- MFE / MAE and 1/3/5/10/15/30-minute forward outcomes
- global market news cached for that replay window

**Analysis Mode**
- shadow equity curve
- adjusted P&L
- win rate / expectancy / profit factor / drawdown
- CALL vs PUT
- regime and time-of-day performance
- reason-code performance

Additional pages include Thesis, Shadow Trader, Records Manager, Trade History, Market Research Browser, Calibration, System Health and Export.

### Global news

Phase 4 adds zero-key worldwide market-news retrieval through the GDELT DOC API and stores matching articles in the same local news cache used by live mode and Time Travel. The embedded Market Research Browser is available for manual article inspection.

### Launch from source

Install desktop dependencies:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev,ui]"
```

Run either:

```powershell
.\.venv\Scripts\python.exe -m intrader desktop
```

or:

```powershell
.\.venv\Scripts\intrader-ui.exe
```

### Build the Windows executable

```powershell
.\scripts\build_windows.ps1
```

Output:

```text
dist\Intrader\Intrader.exe
```

Packaged UI data is stored under Windows LocalAppData rather than inside the executable directory, so application updates do not replace the SQLite learning history.

### Update button

The top-bar **Update** button has two safe modes.

Development checkout:
- requires the current branch to be `intrader-phase4`
- checks `origin/intrader-phase4`
- refuses to update when tracked local changes exist
- applies only a `git pull --ff-only`
- asks for confirmation before applying

Packaged executable:
- checks the latest GitHub release
- requires `Intrader-Windows-x64.zip` and its SHA-256 asset
- downloads and verifies the package
- stages replacement outside the running application
- closes Intrader, replaces application files, and relaunches
- never replaces the LocalAppData database or Windows Credential Manager secrets

The GitHub release workflow builds the Windows package and checksum automatically whenever a release is published.
