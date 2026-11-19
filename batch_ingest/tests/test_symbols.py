from app.symbols import load_symbols, normalize_symbol


def test_normalize_class_shares():
    assert normalize_symbol("brk.b") == "BRK-B"


def test_load_symbols_from_csv(tmp_path):
    path = tmp_path / "symbols.txt"
    path.write_text("MSFT\n# x\nGOOGL\n", encoding="utf-8")
    assert load_symbols(symbols_csv="AAPL,AAPL", symbols_file=str(path)) == [
        "AAPL",
        "MSFT",
        "GOOGL",
    ]
