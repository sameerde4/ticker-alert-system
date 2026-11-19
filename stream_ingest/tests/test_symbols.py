from app.symbols import load_symbols, normalize_symbol, shard_symbols


def test_normalize_class_shares():
    assert normalize_symbol("brk.b") == "BRK-B"
    assert normalize_symbol(" AAPL ") == "AAPL"


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
