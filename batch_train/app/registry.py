"""Local model registry: fitted Isolation Forest, feature list, score cutoff."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import joblib
import numpy as np

from .config import FEATURE_NAMES, MODEL_ID, registry_dir


def registry_paths(lake_root: Path) -> dict[str, Path]:
    folder = registry_dir(lake_root)
    return {
        "dir": folder,
        "model": folder / "model.joblib",
        "meta": folder / "meta.json",
    }


def save_registry(
    lake_root: Path,
    *,
    model: Any,
    meta: dict[str, Any],
) -> dict[str, Path]:
    paths = registry_paths(lake_root)
    paths["dir"].mkdir(parents=True, exist_ok=True)
    joblib.dump(model, paths["model"])
    payload = dict(meta)
    payload.setdefault("model_id", MODEL_ID)
    payload.setdefault("feature_names", list(FEATURE_NAMES))
    payload["model_path"] = paths["model"].name
    paths["meta"].write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return paths


def load_registry(lake_root: Path) -> tuple[Any, dict[str, Any]]:
    paths = registry_paths(lake_root)
    if not paths["model"].is_file() or not paths["meta"].is_file():
        raise FileNotFoundError(
            f"No Isolation Forest registry under {paths['dir']}. Run: python -m app.main"
        )
    model = joblib.load(paths["model"])
    meta = json.loads(paths["meta"].read_text(encoding="utf-8"))
    return model, meta


def score_matrix(model: Any, matrix: np.ndarray) -> np.ndarray:
    """sklearn decision_function: higher is more normal."""
    if matrix.size == 0:
        return np.array([], dtype=float)
    return np.asarray(model.decision_function(matrix), dtype=float)


def is_anomalous(score: float, cutoff: float) -> bool:
    """True when the session score is at or below the registered cutoff."""
    return float(score) <= float(cutoff)
