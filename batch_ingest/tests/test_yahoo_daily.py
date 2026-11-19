from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd

from app.yahoo_daily import bars_frame, fetch_daily_bars, window_for_days


def test_window_for_days_is_inclusive():
    start, end = window_for_days(365, end=date(2026, 11, 18))
    assert end == date(2026, 11, 18)
    assert start == date(2025, 11, 19)


def test_window_rejects_bad_days():
    try:
        window_for_days(0)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_fetch_daily_bars_normalizes_yahoo_history():
    idx = pd.to_datetime(["2026-11-17", "2026-11-18"])
    frame = pd.DataFrame(
        {
            "Open": [100.0, 101.0],
            "High": [102.0, 103.0],
            "Low": [99.0, 100.0],
            "Close": [101.0, 102.5],
            "Volume": [1_000_000, 1_100_000],
        },
        index=idx,
    )
    ticker = MagicMock()
    ticker.history.return_value = frame
    with patch("yfinance.Ticker", return_value=ticker):
        rows = fetch_daily_bars("aapl", start=date(2026, 11, 1), end=date(2026, 11, 18))
    assert len(rows) == 2
    assert rows[0]["symbol"] == "AAPL"
    assert rows[0]["dt"] == date(2026, 11, 17)
    assert rows[1]["close"] == 102.5
    assert rows[0]["source"] == "yahoo"
    ticker.history.assert_called_once()
    kwargs = ticker.history.call_args.kwargs
    assert kwargs["start"] == "2026-11-01"
    assert kwargs["end"] == "2026-11-19"
    assert kwargs["interval"] == "1d"


def test_bars_frame_column_order():
    frame = bars_frame(
        [
            {
                "symbol": "MSFT",
                "dt": date(2026, 11, 18),
                "open": 1,
                "high": 2,
                "low": 0.5,
                "close": 1.5,
                "volume": 10,
                "source": "yahoo",
                "grain": "daily",
            }
        ]
    )
    assert list(frame.columns) == [
        "symbol",
        "dt",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "source",
        "grain",
    ]
