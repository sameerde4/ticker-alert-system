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


def write_symbol_parquet(lake_root: Path, symbol: str, rows: list[dict[str, Any]]) -> Path | None:
    """Replace one symbol's raw daily file. Returns the path, or None when empty."""
    frame = bars_frame(rows)
    if frame.empty:
        return None
    folder = raw_daily_dir(lake_root, symbol)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "part-000.parquet"
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
        "start": start.isoformat(),
        "end": end.isoformat(),
        "symbols_requested": len(symbols_requested),
        "symbols_landed": len(ok),
        "rows_landed": sum(int(row.get("rows") or 0) for row in results),
        "results": results,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path
