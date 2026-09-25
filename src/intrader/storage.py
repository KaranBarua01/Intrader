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


SCHEMA_VERSION = 4


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
            "news_items", "scheduled_events",
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
