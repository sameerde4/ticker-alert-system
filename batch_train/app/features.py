"""Price/volume session features shared by batch training and (later) live scoring.

Same four fields the class diagrams name for Isolation Forest:
gap return, session return, close return, volume z-score vs the prior 20 sessions.
No FinBERT / news inputs.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .config import FEATURE_NAMES, VOLUME_ZSCORE_WINDOW


def session_feature_frame(
    bars: pd.DataFrame,
    *,
    volume_window: int = VOLUME_ZSCORE_WINDOW,
) -> pd.DataFrame:
    """Build one feature row per symbol per session from daily OHLCV.

    ``bars`` needs columns: symbol, dt, open, high, low, close, volume.
    Rows are sorted by symbol then dt. The first ``volume_window`` sessions
    per symbol (and the first session for returns) are dropped as incomplete.
    """
    if bars is None or bars.empty:
        return pd.DataFrame(columns=["symbol", "dt", *FEATURE_NAMES])

    frame = bars.copy()
    required = {"symbol", "dt", "open", "close", "volume"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"Bars are missing columns: {sorted(missing)}")

    frame["symbol"] = frame["symbol"].astype(str).str.upper()
    frame["dt"] = pd.to_datetime(frame["dt"]).dt.date
    frame = frame.sort_values(["symbol", "dt"], kind="mergesort").reset_index(drop=True)

    parts: list[pd.DataFrame] = []
    for symbol, group in frame.groupby("symbol", sort=False):
        part = _features_for_symbol(group, volume_window=volume_window)
        if not part.empty:
            parts.append(part)

    if not parts:
        return pd.DataFrame(columns=["symbol", "dt", *FEATURE_NAMES])

    out = pd.concat(parts, ignore_index=True)
    out = out.sort_values(["symbol", "dt"], kind="mergesort").reset_index(drop=True)
    return out


def feature_matrix(frame: pd.DataFrame) -> np.ndarray:
    """Numeric matrix in FEATURE_NAMES order for sklearn."""
    if frame.empty:
        return np.empty((0, len(FEATURE_NAMES)), dtype=float)
    return frame.loc[:, list(FEATURE_NAMES)].to_numpy(dtype=float)


def vector_from_session(
    *,
    open_px: float,
    close_px: float,
    prior_close: float,
    volume: float,
    prior_volumes: list[float],
    volume_window: int = VOLUME_ZSCORE_WINDOW,
) -> dict[str, float] | None:
    """One live/batch feature vector from a finished (or in-progress) session.

    ``prior_volumes`` are the previous sessions' volumes, oldest first.
    Needs at least ``volume_window`` priors for a volume z-score.
    """
    if prior_close <= 0 or open_px <= 0 or close_px <= 0:
        return None
    if len(prior_volumes) < volume_window:
        return None
    window = np.asarray(prior_volumes[-volume_window:], dtype=float)
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


def _features_for_symbol(group: pd.DataFrame, *, volume_window: int) -> pd.DataFrame:
    g = group.reset_index(drop=True)
    prior_close = g["close"].shift(1)
    open_px = g["open"].astype(float)
    close_px = g["close"].astype(float)
    volume = g["volume"].astype(float)

    gap = (open_px - prior_close) / prior_close
    session = (close_px - open_px) / open_px
    close_ret = (close_px - prior_close) / prior_close

    # Prior 20 sessions only — shift so today's volume is not in the baseline.
    prior_vol = volume.shift(1)
    vol_mean = prior_vol.rolling(window=volume_window, min_periods=volume_window).mean()
    vol_std = prior_vol.rolling(window=volume_window, min_periods=volume_window).std(ddof=0)
    vol_z = (volume - vol_mean) / vol_std

    out = pd.DataFrame(
        {
            "symbol": g["symbol"].to_numpy(),
            "dt": g["dt"].to_numpy(),
            "gap_return": gap.to_numpy(),
            "session_return": session.to_numpy(),
            "close_return": close_ret.to_numpy(),
            "volume_zscore": vol_z.to_numpy(),
        }
    )
    return out.replace([np.inf, -np.inf], np.nan).dropna(subset=list(FEATURE_NAMES)).reset_index(drop=True)


def rows_as_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for row in frame.itertuples(index=False):
        records.append(
            {
                "symbol": row.symbol,
                "dt": row.dt.isoformat() if hasattr(row.dt, "isoformat") else str(row.dt),
                "gap_return": float(row.gap_return),
                "session_return": float(row.session_return),
                "close_return": float(row.close_return),
                "volume_zscore": float(row.volume_zscore),
            }
        )
    return records
