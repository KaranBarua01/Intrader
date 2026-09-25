"""Intrader command-line entry point."""

from pathlib import Path
import getpass
import sys

from intrader import __version__
from intrader.auth import RequestsTransport, authenticate
from intrader.checkpoint2 import MarketAccessError, check_market_access
from intrader.config import load_config
from intrader.credentials import CredentialStore, credential_is_valid
from intrader.doctor import run_doctor
from intrader.feed_health import FeedHealth
from intrader.live_feed import LiveFeed
from intrader.secrets import REQUIRED_SECRET_NAMES


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
        try:
            config = load_config()
            store = CredentialStore()
            transport = RequestsTransport()
            report = check_market_access(store, transport)
            health = FeedHealth(
                report.instruments, config.stale_tick_seconds,
                config.stale_option_seconds,
            )
            feed = LiveFeed(
                lambda: authenticate(store, transport), report.instruments, health,
            )
            snapshot = feed.run_probe(int(argv[1]))
        except Exception:
            print("LIVE FEED: NO TRADE\nReason: ACCESS_UNAVAILABLE")
            return 1
        print(f"LIVE FEED: {snapshot.state}")
        print(f"Fresh instruments: {snapshot.fresh_count}/{snapshot.expected_count}")
        if snapshot.reasons:
            print(f"Reason: {', '.join(snapshot.reasons)}")
        return 0 if snapshot.state == "READY" else 1

    if argv:
        print("Usage: python -m intrader [doctor | credentials set NAME | check-market-access | check-live-feed SECONDS]")
        return 2

    print(f"Intrader {__version__}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
