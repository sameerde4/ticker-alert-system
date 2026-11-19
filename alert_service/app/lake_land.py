"""Settings jobs: full Yahoo → lake land, and incremental refresh + Isolation Forest retrain."""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

_REPO = Path(__file__).resolve().parents[2]
_BATCH = _REPO / "batch_ingest"
_TRAIN = _REPO / "batch_train"
_LAKE = _REPO / "data" / "lake"
_STATUS_PATH = _LAKE / "raw" / "_runs" / "ui-status.json"

# ~2 weeks of calendar days ≈ 10 trading sessions for an incremental merge.
DEFAULT_REFRESH_DAYS = 14

_lock = asyncio.Lock()
_task: asyncio.Task | None = None


def _python() -> Path:
    """Prefer the alert_service interpreter (has yfinance/pandas/sklearn)."""
    return Path(sys.executable)


def _read_status() -> dict[str, Any]:
    if not _STATUS_PATH.is_file():
        return {
            "running": False,
            "job": None,
            "started_at": None,
            "finished_at": None,
            "ok": None,
            "message": "No lake land or refresh has been run from Settings yet.",
            "symbols_landed": None,
            "rows_landed": None,
            "manifest": None,
            "train": None,
            "lake_root": str(_LAKE),
        }
    try:
        payload = json.loads(_STATUS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "running": False,
            "job": None,
            "started_at": None,
            "finished_at": None,
            "ok": False,
            "message": "Could not read the last lake status file.",
            "symbols_landed": None,
            "rows_landed": None,
            "manifest": None,
            "train": None,
            "lake_root": str(_LAKE),
        }
    payload.setdefault("job", None)
    payload.setdefault("train", None)
    payload.setdefault("lake_root", str(_LAKE))
    return payload


def _write_status(payload: dict[str, Any]) -> None:
    _STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _STATUS_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def lake_land_status() -> dict[str, Any]:
    return _read_status()


def _busy() -> bool:
    current = _read_status()
    return bool(current.get("running") or (_task is not None and not _task.done()))


async def start_lake_land(*, days: int = 365) -> dict[str, Any]:
    """Start a background full S&P land (replace Parquet). Raises if a lake job is running."""
    global _task
    async with _lock:
        if _busy():
            raise RuntimeError("A lake land or refresh is already running.")
        started = datetime.now(UTC).isoformat()
        _write_status(
            {
                "running": True,
                "job": "land",
                "started_at": started,
                "finished_at": None,
                "ok": None,
                "message": (
                    f"Landing S&P 500 daily bars for the last {days} calendar days into the local lake…"
                ),
                "symbols_landed": None,
                "rows_landed": None,
                "manifest": None,
                "train": None,
                "lake_root": str(_LAKE),
                "days": days,
            }
        )
        _task = asyncio.create_task(_run_land(days=days), name="lake-land")
        return _read_status()


async def start_lake_refresh(*, days: int = DEFAULT_REFRESH_DAYS) -> dict[str, Any]:
    """Merge recent Yahoo dailies into the lake, then curate + retrain Isolation Forest."""
    global _task
    async with _lock:
        if _busy():
            raise RuntimeError("A lake land or refresh is already running.")
        started = datetime.now(UTC).isoformat()
        _write_status(
            {
                "running": True,
                "job": "refresh",
                "started_at": started,
                "finished_at": None,
                "ok": None,
                "message": (
                    f"Refreshing lake: merging last {days} calendar days of Yahoo dailies, "
                    "then retraining Isolation Forest…"
                ),
                "symbols_landed": None,
                "rows_landed": None,
                "manifest": None,
                "train": None,
                "lake_root": str(_LAKE),
                "days": days,
            }
        )
        _task = asyncio.create_task(_run_refresh(days=days), name="lake-refresh")
        return _read_status()


async def _run_land(*, days: int) -> None:
    started = _read_status().get("started_at")
    log.info("Starting full lake land (days=%s)", days)
    try:
        code, text = await _run_batch_ingest(days=days, merge=False)
        if code != 0:
            tail = text.strip().splitlines()[-8:] if text.strip() else ["land failed"]
            _write_status(
                {
                    "running": False,
                    "job": "land",
                    "started_at": started,
                    "finished_at": datetime.now(UTC).isoformat(),
                    "ok": False,
                    "message": "Historical price land failed. " + " ".join(tail),
                    "symbols_landed": None,
                    "rows_landed": None,
                    "manifest": None,
                    "train": None,
                    "lake_root": str(_LAKE),
                    "days": days,
                }
            )
            log.warning("Lake land failed: %s", " ".join(tail))
            return
        summary = _parse_done_line(text)
        _write_status(
            {
                "running": False,
                "job": "land",
                "started_at": started,
                "finished_at": datetime.now(UTC).isoformat(),
                "ok": True,
                "message": summary["message"],
                "symbols_landed": summary["symbols_landed"],
                "rows_landed": summary["rows_landed"],
                "manifest": summary["manifest"],
                "train": None,
                "lake_root": str(_LAKE),
                "days": days,
            }
        )
        log.info("Lake land finished: %s", summary["message"])
    except Exception as exc:
        _write_status(
            {
                "running": False,
                "job": "land",
                "started_at": started,
                "finished_at": datetime.now(UTC).isoformat(),
                "ok": False,
                "message": f"Historical price land failed: {exc}",
                "symbols_landed": None,
                "rows_landed": None,
                "manifest": None,
                "train": None,
                "lake_root": str(_LAKE),
                "days": days,
            }
        )
        log.exception("Lake land crashed")


async def _run_refresh(*, days: int) -> None:
    started = _read_status().get("started_at")
    log.info("Starting lake refresh + retrain (days=%s)", days)
    try:
        _write_status(
            {
                **_read_status(),
                "running": True,
                "job": "refresh",
                "message": f"Merging last {days} calendar days of Yahoo dailies into the lake…",
            }
        )
        code, text = await _run_batch_ingest(days=days, merge=True)
        if code != 0:
            tail = text.strip().splitlines()[-8:] if text.strip() else ["refresh land failed"]
            _write_status(
                {
                    "running": False,
                    "job": "refresh",
                    "started_at": started,
                    "finished_at": datetime.now(UTC).isoformat(),
                    "ok": False,
                    "message": "Lake refresh (land) failed. " + " ".join(tail),
                    "symbols_landed": None,
                    "rows_landed": None,
                    "manifest": None,
                    "train": None,
                    "lake_root": str(_LAKE),
                    "days": days,
                }
            )
            log.warning("Lake refresh land failed: %s", " ".join(tail))
            return

        summary = _parse_done_line(text)
        _write_status(
            {
                "running": True,
                "job": "refresh",
                "started_at": started,
                "finished_at": None,
                "ok": None,
                "message": (
                    f"{summary['message']} Retraining Isolation Forest on the updated lake…"
                ),
                "symbols_landed": summary["symbols_landed"],
                "rows_landed": summary["rows_landed"],
                "manifest": summary["manifest"],
                "train": None,
                "lake_root": str(_LAKE),
                "days": days,
            }
        )

        train_code, train_text = await _run_batch_train()
        train_info = _parse_train_output(train_text)
        if train_code != 0:
            tail = train_text.strip().splitlines()[-8:] if train_text.strip() else ["train failed"]
            _write_status(
                {
                    "running": False,
                    "job": "refresh",
                    "started_at": started,
                    "finished_at": datetime.now(UTC).isoformat(),
                    "ok": False,
                    "message": (
                        f"Land merged, but Isolation Forest retrain failed. "
                        + " ".join(tail)
                    ),
                    "symbols_landed": summary["symbols_landed"],
                    "rows_landed": summary["rows_landed"],
                    "manifest": summary["manifest"],
                    "train": train_info,
                    "lake_root": str(_LAKE),
                    "days": days,
                }
            )
            log.warning("Lake refresh train failed: %s", " ".join(tail))
            return

        model_bit = ""
        if train_info.get("model_id"):
            model_bit = f" Model {train_info['model_id']}."
        _write_status(
            {
                "running": False,
                "job": "refresh",
                "started_at": started,
                "finished_at": datetime.now(UTC).isoformat(),
                "ok": True,
                "message": (
                    f"Lake refreshed ({summary.get('symbols_landed') or '?'} symbols merged) "
                    f"and Isolation Forest retrained.{model_bit} "
                    "Live will pick up the new registry on its next rules refresh."
                ),
                "symbols_landed": summary["symbols_landed"],
                "rows_landed": summary["rows_landed"],
                "manifest": summary["manifest"],
                "train": train_info,
                "lake_root": str(_LAKE),
                "days": days,
            }
        )
        log.info("Lake refresh finished: %s", _read_status().get("message"))
    except Exception as exc:
        _write_status(
            {
                "running": False,
                "job": "refresh",
                "started_at": started,
                "finished_at": datetime.now(UTC).isoformat(),
                "ok": False,
                "message": f"Lake refresh failed: {exc}",
                "symbols_landed": None,
                "rows_landed": None,
                "manifest": None,
                "train": None,
                "lake_root": str(_LAKE),
                "days": days,
            }
        )
        log.exception("Lake refresh crashed")


async def _run_batch_ingest(*, days: int, merge: bool) -> tuple[int, str]:
    cmd = [
        str(_python()),
        "-m",
        "app.main",
        "--days",
        str(days),
    ]
    if merge:
        cmd.append("--merge")
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(_BATCH),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    stdout, _ = await proc.communicate()
    return proc.returncode or 0, (stdout or b"").decode("utf-8", errors="replace")


async def _run_batch_train() -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        str(_python()),
        "-m",
        "app.main",
        cwd=str(_TRAIN),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    stdout, _ = await proc.communicate()
    return proc.returncode or 0, (stdout or b"").decode("utf-8", errors="replace")


def _parse_done_line(text: str) -> dict[str, Any]:
    """Pull the summary from batch_ingest logs."""
    symbols = None
    rows = None
    manifest = None
    for line in text.splitlines():
        if "Done." not in line:
            continue
        try:
            part = line.split("Done.", 1)[1].strip()
            left, _, right = part.partition(" symbols, ")
            symbols = int(left.split("/")[0].strip())
            mid, _, rest = right.partition(" rows, manifest=")
            rows = int(mid.strip())
            manifest = rest.strip() or None
        except (ValueError, IndexError):
            continue
    if symbols is None:
        return {
            "message": "Historical price land finished.",
            "symbols_landed": None,
            "rows_landed": None,
            "manifest": None,
        }
    return {
        "message": f"Landed {symbols} S&P symbols ({rows} daily rows) into the local lake.",
        "symbols_landed": symbols,
        "rows_landed": rows,
        "manifest": manifest,
    }


def _parse_train_output(text: str) -> dict[str, Any] | None:
    """Best-effort parse of batch_train JSON stdout."""
    blob = text.strip()
    if not blob:
        return None
    # JSON may be preceded by log lines — take the outermost {...} block.
    start = blob.find("{")
    end = blob.rfind("}")
    if start < 0 or end <= start:
        return {"raw_tail": blob.splitlines()[-5:]}
    try:
        parsed = json.loads(blob[start : end + 1])
    except json.JSONDecodeError:
        return {"raw_tail": blob.splitlines()[-5:]}
    train = parsed.get("train") if isinstance(parsed, dict) else None
    if isinstance(train, dict):
        meta = train.get("meta") if isinstance(train.get("meta"), dict) else {}
        return {
            "model_id": meta.get("model_id") or train.get("model_id"),
            "score_cutoff": meta.get("score_cutoff") or train.get("score_cutoff"),
            "n_rows": meta.get("n_rows") or train.get("n_rows"),
            "registry": train.get("registry_dir") or train.get("registry"),
        }
    return parsed if isinstance(parsed, dict) else {"raw_tail": blob.splitlines()[-5:]}
