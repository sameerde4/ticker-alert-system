import json
from datetime import date

from app.land import (
    expected_latest_session,
    latest_daily_dt,
    merge_fetch_start,
    raw_daily_dir,
    write_run_manifest,
    write_symbol_parquet,
)


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


def test_merge_fetch_start_skips_when_current_and_resumes_when_stale(tmp_path):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from app.land import last_session_on_or_before, symbol_is_current

    eastern = ZoneInfo("America/New_York")
    rows = [
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
            "dt": date(2026, 11, 18),  # Wednesday
            "open": 100.5,
            "high": 102.0,
            "low": 100.0,
            "close": 101.0,
            "volume": 1_100,
            "source": "yahoo",
            "grain": "daily",
        },
    ]
    assert write_symbol_parquet(tmp_path, "AAPL", rows) is not None
    assert latest_daily_dt(tmp_path, "AAPL") == date(2026, 11, 18)
    assert last_session_on_or_before(date(2026, 11, 22)) == date(2026, 11, 20)
    assert symbol_is_current(tmp_path, "AAPL", target=date(2026, 11, 18))
    assert not symbol_is_current(tmp_path, "AAPL", target=date(2026, 11, 19))
    # 4am Thursday: expected session is Wednesday — already current, skip Yahoo.
    preopen = datetime(2026, 11, 19, 4, 0, tzinfo=eastern)
    assert expected_latest_session(preopen) == date(2026, 11, 18)
    assert (
        merge_fetch_start(
            tmp_path,
            "AAPL",
            window_start=date(2026, 11, 5),
            now=preopen,
        )
        is None
    )
    # After Thursday close, expect Thursday — resume from Wednesday.
    after_close = datetime(2026, 11, 19, 17, 0, tzinfo=eastern)
    assert expected_latest_session(after_close) == date(2026, 11, 19)
    assert merge_fetch_start(
        tmp_path,
        "AAPL",
        window_start=date(2026, 11, 5),
        now=after_close,
    ) == date(2026, 11, 18)
    assert merge_fetch_start(
        tmp_path,
        "MSFT",
        window_start=date(2026, 11, 5),
        now=after_close,
    ) == date(2026, 11, 5)


def test_expected_latest_session_weekend_and_midday():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    eastern = ZoneInfo("America/New_York")
    # Saturday → Friday.
    assert expected_latest_session(datetime(2026, 11, 14, 12, 0, tzinfo=eastern)) == date(
        2026, 11, 13
    )
    # Sunday → Friday.
    assert expected_latest_session(datetime(2026, 11, 15, 9, 0, tzinfo=eastern)) == date(
        2026, 11, 13
    )
    # Midday Thursday still expects Wednesday (session not closed yet).
    assert expected_latest_session(datetime(2026, 11, 19, 11, 0, tzinfo=eastern)) == date(
        2026, 11, 18
    )
    # Exactly 4:00 PM Eastern on Thursday → Thursday.
    assert expected_latest_session(datetime(2026, 11, 19, 16, 0, tzinfo=eastern)) == date(
        2026, 11, 19
    )


def test_manifest_records_up_to_date_when_all_skipped(tmp_path):
    manifest = write_run_manifest(
        tmp_path,
        run_id="2026-11-19-skip",
        start=date(2026, 11, 5),
        end=date(2026, 11, 19),
        symbols_requested=["AAPL", "MSFT"],
        results=[
            {"symbol": "AAPL", "rows": 0, "path": None, "error": None, "skipped": "up_to_date"},
            {"symbol": "MSFT", "rows": 0, "path": None, "error": None, "skipped": "up_to_date"},
        ],
        merge=True,
        skipped_current=2,
        session_target=date(2026, 11, 18),
    )
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["up_to_date"] is True
    assert payload["skipped_current"] == 2
    assert payload["symbols_landed"] == 0
    assert payload["session_target"] == "2026-11-18"
    assert payload["mode"] == "incremental_merge"


def test_merge_fetch_start_respects_explicit_target(tmp_path):
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
        }
    ]
    assert write_symbol_parquet(tmp_path, "AAPL", rows) is not None
    # Explicit target Saturday → Friday session; lake only through Monday → resume.
    assert merge_fetch_start(
        tmp_path,
        "AAPL",
        window_start=date(2026, 11, 1),
        target=date(2026, 11, 21),  # Sat → Fri 20
    ) == date(2026, 11, 17)
    # Already through Friday → skip.
    rows2 = [
        {
            "symbol": "AAPL",
            "dt": date(2026, 11, 20),
            "open": 101.0,
            "high": 102.0,
            "low": 100.0,
            "close": 101.5,
            "volume": 1_100,
            "source": "yahoo",
            "grain": "daily",
        }
    ]
    assert write_symbol_parquet(tmp_path, "AAPL", rows2, merge=True) is not None
    assert (
        merge_fetch_start(
            tmp_path,
            "AAPL",
            window_start=date(2026, 11, 1),
            target=date(2026, 11, 21),
        )
        is None
    )
