"""Paths and training defaults for the local lake batch job."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LAKE_ROOT = REPO_ROOT / "data" / "lake"

FEATURE_NAMES = (
    "gap_return",
    "session_return",
    "close_return",
    "volume_zscore",
)

VOLUME_ZSCORE_WINDOW = 20
DEFAULT_CONTAMINATION = 0.02
DEFAULT_N_ESTIMATORS = 200
DEFAULT_RANDOM_STATE = 42
MODEL_ID = "isolation_forest_v1"


def raw_prices_dir(lake_root: Path) -> Path:
    return Path(lake_root) / "raw" / "prices" / "daily"


def curated_features_dir(lake_root: Path) -> Path:
    return Path(lake_root) / "curated" / "features" / "session"


def registry_dir(lake_root: Path) -> Path:
    return Path(lake_root) / "registry" / "isolation_forest" / "current"
