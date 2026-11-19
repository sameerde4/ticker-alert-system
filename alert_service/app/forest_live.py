"""Live Isolation Forest scoring (Flink role): same features as batch_train registry."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np

from .config import settings

log = logging.getLogger(__name__)

FEATURE_NAMES = (
    "gap_return",
    "session_return",
    "close_return",
    "volume_zscore",
)
VOLUME_ZSCORE_WINDOW = 20
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LAKE_ROOT = REPO_ROOT / "data" / "lake"


@dataclass(frozen=True)
class SymbolHistory:
    """Prior session context needed for a live feature vector."""

    prior_close: float
    prior_volumes: tuple[float, ...]  # oldest → newest, length VOLUME_ZSCORE_WINDOW


@dataclass(frozen=True)
class ForestScore:
    features: dict[str, float]
    forest_score: float
    score_cutoff: float
    anomalous: bool
    model_id: str


def vector_from_session(
    *,
    open_px: float,
    close_px: float,
    prior_close: float,
    volume: float,
    prior_volumes: list[float] | tuple[float, ...],
    volume_window: int = VOLUME_ZSCORE_WINDOW,
) -> dict[str, float] | None:
    """Match batch_train feature definitions for an in-progress session."""
    if prior_close <= 0 or open_px <= 0 or close_px <= 0:
        return None
    if len(prior_volumes) < volume_window:
        return None
    window = np.asarray(list(prior_volumes)[-volume_window:], dtype=float)
    mean = float(window.mean())
    std = float(window.std(ddof=0))
    if std <= 0:
        return None
    return {
        "gap_return": (open_px - prior_close) / prior_close,
        "session_return": (close_px - open_px) / open_px,
        "close_return": (close_px - prior_close) / prior_close,
        "volume_zscore": (float(volume) - mean) / std,
    }


class LiveForestScorer:
    """Load the lake registry once and score live session vectors."""

    def __init__(self, lake_root: Path | None = None):
        self.lake_root = Path(lake_root or getattr(settings, "lake_root", None) or DEFAULT_LAKE_ROOT)
        self.model: Any | None = None
        self.meta: dict[str, Any] = {}
        self.enabled = False
        self._load()

    def _load(self) -> None:
        folder = self.lake_root / "registry" / "isolation_forest" / "current"
        model_path = folder / "model.joblib"
        meta_path = folder / "meta.json"
        if not model_path.is_file() or not meta_path.is_file():
            log.warning(
                "Isolation Forest registry missing under %s — live forest scoring off. "
                "Run: cd batch_train && python -m app.main",
                folder,
            )
            self.enabled = False
            return
        try:
            import json

            import joblib

            self.model = joblib.load(model_path)
            self.meta = json.loads(meta_path.read_text(encoding="utf-8"))
            self.enabled = True
            log.info(
                "Loaded Isolation Forest %s cutoff=%.6f from %s",
                self.meta.get("model_id"),
                float(self.meta.get("score_cutoff") or 0),
                folder,
            )
        except Exception as exc:
            log.warning("Could not load Isolation Forest registry: %s", exc)
            self.model = None
            self.meta = {}
            self.enabled = False

    def reload(self) -> None:
        self._load()

    def score_session(
        self,
        *,
        open_px: float,
        last_px: float,
        prior_close: float,
        session_volume: float,
        prior_volumes: list[float] | tuple[float, ...],
    ) -> ForestScore | None:
        if not self.enabled or self.model is None:
            return None
        features = vector_from_session(
            open_px=open_px,
            close_px=last_px,
            prior_close=prior_close,
            volume=session_volume,
            prior_volumes=prior_volumes,
        )
        if features is None:
            return None
        matrix = np.asarray([[features[name] for name in FEATURE_NAMES]], dtype=float)
        forest_score = float(self.model.decision_function(matrix)[0])
        cutoff = float(self.meta.get("score_cutoff") or 0.0)
        return ForestScore(
            features=features,
            forest_score=forest_score,
            score_cutoff=cutoff,
            anomalous=forest_score <= cutoff,
            model_id=str(self.meta.get("model_id") or "isolation_forest"),
        )


def history_from_daily_rows(
    rows: list[dict[str, Any]],
    *,
    session_day: date,
    volume_window: int = VOLUME_ZSCORE_WINDOW,
) -> SymbolHistory | None:
    """Build prior_close + prior volumes from daily bars (exclude session_day)."""
    usable: list[dict[str, Any]] = []
    for row in rows:
        raw_dt = row.get("dt")
        if hasattr(raw_dt, "isoformat"):
            day = raw_dt if isinstance(raw_dt, date) else raw_dt.date()
        else:
            day = date.fromisoformat(str(raw_dt)[:10])
        if day >= session_day:
            continue
        try:
            close_px = float(row["close"])
            volume = float(row["volume"])
        except (KeyError, TypeError, ValueError):
            continue
        if close_px <= 0:
            continue
        usable.append({"dt": day, "close": close_px, "volume": volume})
    usable.sort(key=lambda item: item["dt"])
    if len(usable) < volume_window:
        return None
    window = usable[-volume_window:]
    return SymbolHistory(
        prior_close=float(window[-1]["close"]),
        prior_volumes=tuple(float(item["volume"]) for item in window),
    )


def history_from_lake(
    lake_root: Path,
    symbol: str,
    *,
    session_day: date,
    volume_window: int = VOLUME_ZSCORE_WINDOW,
) -> SymbolHistory | None:
    """Fallback prior context from raw lake Parquet when Postgres daily_bars are thin."""
    path = Path(lake_root) / "raw" / "prices" / "daily" / f"symbol={symbol.upper()}" / "part-000.parquet"
    if not path.is_file():
        return None
    try:
        import pandas as pd

        frame = pd.read_parquet(path)
    except Exception:
        return None
    if frame.empty:
        return None
    return history_from_daily_rows(frame.to_dict("records"), session_day=session_day, volume_window=volume_window)
