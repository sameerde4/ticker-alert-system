"""Write raw daily bars into the lake raw zone."""

from __future__ import annotations

import json
import logging
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from .yahoo_daily import bars_frame

log = logging.getLogger(__name__)


def raw_daily_dir(lake_root: Path, symbol: str) -> Path:
    """Hive-style path: raw/prices/daily/symbol=AAPL/"""
    return lake_root / "raw" / "prices" / "daily" / f"symbol={symbol.upper()}"


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
) -> Path:
    """Record what this land run pulled. Lives under raw/_runs/ (not symbol partitions)."""
    folder = lake_root / "raw" / "_runs"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{run_id}.json"
    ok = [row for row in results if row.get("rows", 0) > 0]
    payload = {
        "run_id": run_id,
        "landed_at": datetime.now(UTC).isoformat(),
        "source": "yahoo",
        "grain": "daily",
        "mode": "incremental_merge" if merge else "full_replace",
        "merge": bool(merge),
        "start": start.isoformat(),
        "end": end.isoformat(),
        "symbols_requested": len(symbols_requested),
        "symbols_landed": len(ok),
        "rows_landed": sum(int(row.get("rows") or 0) for row in results),
        "results": results,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path
