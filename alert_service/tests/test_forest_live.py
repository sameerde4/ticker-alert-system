import json
from datetime import UTC, date, datetime
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import IsolationForest

from app.forest_live import (
    FEATURE_NAMES,
    ForestScore,
    LiveForestScorer,
    history_from_daily_rows,
    history_from_lake,
    vector_from_session,
)
from app.live_alerts import forest_price_draft_from_session, should_write_live_price
from app.live_session import SessionBook, SessionState


def test_vector_from_session_matches_batch_contract():
    priors = [1_000_000 + i * 10_000 for i in range(20)]
    vector = vector_from_session(
        open_px=101,
        close_px=104,
        prior_close=100,
        volume=1_500_000,
        prior_volumes=priors,
    )
    assert vector is not None
    assert abs(vector["gap_return"] - 0.01) < 1e-12
    assert abs(vector["session_return"] - 3 / 101) < 1e-12
    assert abs(vector["close_return"] - 0.04) < 1e-12
    mean = float(np.mean(priors))
    std = float(np.std(priors, ddof=0))
    assert abs(vector["volume_zscore"] - (1_500_000 - mean) / std) < 1e-9


def test_vector_rejects_thin_history_or_zero_volume_std():
    assert (
        vector_from_session(
            open_px=100,
            close_px=101,
            prior_close=99,
            volume=1_000_000,
            prior_volumes=[1_000_000] * 19,
        )
        is None
    )
    assert (
        vector_from_session(
            open_px=100,
            close_px=101,
            prior_close=99,
            volume=1_000_000,
            prior_volumes=[500_000] * 20,
        )
        is None
    )


def test_history_from_daily_rows_needs_twenty_priors():
    rows = [
        {"dt": date(2026, 1, i + 1), "close": 100 + i, "volume": 1_000_000 + i}
        for i in range(19)
    ]
    assert history_from_daily_rows(rows, session_day=date(2026, 2, 1)) is None
    rows.append({"dt": date(2026, 1, 20), "close": 120.0, "volume": 2_000_000})
    hist = history_from_daily_rows(rows, session_day=date(2026, 2, 1))
    assert hist is not None
    assert hist.prior_close == 120.0
    assert len(hist.prior_volumes) == 20


def test_history_excludes_session_day_and_later():
    rows = [
        {"dt": date(2026, 1, i + 1), "close": 100.0 + i, "volume": 1_000_000.0 + i}
        for i in range(22)
    ]
    # Include today's incomplete bar — must not become prior_close.
    rows.append({"dt": date(2026, 1, 23), "close": 999.0, "volume": 9_999_999.0})
    hist = history_from_daily_rows(rows, session_day=date(2026, 1, 23))
    assert hist is not None
    assert hist.prior_close == 121.0  # 100 + 21 from day 22
    assert 9_999_999.0 not in hist.prior_volumes


def test_history_from_lake_reads_parquet(tmp_path: Path):
    import pandas as pd

    symbol = "AAPL"
    folder = tmp_path / "raw" / "prices" / "daily" / f"symbol={symbol}"
    folder.mkdir(parents=True)
    frame = pd.DataFrame(
        [
            {"dt": date(2026, 1, i + 1), "close": 100.0 + i, "volume": 1_000_000.0 + i * 1000}
            for i in range(25)
        ]
    )
    frame.to_parquet(folder / "part-000.parquet", index=False)
    hist = history_from_lake(tmp_path, symbol, session_day=date(2026, 2, 1))
    assert hist is not None
    assert len(hist.prior_volumes) == 20
    assert hist.prior_close == 124.0


def test_history_from_lake_missing_file(tmp_path: Path):
    assert history_from_lake(tmp_path, "MSFT", session_day=date(2026, 2, 1)) is None


def test_session_book_accumulates_volume():
    book = SessionBook()
    book.apply(
        {
            "symbol": "AAPL",
            "ts": "2026-11-18T14:30:00Z",
            "open": 100.0,
            "close": 101.0,
            "volume": 1000,
        }
    )
    second = book.apply(
        {
            "symbol": "AAPL",
            "ts": "2026-11-18T15:00:00Z",
            "open": 101.0,
            "close": 102.0,
            "volume": 500,
        }
    )
    assert second is not None
    assert second.volume == 1500


def test_session_book_resets_volume_on_new_day():
    book = SessionBook()
    book.apply(
        {
            "symbol": "AAPL",
            "ts": "2026-11-17T15:00:00Z",
            "open": 90.0,
            "close": 91.0,
            "volume": 5_000,
        }
    )
    nxt = book.apply(
        {
            "symbol": "AAPL",
            "ts": "2026-11-18T14:30:00Z",
            "open": 100.0,
            "close": 101.0,
            "volume": 100,
        }
    )
    assert nxt is not None
    assert nxt.volume == 100


def _write_tiny_registry(lake_root: Path, *, contamination: float = 0.1) -> None:
    folder = lake_root / "registry" / "isolation_forest" / "current"
    folder.mkdir(parents=True)
    rng = np.random.default_rng(0)
    normal = rng.normal(loc=0.0, scale=0.01, size=(200, 4))
    model = IsolationForest(
        n_estimators=50,
        contamination=contamination,
        random_state=0,
    )
    model.fit(normal)
    joblib.dump(model, folder / "model.joblib")
    scores = model.decision_function(normal)
    cutoff = float(np.percentile(scores, contamination * 100))
    (folder / "meta.json").write_text(
        json.dumps(
            {
                "model_id": "isolation_forest_test",
                "score_cutoff": cutoff,
                "feature_names": list(FEATURE_NAMES),
            }
        ),
        encoding="utf-8",
    )


def test_live_forest_scorer_loads_registry_and_scores(tmp_path: Path):
    _write_tiny_registry(tmp_path)
    scorer = LiveForestScorer(tmp_path)
    assert scorer.enabled is True
    priors = [1_000_000 + i * 5_000 for i in range(20)]
    normal = scorer.score_session(
        open_px=100.5,
        last_px=100.6,
        prior_close=100.0,
        session_volume=1_050_000,
        prior_volumes=priors,
    )
    assert normal is not None
    assert set(normal.features) == set(FEATURE_NAMES)
    assert isinstance(normal.forest_score, float)
    weird = scorer.score_session(
        open_px=130.0,
        last_px=70.0,
        prior_close=100.0,
        session_volume=8_000_000,
        prior_volumes=priors,
    )
    assert weird is not None
    assert weird.anomalous is True or weird.forest_score < normal.forest_score


def test_live_forest_scorer_disabled_without_registry(tmp_path: Path):
    scorer = LiveForestScorer(tmp_path)
    assert scorer.enabled is False
    assert (
        scorer.score_session(
            open_px=100,
            last_px=101,
            prior_close=99,
            session_volume=1_000_000,
            prior_volumes=[1_000_000] * 20,
        )
        is None
    )


def test_forest_price_draft_only_when_anomalous():
    state = SessionState(
        symbol="AAPL",
        session_day=date(2026, 11, 18),
        open=100.0,
        last=101.0,
        last_ts=datetime(2026, 11, 18, 16, 0, tzinfo=UTC),
        volume=1_000_000,
    )
    normal = ForestScore(
        features={
            "gap_return": 0.01,
            "session_return": 0.01,
            "close_return": 0.02,
            "volume_zscore": 0.1,
        },
        forest_score=0.2,
        score_cutoff=0.0,
        anomalous=False,
        model_id="isolation_forest_v1",
    )
    assert (
        forest_price_draft_from_session(
            state, normal, price_move_threshold=0.03, sentiment_threshold=25
        )
        is None
    )
    weird = ForestScore(
        features={
            "gap_return": 0.05,
            "session_return": -0.04,
            "close_return": 0.01,
            "volume_zscore": 4.0,
        },
        forest_score=-0.1,
        score_cutoff=0.0,
        anomalous=True,
        model_id="isolation_forest_v1",
    )
    draft = forest_price_draft_from_session(
        state,
        weird,
        price_move_threshold=0.03,
        sentiment_threshold=25,
        now=state.last_ts,
    )
    assert draft is not None
    assert draft.kind == "price"
    assert "Isolation Forest" in draft.summary
    assert draft.sections["forest"]["anomalous"] is True
    assert draft.sections["forest"]["model_id"] == "isolation_forest_v1"


def test_should_write_live_price_still_blocks_news_kinds():
    assert should_write_live_price(None)
    assert should_write_live_price({"kind": "price", "sections": {"forest": {}}})
    assert not should_write_live_price({"kind": "news"})
    assert not should_write_live_price({"kind": "news_price"})
