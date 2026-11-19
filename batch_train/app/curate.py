"""Raw lake Parquet → curated session feature Parquet (Spark ELT role, local)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pandas as pd

from .config import curated_features_dir, raw_prices_dir
from .features import session_feature_frame

log = logging.getLogger(__name__)


def list_raw_symbol_files(lake_root: Path) -> list[Path]:
    root = raw_prices_dir(lake_root)
    if not root.is_dir():
        return []
    return sorted(root.glob("symbol=*/part-*.parquet"))


def read_raw_bars(lake_root: Path, *, max_symbols: int | None = None) -> pd.DataFrame:
    files = list_raw_symbol_files(lake_root)
    if max_symbols is not None:
        files = files[: max(0, max_symbols)]
    if not files:
        return pd.DataFrame(columns=["symbol", "dt", "open", "high", "low", "close", "volume"])

    frames: list[pd.DataFrame] = []
    for path in files:
        frame = pd.read_parquet(path)
        if frame.empty:
            continue
        frames.append(frame)
    if not frames:
        return pd.DataFrame(columns=["symbol", "dt", "open", "high", "low", "close", "volume"])
    return pd.concat(frames, ignore_index=True)


def write_curated_features(lake_root: Path, features: pd.DataFrame) -> Path:
    folder = curated_features_dir(lake_root)
    folder.mkdir(parents=True, exist_ok=True)
    # Clear prior parts so a re-run does not mix schemas.
    for old in folder.glob("part-*.parquet"):
        old.unlink()
    path = folder / "part-000.parquet"
    out = features.copy()
    if not out.empty:
        out["dt"] = pd.to_datetime(out["dt"]).dt.strftime("%Y-%m-%d")
    out.to_parquet(path, index=False, engine="pyarrow")
    return path


def curate_session_features(
    lake_root: Path,
    *,
    max_symbols: int | None = None,
) -> dict[str, Any]:
    """Read raw daily prices, write curated session features, return a summary."""
    bars = read_raw_bars(lake_root, max_symbols=max_symbols)
    symbols = int(bars["symbol"].nunique()) if not bars.empty else 0
    features = session_feature_frame(bars)
    path = write_curated_features(lake_root, features)
    summary = {
        "raw_symbols": symbols,
        "raw_rows": int(len(bars)),
        "feature_rows": int(len(features)),
        "feature_symbols": int(features["symbol"].nunique()) if not features.empty else 0,
        "curated_path": str(path),
    }
    log.info(
        "Curated %s feature rows from %s symbols (%s raw rows) → %s",
        summary["feature_rows"],
        summary["feature_symbols"],
        summary["raw_rows"],
        path,
    )
    return summary
