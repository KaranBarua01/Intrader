# Intrader Phase 2 Checkpoint 4 — News and Scheduled Event Context

**Status:** IMPLEMENTATION COMPLETE. Non-directional context engine, RBI RSS, BLS ICS, Fed FOMC parser, SQLite cache, resilient refresh pipeline, diagnostic command, and tests are committed. Local Python 3.11 regression verification remains pending.

**Goal:** Add zero-cost contextual awareness around scheduled macro events and authoritative recent releases without turning text/news into a direct market-direction signal.

## Source boundaries

Initial public sources:

- RBI official Press Releases RSS
- U.S. BLS official release calendar (ICS)
- Federal Reserve official FOMC meeting calendar
- MoSPI official release calendar / known CPI and IIP release schedules when a reliable machine-readable route is available

Source failures are independent. A failed news/calendar source does not disable SmartAPI market data.

## Context model

Recent news:
- source
- title
- published timestamp
- URL/category
- deduplicated by canonical URL/title

Scheduled events:
- source
- event name
- scheduled timestamp
- category
- impact class: HIGH / MEDIUM / LOW

No sentiment classification is used in this checkpoint.

## Event windows

Default descriptive risk windows:

- HIGH: 30 minutes before through 15 minutes after
- MEDIUM: 15 minutes before through 10 minutes after
- LOW: reported as upcoming only

These windows are configurable metadata, not trading advice.

## Output

- recent authoritative items in configurable lookback
- upcoming events in configurable horizon
- active scheduled-event windows
- minutes to next HIGH-impact event
- sources represented

No BUY/SELL/BULLISH/BEARISH output.

## Acceptance

- duplicate news is removed;
- future news is ignored;
- stale news outside the lookback is ignored;
- timezone conversion is explicit;
- overlapping event windows are preserved rather than collapsed;
- source/parser failures are sanitized;
- BLS ICS parser handles TZID and folded lines;
- RBI RSS parser handles RFC 2822 dates;
- event context remains independent from market-data readiness.
