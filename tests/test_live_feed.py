from datetime import date, datetime, timezone
from decimal import Decimal
import json
import ssl

from intrader.auth import SmartSession
from intrader.__main__ import main
from intrader.checkpoint2 import Checkpoint2Report
from intrader.feed_health import FeedHealth, HealthSnapshot
from intrader.instruments import Instrument, NiftyInstruments
from intrader.live_feed import LiveFeed


def _instrument(token: str, exchange: str) -> Instrument:
    return Instrument(
        token, token, "NIFTY", "OPTIDX", exchange,
        date(2026, 9, 29), Decimal(23150), 65,
    )


def _bundle() -> NiftyInstruments:
    return NiftyInstruments(
        _instrument("spot", "NSE"),
        _instrument("vix", "NSE"),
        _instrument("future", "NFO"),
        date(2026, 9, 29),
        Decimal(23150),
        (Decimal(23150),),
        (_instrument("call", "NFO"),),
        (_instrument("put", "NFO"),),
    )


def _session(suffix: str) -> SmartSession:
    return SmartSession(
        "dummy-api-key",
        "dummy-client",
        f"dummy-jwt-{suffix}",
        "dummy-refresh",
        "dummy-feed",
    )


class FakeSocket:
    def __init__(self, url, header, on_open, on_data, on_error, on_close) -> None:
        self.url = url
        self.header = header
        self.on_open = on_open
        self.on_data = on_data
        self.on_error = on_error
        self.on_close = on_close
        self.sent: list[dict] = []
        self.run_options: dict = {}
        self.closed = False

    def send(self, value: str) -> None:
        self.sent.append(json.loads(value))

    def run_forever(self, **kwargs) -> None:
        self.run_options = kwargs
        self.on_open(self)
        self.on_data(self, b"bad", 2, True)
        self.on_error(self, RuntimeError("dummy-jwt in websocket error"))
        self.on_close(self, 1006, "dummy-feed in close reason")

    def close(self) -> None:
        self.closed = True


def test_socket_uses_tls_and_subscribes_without_logging_tokens() -> None:
    sockets: list[FakeSocket] = []

    def factory(**kwargs):
        socket = FakeSocket(**kwargs)
        sockets.append(socket)
        return socket

    bundle = _bundle()
    health = FeedHealth(bundle, 5, 8)
    feed = LiveFeed(
        lambda: _session("one"),
        bundle,
        health,
        socket_factory=factory,
    )
    feed.run(max_attempts=1)

    assert len(sockets) == 1
    socket = sockets[0]
    assert socket.url == "wss://smartapisocket.angelone.in/smart-stream"
    assert socket.header["Authorization"] == "dummy-jwt-one"
    assert socket.header["x-feed-token"] == "dummy-feed"
    assert socket.run_options["sslopt"]["cert_reqs"] == ssl.CERT_REQUIRED
    assert [message["params"]["mode"] for message in socket.sent] == [1, 3]
    assert health.snapshot(datetime.now(timezone.utc)).state == "NO TRADE"
    assert "dummy-" not in repr(feed)


def test_reconnect_uses_fresh_session_and_resubscribes_every_group(monkeypatch) -> None:
    sockets: list[FakeSocket] = []
    attempts: list[str] = []

    def provider():
        suffix = str(len(attempts) + 1)
        attempts.append(suffix)
        return _session(suffix)

    def factory(**kwargs):
        socket = FakeSocket(**kwargs)
        sockets.append(socket)
        return socket

    bundle = _bundle()
    feed = LiveFeed(
        provider,
        bundle,
        FeedHealth(bundle, 5, 8),
        socket_factory=factory,
    )
    delays: list[float] = []
    monkeypatch.setattr(feed._stop, "wait", lambda delay: delays.append(delay))

    feed.run(max_attempts=3)

    assert attempts == ["1", "2", "3"]
    assert [socket.header["Authorization"] for socket in sockets] == [
        "dummy-jwt-1",
        "dummy-jwt-2",
        "dummy-jwt-3",
    ]
    assert all(len(socket.sent) == 2 for socket in sockets)
    assert delays == [1, 2]


def test_probe_is_bounded_and_reports_no_trade_without_fresh_ticks() -> None:
    bundle = _bundle()
    health = FeedHealth(bundle, 5, 8)
    feed = LiveFeed(
        lambda: _session("probe"),
        bundle,
        health,
        socket_factory=FakeSocket,
    )

    snapshot = feed.run_probe(0.02)

    assert snapshot.state == "NO TRADE"
    assert snapshot.expected_count == 5


def test_cli_live_probe_reports_no_trade_without_exposing_tokens(
    tmp_path, monkeypatch, capsys
) -> None:
    monkeypatch.chdir(tmp_path)
    bundle = _bundle()
    monkeypatch.setattr(
        "intrader.__main__.authenticate",
        lambda *_args: _session("initial"),
    )
    monkeypatch.setattr(
        "intrader.__main__.check_market_access",
        lambda *_args, **_kwargs: Checkpoint2Report(Decimal(23150), bundle),
    )

    class FakeFeed:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def run_probe(self, _duration: float) -> HealthSnapshot:
            return HealthSnapshot("NO TRADE", ("MISSING_TICKS",), 0, 5)

    monkeypatch.setattr("intrader.__main__.LiveFeed", FakeFeed, raising=False)

    exit_code = main(["check-live-feed", "1"])

    output = capsys.readouterr().out
    assert exit_code == 1
    assert "LIVE FEED: NO TRADE" in output
    assert "MISSING_TICKS" in output
    assert "dummy-" not in output


def test_tick_sink_failure_closes_socket_and_forces_no_trade() -> None:
    bundle = _bundle()
    health = FeedHealth(bundle, 5, 8)
    sockets: list[FakeSocket] = []

    class TickSocket(FakeSocket):
        def run_forever(self, **kwargs) -> None:
            self.run_options = kwargs
            self.on_open(self)
            import struct

            packet = bytearray(139)
            packet[0] = 3
            packet[1] = 2
            packet[2:27] = b"call".ljust(25, b"\x00")
            struct.pack_into("<q", packet, 27, 1)
            struct.pack_into(
                "<q",
                packet,
                35,
                int(datetime.now(timezone.utc).timestamp() * 1000),
            )
            struct.pack_into("<q", packet, 43, 12550)
            struct.pack_into("<q", packet, 67, 5000)
            struct.pack_into("<q", packet, 131, 1000)
            self.on_data(self, bytes(packet), 2, True)

    def factory(**kwargs):
        socket = TickSocket(**kwargs)
        sockets.append(socket)
        return socket

    def broken_sink(_tick) -> None:
        raise RuntimeError("disk unavailable")

    feed = LiveFeed(
        lambda: _session("sink"),
        bundle,
        health,
        socket_factory=factory,
        tick_sink=broken_sink,
    )
    feed.run(max_attempts=1)

    assert sockets[0].closed
    assert health.snapshot(datetime.now(timezone.utc)).state == "NO TRADE"
