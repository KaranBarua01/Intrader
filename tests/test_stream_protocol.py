from datetime import date, datetime, timezone
from decimal import Decimal
import struct

import pytest

from intrader.instruments import Instrument, NiftyInstruments
from intrader.stream_protocol import InvalidPacket, decode_tick, subscription_messages


NOW = datetime(2026, 9, 28, 4, 0, tzinfo=timezone.utc)


def _frame(mode: int, exchange: int, token: str = "99926000") -> bytes:
    packet = bytearray(139 if mode == 3 else 51)
    packet[0] = mode
    packet[1] = exchange
    packet[2:27] = token.encode("ascii").ljust(25, b"\x00")
    struct.pack_into("<q", packet, 27, 42)
    struct.pack_into("<q", packet, 35, 1_803_000_000_000)
    struct.pack_into("<q", packet, 43, 2_315_075)
    if mode == 3:
        struct.pack_into("<q", packet, 131, 1_234_567)
    return bytes(packet)


def _instrument(token: str, symbol: str, exchange: str, kind: str) -> Instrument:
    return Instrument(token, symbol, "NIFTY", kind, exchange, date(2026, 9, 29), Decimal("23150"), 65)


def _bundle() -> NiftyInstruments:
    spot = _instrument("99926000", "NIFTY 50", "NSE", "AMXIDX")
    vix = _instrument("99926017", "India VIX", "NSE", "AMXIDX")
    future = _instrument("68407", "NIFTY29SEP26FUT", "NFO", "FUTIDX")
    calls = tuple(_instrument(f"C{i}", f"NIFTY{i}CE", "NFO", "OPTIDX") for i in range(9))
    puts = tuple(_instrument(f"P{i}", f"NIFTY{i}PE", "NFO", "OPTIDX") for i in range(9))
    strikes = tuple(Decimal(22950 + 50 * i) for i in range(9))
    return NiftyInstruments(spot, vix, future, date(2026, 9, 29), Decimal(23150), strikes, calls, puts)


def test_decodes_ltp_packet_with_scaled_price_and_timestamp() -> None:
    tick = decode_tick(_frame(1, 1), NOW)

    assert tick.exchange == "NSE"
    assert tick.token == "99926000"
    assert tick.mode == 1
    assert tick.sequence == 42
    assert tick.last_price == Decimal("23150.75")
    assert tick.open_interest is None
    assert tick.exchange_at == datetime.fromtimestamp(1_803_000_000, timezone.utc)
    assert tick.received_at == NOW


def test_decodes_snap_quote_open_interest_without_using_percentage_field() -> None:
    tick = decode_tick(_frame(3, 2, "68407"), NOW)

    assert tick.exchange == "NFO"
    assert tick.token == "68407"
    assert tick.open_interest == 1_234_567\n    assert tick.volume == 987_654


@pytest.mark.parametrize("frame", [_frame(1, 1)[:50], _frame(3, 2)[:138], _frame(4, 2), _frame(1, 9)])
def test_rejects_truncated_or_unsupported_packets(frame: bytes) -> None:
    with pytest.raises(InvalidPacket):
        decode_tick(frame, NOW)


def test_subscriptions_include_all_and_only_resolved_tokens() -> None:
    ltp, snap = subscription_messages(_bundle())

    assert ltp["action"] == snap["action"] == 1
    assert ltp["params"] == {"mode": 1, "tokenList": [{"exchangeType": 1, "tokens": ["99926000", "99926017"]}]}
    assert snap["params"]["mode"] == 3
    assert snap["params"]["tokenList"][0]["exchangeType"] == 2
    assert set(snap["params"]["tokenList"][0]["tokens"]) == {"68407"} | {f"C{i}" for i in range(9)} | {f"P{i}" for i in range(9)}
