# Intrader Phase 1 Checkpoint 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task by task. Steps use checkbox syntax for tracking.

**Goal:** Finish the local foundation so Intrader can store long lived credentials safely, log diagnostics without leaking secrets, and report whether the machine is ready for SmartAPI work.

**Architecture:** Keep the current `CredentialStore` as the Windows keyring adapter behind `SecretStore`. Add one redacting logging boundary and one read only doctor command. Neither component authenticates with SmartAPI or persists session tokens.

**Tech Stack:** Python 3.11, keyring, pytest, standard library logging and pathlib.

**Spec:** `docs/superpowers/specs/2026-09-25-intrader-design.md`

## Global Constraints

- Windows and Python `>=3.11,<3.12`.
- No order placement, modification, cancellation, GTT, or automatic execution.
- Long lived credentials reside in Windows Credential Manager through `keyring`.
- JWT, refresh token, feed token, TOTP values and broker credentials never appear in logs or normal project files.
- Critical stale or missing data must eventually produce `NO TRADE` in later checkpoints.

## Review Focus

- Missing credential: doctor reports only presence, never its value.
- Logging a mapping or exception containing a secret: no secret appears in output.
- Unavailable keyring: doctor reports a failure without exposing exception details that could contain secrets.
- Unwritable data or log directory: doctor reports not ready without modifying unrelated files.
- Unsupported Python version: doctor reports not ready.

---

### Task 1: Bind credential adapter to the secret contract

**Files:** Modify `src/intrader/credentials.py`; test `tests/test_credentials.py`.

**Interfaces:** `CredentialStore(backend: KeyringBackend | None = None)` implements `SecretStore.set(name, value)` and `SecretStore.get(name)`, retaining `delete(name)`.

- [ ] Add a failing test: `isinstance(CredentialStore(backend=MemoryKeyring()), SecretStore)` and a set/get round trip through a `SecretStore` typed reference.
- [ ] Run `python -m pytest tests/test_credentials.py -v`; confirm the new test fails for the missing interface.
- [ ] Make `CredentialStore` inherit `SecretStore` without changing keyring behavior.
- [ ] Run the targeted test and full suite; inspect Git diff; commit `feat: bind credential store to secret interface`.

### Task 2: Redacting logging boundary

**Files:** Create `src/intrader/safe_logging.py`; test `tests/test_safe_logging.py`.

**Interfaces:** `configure_logging(log_path: Path, *, secret_store: SecretStore | None = None) -> logging.Logger` returns the `intrader` logger. It creates the log directory and installs a filter that redacts known sensitive fields and any nonempty secret values obtained from the store.

- [ ] Add failing tests for message and exception redaction, including a nested mapping containing a known credential value.
- [ ] Run targeted tests and confirm failure due to missing module.
- [ ] Implement the logger with a redaction filter at both logger and handler boundaries; avoid printing exception text when it may contain a secret.
- [ ] Run targeted tests and full suite; inspect Git diff; commit `feat: add secret redacting logs`.

### Task 3: Read only environment doctor

**Files:** Create `src/intrader/doctor.py`; modify `src/intrader/__main__.py`; test `tests/test_doctor.py`.

**Interfaces:** `run_doctor(config: AppConfig, store: SecretStore, data_dir: Path, log_dir: Path) -> DoctorReport` checks Python version, required packages, Windows keyring availability, config, path writability, and credential presence by name. `python -m intrader doctor` prints a report containing no values.

- [ ] Add failing tests for a healthy environment, missing secret, unsupported version, unwritable path, and CLI output free of credential values.
- [ ] Run targeted tests and confirm failure due to missing behavior.
- [ ] Implement `DoctorReport` and `run_doctor`; add the CLI subcommand. Do not initiate SmartAPI authentication.
- [ ] Run targeted tests and full suite; run `python -m intrader doctor`; inspect Git diff and commit `feat: add environment doctor`.

### Task 4: Checkpoint gate and documentation

**Files:** Update `src/intrader/__main__.py` and `README.md`; test `tests/test_credential_cli.py`.

- [ ] Add a failing test for `python -m intrader credentials set NAME`: hidden prompt, Windows keyring write, no value in output, rejection of session-token names.
- [ ] Implement the CLI and run its targeted tests and the full suite.
- [ ] Run the full suite, CLI entry point, `git status`, and a targeted review of tracked files for credential leakage without printing secret values.
- [ ] Document exact local setup and a passing or failing doctor interpretation.
- [ ] Commit `docs: document checkpoint one setup` after verification.

## Execution note

The user selected direct work in `C:\Users\Karanbarua01\Desktop\Intrader`. This Codex session can edit the source tree but its terminal receives an OS-level access denial on `.git/index.lock`, including after a filesystem permission grant for `.git`. The file changes and tests can be completed here; Git staging and commits require a user-side terminal or a future session with Git write access. Do not claim the checkpoint's commit gate has passed until Git confirms it.
