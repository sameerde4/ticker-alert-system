"""Live Kafka path covers the S&P 500 universe, not only the watchlist chips."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

from app.live_consumer import LiveBarConsumer
from app.symbols import universe_symbols


def test_live_consumer_loads_sp500_universe_not_watchlist():
    pool = MagicMock()
    consumer = LiveBarConsumer(pool, forest=MagicMock(enabled=False))
    names = set(universe_symbols())
    assert len(consumer._universe) == len(names)
    assert "AAPL" in consumer._universe
    # Watchlist membership is not consulted for the live universe filter.
    assert not hasattr(consumer, "_watchlist") or not consumer.__dict__.get("_watchlist")


def test_live_consumer_ignores_bars_outside_the_sp500_universe():
    pool = MagicMock()
    consumer = LiveBarConsumer(pool, forest=MagicMock(enabled=False))
    consumer._universe = {"AAPL"}
    consumer.book.apply = MagicMock(return_value=None)

    async def _run():
        await consumer._handle_bar({"symbol": "NOTASP500", "open": 1, "close": 2})
        await consumer._handle_bar(
            {"symbol": "AAPL", "ts": "2026-11-19T15:00:00Z", "open": 100, "close": 101}
        )

    asyncio.run(_run())
    consumer.book.apply.assert_called_once()
    assert consumer.book.apply.call_args[0][0]["symbol"] == "AAPL"
