"""Write raw daily bars into the lake raw zone."""

from __future__ import annotations

import json
import logging
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .yahoo_daily import bars_frame

log = logging.getLogger(__name__)

_EASTERN = ZoneInfo("America/New_York")


def raw_daily_dir(lake_root: Path, symbol: str) -> Path:
    """Hive-style path: raw/prices/daily/symbol=AAPL/"""
    return lake_root / "raw" / "prices" / "daily" / f"symbol={symbol.upper()}"


def last_session_on_or_before(day: date) -> date:
    """Walk back past Sat/Sun to the prior weekday (approx last US equity session)."""
    cursor = day
    while cursor.weekday() >= 5:  # Saturday=5, Sunday=6
        cursor -= timedelta(days=1)
    return cursor


def expected_latest_session(now: datetime | None = None) -> date:
    """Last US equity session we expect Yahoo daily bars to include.

    Before the regular close (and on weekends), that is the prior weekday — so a
    4am refresh does not treat "today" as missing and re-hit Yahoo for every symbol.
    After 4:00 PM Eastern on a weekday, today's session is the target.
    """
    moment = (now or datetime.now(UTC)).astimezone(_EASTERN)
    day = moment.date()
    clock = moment.timetz().replace(tzinfo=None)
    if moment.weekday() < 5 and clock >= time(16, 0):
        return day
    cursor = day - timedelta(days=1)
    while cursor.weekday() >= 5:
        cursor -= timedelta(days=1)
    return cursor


def latest_daily_dt(lake_root: Path, symbol: str) -> date | None:
    """Newest ``dt`` already in the symbol's raw Parquet, if any."""
    import pandas as pd

    path = raw_daily_dir(lake_root, symbol) / "part-000.parquet"
    if not path.is_file():
        return None
    try:
        frame = pd.read_parquet(path, columns=["dt"])
    except Exception as exc:
        log.warning("Could not read latest dt from %s (%s)", path, exc)
        return None
    if frame is None or frame.empty or "dt" not in frame.columns:
        return None
    try:
        series = pd.to_datetime(frame["dt"], errors="coerce").dropna()
    except Exception:
        return None
    if series.empty:
        return None
    stamp = series.max()
    try:
        return stamp.date()
    except Exception:
        try:
            return date.fromisoformat(str(stamp)[:10])
        except ValueError:
            return None


def symbol_is_current(
    lake_root: Path,
    symbol: str,
    *,
    target: date,
) -> bool:
    """True when the lake already has bars through ``target`` (no Yahoo call needed)."""
    latest = latest_daily_dt(lake_root, symbol)
    return latest is not None and latest >= target


def merge_fetch_start(
    lake_root: Path,
    symbol: str,
    *,
    window_start: date,
    target: date | None = None,
    now: datetime | None = None,
) -> date | None:
    """For incremental refresh: next Yahoo start day, or ``None`` when already current.

    When the partition is current through the last expected session, skip Yahoo.
    Otherwise resume from the latest landed day (inclusive) so corrections can land,
    never earlier than ``window_start``.
    """
    if target is not None:
        session_target = last_session_on_or_before(target)
    else:
        session_target = expected_latest_session(now)
    latest = latest_daily_dt(lake_root, symbol)
    if latest is not None and latest >= session_target:
        return None
    if latest is None:
        return window_start
    return max(window_start, latest)


def write_symbol_parquet(
    lake_root: Path,
    symbol: str,
    rows: list[dict[str, Any]],
    *,
    merge: bool = False,
) -> Path | None:
    """Write one symbol's raw daily file.

    ``merge=False`` (full land) replaces the partition.
    ``merge=True`` (incremental refresh) unions by ``dt`` and keeps the newest row.
    """
    import pandas as pd

    frame = bars_frame(rows)
    folder = raw_daily_dir(lake_root, symbol)
    path = folder / "part-000.parquet"
    if frame.empty:
        if merge and path.is_file():
            return path
        return None
    folder.mkdir(parents=True, exist_ok=True)
    if merge and path.is_file():
        try:
            existing = pd.read_parquet(path)
        except Exception as exc:
            log.warning("Could not read %s for merge (%s); replacing", path, exc)
            existing = None
        if existing is not None and not existing.empty:
            existing = bars_frame(existing.to_dict("records"))
            frame = pd.concat([existing, frame], ignore_index=True)
            frame = frame.drop_duplicates(subset=["dt"], keep="last")
            frame = frame.sort_values("dt").reset_index(drop=True)
    frame.to_parquet(path, index=False, engine="pyarrow")
    return path


def write_run_manifest(
    lake_root: Path,
    *,
    run_id: str,
    start: date,
    end: date,
    symbols_requested: list[str],
    results: list[dict[str, Any]],
    merge: bool = False,
    skipped_current: int = 0,
    session_target: date | None = None,
) -> Path:
    """Record what this land run pulled. Lives under raw/_runs/ (not symbol partitions)."""
    folder = lake_root / "raw" / "_runs"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{run_id}.json"
    ok = [row for row in results if row.get("rows", 0) > 0]
    target = session_target or (expected_latest_session() if merge else last_session_on_or_before(end))
    payload = {
        "run_id": run_id,
        "landed_at": datetime.now(UTC).isoformat(),
        "source": "yahoo",
        "grain": "daily",
        "mode": "incremental_merge" if merge else "full_replace",
        "merge": bool(merge),
        "start": start.isoformat(),
        "end": end.isoformat(),
        "session_target": target.isoformat(),
        "symbols_requested": len(symbols_requested),
        "symbols_landed": len(ok),
        "rows_landed": sum(int(row.get("rows") or 0) for row in results),
        "skipped_current": int(skipped_current),
        "up_to_date": bool(merge and skipped_current == len(symbols_requested) and not ok),
        "results": results,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path
