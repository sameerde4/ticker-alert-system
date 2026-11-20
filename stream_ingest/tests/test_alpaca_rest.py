from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from zoneinfo import ZoneInfo

import pytest

from app.alpaca_rest import AlpacaRestBarPoller, _session_backfill_window

_EASTERN = ZoneInfo("America/New_York")


def test_session_backfill_window_none_on_weekend():
    saturday = datetime(2026, 11, 21, 15, 0, tzinfo=UTC)
    assert _session_backfill_window(now=saturday) is None


def test_session_backfill_window_none_before_cash_open():
    # Friday 9:00 ET = 14:00 UTC
    pre_open = datetime(2026, 11, 20, 14, 0, tzinfo=UTC)
    assert _session_backfill_window(now=pre_open) is None


def test_session_backfill_window_during_rth():
    # Friday 12:30 ET = 17:30 UTC
    midday = datetime(2026, 11, 20, 17, 30, tzinfo=UTC)
    window = _session_backfill_window(now=midday)
    assert window is not None
    start, end = window
    assert start.astimezone(_EASTERN).hour == 9
    assert start.astimezone(_EASTERN).minute == 30
    assert end == midday - timedelta(minutes=16)


@pytest.mark.asyncio
async def test_session_backfill_publishes_ordered_bars(monkeypatch):
    published: list[dict] = []

    class _Pub:
        async def publish(self, bar):
            published.append(bar)

    poller = AlpacaRestBarPoller(
        data_url="https://data.example",
        key_id="k",
        secret_key="s",
        feed="delayed_sip",
        symbols=["AAPL", "MSFT"],
        publisher=_Pub(),
        poll_seconds=60,
    )

    async def fake_fetch(_client, symbols, *, start, end):
        assert "AAPL" in symbols
        return {
            "AAPL": [
                {"t": "2026-11-20T14:30:00Z", "o": 100.0, "h": 101.0, "l": 99.0, "c": 100.5, "v": 1000},
                {"t": "2026-11-20T14:31:00Z", "o": 100.5, "h": 101.0, "l": 100.0, "c": 100.8, "v": 800},
            ],
            "MSFT": [
                {"t": "2026-11-20T14:30:00Z", "o": 400.0, "h": 401.0, "l": 399.0, "c": 400.2, "v": 500},
            ],
        }

    monkeypatch.setattr(poller, "_fetch_bars", fake_fetch)
    monkeypatch.setattr(
        "app.alpaca_rest._session_backfill_window",
        lambda: (
            datetime(2026, 11, 20, 14, 30, tzinfo=UTC),
            datetime(2026, 11, 20, 17, 0, tzinfo=UTC),
        ),
    )

    await poller._backfill_session(MagicMock())
    assert len(published) == 3
    assert [row["symbol"] for row in published] == ["AAPL", "AAPL", "MSFT"]
    assert published[0]["ts"] < published[1]["ts"]
    assert poller._seen["AAPL"] == "2026-11-20T14:31:00Z"
    assert poller._session_backfilled is False  # flag set by run(), not backfill alone
