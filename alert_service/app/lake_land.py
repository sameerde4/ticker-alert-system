"""Lake land / refresh jobs: Settings buttons, first-boot bootstrap, and daily auto-refresh."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from .config import settings
from .lake_s3 import ensure_local_lake, s3_configured, s3_has_lake, sync_lake_to_s3

log = logging.getLogger(__name__)

_PROGRESS_BRACKET = re.compile(r"\[(\d+)/(\d+)\]")
_LANDING_COUNT = re.compile(r"Landing\s+(\d+)\s+symbol", re.IGNORECASE)
# Land/refresh symbol loop is most of the wall clock; training is the tail.
_LAND_SHARE = 0.9

_REPO = Path(__file__).resolve().parents[2]
_BATCH = _REPO / "batch_ingest"
_TRAIN = _REPO / "batch_train"
_LAKE = Path(settings.lake_root)


def _status_path() -> Path:
    return _LAKE / "raw" / "_runs" / "ui-status.json"

# ~2 weeks of calendar days ≈ 10 trading sessions for an incremental merge.
DEFAULT_REFRESH_DAYS = 14

_lock = asyncio.Lock()
_task: asyncio.Task | None = None
_scheduler_task: asyncio.Task | None = None


def _python() -> Path:
    """Prefer the alert_service interpreter (has yfinance/pandas/sklearn)."""
    return Path(sys.executable)


def _read_status() -> dict[str, Any]:
    path = _status_path()
    if not path.is_file():
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
        payload = json.loads(path.read_text(encoding="utf-8"))
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
    path = _status_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def lake_land_status() -> dict[str, Any]:
    if _read_status().get("running") and not _task_live():
        reconcile_stale_lake_status()
    status = _read_status()
    status["has_raw_prices"] = lake_has_raw_prices()
    status["has_registry"] = lake_has_registry()
    status["auto_enabled"] = _auto_enabled()
    status["s3_bucket"] = (settings.lake_s3_bucket or "").strip() or None
    status["s3_prefix"] = (settings.lake_s3_prefix or "").strip() or None
    status["s3_configured"] = s3_configured()
    if "s3" not in status and s3_configured():
        # Cheap flag for the UI / docs — full list is avoided on every poll.
        status["s3_has_lake"] = None
    return status


async def _sync_lake_to_s3_after_success() -> dict[str, Any] | None:
    """Push the working lake to S3 after a successful land/train (AWS durable lake)."""
    if not s3_configured() or not lake_has_raw_prices():
        return None
    result = await asyncio.to_thread(sync_lake_to_s3, _LAKE)
    current = _read_status()
    current["s3"] = result
    _write_status(current)
    return result


def lake_has_raw_prices() -> bool:
    root = _LAKE / "raw" / "prices" / "daily"
    if not root.is_dir():
        return False
    return any(root.glob("symbol=*/part-000.parquet"))


def lake_has_registry() -> bool:
    folder = _LAKE / "registry" / "isolation_forest" / "current"
    return (folder / "model.joblib").is_file() and (folder / "meta.json").is_file()


def _auto_enabled() -> bool:
    if os.environ.get("TICKER_ALERT_SKIP_LAKE_AUTO") == "1":
        return False
    return bool(settings.lake_auto_enabled)


def _task_live() -> bool:
    return _task is not None and not _task.done()


def _busy() -> bool:
    """Only a live asyncio task counts as busy — a stale status file must not block forever."""
    return _task_live()


def _parse_iso(raw: Any) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def _latest_run_landed_at() -> datetime | None:
    """Newest successful batch_ingest manifest time (ignores ui-status.json)."""
    runs = _LAKE / "raw" / "_runs"
    if not runs.is_dir():
        return None
    best: datetime | None = None
    for path in runs.glob("*.json"):
        if path.name == "ui-status.json":
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        landed = _parse_iso(payload.get("landed_at"))
        if landed is None:
            continue
        if best is None or landed > best:
            best = landed
    return best


def _last_success_at() -> datetime | None:
    status = _read_status()
    if status.get("ok") is True:
        finished = _parse_iso(status.get("finished_at"))
        if finished is not None:
            return finished
    # After an API restart the UI status can be stuck or missing ok=True even when
    # the lake merge already finished — fall back to the latest ingest manifest.
    return _latest_run_landed_at()


def lake_needs_refresh() -> bool:
    """True when raw prices exist but the registry is missing or the last success is stale."""
    if not lake_has_raw_prices():
        return False
    if not lake_has_registry():
        return True
    last = _last_success_at()
    if last is None:
        return True
    hours = max(1.0, float(settings.lake_refresh_interval_hours or 24.0))
    return datetime.now(UTC) - last >= timedelta(hours=hours)


def reconcile_stale_lake_status() -> dict[str, Any] | None:
    """Clear a ghost ``running`` status left behind when uvicorn reloads mid-job."""
    status = _read_status()
    if not status.get("running") or _task_live():
        return None
    hours = max(1.0, float(settings.lake_refresh_interval_hours or 24.0))
    landed = _latest_run_landed_at()
    fresh = landed is not None and datetime.now(UTC) - landed < timedelta(hours=hours)
    if fresh:
        message = (
            "Recovered after API restart. The latest lake merge already finished; "
            "not starting a duplicate refresh."
        )
        ok: bool | None = True
        finished_at = landed.isoformat() if landed else datetime.now(UTC).isoformat()
    else:
        message = "Lake job was interrupted by an API restart before it finished."
        ok = False
        finished_at = datetime.now(UTC).isoformat()
    payload = {
        **status,
        "running": False,
        "ok": ok,
        "finished_at": finished_at,
        "message": message,
        "phase": None,
        "progress_pct": None,
        "progress_done": None,
        "progress_total": None,
    }
    _write_status(payload)
    log.warning("Cleared stale lake running status: %s", message)
    return payload


async def start_lake_land(
    *, days: int = 365, train_after: bool = False, auto: bool = False
) -> dict[str, Any]:
    """Start a background full S&P land (replace Parquet). Raises if a lake job is running.

    ``train_after=True`` also runs ``batch_train`` (first-boot bootstrap).
    """
    global _task
    async with _lock:
        if _busy():
            raise RuntimeError("A lake land or refresh is already running.")
        started = datetime.now(UTC).isoformat()
        job = "bootstrap" if train_after else "land"
        prefix = "Loading historical prices…" if auto else ""
        message = (
            (prefix + " " if prefix else "")
            + f"Landing S&P 500 daily bars for the last {days} calendar days"
            + (", then training Isolation Forest…" if train_after else " into the local lake…")
        )
        _write_status(
            {
                "running": True,
                "job": job,
                "started_at": started,
                "finished_at": None,
                "ok": None,
                "message": message.strip(),
                "symbols_landed": None,
                "rows_landed": None,
                "manifest": None,
                "train": None,
                "lake_root": str(_LAKE),
                "days": days,
                "auto": auto,
                **_progress_fields(phase="land", done=0, total=None, include_train=train_after),
            }
        )
        _task = asyncio.create_task(
            _run_land(days=days, train_after=train_after, job=job),
            name="lake-land",
        )
        return lake_land_status()


async def start_lake_refresh(
    *, days: int = DEFAULT_REFRESH_DAYS, auto: bool = False
) -> dict[str, Any]:
    """Merge recent Yahoo dailies into the lake, then curate + retrain Isolation Forest."""
    global _task
    async with _lock:
        if _busy():
            raise RuntimeError("A lake land or refresh is already running.")
        started = datetime.now(UTC).isoformat()
        prefix = "Refreshing historical prices…" if auto else ""
        message = (
            (prefix + " " if prefix else "")
            + f"Refreshing lake: merging last {days} calendar days of Yahoo dailies, "
            "then retraining Isolation Forest…"
        )
        _write_status(
            {
                "running": True,
                "job": "refresh",
                "started_at": started,
                "finished_at": None,
                "ok": None,
                "message": message.strip(),
                "symbols_landed": None,
                "rows_landed": None,
                "manifest": None,
                "train": None,
                "lake_root": str(_LAKE),
                "days": days,
                "auto": auto,
                **_progress_fields(phase="land", done=0, total=None, include_train=True),
            }
        )
        _task = asyncio.create_task(_run_refresh(days=days), name="lake-refresh")
        return lake_land_status()


async def maybe_start_auto_lake_job() -> dict[str, Any] | None:
    """Bootstrap an empty lake, or refresh when stale. No-op when busy / disabled."""
    if not _auto_enabled():
        return None
    if _busy():
        return None
    if not lake_has_raw_prices():
        log.info("Lake empty — starting automatic historical land + train")
        return await start_lake_land(days=365, train_after=True, auto=True)
    if lake_needs_refresh():
        log.info("Lake stale or registry missing — starting automatic refresh + retrain")
        try:
            return await start_lake_refresh(days=DEFAULT_REFRESH_DAYS, auto=True)
        except RuntimeError:
            return None
    return None


async def start_lake_auto_scheduler() -> None:
    """Background loop: first-boot land, then periodic refresh+retrain."""
    global _scheduler_task
    if not _auto_enabled():
        log.info("Lake auto scheduler disabled")
        return
    if _scheduler_task is not None and not _scheduler_task.done():
        return

    reconcile_stale_lake_status()

    async def _loop() -> None:
        await asyncio.sleep(2)
        if s3_configured():
            try:
                result = await asyncio.to_thread(ensure_local_lake, _LAKE)
                if result:
                    current = _read_status()
                    current["s3"] = result
                    _write_status(current)
            except Exception:
                log.exception("S3 lake ensure (hydrate/push) failed")
        while True:
            try:
                reconcile_stale_lake_status()
                await maybe_start_auto_lake_job()
            except Exception:
                log.exception("Lake auto job failed")
            hours = max(1.0, float(settings.lake_refresh_interval_hours or 24.0))
            # Poll at least hourly so a failed first land retries; staleness uses ``hours``.
            await asyncio.sleep(min(3600.0, hours * 3600.0))

    _scheduler_task = asyncio.create_task(_loop(), name="lake-auto-scheduler")
    log.info(
        "Lake auto scheduler started (stale after %s hours)",
        settings.lake_refresh_interval_hours,
    )


async def stop_lake_auto_scheduler() -> None:
    global _scheduler_task
    if _scheduler_task is None:
        return
    _scheduler_task.cancel()
    try:
        await _scheduler_task
    except asyncio.CancelledError:
        pass
    _scheduler_task = None


def _progress_fields(
    *,
    phase: str | None,
    done: int | None = None,
    total: int | None = None,
    include_train: bool = False,
) -> dict[str, Any]:
    if phase == "train":
        # Land finished; training has no per-step logs — park near the end.
        pct = round(_LAND_SHARE * 100.0 + (100.0 - _LAND_SHARE * 100.0) * 0.4, 1)
        return {
            "phase": "train",
            "progress_done": done,
            "progress_total": total,
            "progress_pct": pct,
        }
    if phase == "land":
        if total and total > 0 and done is not None:
            land_frac = min(1.0, max(0.0, float(done) / float(total)))
        else:
            land_frac = 0.0
        scale = _LAND_SHARE * 100.0 if include_train else 100.0
        return {
            "phase": "land",
            "progress_done": done if done is not None else 0,
            "progress_total": total,
            "progress_pct": round(land_frac * scale, 1),
        }
    return {
        "phase": phase,
        "progress_done": done,
        "progress_total": total,
        "progress_pct": None,
    }


def _parse_progress_line(line: str) -> dict[str, int] | None:
    """Parse batch_ingest ``[i/n]`` or ``Landing n symbol(s)`` progress."""
    bracket = _PROGRESS_BRACKET.search(line)
    if bracket:
        done = int(bracket.group(1))
        total = int(bracket.group(2))
        if total > 0:
            return {"done": done, "total": total}
    landing = _LANDING_COUNT.search(line)
    if landing:
        total = int(landing.group(1))
        if total > 0:
            return {"done": 0, "total": total}
    return None


def _patch_running_progress(
    *,
    phase: str,
    done: int | None,
    total: int | None,
    include_train: bool,
    message: str | None = None,
) -> None:
    current = _read_status()
    if not current.get("running"):
        return
    payload = {
        **current,
        **_progress_fields(
            phase=phase,
            done=done,
            total=total,
            include_train=include_train,
        ),
    }
    if message:
        payload["message"] = message
    _write_status(payload)


def _job_status(
    *,
    running: bool,
    job: str | None,
    started_at: Any,
    finished_at: Any,
    ok: bool | None,
    message: str,
    symbols_landed: Any = None,
    rows_landed: Any = None,
    manifest: Any = None,
    train: Any = None,
    days: int | None = None,
    auto: bool = False,
    phase: str | None = None,
    progress_done: Any = None,
    progress_total: Any = None,
    progress_pct: Any = None,
    session_target: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "running": running,
        "job": job,
        "started_at": started_at,
        "finished_at": finished_at,
        "ok": ok,
        "message": message,
        "symbols_landed": symbols_landed,
        "rows_landed": rows_landed,
        "manifest": manifest,
        "train": train,
        "lake_root": str(_LAKE),
        "auto": auto,
        "phase": phase,
        "progress_done": progress_done,
        "progress_total": progress_total,
        "progress_pct": progress_pct,
    }
    if days is not None:
        payload["days"] = days
    if session_target:
        payload["session_target"] = session_target
    return payload


async def _run_land(*, days: int, train_after: bool = False, job: str = "land") -> None:
    prior = _read_status()
    started = prior.get("started_at")
    auto = bool(prior.get("auto"))
    log.info("Starting full lake land (days=%s train_after=%s auto=%s)", days, train_after, auto)
    try:
        code, text = await _run_batch_ingest(
            days=days,
            merge=False,
            include_train=train_after,
        )
        if code != 0:
            tail = text.strip().splitlines()[-8:] if text.strip() else ["land failed"]
            _write_status(
                _job_status(
                    running=False,
                    job=job,
                    started_at=started,
                    finished_at=datetime.now(UTC).isoformat(),
                    ok=False,
                    message="Historical price land failed. " + " ".join(tail),
                    days=days,
                    auto=auto,
                )
            )
            log.warning("Lake land failed: %s", " ".join(tail))
            return
        summary = _parse_done_line(text)
        if not train_after:
            _write_status(
                _job_status(
                    running=False,
                    job=job,
                    started_at=started,
                    finished_at=datetime.now(UTC).isoformat(),
                    ok=True,
                    message=summary["message"],
                    symbols_landed=summary["symbols_landed"],
                    rows_landed=summary["rows_landed"],
                    manifest=summary["manifest"],
                    days=days,
                    auto=auto,
                    progress_done=summary["symbols_landed"],
                    progress_total=summary["symbols_landed"],
                    progress_pct=100.0,
                )
            )
            await _sync_lake_to_s3_after_success()
            log.info("Lake land finished: %s", summary["message"])
            return

        land_total = summary["symbols_landed"]
        _write_status(
            _job_status(
                running=True,
                job=job,
                started_at=started,
                finished_at=None,
                ok=None,
                message=f"{summary['message']} Training Isolation Forest on the new lake…",
                symbols_landed=summary["symbols_landed"],
                rows_landed=summary["rows_landed"],
                manifest=summary["manifest"],
                days=days,
                auto=auto,
                **_progress_fields(
                    phase="train",
                    done=land_total,
                    total=land_total,
                    include_train=True,
                ),
            )
        )
        train_code, train_text = await _run_batch_train()
        train_info = _parse_train_output(train_text)
        if train_code != 0:
            tail = train_text.strip().splitlines()[-8:] if train_text.strip() else ["train failed"]
            _write_status(
                _job_status(
                    running=False,
                    job=job,
                    started_at=started,
                    finished_at=datetime.now(UTC).isoformat(),
                    ok=False,
                    message="Land finished, but Isolation Forest training failed. " + " ".join(tail),
                    symbols_landed=summary["symbols_landed"],
                    rows_landed=summary["rows_landed"],
                    manifest=summary["manifest"],
                    train=train_info,
                    days=days,
                    auto=auto,
                )
            )
            log.warning("Lake bootstrap train failed: %s", " ".join(tail))
            return
        model_bit = ""
        if train_info and train_info.get("model_id"):
            model_bit = f" Model {train_info['model_id']}."
        _write_status(
            _job_status(
                running=False,
                job=job,
                started_at=started,
                finished_at=datetime.now(UTC).isoformat(),
                ok=True,
                message=f"{summary['message']} Isolation Forest trained.{model_bit}",
                symbols_landed=summary["symbols_landed"],
                rows_landed=summary["rows_landed"],
                manifest=summary["manifest"],
                train=train_info,
                days=days,
                auto=auto,
                progress_done=land_total,
                progress_total=land_total,
                progress_pct=100.0,
            )
        )
        await _sync_lake_to_s3_after_success()
        log.info("Lake bootstrap finished: %s", _read_status().get("message"))
    except Exception as exc:
        _write_status(
            _job_status(
                running=False,
                job=job,
                started_at=started,
                finished_at=datetime.now(UTC).isoformat(),
                ok=False,
                message=f"Historical price land failed: {exc}",
                days=days,
                auto=auto,
            )
        )
        log.exception("Lake land crashed")


async def _run_refresh(*, days: int) -> None:
    prior = _read_status()
    started = prior.get("started_at")
    auto = bool(prior.get("auto"))
    log.info("Starting lake refresh + retrain (days=%s auto=%s)", days, auto)
    try:
        _write_status(
            {
                **prior,
                "running": True,
                "job": "refresh",
                "auto": auto,
                "message": f"Merging last {days} calendar days of Yahoo dailies into the lake…",
                **_progress_fields(phase="land", done=0, total=None, include_train=True),
            }
        )
        code, text = await _run_batch_ingest(days=days, merge=True, include_train=True)
        if code != 0:
            tail = text.strip().splitlines()[-8:] if text.strip() else ["refresh land failed"]
            _write_status(
                _job_status(
                    running=False,
                    job="refresh",
                    started_at=started,
                    finished_at=datetime.now(UTC).isoformat(),
                    ok=False,
                    message="Lake refresh (land) failed. " + " ".join(tail),
                    days=days,
                    auto=auto,
                )
            )
            log.warning("Lake refresh land failed: %s", " ".join(tail))
            return

        summary = _parse_done_line(text)
        land_total = summary["symbols_landed"]
        if summary.get("up_to_date"):
            skipped = summary.get("skipped_current")
            target = summary.get("session_target")
            through = f" through {target}" if target else ""
            count = f" ({skipped} symbols up to date)" if skipped is not None else ""
            _write_status(
                _job_status(
                    running=False,
                    job="refresh",
                    started_at=started,
                    finished_at=datetime.now(UTC).isoformat(),
                    ok=True,
                    message=(
                        f"Lake already current{through}{count}; skipped Yahoo and retrain. "
                        "Today's session lands after 4:00 PM Eastern "
                        "(live Kafka bars do not write the lake)."
                    ),
                    symbols_landed=0,
                    rows_landed=0,
                    manifest=summary["manifest"],
                    days=days,
                    auto=auto,
                    progress_done=land_total,
                    progress_total=land_total,
                    progress_pct=100.0,
                    session_target=target,
                )
            )
            # Keep S3 durable even when Yahoo had nothing new (first push after enable).
            if s3_configured() and not s3_has_lake(_LAKE):
                await _sync_lake_to_s3_after_success()
            log.info("Lake refresh short-circuited: already current through %s", target)
            return

        _write_status(
            _job_status(
                running=True,
                job="refresh",
                started_at=started,
                finished_at=None,
                ok=None,
                message=(
                    f"{summary['message']} Retraining Isolation Forest on the updated lake…"
                ),
                symbols_landed=summary["symbols_landed"],
                rows_landed=summary["rows_landed"],
                manifest=summary["manifest"],
                days=days,
                auto=auto,
                **_progress_fields(
                    phase="train",
                    done=land_total,
                    total=land_total,
                    include_train=True,
                ),
            )
        )

        train_code, train_text = await _run_batch_train()
        train_info = _parse_train_output(train_text)
        if train_code != 0:
            tail = train_text.strip().splitlines()[-8:] if train_text.strip() else ["train failed"]
            _write_status(
                _job_status(
                    running=False,
                    job="refresh",
                    started_at=started,
                    finished_at=datetime.now(UTC).isoformat(),
                    ok=False,
                    message=(
                        "Land merged, but Isolation Forest retrain failed. " + " ".join(tail)
                    ),
                    symbols_landed=summary["symbols_landed"],
                    rows_landed=summary["rows_landed"],
                    manifest=summary["manifest"],
                    train=train_info,
                    days=days,
                    auto=auto,
                )
            )
            log.warning("Lake refresh train failed: %s", " ".join(tail))
            return

        model_bit = ""
        if train_info and train_info.get("model_id"):
            model_bit = f" Model {train_info['model_id']}."
        _write_status(
            _job_status(
                running=False,
                job="refresh",
                started_at=started,
                finished_at=datetime.now(UTC).isoformat(),
                ok=True,
                message=(
                    f"Lake refreshed ({summary.get('symbols_landed') or '?'} symbols merged) "
                    f"and Isolation Forest retrained.{model_bit} "
                    "Live will pick up the new registry on its next rules refresh."
                ),
                symbols_landed=summary["symbols_landed"],
                rows_landed=summary["rows_landed"],
                manifest=summary["manifest"],
                train=train_info,
                days=days,
                auto=auto,
                progress_done=land_total,
                progress_total=land_total,
                progress_pct=100.0,
            )
        )
        await _sync_lake_to_s3_after_success()
        log.info("Lake refresh finished: %s", _read_status().get("message"))
    except Exception as exc:
        _write_status(
            _job_status(
                running=False,
                job="refresh",
                started_at=started,
                finished_at=datetime.now(UTC).isoformat(),
                ok=False,
                message=f"Lake refresh failed: {exc}",
                days=days,
                auto=auto,
            )
        )
        log.exception("Lake refresh crashed")


async def _run_batch_ingest(
    *,
    days: int,
    merge: bool,
    include_train: bool = False,
) -> tuple[int, str]:
    cmd = [
        str(_python()),
        "-m",
        "app.main",
        "--days",
        str(days),
        "--lake-root",
        str(_LAKE),
    ]
    if merge:
        cmd.append("--merge")
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(_BATCH),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env={**os.environ, "LAKE_ROOT": str(_LAKE)},
    )
    chunks: list[str] = []
    assert proc.stdout is not None
    last_done: int | None = None
    while True:
        raw = await proc.stdout.readline()
        if not raw:
            break
        line = raw.decode("utf-8", errors="replace")
        chunks.append(line)
        progress = _parse_progress_line(line)
        if not progress:
            continue
        done = progress["done"]
        total = progress["total"]
        if done == last_done and done > 0:
            continue
        last_done = done
        if total and done:
            verb = "Refreshing" if merge else "Landing"
            message = f"{verb} historical prices… {done}/{total} symbols ({round(100.0 * done / total)}%)."
        elif total:
            verb = "Refreshing" if merge else "Landing"
            message = f"{verb} historical prices… 0/{total} symbols."
        else:
            message = None
        _patch_running_progress(
            phase="land",
            done=done,
            total=total,
            include_train=include_train,
            message=message,
        )
    code = await proc.wait()
    return code or 0, "".join(chunks)


async def _run_batch_train() -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        str(_python()),
        "-m",
        "app.main",
        "--lake-root",
        str(_LAKE),
        cwd=str(_TRAIN),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        env={**os.environ, "LAKE_ROOT": str(_LAKE)},
    )
    stdout, _ = await proc.communicate()
    return proc.returncode or 0, (stdout or b"").decode("utf-8", errors="replace")


def _parse_done_line(text: str) -> dict[str, Any]:
    """Pull the summary from batch_ingest logs."""
    symbols = None
    requested = None
    rows = None
    manifest = None
    skipped_current = None
    session_target = None
    for line in text.splitlines():
        if "Done." not in line:
            continue
        try:
            part = line.split("Done.", 1)[1].strip()
            left, _, right = part.partition(" symbols, ")
            frac = left.strip()
            if "/" in frac:
                landed_s, _, requested_s = frac.partition("/")
                symbols = int(landed_s.strip())
                requested = int(requested_s.strip())
            else:
                symbols = int(frac)
            # Preferred: "N rows, skipped_current=M, session_target=YYYY-MM-DD, manifest=..."
            if "skipped_current=" in right:
                mid, _, rest = right.partition(" rows, skipped_current=")
                rows = int(mid.strip())
                if "session_target=" in rest:
                    skip_bit, _, after_skip = rest.partition(", session_target=")
                    skipped_current = int(skip_bit.strip())
                    target_bit, _, manifest_bit = after_skip.partition(", manifest=")
                    session_target = target_bit.strip() or None
                    manifest = manifest_bit.strip() or None
                else:
                    skip_bit, _, manifest_bit = rest.partition(", manifest=")
                    skipped_current = int(skip_bit.strip())
                    manifest = manifest_bit.strip() or None
            else:
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
            "skipped_current": None,
            "session_target": None,
            "up_to_date": False,
        }
    up_to_date = bool(
        skipped_current is not None
        and rows == 0
        and requested is not None
        and skipped_current >= requested
        and symbols == 0
    )
    if up_to_date:
        through = f" through {session_target}" if session_target else ""
        message = (
            f"Lake already current{through} ({skipped_current} symbols); "
            "no Yahoo updates needed. Today's session lands after 4:00 PM Eastern "
            "(live Kafka bars do not write the lake)."
        )
    else:
        message = f"Landed {symbols} S&P symbols ({rows} daily rows) into the local lake."
    return {
        "message": message,
        "symbols_landed": symbols,
        "rows_landed": rows,
        "manifest": manifest,
        "skipped_current": skipped_current,
        "session_target": session_target,
        "up_to_date": up_to_date,
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
