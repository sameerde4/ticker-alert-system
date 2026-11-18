"""Daily bar fetch from Yahoo Finance via yfinance."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any


def fetch_daily_bars(symbol: str, *, lookback_days: int, end_date: date | None = None) -> list[dict[str, Any]]:
    """Return normalized daily bars, oldest first. Empty when Yahoo has nothing usable."""
    try:
        import yfinance as yf
    except Exception as exc:  # pragma: no cover - environment without the dependency
        raise RuntimeError("yfinance is not installed. Install requirements first.") from exc

    end = end_date or date.today()
    start = end - timedelta(days=lookback_days)
    ticker = yf.Ticker(symbol)
    try:
        hist = ticker.history(
            start=start.isoformat(),
            end=(end + timedelta(days=1)).isoformat(),
            interval="1d",
            auto_adjust=False,
        )
    except Exception:
        return []
    if hist is None or getattr(hist, "empty", True):
        return []

    rows: list[dict[str, Any]] = []
    for idx, row in hist.iterrows():
        try:
            dt = idx.date()
        except Exception:
            continue
        if dt < start or dt > end:
            continue
        close = _positive(row.get("Close"))
        if close is None:
            continue
        rows.append(
            {
                "dt": dt,
                "open": _positive(row.get("Open")) or close,
                "high": _positive(row.get("High")) or close,
                "low": _positive(row.get("Low")) or close,
                "close": close,
                "volume": int(_positive(row.get("Volume")) or 0),
            }
        )
    rows.sort(key=lambda item: item["dt"])
    return rows


def fetch_sector(symbol: str) -> str | None:
    """GICS-style sector from Yahoo, such as Technology or Financial Services."""
    try:
        import yfinance as yf
    except Exception:  # pragma: no cover
        return None
    try:
        info = yf.Ticker(symbol).info or {}
    except Exception:
        return None
    sector = info.get("sector")
    if sector is None:
        return None
    text = str(sector).strip()
    return text or None


def yahoo_lists_symbol(symbol: str) -> bool:
    """True when Yahoo has a last price for this ticker."""
    try:
        import yfinance as yf
    except Exception:  # pragma: no cover
        return False
    try:
        price = yf.Ticker(symbol).fast_info["last_price"]
        number = float(price)
    except Exception:
        return False
    return number == number and number > 0


def _positive(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number <= 0:  # NaN or non-positive
        return None
    return number
