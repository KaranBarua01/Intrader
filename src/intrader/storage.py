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


SCHEMA_VERSION = 1


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
        if table not in {"candles", "oi_observations", "option_snapshots"}:
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
