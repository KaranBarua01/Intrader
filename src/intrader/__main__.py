"""Intrader command-line entry point."""

from datetime import datetime
from pathlib import Path
import getpass
import sys

from intrader import __version__
from intrader.auth import RequestsTransport, authenticate
from intrader.backfill import BackfillError, backfill_core_market
from intrader.checkpoint2 import MarketAccessError, check_market_access
from intrader.config import load_config
from intrader.credentials import CredentialStore, credential_is_valid
from intrader.doctor import run_doctor
from intrader.feed_health import FeedHealth
from intrader.historical import INDIA_TIME
from intrader.live_feed import LiveFeed
from intrader.secrets import REQUIRED_SECRET_NAMES
from intrader.storage import OptionSnapshotSink, SQLiteStore


def _database_path() -> Path:
    return Path.cwd() / "data" / "intrader.db"


def _parse_india_datetime(day: str, clock: str) -> datetime:
    return datetime.strptime(f"{day} {clock}", "%Y-%m-%d %H:%M").replace(
        tzinfo=INDIA_TIME
    )


def main(argv: list[str] | None = None) -> int:
    if argv and argv[:2] == ["credentials", "set"]:
        if len(argv) != 3 or argv[2] not in REQUIRED_SECRET_NAMES:
            print("Unsupported credential name")
            return 2
        name = argv[2]
        try:
            value = getpass.getpass(f"{name}: ")
            if not credential_is_valid(name, value):
                print(f"{name}: not stored")
                return 1
            CredentialStore().set(name, value)
        except (Exception, KeyboardInterrupt):
            print(f"{name}: not stored")
            return 1
        print(f"{name}: stored")
        return 0

    if argv == ["doctor"]:
        try:
            config = load_config()
        except (ValueError, TypeError):
            print("Intrader doctor: NOT READY\nFAIL config: invalid")
            return 1
        report = run_doctor(
            config, CredentialStore(), Path.cwd() / "data", Path.cwd() / "logs"
        )
        print(report.format())
        return 0 if report.ready else 1

    if argv == ["init-storage"]:
        try:
            with SQLiteStore(_database_path()):
                pass
        except Exception:
            print("STORAGE UNAVAILABLE")
            return 1
        print("STORAGE READY")
        return 0

    if argv == ["check-market-access"]:
        try:
            report = check_market_access(CredentialStore(), RequestsTransport())
        except MarketAccessError:
            print("MARKET ACCESS UNAVAILABLE")
            return 1
        print("MARKET ACCESS OK")
        print(f"NIFTY spot token: {report.instruments.spot.token}")
        print(f"India VIX token: {report.instruments.vix.token}")
        print(f"NIFTY future token: {report.instruments.future.token}")
        print(f"Options expiry: {report.instruments.option_expiry}")
        print(f"ATM strike: {report.instruments.atm_strike}")
        return 0

    if argv and argv[0] == "check-live-feed":
        if len(argv) != 2 or not argv[1].isdigit() or not 1 <= int(argv[1]) <= 120:
            print("Usage: python -m intrader check-live-feed SECONDS (1-120)")
            return 2
        db_store: SQLiteStore | None = None
        try:
            config = load_config()
            credential_store = CredentialStore()
            transport = RequestsTransport()
            initial_session = authenticate(credential_store, transport)
            report = check_market_access(
                credential_store, transport, session=initial_session
            )
            db_store = SQLiteStore(_database_path())
            db_store.initialize()
            health = FeedHealth(
                report.instruments,
                config.stale_tick_seconds,
                config.stale_option_seconds,
            )
            first_session = [initial_session]

            def session_provider():
                if first_session:
                    return first_session.pop()
                return authenticate(credential_store, transport)

            feed = LiveFeed(
                session_provider,
                report.instruments,
                health,
                tick_sink=OptionSnapshotSink(db_store, report.instruments),
            )
            snapshot = feed.run_probe(int(argv[1]))
        except Exception:
            print("LIVE FEED: NO TRADE\nReason: ACCESS_UNAVAILABLE")
            return 1
        finally:
            if db_store is not None:
                db_store.close()
        print(f"LIVE FEED: {snapshot.state}")
        print(f"Fresh instruments: {snapshot.fresh_count}/{snapshot.expected_count}")
        if snapshot.reasons:
            print(f"Reason: {', '.join(snapshot.reasons)}")
        return 0 if snapshot.state == "READY" else 1

    if argv and argv[0] == "backfill-session":
        if len(argv) != 5:
            print(
                "Usage: python -m intrader backfill-session "
                "YYYY-MM-DD HH:MM YYYY-MM-DD HH:MM"
            )
            return 2
        try:
            start = _parse_india_datetime(argv[1], argv[2])
            end = _parse_india_datetime(argv[3], argv[4])
            credential_store = CredentialStore()
            transport = RequestsTransport()
            session = authenticate(credential_store, transport)
            market = check_market_access(
                credential_store,
                transport,
                as_of=start.date(),
                session=session,
            )
            with SQLiteStore(_database_path()) as db_store:
                report = backfill_core_market(
                    db_store,
                    session,
                    transport,
                    market.instruments,
                    start,
                    end,
                )
        except Exception:
            print("BACKFILL UNAVAILABLE")
            return 1
        print("BACKFILL OK")
        print(f"Candle rows processed: {report.candle_rows}")
        print(f"OI rows processed: {report.oi_rows}")
        return 0

    if argv:
        print(
            "Usage: python -m intrader "
            "[doctor | init-storage | credentials set NAME | check-market-access | "
            "check-live-feed SECONDS | backfill-session YYYY-MM-DD HH:MM YYYY-MM-DD HH:MM]"
        )
        return 2

    print(f"Intrader {__version__}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
