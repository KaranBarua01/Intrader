from decimal import Decimal

import pytest

from intrader.breadth_provider import (
    BreadthProviderError,
    NIFTY50_CONSTITUENTS_URL,
    fetch_nifty50_constituents,
    parse_nifty50_constituents,
    resolve_breadth_universe,
)


HEADER = "Company Name,Industry,Symbol,Series,ISIN Code\n"


def _csv(count: int = 50) -> str:
    rows = [
        f"Company {index},Industry {index % 5},SYM{index},EQ,INE{index:09d}"
        for index in range(count)
    ]
    return HEADER + "\n".join(rows)


class TextTransport:
    def __init__(self, text: str) -> None:
        self.text = text
        self.calls = []

    def get_text(self, url: str, timeout: int) -> str:
        self.calls.append((url, timeout))
        return self.text


class MasterTransport:
    def get_json(self, _url: str, timeout: int):
        assert timeout == 30
        return [
            {
                "token": str(10000 + index),
                "symbol": f"SYM{index}-EQ",
                "name": f"SYM{index}",
                "expiry": "",
                "strike": "-1.000000",
                "lotsize": "1",
                "instrumenttype": "",
                "exch_seg": "NSE",
            }
            for index in range(50)
        ]


def test_parses_exactly_50_official_style_rows() -> None:
    result = parse_nifty50_constituents(_csv())

    assert len(result) == 50
    assert result[0].symbol == "SYM0"
    assert result[0].industry == "Industry 0"


def test_fetch_uses_official_constituent_url() -> None:
    transport = TextTransport(_csv())

    result = fetch_nifty50_constituents(transport)

    assert len(result) == 50
    assert transport.calls == [(NIFTY50_CONSTITUENTS_URL, 20)]


@pytest.mark.parametrize("count", [49, 51])
def test_wrong_constituent_count_fails_closed(count: int) -> None:
    with pytest.raises(BreadthProviderError, match="count"):
        parse_nifty50_constituents(_csv(count))


def test_duplicate_symbol_fails_closed() -> None:
    text = _csv(49) + "\nCompany Duplicate,Industry X,SYM0,EQ,INEDUP"

    with pytest.raises(BreadthProviderError, match="row invalid"):
        parse_nifty50_constituents(text)


def test_resolves_all_members_to_exact_nse_equity_tokens() -> None:
    result = resolve_breadth_universe(
        TextTransport(_csv()),
        MasterTransport(),
    )

    assert len(result) == 50
    assert result[0].symbol == "SYM0"
    assert result[0].instrument.token == "10000"
    assert result[-1].instrument.symbol == "SYM49-EQ"
    assert result[-1].instrument.exchange == "NSE"
    assert result[-1].instrument.strike == Decimal("-1.000000")
