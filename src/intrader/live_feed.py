"""TLS-verified, read-only SmartAPI V2 WebSocket lifecycle."""

from datetime import datetime, timezone
import json
import ssl
import threading
from typing import Callable

from intrader.stream_protocol import MarketTick

import websocket

from intrader.auth import SmartSession
from intrader.feed_health import FeedHealth, HealthSnapshot
from intrader.instruments import NiftyInstruments
from intrader.stream_protocol import (
    InvalidPacket,
    breadth_subscription_message,
    decode_tick,
    subscription_messages,
)


STREAM_URL = "wss://smartapisocket.angelone.in/smart-stream"


class LiveFeed:
    """Reconnect with fresh in-memory auth and never retain a stale ready state."""

    def __init__(
        self,
        session_provider: Callable[[], SmartSession],
        instruments: NiftyInstruments,
        health: FeedHealth,
        *,
        socket_factory: Callable = websocket.WebSocketApp,
        tick_sink: Callable[[MarketTick], None] | None = None,
    ) -> None:
        self._session_provider = session_provider
        self._instruments = instruments
        self._health = health
        self._socket_factory = socket_factory
        self._tick_sink = tick_sink
        self._stop = threading.Event()
        self._active = None

    def __repr__(self) -> str:
        return "LiveFeed([REDACTED])"

    def _new_socket(self, session: SmartSession):
        headers = {
            "Authorization": session.jwt_token,
            "x-api-key": session.api_key,
            "x-client-code": session.client_code,
            "x-feed-token": session.feed_token,
        }

        def on_open(socket) -> None:
            try:
                for message in subscription_messages(self._instruments):
                    socket.send(json.dumps(message))
                self._health.on_connected()
            except Exception:
                self._health.on_disconnected()
                socket.close()
                return

            if self._breadth_tokens:
                try:
                    socket.send(
                        json.dumps(
                            breadth_subscription_message(self._breadth_tokens)
                        )
                    )
                except Exception:
                    # Breadth is optional confirmation and must not break core feed.
                    pass

        def on_data(_socket, data, data_type, _continue_flag) -> None:
            if data_type != websocket.ABNF.OPCODE_BINARY:
                return
            try:
                tick = decode_tick(data, datetime.now(timezone.utc))
            except InvalidPacket:
                return
            if self._tick_sink is not None:
                try:
                    self._tick_sink(tick)
                except Exception:
                    self._health.on_disconnected()
                    _socket.close()
                    return
            self._health.accept(tick)

        def on_error(_socket, _error) -> None:
            self._health.on_disconnected()

        def on_close(_socket, _status, _reason) -> None:
            self._health.on_disconnected()

        return self._socket_factory(
            url=STREAM_URL,
            header=headers,
            on_open=on_open,
            on_data=on_data,
            on_error=on_error,
            on_close=on_close,
        )

    def run(self, *, max_attempts: int | None = None) -> None:
        """Run until stopped, with a fresh login and subscriptions each time."""

        attempt = 0
        while not self._stop.is_set() and (max_attempts is None or attempt < max_attempts):
            attempt += 1
            self._health.on_disconnected()
            try:
                session = self._session_provider()
                socket = self._new_socket(session)
                self._active = socket
                socket.run_forever(
                    sslopt={"cert_reqs": ssl.CERT_REQUIRED},
                    ping_interval=10,
                    ping_timeout=5,
                )
            except Exception:
                self._health.on_disconnected()
            finally:
                self._health.on_disconnected()
                self._active = None
            if not self._stop.is_set() and (max_attempts is None or attempt < max_attempts):
                self._stop.wait(min(2 ** (attempt - 1), 30))

    def stop(self) -> None:
        self._stop.set()
        socket = self._active
        if socket is not None:
            socket.close()

    def run_probe(self, duration_seconds: float) -> HealthSnapshot:
        """Observe feed health for a bounded period without emitting ticks."""

        if not 0 < duration_seconds <= 3600:
            raise ValueError("probe duration out of range")
        result: list[HealthSnapshot] = []

        def finish() -> None:
            result.append(self._health.snapshot(datetime.now(timezone.utc)))
            self.stop()

        timer = threading.Timer(duration_seconds, finish)
        timer.start()
        try:
            self.run()
        finally:
            timer.cancel()
            self.stop()
        return result[0] if result else self._health.snapshot(datetime.now(timezone.utc))
