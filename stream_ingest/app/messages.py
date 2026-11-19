"""Normalize Alpaca bar messages into the Kafka payload."""

from __future__ import annotations

from typing import Any

from .symbols import from_alpaca_symbol, normalize_symbol


def bar_from_alpaca(raw: dict[str, Any], *, feed: str, source: str) -> dict[str, Any] | None:
    """Turn an Alpaca minute-bar message into a flat Kafka JSON object."""
    if raw.get("T") not in ("b", "bar"):
        return None
    symbol = from_alpaca_symbol(str(raw.get("S") or ""))
    if not symbol:
        return None
    return {
        "schema": "prices.raw.bars.v1",
        "symbol": symbol,
        "ts": raw.get("t"),
        "open": raw.get("o"),
        "high": raw.get("h"),
        "low": raw.get("l"),
        "close": raw.get("c"),
        "volume": raw.get("v"),
        "trade_count": raw.get("n"),
        "vwap": raw.get("vw"),
        "feed": feed,
        "source": source,
    }


def bar_from_rest(
    symbol: str,
    raw: dict[str, Any],
    *,
    feed: str,
) -> dict[str, Any] | None:
    """Turn a REST historical bar into the same Kafka JSON object."""
    if not symbol or not raw:
        return None
    return {
        "schema": "prices.raw.bars.v1",
        "symbol": normalize_symbol(symbol),
        "ts": raw.get("t"),
        "open": raw.get("o"),
        "high": raw.get("h"),
        "low": raw.get("l"),
        "close": raw.get("c"),
        "volume": raw.get("v"),
        "trade_count": raw.get("n"),
        "vwap": raw.get("vw"),
        "feed": feed,
        "source": "alpaca_rest",
    }
