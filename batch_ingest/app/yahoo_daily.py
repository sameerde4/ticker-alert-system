"""Pull daily OHLCV from Yahoo Finance."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd


def window_for_days(days: int, *, end: date | None = None) -> tuple[date, date]:
    """Inclusive calendar window ending today (or ``end``)."""
    if isinstance(days, bool) or not isinstance(days, int) or days < 1 or days > 4000:
        raise ValueError("Days must be a whole number from 1 to 4000.")
    last = end or date.today()
    first = last - timedelta(days=days - 1)
    return first, last


def fetch_daily_bars(
    symbol: str,
    *,
    start: date,
    end: date,
) -> list[dict[str, Any]]:
    """Download one symbol's daily bars. ``end`` is inclusive on the calendar."""
    try:
        import yfinance as yf
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("yfinance is not installed. Install batch_ingest requirements.") from exc

    # yfinance end is exclusive; add one day so the last session can land.
    hist = yf.Ticker(symbol).history(
        start=start.isoformat(),
        end=(end + timedelta(days=1)).isoformat(),
        interval="1d",
        auto_adjust=False,
        actions=False,
    )
    if hist is None or getattr(hist, "empty", True):
        return []
    rows: list[dict[str, Any]] = []
    for idx, row in hist.iterrows():
        try:
            stamp = idx.to_pydatetime()
        except Exception:
            continue
        if getattr(stamp, "tzinfo", None) is not None:
            day = stamp.date()
        else:
            day = stamp.date() if isinstance(stamp, datetime) else date.fromisoformat(str(stamp)[:10])
        opened = _positive(row.get("Open"))
        high = _positive(row.get("High"))
        low = _positive(row.get("Low"))
        close = _positive(row.get("Close"))
        volume = _nonneg_int(row.get("Volume"))
        if opened is None or high is None or low is None or close is None:
            continue
        rows.append(
            {
                "symbol": symbol.upper(),
                "dt": day,
                "open": opened,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume if volume is not None else 0,
                "source": "yahoo",
                "grain": "daily",
            }
        )
    rows.sort(key=lambda item: item["dt"])
    return rows


def bars_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    """Normalize landed rows for Parquet."""
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    frame["dt"] = pd.to_datetime(frame["dt"]).dt.date
    frame["symbol"] = frame["symbol"].astype(str)
    for col in ("open", "high", "low", "close"):
        frame[col] = frame[col].astype("float64")
    frame["volume"] = frame["volume"].astype("int64")
    return frame[
        ["symbol", "dt", "open", "high", "low", "close", "volume", "source", "grain"]
    ]


def _positive(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number <= 0:
        return None
    return number


def _nonneg_int(value: Any) -> int | None:
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return None
    if number < 0:
        return None
    return number
