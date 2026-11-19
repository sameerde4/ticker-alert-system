"""Fit Isolation Forest on curated features and write the local registry."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest

from .config import (
    DEFAULT_CONTAMINATION,
    DEFAULT_N_ESTIMATORS,
    DEFAULT_RANDOM_STATE,
    FEATURE_NAMES,
    MODEL_ID,
    VOLUME_ZSCORE_WINDOW,
    curated_features_dir,
)
from .features import feature_matrix
from .registry import save_registry, score_matrix

log = logging.getLogger(__name__)


def read_curated_features(lake_root: Path) -> pd.DataFrame:
    folder = curated_features_dir(lake_root)
    files = sorted(folder.glob("part-*.parquet"))
    if not files:
        raise FileNotFoundError(
            f"No curated features under {folder}. Run curate first (python -m app.main)."
        )
    return pd.concat([pd.read_parquet(path) for path in files], ignore_index=True)


def pick_score_cutoff(scores: np.ndarray, contamination: float) -> float:
    """Cutoff from replaying training scores: ~contamination fraction are anomalies.

    Sessions with decision_function <= cutoff are treated as anomalous.
    """
    if scores.size == 0:
        raise ValueError("Cannot pick a cutoff with no training scores.")
    pct = max(0.0, min(50.0, float(contamination) * 100.0))
    return float(np.percentile(scores, pct))


def fit_isolation_forest(
    features: pd.DataFrame,
    *,
    contamination: float = DEFAULT_CONTAMINATION,
    n_estimators: int = DEFAULT_N_ESTIMATORS,
    random_state: int = DEFAULT_RANDOM_STATE,
) -> tuple[IsolationForest, dict[str, Any]]:
    if features.empty:
        raise ValueError("Curated feature table is empty; land more raw history first.")
    matrix = feature_matrix(features)
    if matrix.shape[0] < 50:
        raise ValueError(
            f"Need at least 50 feature rows to fit the forest (got {matrix.shape[0]})."
        )

    model = IsolationForest(
        n_estimators=n_estimators,
        contamination=contamination,
        random_state=random_state,
        n_jobs=-1,
    )
    model.fit(matrix)
    scores = score_matrix(model, matrix)
    cutoff = pick_score_cutoff(scores, contamination)
    predicted = (scores <= cutoff).sum()
    meta = {
        "model_id": MODEL_ID,
        "algorithm": "IsolationForest",
        "library": "scikit-learn",
        "feature_names": list(FEATURE_NAMES),
        "volume_zscore_window": VOLUME_ZSCORE_WINDOW,
        "contamination": contamination,
        "n_estimators": n_estimators,
        "random_state": random_state,
        "score_cutoff": cutoff,
        "score_meaning": (
            "sklearn IsolationForest.decision_function; "
            "higher is more normal; score <= score_cutoff is anomalous"
        ),
        "trained_at": datetime.now(UTC).isoformat(),
        "n_rows": int(matrix.shape[0]),
        "n_symbols": int(features["symbol"].nunique()),
        "anomaly_rows_at_cutoff": int(predicted),
        "score_min": float(scores.min()),
        "score_max": float(scores.max()),
        "score_mean": float(scores.mean()),
    }
    return model, meta


def train_and_register(
    lake_root: Path,
    *,
    contamination: float = DEFAULT_CONTAMINATION,
    n_estimators: int = DEFAULT_N_ESTIMATORS,
    random_state: int = DEFAULT_RANDOM_STATE,
) -> dict[str, Any]:
    features = read_curated_features(lake_root)
    model, meta = fit_isolation_forest(
        features,
        contamination=contamination,
        n_estimators=n_estimators,
        random_state=random_state,
    )
    meta["curated_path"] = str(curated_features_dir(lake_root) / "part-000.parquet")
    paths = save_registry(lake_root, model=model, meta=meta)
    log.info(
        "Registered %s on %s rows (%s symbols); cutoff=%.6f → %s",
        MODEL_ID,
        meta["n_rows"],
        meta["n_symbols"],
        meta["score_cutoff"],
        paths["dir"],
    )
    return {
        "meta": meta,
        "registry_dir": str(paths["dir"]),
        "model_path": str(paths["model"]),
        "meta_path": str(paths["meta"]),
    }
