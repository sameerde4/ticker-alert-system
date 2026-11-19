"""Trigger the historical Yahoo → local-lake land from the Settings UI."""

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
_LAKE = _REPO / "data" / "lake"
_STATUS_PATH = _LAKE / "raw" / "_runs" / "ui-status.json"

_lock = asyncio.Lock()
_task: asyncio.Task | None = None


def _python_for_batch() -> Path:
    """Prefer the alert_service interpreter (has yfinance/pandas); else batch_ingest venv."""
    return Path(sys.executable)


def _read_status() -> dict[str, Any]:
    if not _STATUS_PATH.is_file():
        return {
            "running": False,
            "started_at": None,
            "finished_at": None,
            "ok": None,
            "message": "No lake land has been run from Settings yet.",
            "symbols_landed": None,
            "rows_landed": None,
            "manifest": None,
            "lake_root": str(_LAKE),
        }
    try:
        return json.loads(_STATUS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "running": False,
            "started_at": None,
            "finished_at": None,
            "ok": False,
            "message": "Could not read the last lake status file.",
            "symbols_landed": None,
            "rows_landed": None,
            "manifest": None,
            "lake_root": str(_LAKE),
        }


def _write_status(payload: dict[str, Any]) -> None:
    _STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _STATUS_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def lake_land_status() -> dict[str, Any]:
    return _read_status()


async def start_lake_land(*, days: int = 365) -> dict[str, Any]:
    """Start a background S&P land. Raises RuntimeError if one is already running."""
    global _task
    async with _lock:
        current = _read_status()
        if current.get("running") or (_task is not None and not _task.done()):
            raise RuntimeError("A historical price land is already running.")
        started = datetime.now(UTC).isoformat()
        _write_status(
            {
                "running": True,
                "started_at": started,
                "finished_at": None,
                "ok": None,
                "message": (
                    f"Landing S&P 500 daily bars for the last {days} calendar days into the local lake…"
                ),
                "symbols_landed": None,
                "rows_landed": None,
                "manifest": None,
                "lake_root": str(_LAKE),
                "days": days,
            }
        )
        _task = asyncio.create_task(_run_land(days=days), name="lake-land")
        return _read_status()


async def _run_land(*, days: int) -> None:
    python = _python_for_batch()
    started = _read_status().get("started_at")
    log.info("Starting lake land with %s (days=%s)", python, days)
    try:
        proc = await asyncio.create_subprocess_exec(
            str(python),
            "-m",
            "app.main",
            "--days",
            str(days),
            cwd=str(_BATCH),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        stdout, _ = await proc.communicate()
        text = (stdout or b"").decode("utf-8", errors="replace")
        if proc.returncode != 0:
            tail = text.strip().splitlines()[-8:] if text.strip() else ["land failed"]
            _write_status(
                {
                    "running": False,
                    "started_at": started,
                    "finished_at": datetime.now(UTC).isoformat(),
                    "ok": False,
                    "message": "Historical price land failed. " + " ".join(tail),
                    "symbols_landed": None,
                    "rows_landed": None,
                    "manifest": None,
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
                "started_at": started,
                "finished_at": datetime.now(UTC).isoformat(),
                "ok": True,
                "message": summary["message"],
                "symbols_landed": summary["symbols_landed"],
                "rows_landed": summary["rows_landed"],
                "manifest": summary["manifest"],
                "lake_root": str(_LAKE),
                "days": days,
            }
        )
        log.info("Lake land finished: %s", summary["message"])
    except Exception as exc:
        _write_status(
            {
                "running": False,
                "started_at": started,
                "finished_at": datetime.now(UTC).isoformat(),
                "ok": False,
                "message": f"Historical price land failed: {exc}",
                "symbols_landed": None,
                "rows_landed": None,
                "manifest": None,
                "lake_root": str(_LAKE),
                "days": days,
            }
        )
        log.exception("Lake land crashed")


def _parse_done_line(text: str) -> dict[str, Any]:
    """Pull the summary from batch_ingest logs."""
    symbols = None
    rows = None
    manifest = None
    for line in text.splitlines():
        if "Done." not in line:
            continue
        # Done. 503/503 symbols, 125768 rows, manifest=/path
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
