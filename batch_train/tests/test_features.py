from datetime import date

import pandas as pd

from app.features import feature_matrix, session_feature_frame, vector_from_session


def _bars(n: int = 25) -> pd.DataFrame:
    rows = []
    price = 100.0
    for i in range(n):
        open_px = price
        close_px = price * (1.01 if i % 2 == 0 else 0.99)
        rows.append(
            {
                "symbol": "AAPL",
                "dt": date(2026, 1, 1 + i),
                "open": open_px,
                "high": max(open_px, close_px) + 1,
                "low": min(open_px, close_px) - 1,
                "close": close_px,
                "volume": 1_000_000 + i * 10_000,
            }
        )
        price = close_px
    return pd.DataFrame(rows)


def test_session_features_drop_warm_up_and_match_formulas():
    bars = _bars(25)
    features = session_feature_frame(bars)
    # 25 bars → first complete volume-z row at index 20 → 5 feature rows
    assert len(features) == 5
    assert list(features.columns) == [
        "symbol",
        "dt",
        "gap_return",
        "session_return",
        "close_return",
        "volume_zscore",
    ]
    row = features.iloc[0]
    prior = bars.iloc[19]
    cur = bars.iloc[20]
    assert abs(row.gap_return - (cur.open - prior.close) / prior.close) < 1e-12
    assert abs(row.session_return - (cur.close - cur.open) / cur.open) < 1e-12
    assert abs(row.close_return - (cur.close - prior.close) / prior.close) < 1e-12


def test_feature_matrix_order():
    features = session_feature_frame(_bars(30))
    matrix = feature_matrix(features)
    assert matrix.shape[1] == 4
    assert matrix.shape[0] == len(features)


def test_vector_from_session_needs_twenty_priors():
    assert vector_from_session(
        open_px=101,
        close_px=102,
        prior_close=100,
        volume=1_000_000,
        prior_volumes=[1_000] * 19,
    ) is None
    priors = [1_000_000 + i * 5_000 for i in range(20)]
    vector = vector_from_session(
        open_px=101,
        close_px=102,
        prior_close=100,
        volume=1_200_000,
        prior_volumes=priors,
    )
    assert vector is not None
    assert abs(vector["gap_return"] - 0.01) < 1e-12
    assert abs(vector["session_return"] - (102 - 101) / 101) < 1e-12
    assert abs(vector["close_return"] - 0.02) < 1e-12
    assert isinstance(vector["volume_zscore"], float)
