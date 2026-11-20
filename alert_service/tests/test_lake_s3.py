"""Local lake ↔ S3 sync helpers for the AWS demo durable lake."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app import lake_s3


def _write_tiny_lake(root: Path) -> Path:
    parquet = root / "raw" / "prices" / "daily" / "symbol=AAPL" / "part-000.parquet"
    parquet.parent.mkdir(parents=True, exist_ok=True)
    parquet.write_bytes(b"PARQUET")
    reg = root / "registry" / "isolation_forest" / "current"
    reg.mkdir(parents=True, exist_ok=True)
    (reg / "model.joblib").write_bytes(b"MODEL")
    (reg / "meta.json").write_text('{"model_id":"isolation_forest_v1"}\n', encoding="utf-8")
    status = root / "raw" / "_runs" / "ui-status.json"
    status.parent.mkdir(parents=True, exist_ok=True)
    status.write_text('{"ok":true}\n', encoding="utf-8")
    return parquet


def test_s3_configured_requires_bucket(monkeypatch):
    monkeypatch.setattr(lake_s3.settings, "lake_s3_bucket", "")
    assert lake_s3.s3_configured() is False
    monkeypatch.setattr(lake_s3.settings, "lake_s3_bucket", "market-radar-lake")
    assert lake_s3.s3_configured() is True


def test_sync_lake_to_s3_uploads_zones_and_skips_ui_status(tmp_path, monkeypatch):
    _write_tiny_lake(tmp_path)
    monkeypatch.setattr(lake_s3.settings, "lake_s3_bucket", "market-radar-lake")
    monkeypatch.setattr(lake_s3.settings, "lake_s3_prefix", "")
    monkeypatch.setattr(lake_s3.settings, "lake_s3_region", "us-east-1")

    client = MagicMock()
    monkeypatch.setattr(lake_s3, "_client", lambda: client)

    result = lake_s3.sync_lake_to_s3(tmp_path)
    assert result["ok"] is True
    assert result["uploaded"] == 3
    keys = [call.args[2] for call in client.upload_file.call_args_list]
    assert "raw/prices/daily/symbol=AAPL/part-000.parquet" in keys
    assert "registry/isolation_forest/current/model.joblib" in keys
    assert "registry/isolation_forest/current/meta.json" in keys
    assert not any(k.endswith("ui-status.json") for k in keys)


def test_hydrate_lake_from_s3_downloads_objects(tmp_path, monkeypatch):
    monkeypatch.setattr(lake_s3.settings, "lake_s3_bucket", "market-radar-lake")
    monkeypatch.setattr(lake_s3.settings, "lake_s3_prefix", "")
    monkeypatch.setattr(lake_s3.settings, "lake_s3_region", "us-east-1")

    client = MagicMock()
    client.list_objects_v2.return_value = {
        "Contents": [
            {"Key": "raw/prices/daily/symbol=MSFT/part-000.parquet"},
            {"Key": "raw/"},
            {"Key": "raw/_runs/ui-status.json"},
        ],
        "IsTruncated": False,
    }

    def _download(_bucket, key, dest):
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        Path(dest).write_bytes(b"x")

    client.download_file.side_effect = _download
    monkeypatch.setattr(lake_s3, "_client", lambda: client)

    result = lake_s3.hydrate_lake_from_s3(tmp_path)
    assert result["ok"] is True
    assert result["downloaded"] == 1
    assert (tmp_path / "raw/prices/daily/symbol=MSFT/part-000.parquet").is_file()
    assert not (tmp_path / "raw/_runs/ui-status.json").exists()


def test_ensure_local_lake_pushes_when_s3_empty(tmp_path, monkeypatch):
    _write_tiny_lake(tmp_path)
    monkeypatch.setattr(lake_s3.settings, "lake_s3_bucket", "market-radar-lake")
    monkeypatch.setattr(lake_s3, "s3_has_lake", lambda _root=None: False)
    called = {}

    def _sync(root):
        called["root"] = root
        return {"ok": True, "uploaded": 1}

    monkeypatch.setattr(lake_s3, "sync_lake_to_s3", _sync)
    result = lake_s3.ensure_local_lake(tmp_path)
    assert result["ok"] is True
    assert called["root"] == tmp_path


def test_ensure_local_lake_hydrates_when_local_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(lake_s3.settings, "lake_s3_bucket", "market-radar-lake")
    monkeypatch.setattr(lake_s3, "s3_has_lake", lambda _root=None: True)

    def _hydrate(root):
        parquet = root / "raw" / "prices" / "daily" / "symbol=AAPL" / "part-000.parquet"
        parquet.parent.mkdir(parents=True, exist_ok=True)
        parquet.write_bytes(b"x")
        return {"ok": True, "downloaded": 1}

    monkeypatch.setattr(lake_s3, "hydrate_lake_from_s3", _hydrate)
    result = lake_s3.ensure_local_lake(tmp_path)
    assert result["ok"] is True
    assert result["downloaded"] == 1
