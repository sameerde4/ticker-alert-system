"""Sync the local price lake with the durable S3 lake bucket (AWS demo).

Compute still reads/writes ``LAKE_ROOT`` on disk (Parquet + Isolation Forest
registry). When ``TICKER_ALERT_LAKE_S3_BUCKET`` is set, successful land/train
jobs push that tree to S3, and an empty local volume can hydrate from S3 on boot.
"""

from __future__ import annotations

import logging
import mimetypes
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import settings

log = logging.getLogger(__name__)

# Zones that make up the training lake (skip ephemeral UI status under raw/_runs).
_SYNC_ROOTS = ("raw", "curated", "registry")
_SKIP_NAMES = {"ui-status.json"}


def s3_configured() -> bool:
    return bool((settings.lake_s3_bucket or "").strip())


def _bucket() -> str:
    return (settings.lake_s3_bucket or "").strip()


def _prefix() -> str:
    raw = (settings.lake_s3_prefix or "").strip().strip("/")
    return f"{raw}/" if raw else ""


def _client():
    import boto3

    kwargs: dict[str, Any] = {}
    region = (settings.lake_s3_region or "").strip()
    if region:
        kwargs["region_name"] = region
    return boto3.client("s3", **kwargs)


def _object_key(relative: Path) -> str:
    return f"{_prefix()}{relative.as_posix()}"


def _iter_local_files(lake_root: Path) -> list[Path]:
    files: list[Path] = []
    for name in _SYNC_ROOTS:
        root = lake_root / name
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.name in _SKIP_NAMES:
                continue
            files.append(path)
    return files


def s3_has_lake(lake_root: Path | None = None) -> bool:
    """True when the bucket has at least one daily Parquet under raw/prices/daily/."""
    if not s3_configured():
        return False
    try:
        client = _client()
        prefix = f"{_prefix()}raw/prices/daily/"
        token: str | None = None
        while True:
            kwargs: dict[str, Any] = {
                "Bucket": _bucket(),
                "Prefix": prefix,
                "MaxKeys": 50,
            }
            if token:
                kwargs["ContinuationToken"] = token
            resp = client.list_objects_v2(**kwargs)
            for item in resp.get("Contents") or []:
                key = str(item.get("Key") or "")
                if key.endswith(".parquet"):
                    return True
            if not resp.get("IsTruncated"):
                break
            token = resp.get("NextContinuationToken")
        return False
    except Exception as exc:
        log.warning("Could not list S3 lake (%s): %s", _bucket(), exc)
        return False


def sync_lake_to_s3(lake_root: Path | None = None) -> dict[str, Any]:
    """Upload local raw/curated/registry to the configured S3 bucket."""
    root = Path(lake_root or settings.lake_root)
    if not s3_configured():
        return {"ok": False, "skipped": True, "message": "S3 lake bucket not configured."}
    files = _iter_local_files(root)
    if not files:
        return {"ok": False, "skipped": True, "message": "Local lake has nothing to sync."}
    client = _client()
    bucket = _bucket()
    uploaded = 0
    errors: list[str] = []
    for path in files:
        relative = path.relative_to(root)
        key = _object_key(relative)
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        try:
            extra = {"ContentType": content_type}
            client.upload_file(str(path), bucket, key, ExtraArgs=extra)
            uploaded += 1
        except Exception as exc:
            errors.append(f"{key}: {exc}")
            if len(errors) >= 5:
                break
    ok = uploaded > 0 and not errors
    message = (
        f"Synced {uploaded} lake object(s) to s3://{bucket}/{_prefix()}"
        if ok
        else (
            f"S3 sync incomplete ({uploaded} uploaded). " + "; ".join(errors[:3])
            if errors
            else f"Synced {uploaded} object(s) to s3://{bucket}/{_prefix()}"
        )
    )
    if ok:
        log.info(message)
    else:
        log.warning(message)
    return {
        "ok": ok,
        "skipped": False,
        "bucket": bucket,
        "prefix": _prefix(),
        "uploaded": uploaded,
        "errors": errors,
        "message": message,
        "synced_at": datetime.now(UTC).isoformat(),
    }


def hydrate_lake_from_s3(lake_root: Path | None = None) -> dict[str, Any]:
    """Download S3 lake objects into an empty (or partial) local lake root."""
    root = Path(lake_root or settings.lake_root)
    if not s3_configured():
        return {"ok": False, "skipped": True, "message": "S3 lake bucket not configured."}
    client = _client()
    bucket = _bucket()
    downloaded = 0
    errors: list[str] = []
    try:
        token: str | None = None
        while True:
            kwargs: dict[str, Any] = {"Bucket": bucket, "Prefix": _prefix(), "MaxKeys": 1000}
            if token:
                kwargs["ContinuationToken"] = token
            resp = client.list_objects_v2(**kwargs)
            for item in resp.get("Contents") or []:
                key = str(item.get("Key") or "")
                if not key or key.endswith("/"):
                    continue
                relative = key[len(_prefix()) :] if _prefix() and key.startswith(_prefix()) else key
                if not relative or Path(relative).name in _SKIP_NAMES:
                    continue
                # Only hydrate lake zones we own.
                top = relative.split("/", 1)[0]
                if top not in _SYNC_ROOTS:
                    continue
                dest = root / relative
                dest.parent.mkdir(parents=True, exist_ok=True)
                try:
                    client.download_file(bucket, key, str(dest))
                    downloaded += 1
                except Exception as exc:
                    errors.append(f"{key}: {exc}")
                    if len(errors) >= 5:
                        break
            if errors and len(errors) >= 5:
                break
            if not resp.get("IsTruncated"):
                break
            token = resp.get("NextContinuationToken")
    except Exception as exc:
        return {
            "ok": False,
            "skipped": False,
            "bucket": bucket,
            "downloaded": downloaded,
            "message": f"S3 hydrate failed: {exc}",
        }
    ok = downloaded > 0 and not errors
    message = (
        f"Hydrated {downloaded} lake object(s) from s3://{bucket}/{_prefix()}"
        if downloaded
        else f"No lake objects under s3://{bucket}/{_prefix()}"
    )
    if ok:
        log.info(message)
    elif downloaded:
        log.warning("%s (%s)", message, "; ".join(errors[:3]))
    return {
        "ok": ok,
        "skipped": False,
        "bucket": bucket,
        "prefix": _prefix(),
        "downloaded": downloaded,
        "errors": errors,
        "message": message,
        "synced_at": datetime.now(UTC).isoformat(),
    }


def _local_has_raw_prices(lake_root: Path) -> bool:
    daily = lake_root / "raw" / "prices" / "daily"
    if not daily.is_dir():
        return False
    return any(daily.glob("symbol=*/part-000.parquet"))


def ensure_local_lake(lake_root: Path | None = None) -> dict[str, Any] | None:
    """On boot: hydrate from S3 when local is empty; push local when S3 is empty."""
    if not s3_configured():
        return None
    root = Path(lake_root or settings.lake_root)
    local = _local_has_raw_prices(root)
    remote = s3_has_lake(root)
    if not local and remote:
        log.info("Local lake empty — hydrating from s3://%s/%s", _bucket(), _prefix())
        return hydrate_lake_from_s3(root)
    if local and not remote:
        log.info("S3 lake empty — pushing local lake to s3://%s/%s", _bucket(), _prefix())
        return sync_lake_to_s3(root)
    return None
