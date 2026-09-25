"""Small, strict decoder for Angel One SmartAPI WebSocket V2 market ticks."""

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import struct

from intrader.instruments import NiftyInstruments


class InvalidPacket(Exception):
    """A market frame cannot be trusted for data-health purposes."""


@dataclass(frozen=True, slots=True)
class MarketTick:
    exchange: str
    token: str
    mode: int
    sequence: int
    exchange_at: datetime
    received_at: datetime
    last_price: Decimal
    open_interest: int | None
    volume: int | None = None


def decode_tick(frame: bytes, received_at: datetime) -> MarketTick:
    """Decode the documented V2 header plus public volume/OI fields."""

    if not isinstance(frame, bytes) or len(frame) < 51 or received_at.tzinfo is None:
        raise InvalidPacket("market packet invalid")
    mode, exchange_type = frame[0], frame[1]
    if mode not in (1, 2, 3) or exchange_type not in (1, 2):
        raise InvalidPacket("market packet unsupported")
    minimum_length = {1: 51, 2: 123, 3: 139}[mode]
    if len(frame) < minimum_length:
        raise InvalidPacket("market packet truncated")
    try:
        token = frame[2:27].split(b"\x00", 1)[0].decode("ascii")
        sequence, timestamp_ms, price_units = struct.unpack_from("<qqq", frame, 27)
        exchange_at = datetime.fromtimestamp(timestamp_ms / 1000, timezone.utc)
        volume = struct.unpack_from("<q", frame, 67)[0] if mode in (2, 3) else None
        open_interest = struct.unpack_from("<q", frame, 131)[0] if mode == 3 else None
    except (UnicodeDecodeError, OverflowError, OSError, ValueError, struct.error):
        raise InvalidPacket("market packet invalid") from None
    if (
        not token
        or sequence < 0
        or timestamp_ms <= 0
        or price_units <= 0
        or (volume is not None and volume < 0)
        or (open_interest is not None and open_interest < 0)
    ):
        raise InvalidPacket("market packet invalid")
    return MarketTick(
        "NSE" if exchange_type == 1 else "NFO",
        token,
        mode,
        sequence,
        exchange_at,
        received_at.astimezone(timezone.utc),
        Decimal(price_units) / 100,
        open_interest,
        volume,
    )


def subscription_messages(instruments: NiftyInstruments) -> tuple[dict, dict]:
    """Subscribe to public NSE LTP and NFO SNAP_QUOTE data only."""

    nfo_tokens = [
        instruments.future.token,
        *(item.token for item in instruments.calls),
        *(item.token for item in instruments.puts),
    ]
    return (
        {
            "correlationID": "intrader01",
            "action": 1,
            "params": {
                "mode": 1,
                "tokenList": [
                    {
                        "exchangeType": 1,
                        "tokens": [instruments.spot.token, instruments.vix.token],
                    }
                ],
            },
        },
        {
            "correlationID": "intrader02",
            "action": 1,
            "params": {
                "mode": 3,
                "tokenList": [{"exchangeType": 2, "tokens": nfo_tokens}],
            },
        },
    )
