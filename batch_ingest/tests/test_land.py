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


def test_merge_keeps_older_days_and_updates_overlap(tmp_path):
    import pandas as pd

    first = [
        {
            "symbol": "AAPL",
            "dt": date(2026, 11, 10),
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
            "dt": date(2026, 11, 17),
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.5,
            "volume": 1_000,
            "source": "yahoo",
            "grain": "daily",
        },
    ]
    path = write_symbol_parquet(tmp_path, "AAPL", first)
    assert path is not None

    newer = [
        {
            "symbol": "AAPL",
            "dt": date(2026, 11, 17),
            "open": 101.0,
            "high": 103.0,
            "low": 100.0,
            "close": 102.0,
            "volume": 2_000,
            "source": "yahoo",
            "grain": "daily",
        },
        {
            "symbol": "AAPL",
            "dt": date(2026, 11, 18),
            "open": 102.0,
            "high": 104.0,
            "low": 101.0,
            "close": 103.0,
            "volume": 2_100,
            "source": "yahoo",
            "grain": "daily",
        },
    ]
    merged = write_symbol_parquet(tmp_path, "AAPL", newer, merge=True)
    assert merged == path
    frame = pd.read_parquet(path)
    assert len(frame) == 3
    row = frame[frame["dt"].astype(str) == "2026-11-17"].iloc[0]
    assert float(row["close"]) == 102.0
    assert int(row["volume"]) == 2_000


def test_merge_empty_keeps_existing(tmp_path):
    rows = [
        {
            "symbol": "AAPL",
            "dt": date(2026, 11, 18),
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.5,
            "volume": 1_000,
            "source": "yahoo",
            "grain": "daily",
        }
    ]
    path = write_symbol_parquet(tmp_path, "AAPL", rows)
    assert write_symbol_parquet(tmp_path, "AAPL", [], merge=True) == path
    assert path.is_file()


def test_manifest_records_merge_mode(tmp_path):
    manifest = write_run_manifest(
        tmp_path,
        run_id="2026-11-18-refresh",
        start=date(2026, 11, 5),
        end=date(2026, 11, 18),
        symbols_requested=["AAPL"],
        results=[{"symbol": "AAPL", "rows": 5, "path": "x", "error": None}],
        merge=True,
    )
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["merge"] is True
    assert payload["mode"] == "incremental_merge"
