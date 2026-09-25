"""Strict decoder for Angel One SmartAPI WebSocket V2 market ticks."""

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
import math
import struct

from intrader.instruments import NiftyInstruments


class InvalidPacket(Exception):
    """A market frame cannot be trusted for data-health purposes."""


@dataclass(frozen=True, slots=True)
class DepthLevel:
    price: Decimal
    quantity: int
    orders: int


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
    last_traded_quantity: int | None = None
    average_traded_price: Decimal | None = None
    total_buy_quantity: Decimal | None = None
    total_sell_quantity: Decimal | None = None
    day_open: Decimal | None = None
    day_high: Decimal | None = None
    day_low: Decimal | None = None
    previous_close: Decimal | None = None
    best_5_buy: tuple[DepthLevel, ...] = ()
    best_5_sell: tuple[DepthLevel, ...] = ()


def _price(raw: int) -> Decimal:
    return Decimal(raw) / Decimal(100)


def _parse_best_five(frame: bytes) -> tuple[tuple[DepthLevel, ...], tuple[DepthLevel, ...]]:
    buys: list[DepthLevel] = []
    sells: list[DepthLevel] = []
    for index in range(10):
        start = 147 + (index * 20)
        try:
            flag = struct.unpack_from("<H", frame, start)[0]
            quantity = struct.unpack_from("<q", frame, start + 2)[0]
            price_units = struct.unpack_from("<q", frame, start + 10)[0]
            orders = struct.unpack_from("<H", frame, start + 18)[0]
        except struct.error:
            raise InvalidPacket("market depth packet truncated") from None

        if flag not in (0, 1) or quantity < 0 or price_units < 0:
            raise InvalidPacket("market depth packet invalid")
        if quantity == 0 or price_units == 0:
            continue

        level = DepthLevel(_price(price_units), quantity, orders)
        if flag == 1:
            buys.append(level)
        else:
            sells.append(level)

    if len(buys) > 5 or len(sells) > 5:
        raise InvalidPacket("market depth packet invalid")
    return tuple(buys), tuple(sells)


def decode_tick(frame: bytes, received_at: datetime) -> MarketTick:
    """Decode the documented V2 LTP/QUOTE/SNAP_QUOTE packet."""

    if not isinstance(frame, bytes) or len(frame) < 51 or received_at.tzinfo is None:
        raise InvalidPacket("market packet invalid")
    mode, exchange_type = frame[0], frame[1]
    if mode not in (1, 2, 3) or exchange_type not in (1, 2):
        raise InvalidPacket("market packet unsupported")
    minimum_length = {1: 51, 2: 123, 3: 379}[mode]
    if len(frame) < minimum_length:
        raise InvalidPacket("market packet truncated")

    try:
        token = frame[2:27].split(b"\x00", 1)[0].decode("ascii")
        sequence, timestamp_ms, price_units = struct.unpack_from("<qqq", frame, 27)
        exchange_at = datetime.fromtimestamp(timestamp_ms / 1000, timezone.utc)
    except (UnicodeDecodeError, OverflowError, OSError, ValueError, struct.error):
        raise InvalidPacket("market packet invalid") from None

    if not token or sequence < 0 or timestamp_ms <= 0 or price_units <= 0:
        raise InvalidPacket("market packet invalid")

    last_traded_quantity = None
    average_traded_price = None
    volume = None
    total_buy_quantity = None
    total_sell_quantity = None
    day_open = None
    day_high = None
    day_low = None
    previous_close = None
    open_interest = None
    best_5_buy: tuple[DepthLevel, ...] = ()
    best_5_sell: tuple[DepthLevel, ...] = ()

    if mode in (2, 3):
        try:
            last_traded_quantity = struct.unpack_from("<q", frame, 51)[0]
            average_units = struct.unpack_from("<q", frame, 59)[0]
            volume = struct.unpack_from("<q", frame, 67)[0]
            total_buy_raw = struct.unpack_from("<d", frame, 75)[0]
            total_sell_raw = struct.unpack_from("<d", frame, 83)[0]
            open_units = struct.unpack_from("<q", frame, 91)[0]
            high_units = struct.unpack_from("<q", frame, 99)[0]
            low_units = struct.unpack_from("<q", frame, 107)[0]
            close_units = struct.unpack_from("<q", frame, 115)[0]
        except struct.error:
            raise InvalidPacket("market quote packet truncated") from None

        if (
            last_traded_quantity < 0
            or volume < 0
            or average_units < 0
            or open_units < 0
            or high_units < 0
            or low_units < 0
            or close_units < 0
            or not math.isfinite(total_buy_raw)
            or not math.isfinite(total_sell_raw)
            or total_buy_raw < 0
            or total_sell_raw < 0
        ):
            raise InvalidPacket("market quote packet invalid")

        average_traded_price = _price(average_units)
        total_buy_quantity = Decimal(str(total_buy_raw))
        total_sell_quantity = Decimal(str(total_sell_raw))
        day_open = _price(open_units)
        day_high = _price(high_units)
        day_low = _price(low_units)
        previous_close = _price(close_units)

    if mode == 3:
        try:
            open_interest = struct.unpack_from("<q", frame, 131)[0]
        except struct.error:
            raise InvalidPacket("market packet truncated") from None
        if open_interest < 0:
            raise InvalidPacket("market packet invalid")
        best_5_buy, best_5_sell = _parse_best_five(frame)

    return MarketTick(
        exchange="NSE" if exchange_type == 1 else "NFO",
        token=token,
        mode=mode,
        sequence=sequence,
        exchange_at=exchange_at,
        received_at=received_at.astimezone(timezone.utc),
        last_price=_price(price_units),
        open_interest=open_interest,
        volume=volume,
        last_traded_quantity=last_traded_quantity,
        average_traded_price=average_traded_price,
        total_buy_quantity=total_buy_quantity,
        total_sell_quantity=total_sell_quantity,
        day_open=day_open,
        day_high=day_high,
        day_low=day_low,
        previous_close=previous_close,
        best_5_buy=best_5_buy,
        best_5_sell=best_5_sell,
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



def breadth_subscription_message(tokens) -> dict:
    """Subscribe optional NSE constituent tokens in QUOTE mode."""

    unique = tuple(dict.fromkeys(str(token) for token in tokens if str(token)))
    if not unique:
        raise ValueError("breadth tokens unavailable")
    if len(unique) > 1000:
        raise ValueError("breadth subscription exceeds token quota")
    return {
        "correlationID": "intrader03",
        "action": 1,
        "params": {
            "mode": 2,
            "tokenList": [
                {
                    "exchangeType": 1,
                    "tokens": list(unique),
                }
            ],
        },
    }
