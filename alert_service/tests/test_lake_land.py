from app.lake_land import (
    DEFAULT_REFRESH_DAYS,
    _parse_done_line,
    _parse_progress_line,
    _parse_train_output,
    _progress_fields,
    lake_has_raw_prices,
    lake_land_status,
    lake_needs_refresh,
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
    assert summary["up_to_date"] is False


def test_parse_done_line_detects_up_to_date_short_circuit():
    text = (
        "2026-11-19 INFO batch_ingest: Done. 0/503 symbols, 0 rows, "
        "skipped_current=503, session_target=2026-11-18, manifest=/tmp/run.json\n"
    )
    summary = _parse_done_line(text)
    assert summary["up_to_date"] is True
    assert summary["skipped_current"] == 503
    assert summary["session_target"] == "2026-11-18"
    assert summary["rows_landed"] == 0
    assert "already current" in summary["message"].lower()
    assert "2026-11-18" in summary["message"]
    assert "4:00 PM Eastern" in summary["message"]


def test_parse_done_line_still_reads_legacy_skip_without_session_target():
    text = (
        "2026-11-19 INFO batch_ingest: Done. 0/503 symbols, 0 rows, "
        "skipped_current=503, manifest=/tmp/run.json\n"
    )
    summary = _parse_done_line(text)
    assert summary["up_to_date"] is True
    assert summary["session_target"] is None
    assert "already current" in summary["message"].lower()


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


def test_parse_progress_line_reads_bracket_counts():
    assert _parse_progress_line("INFO batch_ingest: [42/503] AAPL landed 251 row(s)") == {
        "done": 42,
        "total": 503,
    }
    assert _parse_progress_line("Landing 503 symbol(s) daily bars 2025-01-01 → 2026-01-01") == {
        "done": 0,
        "total": 503,
    }
    assert _parse_progress_line("no progress here") is None


def test_progress_fields_scales_land_when_train_follows():
    land = _progress_fields(phase="land", done=251, total=503, include_train=True)
    assert land["phase"] == "land"
    assert land["progress_done"] == 251
    assert 40.0 < land["progress_pct"] < 50.0
    train = _progress_fields(phase="train", done=503, total=503, include_train=True)
    assert train["phase"] == "train"
    assert train["progress_pct"] >= 90.0
    land_only = _progress_fields(phase="land", done=251, total=503, include_train=False)
    assert abs(land_only["progress_pct"] - round(100.0 * 251 / 503, 1)) < 0.01


def test_lake_land_status_returns_a_dict():
    status = lake_land_status()
    assert "running" in status
    assert "lake_root" in status
    assert "train" in status or status.get("train") is None
    assert "has_raw_prices" in status
    assert "has_registry" in status
    assert "auto_enabled" in status


def test_lake_needs_refresh_false_when_empty(monkeypatch, tmp_path):
    from app import lake_land

    monkeypatch.setattr(lake_land, "_LAKE", tmp_path)
    assert lake_has_raw_prices() is False
    assert lake_needs_refresh() is False


def test_lake_needs_refresh_when_prices_but_no_registry(monkeypatch, tmp_path):
    from app import lake_land

    monkeypatch.setattr(lake_land, "_LAKE", tmp_path)
    part = tmp_path / "raw" / "prices" / "daily" / "symbol=AAPL"
    part.mkdir(parents=True)
    (part / "part-000.parquet").write_bytes(b"x")
    assert lake_has_raw_prices() is True
    assert lake_needs_refresh() is True


def test_maybe_start_auto_lake_job_skips_when_disabled(monkeypatch):
    import asyncio

    from app import lake_land

    monkeypatch.setattr(lake_land, "_auto_enabled", lambda: False)

    async def _run():
        assert await lake_land.maybe_start_auto_lake_job() is None

    asyncio.run(_run())


def test_reconcile_clears_ghost_running_when_manifest_is_fresh(monkeypatch, tmp_path):
    from datetime import UTC, datetime, timedelta

    from app import lake_land

    monkeypatch.setattr(lake_land, "_LAKE", tmp_path)
    monkeypatch.setattr(lake_land, "_task", None)
    runs = tmp_path / "raw" / "_runs"
    runs.mkdir(parents=True)
    landed = datetime.now(UTC) - timedelta(minutes=5)
    (runs / "2026-11-19-abcd.json").write_text(
        '{"landed_at": "%s", "mode": "incremental_merge", "symbols_landed": 3}\n'
        % landed.isoformat(),
        encoding="utf-8",
    )
    (runs / "ui-status.json").write_text(
        '{"running": true, "job": "refresh", "ok": null, "message": "stuck"}\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(lake_land, "lake_has_registry", lambda: True)
    cleared = lake_land.reconcile_stale_lake_status()
    assert cleared is not None
    assert cleared["running"] is False
    assert cleared["ok"] is True
    assert lake_land.lake_needs_refresh() is False


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


def test_parse_done_line_partial_skip_not_up_to_date():
    text = (
        "2026-11-19 INFO batch_ingest: Done. 2/503 symbols, 40 rows, "
        "skipped_current=501, manifest=/tmp/run.json\n"
    )
    summary = _parse_done_line(text)
    assert summary["up_to_date"] is False
    assert summary["skipped_current"] == 501
    assert summary["symbols_landed"] == 2
    assert summary["rows_landed"] == 40


def test_progress_fields_land_only_and_zero_total():
    empty = _progress_fields(phase="land", done=0, total=0, include_train=False)
    assert empty["progress_pct"] == 0.0 or empty["progress_pct"] is None or empty["progress_done"] == 0
    mid = _progress_fields(phase="land", done=100, total=200, include_train=False)
    assert mid["progress_pct"] == 50.0
    done = _progress_fields(phase="land", done=200, total=200, include_train=False)
    assert done["progress_pct"] == 100.0


def test_maybe_start_auto_lake_job_lands_when_empty(monkeypatch):
    import asyncio

    from app import lake_land

    started = {}

    async def fake_land(**kwargs):
        started.update(kwargs)
        return {"running": True, "job": "land"}

    monkeypatch.setattr(lake_land, "_auto_enabled", lambda: True)
    monkeypatch.setattr(lake_land, "_busy", lambda: False)
    monkeypatch.setattr(lake_land, "lake_has_raw_prices", lambda: False)
    monkeypatch.setattr(lake_land, "start_lake_land", fake_land)

    async def _run():
        result = await lake_land.maybe_start_auto_lake_job()
        assert result is not None
        assert result["job"] == "land"
        assert started.get("train_after") is True

    asyncio.run(_run())


def test_maybe_start_auto_lake_job_refreshes_when_needed(monkeypatch):
    import asyncio

    from app import lake_land

    started = {}

    async def fake_refresh(**kwargs):
        started.update(kwargs)
        return {"running": True, "job": "refresh"}

    monkeypatch.setattr(lake_land, "_auto_enabled", lambda: True)
    monkeypatch.setattr(lake_land, "_busy", lambda: False)
    monkeypatch.setattr(lake_land, "lake_has_raw_prices", lambda: True)
    monkeypatch.setattr(lake_land, "lake_needs_refresh", lambda: True)
    monkeypatch.setattr(lake_land, "start_lake_refresh", fake_refresh)

    async def _run():
        result = await lake_land.maybe_start_auto_lake_job()
        assert result is not None
        assert result["job"] == "refresh"
        assert started.get("days") == DEFAULT_REFRESH_DAYS

    asyncio.run(_run())


def test_maybe_start_auto_lake_job_noops_when_current(monkeypatch):
    import asyncio

    from app import lake_land

    monkeypatch.setattr(lake_land, "_auto_enabled", lambda: True)
    monkeypatch.setattr(lake_land, "_busy", lambda: False)
    monkeypatch.setattr(lake_land, "lake_has_raw_prices", lambda: True)
    monkeypatch.setattr(lake_land, "lake_needs_refresh", lambda: False)

    async def _run():
        assert await lake_land.maybe_start_auto_lake_job() is None

    asyncio.run(_run())


def test_reconcile_leaves_running_when_task_live(monkeypatch, tmp_path):
    from app import lake_land

    monkeypatch.setattr(lake_land, "_LAKE", tmp_path)
    monkeypatch.setattr(lake_land, "_task_live", lambda: True)
    (tmp_path / "raw" / "_runs").mkdir(parents=True)
    (tmp_path / "raw" / "_runs" / "ui-status.json").write_text(
        '{"running": true, "job": "refresh", "ok": null, "message": "working"}\n',
        encoding="utf-8",
    )
    assert lake_land.reconcile_stale_lake_status() is None


def test_lake_needs_refresh_false_when_recent_success(monkeypatch, tmp_path):
    from datetime import UTC, datetime, timedelta

    from app import lake_land

    monkeypatch.setattr(lake_land, "_LAKE", tmp_path)
    part = tmp_path / "raw" / "prices" / "daily" / "symbol=AAPL"
    part.mkdir(parents=True)
    (part / "part-000.parquet").write_bytes(b"x")
    reg = tmp_path / "registry" / "isolation_forest" / "current"
    reg.mkdir(parents=True)
    (reg / "model.joblib").write_bytes(b"x")
    runs = tmp_path / "raw" / "_runs"
    runs.mkdir(parents=True)
    landed = datetime.now(UTC) - timedelta(hours=1)
    (runs / "fresh.json").write_text(
        '{"landed_at": "%s", "mode": "incremental_merge", "symbols_landed": 1}\n'
        % landed.isoformat(),
        encoding="utf-8",
    )
    monkeypatch.setattr(lake_land, "lake_has_registry", lambda: True)
    assert lake_needs_refresh() is False


def test_auto_enabled_respects_skip_env(monkeypatch):
    from app import lake_land

    monkeypatch.setenv("TICKER_ALERT_SKIP_LAKE_AUTO", "1")
    assert lake_land._auto_enabled() is False
    monkeypatch.delenv("TICKER_ALERT_SKIP_LAKE_AUTO", raising=False)
    monkeypatch.setattr(lake_land.settings, "lake_auto_enabled", False)
    assert lake_land._auto_enabled() is False
    monkeypatch.setattr(lake_land.settings, "lake_auto_enabled", True)
    assert lake_land._auto_enabled() is True
