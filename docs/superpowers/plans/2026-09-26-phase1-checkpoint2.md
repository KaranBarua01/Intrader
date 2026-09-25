# Intrader Phase 1 Checkpoint 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task by task. Steps use checkbox syntax for tracking.

**Goal:** Authenticate for read-only SmartAPI data and resolve current NIFTY instruments, expiry, and ATM option strikes without exposing credentials or tokens.

**Architecture:** A small HTTP adapter reads long-lived credentials from `SecretStore`, generates TOTP in memory, and retains returned tokens only in an in-memory session object. The installed SDK is not used for login because its error logger can write request headers and login fields. A separate instrument parser consumes the official master list and selects contracts from their actual expiry and strike fields.

**Tech Stack:** Python 3.11, requests, pyotp, pytest, Angel One SmartAPI and official instrument master.

**Spec:** `docs/superpowers/specs/2026-09-25-intrader-design.md`

**Current status:** Offline implementation and 39 tests pass. Live authentication is pending rotation of the exposed TOTP setup key and API key. Git staging is blocked by repository `.git` permissions in the Codex sandbox.

## Global Constraints

- No order, modification, cancellation, GTT or automatic execution code.
- No broker credentials or current TOTP codes in source, logs, command output, error messages or normal files.
- JWT, refresh and feed tokens remain in memory only.
- A failed or malformed authentication response fails closed.
- The exposed TOTP seed and API key must both be rotated before any live authentication test.
- The official instrument master is fetched over HTTPS with a timeout; stale or incomplete instrument data cannot produce a ready state.

## Review Focus

- Missing credential or malformed TOTP seed: no HTTP request and no value in errors.
- Network or API failure: sanitized error containing no request or response body.
- Invalid or missing JWT, refresh or feed token: no session returned.
- Duplicate, expired or missing NIFTY instruments: resolution fails explicitly.
- Missing CE or PE among ATM ±4 strikes: resolution fails explicitly.

---

### Task 1: Safe authentication boundary

**Files:** Create `src/intrader/auth.py`; test `tests/test_auth.py`.

**Interfaces:** `authenticate(store: SecretStore, transport: HTTPTransport, *, now: datetime | None = None) -> SmartSession`. `SmartSession` stores `api_key`, `client_code`, `jwt_token`, `refresh_token`, `feed_token` in memory, has a redacted repr, and is never serialized. `HTTPTransport.post_json(url, headers, body, timeout) -> dict` is injectable for tests.

- [ ] Write failing tests for request shape and generated TOTP, missing inputs, malformed response, transport error sanitization, and redacted session repr.
- [ ] Run targeted tests to see expected failure.
- [ ] Implement only the documented login endpoint and a strict response parser.
- [ ] Run targeted tests and full suite; review diff; commit `feat: add safe SmartAPI authentication`.

### Task 2: Instrument master and resolver

**Files:** Create `src/intrader/instruments.py`; test `tests/test_instruments.py`.

**Interfaces:** `fetch_instrument_master(transport: HTTPTransport) -> list[Instrument]`; `resolve_nifty_instruments(master: Sequence[Instrument], as_of: date, spot_ltp: Decimal, strikes_each_side: int = 4) -> NiftyInstruments`.

- [ ] Write failing tests using realistic official master rows for NIFTY spot, India VIX, nearest futures expiry, nearest option expiry, and ATM ±4 CE/PE selection.
- [ ] Test malformed expiry, 100x strike scaling, missing pair, and expired contracts.
- [ ] Run targeted tests to see expected failure.
- [ ] Implement strict parsing and selection with no fixed token or strike interval assumptions.
- [ ] Run targeted tests and full suite; review diff; commit `feat: resolve NIFTY instruments from master`.

### Task 3: Read-only live verification gate

**Files:** Create `src/intrader/checkpoint2.py`; test `tests/test_checkpoint2.py`; update `README.md`.

**Interfaces:** `check_market_access(store: SecretStore, transport: HTTPTransport) -> Checkpoint2Report` authenticates, fetches master, obtains current NIFTY spot LTP through a market-data-only endpoint, and resolves the bundle. CLI output includes only status and public instrument identifiers, never secrets or tokens.

- [ ] Write failing tests for success, missing spot quote, network failure and output redaction.
- [ ] Run targeted tests to see expected failure.
- [ ] Implement a read-only command with timeout and no order endpoint references.
- [ ] Run targeted and full suite, then one live verification only after the user confirms the TOTP seed was rotated.
- [ ] Review command output and Git status; commit `feat: verify SmartAPI market access`.

## Source notes

- Angel One's SmartAPI documentation describes client code, MPIN and TOTP login: `https://smartapi.angelone.in/docs`.
- Angel One's official Python SDK documents `loginByPassword` and response token fields: `https://github.com/angel-one/smartapi-python/blob/main/SmartApi/smartConnect.py`.
- Angel One publishes the instrument master at `https://margincalculator.angelone.in/OpenAPI_File/files/OpenAPIScripMaster.json`.
