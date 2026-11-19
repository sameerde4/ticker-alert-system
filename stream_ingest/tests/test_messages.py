from app.alpaca_rest import rest_feed
from app.messages import bar_from_alpaca, bar_from_rest


def test_websocket_bar_is_normalized():
    bar = bar_from_alpaca(
        {
            "T": "b",
            "S": "AAPL",
            "o": 1,
            "h": 2,
            "l": 0.5,
            "c": 1.5,
            "v": 100,
            "n": 9,
            "vw": 1.2,
            "t": "2026-11-18T20:00:00Z",
        },
        feed="delayed_sip",
        source="alpaca_ws",
    )
    assert bar == {
        "schema": "prices.raw.bars.v1",
        "symbol": "AAPL",
        "ts": "2026-11-18T20:00:00Z",
        "open": 1,
        "high": 2,
        "low": 0.5,
        "close": 1.5,
        "volume": 100,
        "trade_count": 9,
        "vwap": 1.2,
        "feed": "delayed_sip",
        "source": "alpaca_ws",
    }


def test_non_bar_messages_are_ignored():
    assert bar_from_alpaca({"T": "success", "msg": "connected"}, feed="delayed_sip", source="alpaca_ws") is None


def test_rest_bar_matches_the_same_schema():
    bar = bar_from_rest(
        "msft",
        {"t": "2026-11-18T19:59:00Z", "o": 10, "h": 11, "l": 9, "c": 10.5, "v": 50, "n": 3, "vw": 10.1},
        feed="delayed_sip",
    )
    assert bar["schema"] == "prices.raw.bars.v1"
    assert bar["symbol"] == "MSFT"
    assert bar["source"] == "alpaca_rest"
    assert bar["close"] == 10.5


def test_delayed_sip_uses_sip_on_rest():
    assert rest_feed("delayed_sip") == "sip"
    assert rest_feed("iex") == "iex"


def test_rest_bar_rejects_empty_symbol_or_payload():
    assert bar_from_rest("", {"t": "2026-11-18T19:59:00Z", "o": 1, "c": 1}, feed="delayed_sip") is None
    assert bar_from_rest("AAPL", {}, feed="delayed_sip") is None
