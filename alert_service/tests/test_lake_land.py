from app.lake_land import (
    DEFAULT_REFRESH_DAYS,
    _parse_done_line,
    _parse_train_output,
    lake_land_status,
)


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


def test_parse_train_output_reads_model_meta():
    text = (
        "2026-11-18 INFO batch_train: fitting…\n"
        '{\n  "train": {\n    "meta": {"model_id": "isolation_forest_v1", '
        '"score_cutoff": -0.1, "n_rows": 100},\n'
        '    "registry_dir": "/tmp/registry"\n  }\n}\n'
    )
    info = _parse_train_output(text)
    assert info["model_id"] == "isolation_forest_v1"
    assert info["registry"] == "/tmp/registry"
    assert info["n_rows"] == 100


def test_default_refresh_days_covers_about_two_weeks():
    assert DEFAULT_REFRESH_DAYS == 14


def test_lake_land_status_returns_a_dict():
    status = lake_land_status()
    assert "running" in status
    assert "lake_root" in status
    assert "train" in status or status.get("train") is None


def test_start_lake_refresh_rejects_when_busy(monkeypatch):
    import asyncio

    from app import lake_land

    monkeypatch.setattr(lake_land, "_busy", lambda: True)

    async def _run():
        try:
            await lake_land.start_lake_refresh(days=14)
            raise AssertionError("expected RuntimeError")
        except RuntimeError as exc:
            assert "already running" in str(exc).lower()

    asyncio.run(_run())


def test_start_lake_land_rejects_when_busy(monkeypatch):
    import asyncio

    from app import lake_land

    monkeypatch.setattr(lake_land, "_busy", lambda: True)

    async def _run():
        try:
            await lake_land.start_lake_land(days=365)
            raise AssertionError("expected RuntimeError")
        except RuntimeError as exc:
            assert "already running" in str(exc).lower()

    asyncio.run(_run())
