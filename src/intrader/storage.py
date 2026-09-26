"""Restart-safe local SQLite persistence for Intrader market data."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from pathlib import Path
import sqlite3
from typing import TYPE_CHECKING

from intrader.instruments import Instrument, NiftyInstruments
from intrader.stream_protocol import MarketTick

if TYPE_CHECKING:
    from intrader.historical import Candle, OIObservation


SCHEMA_VERSION = 8


class StorageError(Exception):
    """Local persistence is unavailable or received invalid data."""


def _utc_iso(value) -> str:
    if value.tzinfo is None:
        raise StorageError("timestamp must be timezone aware")
    from datetime import timezone

    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds")


class SQLiteStore:
    """Small transactional SQLite boundary for Phase 1 market data."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(path)
        self._connection.execute("PRAGMA busy_timeout=5000")

    def initialize(self) -> None:
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA foreign_keys=ON")
        self._connection.execute("PRAGMA synchronous=NORMAL")
        with self._connection:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS candles (
                    exchange TEXT NOT NULL,
                    token TEXT NOT NULL,
                    interval TEXT NOT NULL,
                    ts_utc TEXT NOT NULL,
                    open REAL NOT NULL,
                    high REAL NOT NULL,
                    low REAL NOT NULL,
                    close REAL NOT NULL,
                    volume INTEGER NOT NULL CHECK(volume >= 0),
                    PRIMARY KEY (exchange, token, interval, ts_utc)
                );

                CREATE TABLE IF NOT EXISTS oi_observations (
                    exchange TEXT NOT NULL,
                    token TEXT NOT NULL,
                    interval TEXT NOT NULL,
                    ts_utc TEXT NOT NULL,
                    oi INTEGER NOT NULL CHECK(oi >= 0),
                    PRIMARY KEY (exchange, token, interval, ts_utc)
                );

                CREATE TABLE IF NOT EXISTS option_snapshots (
                    exchange TEXT NOT NULL,
                    token TEXT NOT NULL,
                    exchange_ts_utc TEXT NOT NULL,
                    received_ts_utc TEXT NOT NULL,
                    sequence INTEGER NOT NULL CHECK(sequence >= 0),
                    expiry TEXT NOT NULL,
                    strike REAL NOT NULL,
                    option_type TEXT NOT NULL CHECK(option_type IN ('CE', 'PE')),
                    ltp REAL NOT NULL CHECK(ltp > 0),
                    open_interest INTEGER NOT NULL CHECK(open_interest >= 0),
                    volume INTEGER NOT NULL CHECK(volume >= 0),
                    PRIMARY KEY (exchange, token, exchange_ts_utc, sequence)
                );

                CREATE TABLE IF NOT EXISTS index_snapshots (
                    exchange TEXT NOT NULL,
                    token TEXT NOT NULL,
                    exchange_ts_utc TEXT NOT NULL,
                    received_ts_utc TEXT NOT NULL,
                    sequence INTEGER NOT NULL CHECK(sequence >= 0),
                    ltp REAL NOT NULL CHECK(ltp > 0),
                    PRIMARY KEY (exchange, token, exchange_ts_utc, sequence)
                );

                CREATE TABLE IF NOT EXISTS future_snapshots (
                    exchange TEXT NOT NULL,
                    token TEXT NOT NULL,
                    exchange_ts_utc TEXT NOT NULL,
                    received_ts_utc TEXT NOT NULL,
                    sequence INTEGER NOT NULL CHECK(sequence >= 0),
                    ltp REAL NOT NULL CHECK(ltp > 0),
                    open_interest INTEGER NOT NULL CHECK(open_interest >= 0),
                    volume INTEGER NOT NULL CHECK(volume >= 0),
                    total_buy_quantity REAL NOT NULL CHECK(total_buy_quantity >= 0),
                    total_sell_quantity REAL NOT NULL CHECK(total_sell_quantity >= 0),
                    best_bid_price REAL,
                    best_bid_quantity INTEGER NOT NULL CHECK(best_bid_quantity >= 0),
                    best_ask_price REAL,
                    best_ask_quantity INTEGER NOT NULL CHECK(best_ask_quantity >= 0),
                    depth_buy_quantity INTEGER NOT NULL CHECK(depth_buy_quantity >= 0),
                    depth_sell_quantity INTEGER NOT NULL CHECK(depth_sell_quantity >= 0),
                    PRIMARY KEY (exchange, token, exchange_ts_utc, sequence)
                );

                CREATE TABLE IF NOT EXISTS breadth_snapshots (
                    exchange TEXT NOT NULL,
                    token TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    industry TEXT NOT NULL,
                    exchange_ts_utc TEXT NOT NULL,
                    received_ts_utc TEXT NOT NULL,
                    sequence INTEGER NOT NULL CHECK(sequence >= 0),
                    ltp REAL NOT NULL CHECK(ltp > 0),
                    previous_close REAL NOT NULL CHECK(previous_close > 0),
                    PRIMARY KEY (exchange, token, exchange_ts_utc, sequence)
                );

                CREATE TABLE IF NOT EXISTS news_items (
                    source TEXT NOT NULL,
                    title TEXT NOT NULL,
                    published_at_utc TEXT NOT NULL,
                    url TEXT NOT NULL,
                    category TEXT NOT NULL,
                    PRIMARY KEY (source, url)
                );

                CREATE TABLE IF NOT EXISTS scheduled_events (
                    source TEXT NOT NULL,
                    name TEXT NOT NULL,
                    scheduled_at_utc TEXT NOT NULL,
                    category TEXT NOT NULL,
                    impact TEXT NOT NULL CHECK(impact IN ('HIGH', 'MEDIUM', 'LOW')),
                    PRIMARY KEY (source, category, scheduled_at_utc)
                );

                CREATE TABLE IF NOT EXISTS decision_records (
                    decision_id TEXT PRIMARY KEY,
                    decided_at_utc TEXT NOT NULL,
                    session_date TEXT NOT NULL,
                    brain_version TEXT NOT NULL,
                    rule_version TEXT NOT NULL,
                    brain_state TEXT NOT NULL,
                    action TEXT NOT NULL,
                    rejected_action TEXT,
                    direction_score REAL NOT NULL,
                    entry_quality REAL NOT NULL,
                    reversal_risk REAL NOT NULL,
                    confidence REAL NOT NULL,
                    family_coverage REAL NOT NULL,
                    regime TEXT NOT NULL,
                    spot_price REAL NOT NULL,
                    future_price REAL,
                    vix REAL NOT NULL,
                    ema9 REAL NOT NULL,
                    ema20 REAL NOT NULL,
                    rsi14 REAL NOT NULL,
                    atr14 REAL NOT NULL,
                    opening_range_high REAL NOT NULL,
                    opening_range_low REAL NOT NULL,
                    future_oi INTEGER NOT NULL,
                    future_oi_change INTEGER NOT NULL,
                    future_volume_change INTEGER NOT NULL,
                    basis REAL NOT NULL,
                    basis_change REAL NOT NULL,
                    oi_pcr REAL,
                    volume_pcr REAL,
                    breadth_pct REAL,
                    depth_imbalance REAL,
                    high_impact_event_active INTEGER NOT NULL CHECK(high_impact_event_active IN (0, 1))
                );

                CREATE TABLE IF NOT EXISTS decision_families (
                    decision_id TEXT NOT NULL,
                    family_name TEXT NOT NULL,
                    family_weight REAL NOT NULL,
                    family_value REAL NOT NULL,
                    PRIMARY KEY (decision_id, family_name),
                    FOREIGN KEY (decision_id) REFERENCES decision_records(decision_id)
                );

                CREATE TABLE IF NOT EXISTS decision_reasons (
                    decision_id TEXT NOT NULL,
                    thesis TEXT NOT NULL CHECK(thesis IN ('CHOSEN', 'REJECTED', 'GATE')),
                    reason_code TEXT NOT NULL,
                    category TEXT NOT NULL,
                    evidence_value REAL,
                    expected_direction INTEGER NOT NULL CHECK(expected_direction IN (-1, 0, 1)),
                    explanation TEXT NOT NULL,
                    PRIMARY KEY (decision_id, thesis, reason_code),
                    FOREIGN KEY (decision_id) REFERENCES decision_records(decision_id)
                );

                CREATE TRIGGER IF NOT EXISTS decision_records_no_update
                BEFORE UPDATE ON decision_records
                BEGIN
                    SELECT RAISE(ABORT, 'decision records are immutable');
                END;

                CREATE TRIGGER IF NOT EXISTS decision_records_no_delete
                BEFORE DELETE ON decision_records
                BEGIN
                    SELECT RAISE(ABORT, 'decision records are immutable');
                END;

                CREATE TRIGGER IF NOT EXISTS decision_families_no_update
                BEFORE UPDATE ON decision_families
                BEGIN
                    SELECT RAISE(ABORT, 'decision families are immutable');
                END;

                CREATE TRIGGER IF NOT EXISTS decision_families_no_delete
                BEFORE DELETE ON decision_families
                BEGIN
                    SELECT RAISE(ABORT, 'decision families are immutable');
                END;

                CREATE TRIGGER IF NOT EXISTS decision_reasons_no_update
                BEFORE UPDATE ON decision_reasons
                BEGIN
                    SELECT RAISE(ABORT, 'decision reasons are immutable');
                END;

                CREATE TRIGGER IF NOT EXISTS decision_reasons_no_delete
                BEFORE DELETE ON decision_reasons
                BEGIN
                    SELECT RAISE(ABORT, 'decision reasons are immutable');
                END;

                CREATE TABLE IF NOT EXISTS shadow_trades (
                    trade_id TEXT PRIMARY KEY,
                    decision_id TEXT NOT NULL UNIQUE,
                    shadow_version TEXT NOT NULL,
                    opened_at_utc TEXT NOT NULL,
                    action TEXT NOT NULL CHECK(action IN ('BUY_CALL', 'BUY_PUT')),
                    token TEXT NOT NULL,
                    strike REAL NOT NULL,
                    option_type TEXT NOT NULL CHECK(option_type IN ('CE', 'PE')),
                    entry_price REAL NOT NULL CHECK(entry_price > 0),
                    quantity INTEGER NOT NULL CHECK(quantity > 0),
                    lot_size INTEGER NOT NULL CHECK(lot_size > 0),
                    lots INTEGER NOT NULL CHECK(lots > 0),
                    stop_price REAL NOT NULL CHECK(stop_price > 0),
                    target_price REAL NOT NULL CHECK(target_price > 0),
                    max_minutes INTEGER NOT NULL CHECK(max_minutes > 0),
                    FOREIGN KEY (decision_id) REFERENCES decision_records(decision_id)
                );

                CREATE TRIGGER IF NOT EXISTS shadow_trades_no_update
                BEFORE UPDATE ON shadow_trades
                BEGIN
                    SELECT RAISE(ABORT, 'shadow trades are immutable');
                END;

                CREATE TRIGGER IF NOT EXISTS shadow_trades_no_delete
                BEFORE DELETE ON shadow_trades
                BEGIN
                    SELECT RAISE(ABORT, 'shadow trades are immutable');
                END;

                CREATE TABLE IF NOT EXISTS shadow_outcomes (
                    trade_id TEXT PRIMARY KEY,
                    evaluated_at_utc TEXT NOT NULL,
                    exit_at_utc TEXT NOT NULL,
                    exit_reason TEXT NOT NULL CHECK(exit_reason IN ('TARGET', 'STOP', 'TIMEOUT')),
                    exit_price REAL NOT NULL CHECK(exit_price > 0),
                    gross_pnl REAL NOT NULL,
                    estimated_friction REAL NOT NULL CHECK(estimated_friction >= 0),
                    adjusted_pnl REAL NOT NULL,
                    gross_return_pct REAL NOT NULL,
                    adjusted_return_pct REAL NOT NULL,
                    mfe_price REAL NOT NULL,
                    mae_price REAL NOT NULL,
                    mfe_amount REAL NOT NULL,
                    mae_amount REAL NOT NULL,
                    spot_exit REAL,
                    spot_change REAL,
                    directional_spot_change REAL,
                    forward_1m REAL,
                    forward_3m REAL,
                    forward_5m REAL,
                    forward_10m REAL,
                    forward_15m REAL,
                    forward_30m REAL,
                    FOREIGN KEY (trade_id) REFERENCES shadow_trades(trade_id)
                );

                CREATE TRIGGER IF NOT EXISTS shadow_outcomes_no_update
                BEFORE UPDATE ON shadow_outcomes
                BEGIN
                    SELECT RAISE(ABORT, 'shadow outcomes are immutable');
                END;

                CREATE TRIGGER IF NOT EXISTS shadow_outcomes_no_delete
                BEFORE DELETE ON shadow_outcomes
                BEGIN
                    SELECT RAISE(ABORT, 'shadow outcomes are immutable');
                END;

                CREATE TABLE IF NOT EXISTS reason_audits (
                    trade_id TEXT NOT NULL,
                    decision_id TEXT NOT NULL,
                    auditor_version TEXT NOT NULL,
                    thesis TEXT NOT NULL,
                    reason_code TEXT NOT NULL,
                    category TEXT NOT NULL,
                    expected_direction INTEGER NOT NULL CHECK(expected_direction IN (-1, 0, 1)),
                    verdict TEXT NOT NULL CHECK(verdict IN ('SUPPORTED', 'CONTRADICTED', 'FLAT', 'UNKNOWN', 'UNGRADED')),
                    trade_result TEXT NOT NULL CHECK(trade_result IN ('PROFIT', 'LOSS', 'FLAT')),
                    adjusted_pnl REAL NOT NULL,
                    spot_change REAL,
                    PRIMARY KEY (trade_id, auditor_version, thesis, reason_code),
                    FOREIGN KEY (trade_id) REFERENCES shadow_trades(trade_id),
                    FOREIGN KEY (decision_id) REFERENCES decision_records(decision_id)
                );

                CREATE TRIGGER IF NOT EXISTS reason_audits_no_update
                BEFORE UPDATE ON reason_audits
                BEGIN
                    SELECT RAISE(ABORT, 'reason audits are immutable');
                END;

                CREATE TRIGGER IF NOT EXISTS reason_audits_no_delete
                BEFORE DELETE ON reason_audits
                BEGIN
                    SELECT RAISE(ABORT, 'reason audits are immutable');
                END;
                """
            )
            self._connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> "SQLiteStore":
        self.initialize()
        return self

    def __exit__(self, _exc_type, _exc, _tb) -> None:
        self.close()

    def _candle_rows(
        self, instrument: Instrument, interval: str, candles: Sequence["Candle"]
    ) -> list[tuple]:
        rows: list[tuple] = []
        for candle in candles:
            if candle.volume < 0:
                raise StorageError("candle volume invalid")
            rows.append(
                (
                    instrument.exchange,
                    instrument.token,
                    interval,
                    _utc_iso(candle.at),
                    float(candle.open),
                    float(candle.high),
                    float(candle.low),
                    float(candle.close),
                    candle.volume,
                )
            )
        return rows

    def _oi_rows(
        self, instrument: Instrument, interval: str, observations: Sequence["OIObservation"]
    ) -> list[tuple]:
        rows: list[tuple] = []
        for observation in observations:
            if observation.oi < 0:
                raise StorageError("open interest invalid")
            rows.append(
                (
                    instrument.exchange,
                    instrument.token,
                    interval,
                    _utc_iso(observation.at),
                    observation.oi,
                )
            )
        return rows

    def load_candles(
        self,
        exchange: str,
        token: str,
        interval: str,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> tuple["Candle", ...]:
        """Load stored candles in ascending UTC timestamp order."""

        clauses = [
            "exchange = ?",
            "token = ?",
            "interval = ?",
        ]
        params: list[object] = [exchange, token, interval]

        if start is not None:
            if start.tzinfo is None:
                raise StorageError("candle start timestamp must be timezone aware")
            clauses.append("ts_utc >= ?")
            params.append(_utc_iso(start))
        if end is not None:
            if end.tzinfo is None:
                raise StorageError("candle end timestamp must be timezone aware")
            clauses.append("ts_utc <= ?")
            params.append(_utc_iso(end))
        if start is not None and end is not None and start > end:
            raise StorageError("candle load range invalid")

        query = (
            "SELECT ts_utc, open, high, low, close, volume "
            "FROM candles WHERE "
            + " AND ".join(clauses)
            + " ORDER BY ts_utc ASC"
        )
        try:
            rows = self._connection.execute(query, params).fetchall()
        except sqlite3.Error:
            raise StorageError("SQLite candle read failed") from None

        from intrader.historical import Candle

        return tuple(
            Candle(
                datetime.fromisoformat(row[0]),
                Decimal(str(row[1])),
                Decimal(str(row[2])),
                Decimal(str(row[3])),
                Decimal(str(row[4])),
                int(row[5]),
            )
            for row in rows
        )

    def load_option_snapshots(
        self,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        expiry: str | None = None,
    ) -> tuple["OptionSnapshot", ...]:
        """Load stored option snapshots in deterministic time/token order."""

        clauses: list[str] = []
        params: list[object] = []

        if start is not None:
            if start.tzinfo is None:
                raise StorageError("option start timestamp must be timezone aware")
            clauses.append("exchange_ts_utc >= ?")
            params.append(_utc_iso(start))
        if end is not None:
            if end.tzinfo is None:
                raise StorageError("option end timestamp must be timezone aware")
            clauses.append("exchange_ts_utc <= ?")
            params.append(_utc_iso(end))
        if start is not None and end is not None and start > end:
            raise StorageError("option load range invalid")
        if expiry is not None:
            clauses.append("expiry = ?")
            params.append(expiry)

        query = (
            "SELECT token, exchange_ts_utc, received_ts_utc, sequence, "
            "expiry, strike, option_type, ltp, open_interest, volume "
            "FROM option_snapshots"
        )
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY exchange_ts_utc ASC, token ASC, sequence ASC"

        try:
            rows = self._connection.execute(query, params).fetchall()
        except sqlite3.Error:
            raise StorageError("SQLite option snapshot read failed") from None

        from intrader.options_intelligence import OptionSnapshot

        return tuple(
            OptionSnapshot(
                token=str(row[0]),
                exchange_at=datetime.fromisoformat(row[1]),
                received_at=datetime.fromisoformat(row[2]),
                sequence=int(row[3]),
                expiry=datetime.fromisoformat(row[4]).date(),
                strike=Decimal(str(row[5])),
                option_type=str(row[6]),
                ltp=Decimal(str(row[7])),
                open_interest=int(row[8]),
                volume=int(row[9]),
            )
            for row in rows
        )

    def load_index_snapshots(
        self,
        token: str,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> tuple["IndexSnapshot", ...]:
        """Load one stored NSE index stream in chronological order."""

        clauses = ["token = ?"]
        params: list[object] = [token]
        if start is not None:
            if start.tzinfo is None:
                raise StorageError("index start timestamp must be timezone aware")
            clauses.append("exchange_ts_utc >= ?")
            params.append(_utc_iso(start))
        if end is not None:
            if end.tzinfo is None:
                raise StorageError("index end timestamp must be timezone aware")
            clauses.append("exchange_ts_utc <= ?")
            params.append(_utc_iso(end))
        if start is not None and end is not None and start > end:
            raise StorageError("index load range invalid")

        try:
            rows = self._connection.execute(
                "SELECT token, exchange_ts_utc, received_ts_utc, sequence, ltp "
                "FROM index_snapshots WHERE "
                + " AND ".join(clauses)
                + " ORDER BY exchange_ts_utc ASC, sequence ASC",
                params,
            ).fetchall()
        except sqlite3.Error:
            raise StorageError("SQLite index snapshot read failed") from None

        from intrader.market_confirmation import IndexSnapshot

        return tuple(
            IndexSnapshot(
                token=str(row[0]),
                exchange_at=datetime.fromisoformat(row[1]),
                received_at=datetime.fromisoformat(row[2]),
                sequence=int(row[3]),
                ltp=Decimal(str(row[4])),
            )
            for row in rows
        )

    def load_future_snapshots(
        self,
        token: str,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> tuple["FutureSnapshot", ...]:
        """Load one stored future stream in chronological order."""

        clauses = ["token = ?"]
        params: list[object] = [token]
        if start is not None:
            if start.tzinfo is None:
                raise StorageError("future start timestamp must be timezone aware")
            clauses.append("exchange_ts_utc >= ?")
            params.append(_utc_iso(start))
        if end is not None:
            if end.tzinfo is None:
                raise StorageError("future end timestamp must be timezone aware")
            clauses.append("exchange_ts_utc <= ?")
            params.append(_utc_iso(end))
        if start is not None and end is not None and start > end:
            raise StorageError("future load range invalid")

        try:
            rows = self._connection.execute(
                "SELECT token, exchange_ts_utc, received_ts_utc, sequence, ltp, "
                "open_interest, volume, total_buy_quantity, total_sell_quantity, "
                "best_bid_price, best_bid_quantity, best_ask_price, best_ask_quantity, "
                "depth_buy_quantity, depth_sell_quantity "
                "FROM future_snapshots WHERE "
                + " AND ".join(clauses)
                + " ORDER BY exchange_ts_utc ASC, sequence ASC",
                params,
            ).fetchall()
        except sqlite3.Error:
            raise StorageError("SQLite future snapshot read failed") from None

        from intrader.market_confirmation import FutureSnapshot

        return tuple(
            FutureSnapshot(
                token=str(row[0]),
                exchange_at=datetime.fromisoformat(row[1]),
                received_at=datetime.fromisoformat(row[2]),
                sequence=int(row[3]),
                ltp=Decimal(str(row[4])),
                open_interest=int(row[5]),
                volume=int(row[6]),
                total_buy_quantity=Decimal(str(row[7])),
                total_sell_quantity=Decimal(str(row[8])),
                best_bid_price=None if row[9] is None else Decimal(str(row[9])),
                best_bid_quantity=int(row[10]),
                best_ask_price=None if row[11] is None else Decimal(str(row[11])),
                best_ask_quantity=int(row[12]),
                depth_buy_quantity=int(row[13]),
                depth_sell_quantity=int(row[14]),
            )
            for row in rows
        )

    def load_breadth_snapshots(
        self,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> tuple["BreadthMarketSnapshot", ...]:
        """Load stored constituent quote snapshots in deterministic order."""

        clauses: list[str] = []
        params: list[object] = []
        if start is not None:
            if start.tzinfo is None:
                raise StorageError("breadth start timestamp must be timezone aware")
            clauses.append("exchange_ts_utc >= ?")
            params.append(_utc_iso(start))
        if end is not None:
            if end.tzinfo is None:
                raise StorageError("breadth end timestamp must be timezone aware")
            clauses.append("exchange_ts_utc <= ?")
            params.append(_utc_iso(end))
        if start is not None and end is not None and start > end:
            raise StorageError("breadth load range invalid")

        query = (
            "SELECT symbol, industry, token, exchange_ts_utc, received_ts_utc, "
            "sequence, ltp, previous_close FROM breadth_snapshots"
        )
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY exchange_ts_utc ASC, symbol ASC, sequence ASC"

        try:
            rows = self._connection.execute(query, params).fetchall()
        except sqlite3.Error:
            raise StorageError("SQLite breadth snapshot read failed") from None

        from intrader.breadth import BreadthMarketSnapshot

        return tuple(
            BreadthMarketSnapshot(
                symbol=str(row[0]),
                industry=str(row[1]),
                token=str(row[2]),
                exchange_at=datetime.fromisoformat(row[3]),
                received_at=datetime.fromisoformat(row[4]),
                sequence=int(row[5]),
                current_price=Decimal(str(row[6])),
                previous_close=Decimal(str(row[7])),
            )
            for row in rows
        )

    def store_news_items(self, items) -> int:
        rows = []
        for item in items:
            if item.published_at.tzinfo is None:
                raise StorageError("news timestamp must be timezone aware")
            rows.append(
                (
                    item.source,
                    item.title,
                    _utc_iso(item.published_at),
                    item.url,
                    item.category,
                )
            )
        try:
            with self._connection:
                self._connection.executemany(
                    """
                    INSERT INTO news_items
                        (source, title, published_at_utc, url, category)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(source, url) DO UPDATE SET
                        title=excluded.title,
                        published_at_utc=excluded.published_at_utc,
                        category=excluded.category
                    """,
                    rows,
                )
        except sqlite3.Error:
            raise StorageError("SQLite news write failed") from None
        return len(rows)

    def store_scheduled_events(self, events) -> int:
        rows = []
        for event in events:
            if event.scheduled_at.tzinfo is None:
                raise StorageError("event timestamp must be timezone aware")
            rows.append(
                (
                    event.source,
                    event.name,
                    _utc_iso(event.scheduled_at),
                    event.category,
                    event.impact,
                )
            )
        try:
            with self._connection:
                self._connection.executemany(
                    """
                    INSERT INTO scheduled_events
                        (source, name, scheduled_at_utc, category, impact)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(source, category, scheduled_at_utc) DO UPDATE SET
                        name=excluded.name,
                        impact=excluded.impact
                    """,
                    rows,
                )
        except sqlite3.Error:
            raise StorageError("SQLite event write failed") from None
        return len(rows)

    def load_news_items(
        self,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
    ):
        clauses: list[str] = []
        params: list[object] = []
        if start is not None:
            if start.tzinfo is None:
                raise StorageError("news start timestamp must be timezone aware")
            clauses.append("published_at_utc >= ?")
            params.append(_utc_iso(start))
        if end is not None:
            if end.tzinfo is None:
                raise StorageError("news end timestamp must be timezone aware")
            clauses.append("published_at_utc <= ?")
            params.append(_utc_iso(end))
        query = (
            "SELECT source, title, published_at_utc, url, category FROM news_items"
        )
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY published_at_utc DESC"
        try:
            rows = self._connection.execute(query, params).fetchall()
        except sqlite3.Error:
            raise StorageError("SQLite news read failed") from None

        from intrader.context import NewsItem

        return tuple(
            NewsItem(
                source=str(row[0]),
                title=str(row[1]),
                published_at=datetime.fromisoformat(row[2]),
                url=str(row[3]),
                category=str(row[4]),
            )
            for row in rows
        )

    def load_scheduled_events(
        self,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
    ):
        clauses: list[str] = []
        params: list[object] = []
        if start is not None:
            if start.tzinfo is None:
                raise StorageError("event start timestamp must be timezone aware")
            clauses.append("scheduled_at_utc >= ?")
            params.append(_utc_iso(start))
        if end is not None:
            if end.tzinfo is None:
                raise StorageError("event end timestamp must be timezone aware")
            clauses.append("scheduled_at_utc <= ?")
            params.append(_utc_iso(end))
        query = (
            "SELECT source, name, scheduled_at_utc, category, impact "
            "FROM scheduled_events"
        )
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY scheduled_at_utc ASC"
        try:
            rows = self._connection.execute(query, params).fetchall()
        except sqlite3.Error:
            raise StorageError("SQLite event read failed") from None

        from intrader.context import ScheduledEvent

        return tuple(
            ScheduledEvent(
                source=str(row[0]),
                name=str(row[1]),
                scheduled_at=datetime.fromisoformat(row[2]),
                category=str(row[3]),
                impact=str(row[4]),
            )
            for row in rows
        )

    def store_decision_record(self, record) -> bool:
        """Insert one immutable pre-outcome decision and its reasoning."""

        try:
            existing = self._connection.execute(
                "SELECT 1 FROM decision_records WHERE decision_id = ?",
                (record.decision_id,),
            ).fetchone()
            if existing is not None:
                return False

            with self._connection:
                self._connection.execute(
                    """
                    INSERT INTO decision_records (
                        decision_id, decided_at_utc, session_date,
                        brain_version, rule_version, brain_state, action,
                        rejected_action, direction_score, entry_quality,
                        reversal_risk, confidence, family_coverage, regime,
                        spot_price, future_price, vix, ema9, ema20, rsi14,
                        atr14, opening_range_high, opening_range_low,
                        future_oi, future_oi_change, future_volume_change,
                        basis, basis_change, oi_pcr, volume_pcr, breadth_pct,
                        depth_imbalance, high_impact_event_active
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                    )
                    """,
                    (
                        record.decision_id,
                        _utc_iso(record.decided_at),
                        record.session_date.isoformat(),
                        record.brain_version,
                        record.rule_version,
                        record.brain_state,
                        record.action,
                        record.rejected_action,
                        float(record.direction_score),
                        float(record.entry_quality),
                        float(record.reversal_risk),
                        float(record.confidence),
                        float(record.family_coverage),
                        record.regime,
                        float(record.spot_price),
                        None if record.future_price is None else float(record.future_price),
                        float(record.vix),
                        float(record.ema9),
                        float(record.ema20),
                        float(record.rsi14),
                        float(record.atr14),
                        float(record.opening_range_high),
                        float(record.opening_range_low),
                        record.future_oi,
                        record.future_oi_change,
                        record.future_volume_change,
                        float(record.basis),
                        float(record.basis_change),
                        None if record.oi_pcr is None else float(record.oi_pcr),
                        None if record.volume_pcr is None else float(record.volume_pcr),
                        None if record.breadth_pct is None else float(record.breadth_pct),
                        None if record.depth_imbalance is None else float(record.depth_imbalance),
                        1 if record.high_impact_event_active else 0,
                    ),
                )
                self._connection.executemany(
                    """
                    INSERT INTO decision_families
                        (decision_id, family_name, family_weight, family_value)
                    VALUES (?, ?, ?, ?)
                    """,
                    [
                        (
                            record.decision_id,
                            family.name,
                            float(family.weight),
                            float(family.value),
                        )
                        for family in record.families
                    ],
                )
                self._connection.executemany(
                    """
                    INSERT INTO decision_reasons
                        (decision_id, thesis, reason_code, category,
                         evidence_value, expected_direction, explanation)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            record.decision_id,
                            reason.thesis,
                            reason.reason_code,
                            reason.category,
                            None if reason.evidence_value is None else float(reason.evidence_value),
                            reason.expected_direction,
                            reason.explanation,
                        )
                        for reason in record.reasons
                    ],
                )
        except sqlite3.Error:
            raise StorageError("SQLite decision record write failed") from None
        return True

    def load_decision_record(self, decision_id: str):
        """Load one immutable decision with family evidence and reasons."""

        try:
            row = self._connection.execute(
                """
                SELECT decision_id, decided_at_utc, session_date, brain_version,
                       rule_version, brain_state, action, rejected_action,
                       direction_score, entry_quality, reversal_risk, confidence,
                       family_coverage, regime, spot_price, future_price, vix,
                       ema9, ema20, rsi14, atr14, opening_range_high,
                       opening_range_low, future_oi, future_oi_change,
                       future_volume_change, basis, basis_change, oi_pcr,
                       volume_pcr, breadth_pct, depth_imbalance,
                       high_impact_event_active
                FROM decision_records
                WHERE decision_id = ?
                """,
                (decision_id,),
            ).fetchone()
            if row is None:
                return None
            family_rows = self._connection.execute(
                """
                SELECT family_name, family_weight, family_value
                FROM decision_families
                WHERE decision_id = ?
                ORDER BY family_name
                """,
                (decision_id,),
            ).fetchall()
            reason_rows = self._connection.execute(
                """
                SELECT thesis, reason_code, category, evidence_value,
                       expected_direction, explanation
                FROM decision_reasons
                WHERE decision_id = ?
                ORDER BY thesis, reason_code
                """,
                (decision_id,),
            ).fetchall()
        except sqlite3.Error:
            raise StorageError("SQLite decision record read failed") from None

        from intrader.market_brain import FamilyEvidence
        from intrader.records import DecisionReason, DecisionRecord

        families = tuple(
            FamilyEvidence(
                name=str(item[0]),
                weight=Decimal(str(item[1])),
                value=Decimal(str(item[2])),
            )
            for item in family_rows
        )
        reasons = tuple(
            DecisionReason(
                thesis=str(item[0]),
                reason_code=str(item[1]),
                category=str(item[2]),
                evidence_value=None if item[3] is None else Decimal(str(item[3])),
                expected_direction=int(item[4]),
                explanation=str(item[5]),
            )
            for item in reason_rows
        )
        from datetime import date

        return DecisionRecord(
            decision_id=str(row[0]),
            decided_at=datetime.fromisoformat(row[1]),
            session_date=date.fromisoformat(row[2]),
            brain_version=str(row[3]),
            rule_version=str(row[4]),
            brain_state=str(row[5]),
            action=str(row[6]),
            rejected_action=None if row[7] is None else str(row[7]),
            direction_score=Decimal(str(row[8])),
            entry_quality=Decimal(str(row[9])),
            reversal_risk=Decimal(str(row[10])),
            confidence=Decimal(str(row[11])),
            family_coverage=Decimal(str(row[12])),
            regime=str(row[13]),
            spot_price=Decimal(str(row[14])),
            future_price=None if row[15] is None else Decimal(str(row[15])),
            vix=Decimal(str(row[16])),
            ema9=Decimal(str(row[17])),
            ema20=Decimal(str(row[18])),
            rsi14=Decimal(str(row[19])),
            atr14=Decimal(str(row[20])),
            opening_range_high=Decimal(str(row[21])),
            opening_range_low=Decimal(str(row[22])),
            future_oi=int(row[23]),
            future_oi_change=int(row[24]),
            future_volume_change=int(row[25]),
            basis=Decimal(str(row[26])),
            basis_change=Decimal(str(row[27])),
            oi_pcr=None if row[28] is None else Decimal(str(row[28])),
            volume_pcr=None if row[29] is None else Decimal(str(row[29])),
            breadth_pct=None if row[30] is None else Decimal(str(row[30])),
            depth_imbalance=None if row[31] is None else Decimal(str(row[31])),
            high_impact_event_active=bool(row[32]),
            families=families,
            reasons=reasons,
        )

    def load_decision_records(self):
        """Load all immutable decisions in chronological order."""

        try:
            rows = self._connection.execute(
                """
                SELECT decision_id
                FROM decision_records
                ORDER BY decided_at_utc ASC, decision_id ASC
                """
            ).fetchall()
        except sqlite3.Error:
            raise StorageError("SQLite decision list read failed") from None

        return tuple(
            record
            for row in rows
            if (record := self.load_decision_record(str(row[0]))) is not None
        )

    def load_completed_shadow_bundles(self):
        """Load completed decision/trade/outcome triples chronologically."""

        try:
            rows = self._connection.execute(
                """
                SELECT st.trade_id
                FROM shadow_trades st
                JOIN shadow_outcomes so ON so.trade_id = st.trade_id
                ORDER BY st.opened_at_utc ASC, st.trade_id ASC
                """
            ).fetchall()
        except sqlite3.Error:
            raise StorageError("SQLite completed shadow read failed") from None

        bundles = []
        for row in rows:
            trade = self.load_shadow_trade(str(row[0]))
            if trade is None:
                continue
            decision = self.load_decision_record(trade.decision_id)
            outcome = self.load_shadow_outcome(trade.trade_id)
            if decision is None or outcome is None:
                continue
            bundles.append((decision, trade, outcome))
        return tuple(bundles)

    def store_shadow_trade(self, trade) -> bool:
        """Insert one immutable simulated entry plan."""

        try:
            existing = self._connection.execute(
                "SELECT 1 FROM shadow_trades WHERE trade_id = ? OR decision_id = ?",
                (trade.trade_id, trade.decision_id),
            ).fetchone()
            if existing is not None:
                return False
            with self._connection:
                self._connection.execute(
                    """
                    INSERT INTO shadow_trades (
                        trade_id, decision_id, shadow_version, opened_at_utc,
                        action, token, strike, option_type, entry_price,
                        quantity, lot_size, lots, stop_price, target_price,
                        max_minutes
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        trade.trade_id,
                        trade.decision_id,
                        trade.shadow_version,
                        _utc_iso(trade.opened_at),
                        trade.action,
                        trade.token,
                        float(trade.strike),
                        trade.option_type,
                        float(trade.entry_price),
                        trade.quantity,
                        trade.lot_size,
                        trade.lots,
                        float(trade.stop_price),
                        float(trade.target_price),
                        trade.max_minutes,
                    ),
                )
        except sqlite3.Error:
            raise StorageError("SQLite shadow trade write failed") from None
        return True

    def load_shadow_trade(self, trade_id: str):
        try:
            row = self._connection.execute(
                """
                SELECT trade_id, decision_id, shadow_version, opened_at_utc,
                       action, token, strike, option_type, entry_price,
                       quantity, lot_size, lots, stop_price, target_price,
                       max_minutes
                FROM shadow_trades
                WHERE trade_id = ?
                """,
                (trade_id,),
            ).fetchone()
        except sqlite3.Error:
            raise StorageError("SQLite shadow trade read failed") from None
        if row is None:
            return None

        from intrader.shadow import ShadowTrade

        return ShadowTrade(
            trade_id=str(row[0]),
            decision_id=str(row[1]),
            shadow_version=str(row[2]),
            opened_at=datetime.fromisoformat(row[3]),
            action=str(row[4]),
            token=str(row[5]),
            strike=Decimal(str(row[6])),
            option_type=str(row[7]),
            entry_price=Decimal(str(row[8])),
            quantity=int(row[9]),
            lot_size=int(row[10]),
            lots=int(row[11]),
            stop_price=Decimal(str(row[12])),
            target_price=Decimal(str(row[13])),
            max_minutes=int(row[14]),
        )

    def load_shadow_trade_for_decision(self, decision_id: str):
        try:
            row = self._connection.execute(
                "SELECT trade_id FROM shadow_trades WHERE decision_id = ?",
                (decision_id,),
            ).fetchone()
        except sqlite3.Error:
            raise StorageError("SQLite shadow trade read failed") from None
        return None if row is None else self.load_shadow_trade(str(row[0]))

    def store_shadow_outcome(self, outcome) -> bool:
        """Insert one immutable terminal shadow outcome."""

        try:
            existing = self._connection.execute(
                "SELECT 1 FROM shadow_outcomes WHERE trade_id = ?",
                (outcome.trade_id,),
            ).fetchone()
            if existing is not None:
                return False
            forwards = dict(outcome.forward_returns)
            with self._connection:
                self._connection.execute(
                    """
                    INSERT INTO shadow_outcomes (
                        trade_id, evaluated_at_utc, exit_at_utc, exit_reason,
                        exit_price, gross_pnl, estimated_friction, adjusted_pnl,
                        gross_return_pct, adjusted_return_pct, mfe_price,
                        mae_price, mfe_amount, mae_amount, spot_exit, spot_change,
                        directional_spot_change, forward_1m, forward_3m,
                        forward_5m, forward_10m, forward_15m, forward_30m
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?
                    )
                    """,
                    (
                        outcome.trade_id,
                        _utc_iso(outcome.evaluated_at),
                        _utc_iso(outcome.exit_at),
                        outcome.exit_reason,
                        float(outcome.exit_price),
                        float(outcome.gross_pnl),
                        float(outcome.estimated_friction),
                        float(outcome.adjusted_pnl),
                        float(outcome.gross_return_pct),
                        float(outcome.adjusted_return_pct),
                        float(outcome.mfe_price),
                        float(outcome.mae_price),
                        float(outcome.mfe_amount),
                        float(outcome.mae_amount),
                        None if outcome.spot_exit is None else float(outcome.spot_exit),
                        None if outcome.spot_change is None else float(outcome.spot_change),
                        None if outcome.directional_spot_change is None else float(outcome.directional_spot_change),
                        None if forwards.get(1) is None else float(forwards[1]),
                        None if forwards.get(3) is None else float(forwards[3]),
                        None if forwards.get(5) is None else float(forwards[5]),
                        None if forwards.get(10) is None else float(forwards[10]),
                        None if forwards.get(15) is None else float(forwards[15]),
                        None if forwards.get(30) is None else float(forwards[30]),
                    ),
                )
        except sqlite3.Error:
            raise StorageError("SQLite shadow outcome write failed") from None
        return True

    def load_shadow_outcome(self, trade_id: str):
        try:
            row = self._connection.execute(
                """
                SELECT trade_id, evaluated_at_utc, exit_at_utc, exit_reason,
                       exit_price, gross_pnl, estimated_friction, adjusted_pnl,
                       gross_return_pct, adjusted_return_pct, mfe_price,
                       mae_price, mfe_amount, mae_amount, spot_exit, spot_change,
                       directional_spot_change, forward_1m, forward_3m,
                       forward_5m, forward_10m, forward_15m, forward_30m
                FROM shadow_outcomes
                WHERE trade_id = ?
                """,
                (trade_id,),
            ).fetchone()
        except sqlite3.Error:
            raise StorageError("SQLite shadow outcome read failed") from None
        if row is None:
            return None

        from intrader.outcomes import ShadowOutcome

        forward_minutes = (1, 3, 5, 10, 15, 30)
        forward_values = row[17:23]
        return ShadowOutcome(
            trade_id=str(row[0]),
            evaluated_at=datetime.fromisoformat(row[1]),
            exit_at=datetime.fromisoformat(row[2]),
            exit_reason=str(row[3]),
            exit_price=Decimal(str(row[4])),
            gross_pnl=Decimal(str(row[5])),
            estimated_friction=Decimal(str(row[6])),
            adjusted_pnl=Decimal(str(row[7])),
            gross_return_pct=Decimal(str(row[8])),
            adjusted_return_pct=Decimal(str(row[9])),
            mfe_price=Decimal(str(row[10])),
            mae_price=Decimal(str(row[11])),
            mfe_amount=Decimal(str(row[12])),
            mae_amount=Decimal(str(row[13])),
            spot_exit=None if row[14] is None else Decimal(str(row[14])),
            spot_change=None if row[15] is None else Decimal(str(row[15])),
            directional_spot_change=None if row[16] is None else Decimal(str(row[16])),
            forward_returns=tuple(
                (
                    minute,
                    None if value is None else Decimal(str(value)),
                )
                for minute, value in zip(forward_minutes, forward_values)
            ),
        )

    def load_unsettled_shadow_trades(self):
        try:
            rows = self._connection.execute(
                """
                SELECT trade_id
                FROM shadow_trades
                WHERE trade_id NOT IN (SELECT trade_id FROM shadow_outcomes)
                ORDER BY opened_at_utc ASC
                """
            ).fetchall()
        except sqlite3.Error:
            raise StorageError("SQLite unsettled shadow read failed") from None
        return tuple(
            trade
            for row in rows
            if (trade := self.load_shadow_trade(str(row[0]))) is not None
        )

    def store_reason_audits(self, audits) -> int:
        """Insert versioned immutable reasoning audits idempotently."""

        rows = [
            (
                audit.trade_id,
                audit.decision_id,
                audit.auditor_version,
                audit.thesis,
                audit.reason_code,
                audit.category,
                audit.expected_direction,
                audit.verdict,
                audit.trade_result,
                float(audit.adjusted_pnl),
                None if audit.spot_change is None else float(audit.spot_change),
            )
            for audit in audits
        ]
        if not rows:
            return 0
        try:
            with self._connection:
                before = self._connection.total_changes
                self._connection.executemany(
                    """
                    INSERT OR IGNORE INTO reason_audits (
                        trade_id, decision_id, auditor_version, thesis,
                        reason_code, category, expected_direction, verdict,
                        trade_result, adjusted_pnl, spot_change
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    rows,
                )
                inserted = self._connection.total_changes - before
        except sqlite3.Error:
            raise StorageError("SQLite reason audit write failed") from None
        return int(inserted)

    def load_reason_audits(
        self,
        *,
        trade_id: str | None = None,
        auditor_version: str | None = None,
    ):
        clauses: list[str] = []
        params: list[object] = []
        if trade_id is not None:
            clauses.append("trade_id = ?")
            params.append(trade_id)
        if auditor_version is not None:
            clauses.append("auditor_version = ?")
            params.append(auditor_version)

        query = (
            "SELECT trade_id, decision_id, auditor_version, thesis, "
            "reason_code, category, expected_direction, verdict, trade_result, "
            "adjusted_pnl, spot_change FROM reason_audits"
        )
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY trade_id, thesis, reason_code"

        try:
            rows = self._connection.execute(query, params).fetchall()
        except sqlite3.Error:
            raise StorageError("SQLite reason audit read failed") from None

        from intrader.reasoning_auditor import ReasonAudit

        return tuple(
            ReasonAudit(
                trade_id=str(row[0]),
                decision_id=str(row[1]),
                auditor_version=str(row[2]),
                thesis=str(row[3]),
                reason_code=str(row[4]),
                category=str(row[5]),
                expected_direction=int(row[6]),
                verdict=str(row[7]),
                trade_result=str(row[8]),
                adjusted_pnl=Decimal(str(row[9])),
                spot_change=None if row[10] is None else Decimal(str(row[10])),
            )
            for row in rows
        )

    def store_candles(
        self, instrument: Instrument, interval: str, candles: Sequence["Candle"]
    ) -> int:
        rows = self._candle_rows(instrument, interval, candles)
        with self._connection:
            self._connection.executemany(
                """
                INSERT INTO candles
                    (exchange, token, interval, ts_utc, open, high, low, close, volume)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(exchange, token, interval, ts_utc) DO UPDATE SET
                    open=excluded.open,
                    high=excluded.high,
                    low=excluded.low,
                    close=excluded.close,
                    volume=excluded.volume
                """,
                rows,
            )
        return len(rows)

    def store_oi(
        self, instrument: Instrument, interval: str, observations: Sequence["OIObservation"]
    ) -> int:
        rows = self._oi_rows(instrument, interval, observations)
        with self._connection:
            self._connection.executemany(
                """
                INSERT INTO oi_observations
                    (exchange, token, interval, ts_utc, oi)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(exchange, token, interval, ts_utc) DO UPDATE SET
                    oi=excluded.oi
                """,
                rows,
            )
        return len(rows)

    def store_backfill(
        self,
        candle_batches: Sequence[tuple[Instrument, str, Sequence["Candle"]]],
        oi_batches: Sequence[tuple[Instrument, str, Sequence["OIObservation"]]],
    ) -> tuple[int, int]:
        candle_rows = [
            row
            for instrument, interval, candles in candle_batches
            for row in self._candle_rows(instrument, interval, candles)
        ]
        oi_rows = [
            row
            for instrument, interval, observations in oi_batches
            for row in self._oi_rows(instrument, interval, observations)
        ]
        try:
            with self._connection:
                self._connection.executemany(
                    """
                    INSERT INTO candles
                        (exchange, token, interval, ts_utc, open, high, low, close, volume)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(exchange, token, interval, ts_utc) DO UPDATE SET
                        open=excluded.open,
                        high=excluded.high,
                        low=excluded.low,
                        close=excluded.close,
                        volume=excluded.volume
                    """,
                    candle_rows,
                )
                self._connection.executemany(
                    """
                    INSERT INTO oi_observations
                        (exchange, token, interval, ts_utc, oi)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(exchange, token, interval, ts_utc) DO UPDATE SET
                        oi=excluded.oi
                    """,
                    oi_rows,
                )
        except sqlite3.Error:
            raise StorageError("SQLite backfill write failed") from None
        return len(candle_rows), len(oi_rows)

    def store_index_tick(self, instrument: Instrument, tick: MarketTick) -> bool:
        if (
            instrument.exchange != "NSE"
            or tick.exchange != "NSE"
            or tick.token != instrument.token
            or tick.mode != 1
        ):
            raise StorageError("index snapshot invalid")
        try:
            with self._connection:
                cursor = self._connection.execute(
                    """
                    INSERT OR IGNORE INTO index_snapshots
                        (exchange, token, exchange_ts_utc, received_ts_utc, sequence, ltp)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        tick.exchange,
                        tick.token,
                        _utc_iso(tick.exchange_at),
                        _utc_iso(tick.received_at),
                        tick.sequence,
                        float(tick.last_price),
                    ),
                )
        except sqlite3.Error:
            raise StorageError("SQLite index snapshot write failed") from None
        return cursor.rowcount == 1

    def store_future_tick(self, instrument: Instrument, tick: MarketTick) -> bool:
        if (
            instrument.exchange != "NFO"
            or instrument.instrument_type != "FUTIDX"
            or tick.exchange != "NFO"
            or tick.token != instrument.token
            or tick.mode != 3
            or tick.open_interest is None
            or tick.volume is None
            or tick.total_buy_quantity is None
            or tick.total_sell_quantity is None
        ):
            raise StorageError("future snapshot invalid")

        best_bid = max(tick.best_5_buy, key=lambda level: level.price, default=None)
        best_ask = min(tick.best_5_sell, key=lambda level: level.price, default=None)
        depth_buy = sum(level.quantity for level in tick.best_5_buy)
        depth_sell = sum(level.quantity for level in tick.best_5_sell)

        try:
            with self._connection:
                cursor = self._connection.execute(
                    """
                    INSERT OR IGNORE INTO future_snapshots
                        (exchange, token, exchange_ts_utc, received_ts_utc, sequence,
                         ltp, open_interest, volume, total_buy_quantity,
                         total_sell_quantity, best_bid_price, best_bid_quantity,
                         best_ask_price, best_ask_quantity, depth_buy_quantity,
                         depth_sell_quantity)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        tick.exchange,
                        tick.token,
                        _utc_iso(tick.exchange_at),
                        _utc_iso(tick.received_at),
                        tick.sequence,
                        float(tick.last_price),
                        tick.open_interest,
                        tick.volume,
                        float(tick.total_buy_quantity),
                        float(tick.total_sell_quantity),
                        None if best_bid is None else float(best_bid.price),
                        0 if best_bid is None else best_bid.quantity,
                        None if best_ask is None else float(best_ask.price),
                        0 if best_ask is None else best_ask.quantity,
                        depth_buy,
                        depth_sell,
                    ),
                )
        except sqlite3.Error:
            raise StorageError("SQLite future snapshot write failed") from None
        return cursor.rowcount == 1

    def store_breadth_tick(self, member, tick: MarketTick) -> bool:
        instrument = member.instrument
        if (
            instrument.exchange != "NSE"
            or tick.exchange != "NSE"
            or tick.token != instrument.token
            or tick.mode != 2
            or tick.previous_close is None
            or tick.previous_close <= 0
        ):
            raise StorageError("breadth snapshot invalid")
        try:
            with self._connection:
                cursor = self._connection.execute(
                    """
                    INSERT OR IGNORE INTO breadth_snapshots
                        (exchange, token, symbol, industry, exchange_ts_utc,
                         received_ts_utc, sequence, ltp, previous_close)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        tick.exchange,
                        tick.token,
                        member.symbol,
                        member.industry,
                        _utc_iso(tick.exchange_at),
                        _utc_iso(tick.received_at),
                        tick.sequence,
                        float(tick.last_price),
                        float(tick.previous_close),
                    ),
                )
        except sqlite3.Error:
            raise StorageError("SQLite breadth snapshot write failed") from None
        return cursor.rowcount == 1

    def store_option_tick(self, instrument: Instrument, tick: MarketTick) -> bool:
        if (
            instrument.exchange != "NFO"
            or instrument.instrument_type != "OPTIDX"
            or instrument.expiry is None
            or instrument.strike is None
            or tick.exchange != instrument.exchange
            or tick.token != instrument.token
            or tick.mode != 3
            or tick.open_interest is None
            or tick.volume is None
        ):
            raise StorageError("option snapshot invalid")
        option_type = (
            "CE"
            if instrument.symbol.endswith("CE")
            else "PE"
            if instrument.symbol.endswith("PE")
            else None
        )
        if option_type is None:
            raise StorageError("option type invalid")
        try:
            with self._connection:
                cursor = self._connection.execute(
                    """
                    INSERT OR IGNORE INTO option_snapshots
                        (exchange, token, exchange_ts_utc, received_ts_utc, sequence,
                         expiry, strike, option_type, ltp, open_interest, volume)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        instrument.exchange,
                        instrument.token,
                        _utc_iso(tick.exchange_at),
                        _utc_iso(tick.received_at),
                        tick.sequence,
                        instrument.expiry.isoformat(),
                        float(instrument.strike),
                        option_type,
                        float(tick.last_price),
                        tick.open_interest,
                        tick.volume,
                    ),
                )
        except sqlite3.Error:
            raise StorageError("SQLite option snapshot write failed") from None
        return cursor.rowcount == 1

    def count(self, table: str) -> int:
        if table not in {
            "candles", "oi_observations", "option_snapshots",
            "index_snapshots", "future_snapshots", "breadth_snapshots",
            "news_items", "scheduled_events", "decision_records",
            "decision_families", "decision_reasons", "shadow_trades",
            "shadow_outcomes", "reason_audits",
        }:
            raise ValueError("unsupported table")
        return int(self._connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


class OptionSnapshotSink:
    """Persist only the resolved live CE/PE SNAP_QUOTE ticks."""

    def __init__(self, store: SQLiteStore, instruments: NiftyInstruments) -> None:
        self._store = store
        self._options = {
            ("NFO", instrument.token): instrument
            for instrument in (*instruments.calls, *instruments.puts)
        }

    def __call__(self, tick: MarketTick) -> None:
        instrument = self._options.get((tick.exchange, tick.token))
        if instrument is None:
            return
        self._store.store_option_tick(instrument, tick)


class MarketSnapshotSink:
    """Persist core Phase 2 streams plus optional breadth quotes."""

    def __init__(
        self,
        store: SQLiteStore,
        instruments: NiftyInstruments,
        breadth_members=(),
    ) -> None:
        self._store = store
        self._spot = ("NSE", instruments.spot.token)
        self._vix = ("NSE", instruments.vix.token)
        self._future = ("NFO", instruments.future.token)
        self._future_instrument = instruments.future
        self._index_instruments = {
            self._spot: instruments.spot,
            self._vix: instruments.vix,
        }
        self._options = {
            ("NFO", instrument.token): instrument
            for instrument in (*instruments.calls, *instruments.puts)
        }
        self._breadth = {
            ("NSE", member.instrument.token): member
            for member in breadth_members
        }

    def __call__(self, tick: MarketTick) -> None:
        key = (tick.exchange, tick.token)
        if key in self._index_instruments:
            self._store.store_index_tick(self._index_instruments[key], tick)
            return
        if key == self._future:
            self._store.store_future_tick(self._future_instrument, tick)
            return
        option = self._options.get(key)
        if option is not None:
            self._store.store_option_tick(option, tick)
            return
        breadth_member = self._breadth.get(key)
        if breadth_member is not None:
            try:
                self._store.store_breadth_tick(breadth_member, tick)
            except StorageError:
                # Breadth is optional confirmation and cannot break core readiness.
                return
