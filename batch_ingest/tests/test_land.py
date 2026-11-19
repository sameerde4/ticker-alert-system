import json
from datetime import date

from app.land import raw_daily_dir, write_run_manifest, write_symbol_parquet


def test_write_symbol_parquet_and_manifest(tmp_path):
    rows = [
        {
            "symbol": "AAPL",
            "dt": date(2026, 11, 17),
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.5,
            "volume": 1_000,
            "source": "yahoo",
            "grain": "daily",
        },
        {
            "symbol": "AAPL",
            "dt": date(2026, 11, 18),
            "open": 100.5,
            "high": 102.0,
            "low": 100.0,
            "close": 101.0,
            "volume": 1_100,
            "source": "yahoo",
            "grain": "daily",
        },
    ]
    path = write_symbol_parquet(tmp_path, "AAPL", rows)
    assert path is not None
    assert path.parent == raw_daily_dir(tmp_path, "AAPL")
    assert path.name == "part-000.parquet"
    assert path.is_file()

    manifest = write_run_manifest(
        tmp_path,
        run_id="2026-11-18-test",
        start=date(2025, 11, 19),
        end=date(2026, 11, 18),
        symbols_requested=["AAPL"],
        results=[{"symbol": "AAPL", "rows": 2, "path": str(path), "error": None}],
    )
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["symbols_landed"] == 1
    assert payload["rows_landed"] == 2
    assert payload["grain"] == "daily"


def test_empty_rows_write_nothing(tmp_path):
    assert write_symbol_parquet(tmp_path, "AAPL", []) is None
    assert not raw_daily_dir(tmp_path, "AAPL").exists()
