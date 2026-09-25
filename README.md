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
