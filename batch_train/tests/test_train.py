from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from app.config import FEATURE_NAMES
from app.curate import curate_session_features
from app.features import feature_matrix, session_feature_frame
from app.registry import is_anomalous, load_registry, score_matrix
from app.train import fit_isolation_forest, pick_score_cutoff, train_and_register


def _write_raw(lake: Path, symbol: str, n: int = 40) -> None:
    rows = []
    price = 100.0
    start = date(2025, 1, 2)
    for i in range(n):
        volume = 50_000_000 if i == n - 2 else 1_000_000 + i * 1000
        open_px = price
        close_px = price * (1.0 + (0.04 if i == n - 2 else 0.002 * ((-1) ** i)))
        rows.append(
            {
                "symbol": symbol,
                "dt": start + timedelta(days=i),
                "open": open_px,
                "high": max(open_px, close_px) + 1,
                "low": min(open_px, close_px) - 1,
                "close": close_px,
                "volume": volume,
                "source": "yahoo",
                "grain": "daily",
            }
        )
        price = close_px
    folder = lake / "raw" / "prices" / "daily" / f"symbol={symbol}"
    folder.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(folder / "part-000.parquet", index=False)


def test_pick_cutoff_matches_contamination_percentile():
    scores = np.linspace(-1.0, 1.0, 101)
    cutoff = pick_score_cutoff(scores, 0.02)
    assert abs(cutoff - np.percentile(scores, 2.0)) < 1e-12


def test_curate_and_train_writes_registry(tmp_path):
    lake = Path(tmp_path)
    _write_raw(lake, "AAPL", n=60)
    _write_raw(lake, "MSFT", n=60)

    curated = curate_session_features(lake)
    assert curated["feature_rows"] > 50
    assert (lake / "curated" / "features" / "session" / "part-000.parquet").is_file()

    result = train_and_register(lake, contamination=0.05, n_estimators=50, random_state=0)
    meta = result["meta"]
    assert meta["feature_names"] == list(FEATURE_NAMES)
    assert meta["n_rows"] == curated["feature_rows"]
    assert "score_cutoff" in meta

    model, loaded = load_registry(lake)
    assert loaded["score_cutoff"] == meta["score_cutoff"]
    features = session_feature_frame(
        pd.concat(
            [
                pd.read_parquet(path)
                for path in (lake / "raw" / "prices" / "daily").glob("symbol=*/part-000.parquet")
            ],
            ignore_index=True,
        )
    )
    scores = score_matrix(model, feature_matrix(features))
    assert scores.shape[0] == len(features)
    assert is_anomalous(meta["score_cutoff"], meta["score_cutoff"]) is True
    assert is_anomalous(meta["score_cutoff"] + 1.0, meta["score_cutoff"]) is False


def test_fit_rejects_tiny_tables():
    frame = pd.DataFrame(
        {
            "symbol": ["AAPL"] * 10,
            "dt": [date(2026, 1, i + 1) for i in range(10)],
            "gap_return": [0.01] * 10,
            "session_return": [0.01] * 10,
            "close_return": [0.02] * 10,
            "volume_zscore": [0.0] * 10,
        }
    )
    try:
        fit_isolation_forest(frame)
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "50" in str(exc)
