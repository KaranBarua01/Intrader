"""Intrader command-line entry point."""

from datetime import date, datetime
from pathlib import Path
import getpass
import sys

from intrader import __version__
from intrader.auth import RequestsTransport, authenticate
from intrader.backfill import BackfillError, backfill_core_market
from intrader.brain_pipeline import build_stored_market_brain
from intrader.breadth_pipeline import build_stored_breadth
from intrader.breadth_provider import (
    RequestsTextTransport,
    fetch_nifty50_constituents,
    resolve_breadth_members,
)
from intrader.checkpoint2 import MarketAccessError, check_market_access
from intrader.config import load_config
from intrader.context_pipeline import refresh_context
from intrader.context_sources import RequestsContextTransport
from intrader.credentials import CredentialStore, credential_is_valid
from intrader.doctor import run_doctor
from intrader.feed_health import FeedHealth
from intrader.historical import INDIA_TIME
from intrader.live_feed import LiveFeed
from intrader.market_confirmation_pipeline import build_stored_market_confirmation
from intrader.options_pipeline import OptionsPipelineError, build_stored_options_intelligence
from intrader.outcome_pipeline import OutcomePipelinePending, settle_shadow_trade
from intrader.price_pipeline import PricePipelineError, build_stored_price_structure
from intrader.reasoning_pipeline import audit_shadow_trade
from intrader.records_manager_pipeline import build_records_manager
from intrader.records_pipeline import record_stored_decision
from intrader.secrets import REQUIRED_SECRET_NAMES
from intrader.shadow_pipeline import run_shadow_step
from intrader.session import (
    SessionCoordinator,
    SessionScheduleError,
    SessionState,
    WarmupRunner,
    build_session_schedule,
)
from intrader.storage import MarketSnapshotSink, OptionSnapshotSink, SQLiteStore


def _database_path() -> Path:
    return Path.cwd() / "data" / "intrader.db"


def _parse_india_datetime(day: str, clock: str) -> datetime:
    return datetime.strptime(f"{day} {clock}", "%Y-%m-%d %H:%M").replace(
        tzinfo=INDIA_TIME
    )


def _now_india() -> datetime:
    return datetime.now(INDIA_TIME)


def _optional_breadth_members(market_report):
    """Resolve current NIFTY 50 breadth without making it a core dependency."""

    if not market_report.master:
        return ()
    try:
        constituents = fetch_nifty50_constituents(RequestsTextTransport())
        return resolve_breadth_members(constituents, market_report.master)
    except Exception:
        return ()


def _print_schedule(schedule) -> None:
    print("SESSION PLAN")
    print(f"Market open: {schedule.market_open:%Y-%m-%d %H:%M %Z}")
    print(f"Warm-up start: {schedule.warmup_start:%Y-%m-%d %H:%M %Z}")
    print(f"Live start: {schedule.live_start:%Y-%m-%d %H:%M %Z}")
    print(f"Live end: {schedule.live_end:%Y-%m-%d %H:%M %Z}")


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

    if argv and argv[0] == "session-plan":
        if len(argv) != 2:
            print("Usage: python -m intrader session-plan YYYY-MM-DD")
            return 2
        try:
            session_date = date.fromisoformat(argv[1])
            schedule = build_session_schedule(load_config(), session_date)
        except (ValueError, SessionScheduleError):
            print("SESSION PLAN UNAVAILABLE")
            return 1
        _print_schedule(schedule)
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
            breadth_members = _optional_breadth_members(report)
            breadth_tokens = tuple(
                member.instrument.token for member in breadth_members
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
                tick_sink=MarketSnapshotSink(
                    db_store, report.instruments, breadth_members
                ),
                breadth_tokens=breadth_tokens,
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

    if argv and argv[0] == "price-structure":
        if len(argv) != 3:
            print("Usage: python -m intrader price-structure YYYY-MM-DD HH:MM")
            return 2
        try:
            session_date = date.fromisoformat(argv[1])
            at = _parse_india_datetime(argv[1], argv[2])
            config = load_config()
            credential_store = CredentialStore()
            transport = RequestsTransport()
            session = authenticate(credential_store, transport)
            market = check_market_access(
                credential_store,
                transport,
                as_of=session_date,
                session=session,
            )
            with SQLiteStore(_database_path()) as db_store:
                snapshot = build_stored_price_structure(
                    db_store,
                    market.instruments,
                    session_date,
                    at,
                    config,
                )
        except Exception:
            print("PRICE STRUCTURE UNAVAILABLE")
            return 1

        def display(value):
            return "N/A" if value is None else str(value)

        print("PRICE STRUCTURE OK")
        print(f"At: {snapshot.at.astimezone(INDIA_TIME):%Y-%m-%d %H:%M %Z}")
        print(f"Spot close: {snapshot.spot_close}")
        print(f"EMA 9: {snapshot.ema9}")
        print(f"EMA 20: {snapshot.ema20}")
        print(f"RSI 14: {snapshot.rsi14}")
        print(f"ATR 14: {snapshot.atr14}")
        print(f"Candle body: {snapshot.candle_body}")
        print(f"Upper wick: {snapshot.upper_wick}")
        print(f"Lower wick: {snapshot.lower_wick}")
        print(f"Opening range high: {snapshot.opening_range_high}")
        print(f"Opening range low: {snapshot.opening_range_low}")
        print(f"Previous session high: {display(snapshot.previous_session_high)}")
        print(f"Previous session low: {display(snapshot.previous_session_low)}")
        print(f"Future close: {display(snapshot.future_close)}")
        print(f"Future VWAP: {display(snapshot.future_vwap)}")
        print(f"Relative volume: {display(snapshot.relative_volume)}")
        return 0

    if argv and argv[0] == "options-intelligence":
        if len(argv) != 3:
            print("Usage: python -m intrader options-intelligence YYYY-MM-DD HH:MM")
            return 2
        try:
            session_date = date.fromisoformat(argv[1])
            at = _parse_india_datetime(argv[1], argv[2])
            config = load_config()
            with SQLiteStore(_database_path()) as db_store:
                snapshot = build_stored_options_intelligence(
                    db_store,
                    session_date,
                    at,
                    config,
                )
        except Exception:
            print("OPTIONS INTELLIGENCE UNAVAILABLE")
            return 1

        def display(value):
            return "N/A" if value is None else str(value)

        print("OPTIONS INTELLIGENCE OK")
        print(f"At: {snapshot.at.astimezone(INDIA_TIME):%Y-%m-%d %H:%M %Z}")
        print(f"Lookback: {snapshot.lookback_minutes} minutes")
        print(f"CE OI: {snapshot.total_call_open_interest}")
        print(f"PE OI: {snapshot.total_put_open_interest}")
        print(f"OI PCR: {display(snapshot.open_interest_pcr)}")
        print(f"CE volume: {snapshot.total_call_volume}")
        print(f"PE volume: {snapshot.total_put_volume}")
        print(f"Volume PCR: {display(snapshot.volume_pcr)}")
        print(
            "Max CE OI strike: "
            f"{snapshot.max_call_open_interest_strike}"
        )
        print(
            "Max PE OI strike: "
            f"{snapshot.max_put_open_interest_strike}"
        )
        print(
            "Max +CE OI change strike: "
            f"{display(snapshot.max_call_open_interest_change_strike)}"
        )
        print(
            "Max +PE OI change strike: "
            f"{display(snapshot.max_put_open_interest_change_strike)}"
        )
        print(
            "CE OI concentration: "
            f"{display(snapshot.call_open_interest_concentration)}"
        )
        print(
            "PE OI concentration: "
            f"{display(snapshot.put_open_interest_concentration)}"
        )
        for contract in snapshot.contracts:
            print(
                f"{contract.strike} {contract.option_type} | "
                f"LTP {contract.current_ltp} "
                f"dLTP {contract.ltp_change} "
                f"OI {contract.current_open_interest} "
                f"dOI {contract.open_interest_change} "
                f"VOL {contract.current_volume} "
                f"dVOL {contract.volume_change} "
                f"{contract.buildup}"
            )
        return 0

    if argv and argv[0] == "market-confirmation":
        if len(argv) != 3:
            print("Usage: python -m intrader market-confirmation YYYY-MM-DD HH:MM")
            return 2
        try:
            session_date = date.fromisoformat(argv[1])
            at = _parse_india_datetime(argv[1], argv[2])
            config = load_config()
            credential_store = CredentialStore()
            transport = RequestsTransport()
            session = authenticate(credential_store, transport)
            market = check_market_access(
                credential_store,
                transport,
                as_of=session_date,
                session=session,
            )
            with SQLiteStore(_database_path()) as db_store:
                snapshot = build_stored_market_confirmation(
                    db_store,
                    market.instruments,
                    session_date,
                    at,
                    config,
                )
        except Exception:
            print("MARKET CONFIRMATION UNAVAILABLE")
            return 1

        def display(value):
            return "N/A" if value is None else str(value)

        print("MARKET CONFIRMATION OK")
        print(f"At: {snapshot.at.astimezone(INDIA_TIME):%Y-%m-%d %H:%M %Z}")
        print(f"Lookback: {snapshot.lookback_minutes} minutes")
        print(f"Future LTP: {snapshot.futures.ltp}")
        print(f"Future dLTP: {snapshot.futures.ltp_change}")
        print(f"Future OI: {snapshot.futures.open_interest}")
        print(f"Future dOI: {snapshot.futures.open_interest_change}")
        print(f"Future volume: {snapshot.futures.volume}")
        print(f"Future dVolume: {snapshot.futures.volume_change}")
        print(f"Future buildup: {snapshot.futures.buildup}")
        print(f"Basis: {snapshot.futures.basis}")
        print(f"Basis change: {snapshot.futures.basis_change}")
        print(f"VIX: {snapshot.vix.value}")
        print(f"VIX change: {snapshot.vix.change}")
        print(f"VIX change %: {display(snapshot.vix.change_pct)}")
        print(
            "Total buy/sell ratio: "
            f"{display(snapshot.order_flow.total_buy_sell_ratio)}"
        )
        print(
            "Depth buy/sell ratio: "
            f"{display(snapshot.order_flow.depth_buy_sell_ratio)}"
        )
        print(
            "Depth imbalance: "
            f"{display(snapshot.order_flow.depth_imbalance)}"
        )
        print(f"Best bid: {display(snapshot.order_flow.best_bid)}")
        print(f"Best ask: {display(snapshot.order_flow.best_ask)}")
        print(f"Spread: {display(snapshot.order_flow.spread)}")
        print(f"Spread bps: {display(snapshot.order_flow.spread_bps)}")
        return 0

    if argv and argv[0] == "breadth":
        if len(argv) != 3:
            print("Usage: python -m intrader breadth YYYY-MM-DD HH:MM")
            return 2
        try:
            session_date = date.fromisoformat(argv[1])
            at = _parse_india_datetime(argv[1], argv[2])
            config = load_config()
            with SQLiteStore(_database_path()) as db_store:
                snapshot = build_stored_breadth(
                    db_store,
                    session_date,
                    at,
                    config,
                )
        except Exception:
            print("BREADTH UNAVAILABLE")
            return 1

        def display(value):
            return "N/A" if value is None else str(value)

        print("BREADTH OK")
        print(f"At: {snapshot.at.astimezone(INDIA_TIME):%Y-%m-%d %H:%M %Z}")
        print(f"Members: {snapshot.total}")
        print(f"Advancing: {snapshot.advancing}")
        print(f"Declining: {snapshot.declining}")
        print(f"Unchanged: {snapshot.unchanged}")
        print(f"A/D ratio: {display(snapshot.advance_decline_ratio)}")
        print(f"Equal-weight breadth %: {snapshot.equal_weight_breadth_pct}")
        print(f"Weighted return %: {display(snapshot.weighted_return_pct)}")
        for sector in snapshot.sectors:
            print(
                f"{sector.sector} | ADV {sector.advancing} "
                f"DEC {sector.declining} UNCH {sector.unchanged} "
                f"BREADTH {sector.equal_weight_breadth_pct}"
            )
        return 0

    if argv and argv[0] == "context":
        if len(argv) != 3:
            print("Usage: python -m intrader context YYYY-MM-DD HH:MM")
            return 2
        try:
            at = _parse_india_datetime(argv[1], argv[2])
            with SQLiteStore(_database_path()) as db_store:
                result = refresh_context(
                    db_store,
                    RequestsContextTransport(),
                    at,
                )
        except Exception:
            print("CONTEXT UNAVAILABLE")
            return 1

        snapshot = result.snapshot
        print("CONTEXT OK")
        print(
            "Refreshed sources: "
            + (", ".join(result.refreshed_sources) or "NONE")
        )
        print(
            "Failed sources: "
            + (", ".join(result.failed_sources) or "NONE")
        )
        next_high = snapshot.minutes_to_next_high_impact
        print(
            "Minutes to next HIGH event: "
            + ("N/A" if next_high is None else str(next_high))
        )
        print(f"Active event windows: {len(snapshot.active_event_windows)}")
        for event in snapshot.active_event_windows:
            print(
                f"ACTIVE {event.impact} | {event.source} | "
                f"{event.name} | {event.scheduled_at.isoformat()}"
            )
        print(f"Upcoming events: {len(snapshot.upcoming_events)}")
        for event in snapshot.upcoming_events:
            print(
                f"UPCOMING {event.impact} | {event.source} | "
                f"{event.name} | {event.scheduled_at.isoformat()}"
            )
        print(f"Recent news: {len(snapshot.recent_news)}")
        for item in snapshot.recent_news[:10]:
            print(
                f"NEWS | {item.source} | {item.published_at.isoformat()} | "
                f"{item.title}"
            )
        return 0

    if argv and argv[0] == "market-brain":
        if len(argv) != 3:
            print("Usage: python -m intrader market-brain YYYY-MM-DD HH:MM")
            return 2
        try:
            session_date = date.fromisoformat(argv[1])
            at = _parse_india_datetime(argv[1], argv[2])
            config = load_config()
            credential_store = CredentialStore()
            transport = RequestsTransport()
            session = authenticate(credential_store, transport)
            market = check_market_access(
                credential_store,
                transport,
                as_of=session_date,
                session=session,
            )
            with SQLiteStore(_database_path()) as db_store:
                snapshot = build_stored_market_brain(
                    db_store,
                    market.instruments,
                    session_date,
                    at,
                    config,
                )
        except Exception:
            print("MARKET BRAIN: NO TRADE")
            print("Reason: CORE_DATA_UNAVAILABLE")
            return 1

        print(f"MARKET BRAIN: {snapshot.state}")
        print(f"Direction: {snapshot.direction_score}")
        print(f"Entry quality: {snapshot.entry_quality}")
        print(f"Reversal risk: {snapshot.reversal_risk}")
        print(f"Confidence: {snapshot.confidence}")
        print(f"Family coverage: {snapshot.family_coverage}")
        for family in snapshot.families:
            print(
                f"{family.name} | weight {family.weight} | "
                f"value {family.value}"
            )
        if snapshot.reasons:
            print(f"Reason: {', '.join(snapshot.reasons)}")
        return 0 if snapshot.state != "NO TRADE" else 1

    if argv and argv[0] == "record-decision":
        if len(argv) != 3:
            print("Usage: python -m intrader record-decision YYYY-MM-DD HH:MM")
            return 2
        try:
            session_date = date.fromisoformat(argv[1])
            at = _parse_india_datetime(argv[1], argv[2])
            config = load_config()
            credential_store = CredentialStore()
            transport = RequestsTransport()
            session = authenticate(credential_store, transport)
            market = check_market_access(
                credential_store,
                transport,
                as_of=session_date,
                session=session,
            )
            with SQLiteStore(_database_path()) as db_store:
                result = record_stored_decision(
                    db_store,
                    market.instruments,
                    session_date,
                    at,
                    config,
                )
        except Exception:
            print("DECISION RECORD UNAVAILABLE")
            return 1

        record = result.record
        print("DECISION RECORDED" if result.inserted else "DECISION ALREADY RECORDED")
        print(f"Decision ID: {record.decision_id}")
        print(f"Brain: {record.brain_version}")
        print(f"Rules: {record.rule_version}")
        print(f"State: {record.brain_state}")
        print(f"Action: {record.action}")
        print(f"Rejected action: {record.rejected_action or 'N/A'}")
        print(f"Regime: {record.regime}")
        print(f"Direction: {record.direction_score}")
        print(f"Confidence: {record.confidence}")
        print("Chosen reasoning:")
        chosen = [reason for reason in record.reasons if reason.thesis == "CHOSEN"]
        for reason in chosen:
            print(f"- {reason.reason_code}: {reason.explanation}")
        print("Rejected-thesis reasoning:")
        rejected = [reason for reason in record.reasons if reason.thesis == "REJECTED"]
        if rejected:
            for reason in rejected:
                print(f"- {reason.reason_code}: {reason.explanation}")
        else:
            print("- N/A")
        gates = [reason for reason in record.reasons if reason.thesis == "GATE"]
        if gates:
            print("Gate/context reasoning:")
            for reason in gates:
                print(f"- {reason.reason_code}: {reason.explanation}")
        return 0

    if argv and argv[0] == "shadow-step":
        if len(argv) != 3:
            print("Usage: python -m intrader shadow-step YYYY-MM-DD HH:MM")
            return 2
        try:
            session_date = date.fromisoformat(argv[1])
            at = _parse_india_datetime(argv[1], argv[2])
            config = load_config()
            credential_store = CredentialStore()
            transport = RequestsTransport()
            session = authenticate(credential_store, transport)
            market = check_market_access(
                credential_store,
                transport,
                as_of=session_date,
                session=session,
            )
            with SQLiteStore(_database_path()) as db_store:
                result = run_shadow_step(
                    db_store,
                    market.instruments,
                    session_date,
                    at,
                    config,
                )
        except Exception:
            print("SHADOW STEP UNAVAILABLE")
            return 1

        decision = result.decision.record
        print(f"DECISION: {decision.action}")
        print(f"Decision ID: {decision.decision_id}")
        print(f"Brain: {decision.brain_version}")
        print(f"Rules: {decision.rule_version}")
        print(f"Rejected action: {decision.rejected_action or 'N/A'}")
        if result.trade is None:
            print("SHADOW TRADE: NONE")
            return 0

        trade = result.trade
        print(
            "SHADOW TRADE OPENED"
            if result.trade_inserted
            else "SHADOW TRADE ALREADY EXISTS"
        )
        print(f"Trade ID: {trade.trade_id}")
        print(f"Shadow rules: {trade.shadow_version}")
        print(f"Action: {trade.action}")
        print(f"Contract: {trade.strike} {trade.option_type}")
        print(f"Entry: {trade.entry_price}")
        print(f"Quantity: {trade.quantity}")
        print(f"Stop: {trade.stop_price}")
        print(f"Target: {trade.target_price}")
        print(f"Timeout: {trade.max_minutes} minutes")
        return 0

    if argv and argv[0] == "settle-shadow":
        if len(argv) != 4:
            print(
                "Usage: python -m intrader settle-shadow "
                "TRADE_ID YYYY-MM-DD HH:MM"
            )
            return 2
        trade_id = argv[1]
        try:
            as_of = _parse_india_datetime(argv[2], argv[3])
            credential_store = CredentialStore()
            transport = RequestsTransport()
            session = authenticate(credential_store, transport)
            market = check_market_access(
                credential_store,
                transport,
                as_of=as_of.date(),
                session=session,
            )
            with SQLiteStore(_database_path()) as db_store:
                result = settle_shadow_trade(
                    db_store,
                    market.instruments,
                    trade_id,
                    as_of,
                )
        except OutcomePipelinePending as exc:
            print("SHADOW OUTCOME: PENDING")
            print(f"Reason: {exc}")
            return 0
        except Exception:
            print("SHADOW OUTCOME UNAVAILABLE")
            return 1

        outcome = result.outcome
        print(
            "SHADOW OUTCOME RECORDED"
            if result.inserted
            else "SHADOW OUTCOME ALREADY RECORDED"
        )
        print(f"Trade ID: {outcome.trade_id}")
        print(f"Exit reason: {outcome.exit_reason}")
        print(f"Exit price: {outcome.exit_price}")
        print(f"Gross P&L: {outcome.gross_pnl}")
        print(f"Estimated friction: {outcome.estimated_friction}")
        print(f"Adjusted P&L: {outcome.adjusted_pnl}")
        print(f"MFE amount: {outcome.mfe_amount}")
        print(f"MAE amount: {outcome.mae_amount}")
        print(
            "Directional NIFTY move: "
            + (
                "N/A"
                if outcome.directional_spot_change is None
                else str(outcome.directional_spot_change)
            )
        )
        for minutes, value in outcome.forward_returns:
            print(
                f"Forward {minutes}m: "
                + ("N/A" if value is None else f"{value}%")
            )
        return 0

    if argv and argv[0] == "audit-shadow":
        if len(argv) != 2:
            print("Usage: python -m intrader audit-shadow TRADE_ID")
            return 2
        try:
            with SQLiteStore(_database_path()) as db_store:
                result = audit_shadow_trade(db_store, argv[1])
        except Exception:
            print("REASONING AUDIT UNAVAILABLE")
            return 1

        print("REASONING AUDIT OK")
        print(f"Trade ID: {argv[1]}")
        print(f"New audit rows: {result.inserted_rows}")
        for audit in result.audits:
            print(
                f"{audit.thesis} | {audit.reason_code} | "
                f"{audit.verdict} | trade {audit.trade_result} | "
                f"P&L {audit.adjusted_pnl}"
            )
        return 0

    if argv == ["records-manager"]:
        try:
            with SQLiteStore(_database_path()) as db_store:
                snapshot = build_records_manager(db_store)
        except Exception:
            print("RECORDS MANAGER UNAVAILABLE")
            return 1

        overall = snapshot.overall
        print("INTRADER RECORDS MANAGER")
        print(f"Starting capital: {snapshot.starting_capital}")
        print(f"Current shadow equity: {snapshot.current_equity}")
        print(f"Completed trades: {overall.trades}")
        print(f"Wins: {overall.wins}")
        print(f"Losses: {overall.losses}")
        print(
            "Win rate: "
            + ("N/A" if overall.win_rate is None else f"{overall.win_rate}%")
        )
        print(f"Gross P&L: {overall.gross_pnl}")
        print(f"Adjusted P&L: {overall.adjusted_pnl}")
        print(
            "Expectancy: "
            + ("N/A" if overall.expectancy is None else str(overall.expectancy))
        )
        print(
            "Profit factor: "
            + ("N/A" if overall.profit_factor is None else str(overall.profit_factor))
        )
        print(f"Max drawdown: {overall.max_drawdown}")
        print(f"Max drawdown %: {overall.max_drawdown_pct}")
        print(f"Max winning streak: {overall.max_winning_streak}")
        print(f"Max losing streak: {overall.max_losing_streak}")
        print("Decision counts:")
        for action, count in snapshot.decision_counts:
            print(f"- {action}: {count}")
        print("CALL / PUT:")
        for action, metrics in snapshot.by_action:
            print(
                f"- {action}: trades {metrics.trades}, "
                f"P&L {metrics.adjusted_pnl}, "
                f"win rate "
                + ("N/A" if metrics.win_rate is None else f"{metrics.win_rate}%")
            )
        print("Regimes:")
        for regime, metrics in snapshot.by_regime:
            print(
                f"- {regime}: trades {metrics.trades}, "
                f"P&L {metrics.adjusted_pnl}, "
                f"expectancy "
                + ("N/A" if metrics.expectancy is None else str(metrics.expectancy))
            )
        print("Reason associations:")
        for reason in snapshot.reasons[:20]:
            print(
                f"- {reason.reason_code}: n={reason.occurrences}, "
                f"profit={reason.profitable}, loss={reason.losing}, "
                f"supported={reason.supported}, "
                f"contradicted={reason.contradicted}, "
                f"avg P&L={reason.average_pnl}"
            )
        return 0

    if argv and argv[0] == "prepare-session":
        if len(argv) != 2:
            print("Usage: python -m intrader prepare-session YYYY-MM-DD")
            return 2
        db_store: SQLiteStore | None = None
        try:
            config = load_config()
            session_date = date.fromisoformat(argv[1])
            schedule = build_session_schedule(config, session_date)
            now = _now_india()
            precheck = SessionCoordinator(
                schedule,
                warmup_start_grace_seconds=config.warmup_start_grace_seconds,
            )
            state = precheck.begin(now)
            if state == SessionState.CONFIGURED:
                print("SESSION: CONFIGURED")
                print("Reason: WARMUP_NOT_STARTED")
                _print_schedule(schedule)
                return 0
            if state in {SessionState.NO_TRADE, SessionState.ENDED}:
                print(f"SESSION: {state.value}")
                if precheck.reasons:
                    print(f"Reason: {', '.join(precheck.reasons)}")
                return 1

            credential_store = CredentialStore()
            transport = RequestsTransport()
            initial_session = authenticate(credential_store, transport)
            market = check_market_access(
                credential_store,
                transport,
                as_of=session_date,
                session=initial_session,
            )
            breadth_members = _optional_breadth_members(market)
            breadth_tokens = tuple(
                member.instrument.token for member in breadth_members
            )
            db_store = SQLiteStore(_database_path())
            db_store.initialize()
            health = FeedHealth(
                market.instruments,
                config.stale_tick_seconds,
                config.stale_option_seconds,
            )
            first_session = [initial_session]

            def session_provider():
                if first_session:
                    return first_session.pop()
                return authenticate(credential_store, transport)

            def backfill_action(start: datetime, end: datetime):
                return backfill_core_market(
                    db_store,
                    initial_session,
                    transport,
                    market.instruments,
                    start,
                    end,
                )

            def live_action(seconds: float):
                feed = LiveFeed(
                    session_provider,
                    market.instruments,
                    health,
                    tick_sink=MarketSnapshotSink(
                        db_store, market.instruments, breadth_members
                    ),
                    breadth_tokens=breadth_tokens,
                )
                return feed.run_probe(seconds)

            coordinator = SessionCoordinator(
                schedule,
                warmup_start_grace_seconds=config.warmup_start_grace_seconds,
            )
            preparation_started = _now_india()
            result = WarmupRunner(
                schedule,
                coordinator,
                backfill_action,
                live_action,
            ).run(preparation_started)
        except Exception:
            print("SESSION: NO TRADE")
            print("Reason: PREPARATION_FAILED")
            return 1
        finally:
            if db_store is not None:
                db_store.close()

        print(f"SESSION: {result.state.value}")
        if result.initial_backfill is not None:
            print(
                "Initial backfill: "
                f"{result.initial_backfill.candle_rows} candles, "
                f"{result.initial_backfill.oi_rows} OI"
            )
        if result.final_backfill is not None:
            print(
                "Warm-up backfill: "
                f"{result.final_backfill.candle_rows} candles, "
                f"{result.final_backfill.oi_rows} OI"
            )
        if result.health is not None:
            print(
                "Fresh instruments: "
                f"{result.health.fresh_count}/{result.health.expected_count}"
            )
        if result.reasons:
            print(f"Reason: {', '.join(result.reasons)}")
        return 0 if result.state == SessionState.READY else 1

    if argv:
        print(
            "Usage: python -m intrader "
            "[doctor | init-storage | credentials set NAME | check-market-access | "
            "check-live-feed SECONDS | backfill-session YYYY-MM-DD HH:MM YYYY-MM-DD HH:MM | "
            "session-plan YYYY-MM-DD | prepare-session YYYY-MM-DD | price-structure YYYY-MM-DD HH:MM | options-intelligence YYYY-MM-DD HH:MM | market-confirmation YYYY-MM-DD HH:MM | breadth YYYY-MM-DD HH:MM | context YYYY-MM-DD HH:MM | market-brain YYYY-MM-DD HH:MM | record-decision YYYY-MM-DD HH:MM | shadow-step YYYY-MM-DD HH:MM | settle-shadow TRADE_ID YYYY-MM-DD HH:MM | audit-shadow TRADE_ID | records-manager]"
        )
        return 2

    print(f"Intrader {__version__}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
