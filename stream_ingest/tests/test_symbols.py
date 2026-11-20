from app.symbols import (
    from_alpaca_symbol,
    load_symbols,
    normalize_symbol,
    prioritize_symbols,
    shard_symbols,
    to_alpaca_symbol,
)


def test_normalize_class_shares():
    assert normalize_symbol("brk.b") == "BRK-B"
    assert normalize_symbol(" AAPL ") == "AAPL"


def test_alpaca_class_share_dot_form():
    assert to_alpaca_symbol("BRK-B") == "BRK.B"
    assert to_alpaca_symbol("BF-B") == "BF.B"
    assert from_alpaca_symbol("BRK.B") == "BRK-B"
    assert to_alpaca_symbol("AAPL") == "AAPL"


def test_load_symbols_from_csv_and_file(tmp_path):
    path = tmp_path / "symbols.txt"
    path.write_text("MSFT\n# comment\nGOOGL\n", encoding="utf-8")
    assert load_symbols(symbols_csv="AAPL,MSFT", symbols_file=str(path)) == ["AAPL", "MSFT", "GOOGL"]


def test_shard_symbols_respects_the_free_cap():
    symbols = [f"S{i}" for i in range(75)]
    shards = shard_symbols(symbols, limit=30)
    assert [len(shard) for shard in shards] == [30, 30, 15]


def test_shard_symbols_handles_empty_and_small_lists():
    assert shard_symbols([], limit=30) == []
    assert shard_symbols(["AAPL", "MSFT"], limit=30) == [["AAPL", "MSFT"]]


def test_load_symbols_dedupes_and_uppercases():
    assert load_symbols(symbols_csv="aapl,AAPL, msft ", symbols_file="") == ["AAPL", "MSFT"]


def test_prioritize_symbols_pins_websocket_names_first():
    universe = ["MSFT", "AAPL", "GOOGL", "XOM", "UNH"]
    assert prioritize_symbols(["AAPL", "NVDA", "MSFT"], universe) == [
        "AAPL",
        "NVDA",
        "MSFT",
        "GOOGL",
        "XOM",
        "UNH",
    ]


def test_split_ws_rest_uses_only_chosen_symbols():
    from app.symbols import split_ws_rest

    universe = ["AAPL", "MSFT", "NVDA", "GOOGL", "XOM"]
    ws, rest = split_ws_rest(
        universe,
        ws_priority=["NVDA", "AAPL", "ZZZZ"],
        limit=30,
        rest_enabled=True,
    )
    assert ws == ["NVDA", "AAPL", "ZZZZ"]
    assert rest == ["MSFT", "GOOGL", "XOM"]
    ws_capped, _ = split_ws_rest(universe, ws_priority=["AAPL", "MSFT", "NVDA"], limit=2)
    assert ws_capped == ["AAPL", "MSFT"]
