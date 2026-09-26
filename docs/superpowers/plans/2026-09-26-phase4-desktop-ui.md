# Intrader Phase 4 — Desktop UI + Live Shadow Operations

**Status:** IN PROGRESS.

## Objective

Package Intrader as a practical Windows desktop application with a clean minimalist light interface, three operating modes, integrated Records Manager, research browser, export tools, system health, and safe GitHub updates.

## Visual direction

- white / warm off-white base
- subtle sand-cast paper texture impression through low-contrast surfaces
- extremely limited pale blue accents
- red/green reserved for market direction, P&L and health exceptions
- dense numerical information without ornamental visual noise
- rounded cards, thin separators, soft shadows
- typography optimized for desktop data analysis

## Modes

### Intrader Mode
Live market dashboard and shadow trading:
- current decision
- Direction / Confidence / Entry Quality / Reversal Risk
- live candles
- CALL/PUT thesis
- shadow position
- breadth/futures/order-flow/VIX
- global context/news
- system health

### Time Travel
Historical 30-minute replay:
- timestamp scrubber
- play/pause/step controls
- synchronized candles, market measurements, news/event context
- decision at that historical timestamp
- forward 1/3/5/10/15/30-minute outcome
- original reasoning and rejected thesis

### Analysis Mode
Today/session review:
- equity/P&L metrics
- win rate / expectancy / profit factor / drawdown
- CALL vs PUT
- regime/time/reason performance
- trade history
- reasoning audits
- calibration / promotion status
- exports

## Global navigation

Dashboard, Intrader Mode, Time Travel, Analysis Mode, Thesis, Shadow Trader,
Records Manager, Trade History, Research Browser, Calibration, System Health,
Export.

## Update button

Top-bar Update button:
- development checkout: fetch/check `origin/intrader-phase4`, show commits, update with `git pull --ff-only` only after confirmation;
- refuse source update when tracked working tree changes exist;
- never touch ignored `data/`, logs, keyring credentials or local secrets;
- packaged executable: check GitHub release channel; self-replacement is handled only through a release updater, never by editing the running executable in place.

## Packaging

PySide6 + PyQtGraph desktop application.
PyInstaller build target for Windows executable.
Trading logic remains outside UI widgets.
