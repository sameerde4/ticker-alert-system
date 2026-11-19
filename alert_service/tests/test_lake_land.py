from app.lake_land import _parse_done_line, lake_land_status


def test_parse_done_line_extracts_counts():
    text = (
        "2026-11-18 INFO batch_ingest: [503/503] ZTS landed 251 row(s)\n"
        "2026-11-18 INFO batch_ingest: Done. 503/503 symbols, 125768 rows, "
        "manifest=/tmp/run.json\n"
    )
    summary = _parse_done_line(text)
    assert summary["symbols_landed"] == 503
    assert summary["rows_landed"] == 125768
    assert summary["manifest"].endswith("run.json")
    assert "503 S&P symbols" in summary["message"]


def test_parse_done_line_handles_missing_summary():
    summary = _parse_done_line("no done line here")
    assert summary["symbols_landed"] is None
    assert "finished" in summary["message"].lower()


def test_lake_land_status_returns_a_dict():
    status = lake_land_status()
    assert "running" in status
    assert "lake_root" in status
