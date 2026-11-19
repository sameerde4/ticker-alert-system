"""Alpaca stock WebSocket client for delayed SIP (or IEX) minute bars."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import websockets

from .messages import bar_from_alpaca
from .publisher import BarPublisher
from .symbols import to_alpaca_symbol

log = logging.getLogger(__name__)


class AlpacaBarStream:
    """One WebSocket session for a shard of symbols."""

    def __init__(
        self,
        *,
        url: str,
        key_id: str,
        secret_key: str,
        feed: str,
        symbols: list[str],
        publisher: BarPublisher,
    ):
        self.url = url
        self.key_id = key_id
        self.secret_key = secret_key
        self.feed = feed
        self.symbols = symbols
        self.publisher = publisher
        self._stop = asyncio.Event()

    def request_stop(self) -> None:
        self._stop.set()

    async def run(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            try:
                await self._session()
                backoff = 1.0
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if self._stop.is_set():
                    return
                log.warning("Alpaca WebSocket error (%s). Reconnecting in %.0fs.", exc, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60.0)

    async def _session(self) -> None:
        log.info("Connecting to %s for %s symbol(s)", self.url, len(self.symbols))
        async with websockets.connect(self.url, ping_interval=20, ping_timeout=20) as ws:
            await self._await_msg(ws, wanted="connected")
            await ws.send(
                json.dumps(
                    {
                        "action": "auth",
                        "key": self.key_id,
                        "secret": self.secret_key,
                    }
                )
            )
            await self._await_msg(ws, wanted="authenticated")
            log.info("Alpaca WebSocket authenticated (%s)", self.feed)
            api_symbols = [to_alpaca_symbol(symbol) for symbol in self.symbols]
            await ws.send(json.dumps({"action": "subscribe", "bars": api_symbols}))
            sub = await self._await_type(ws, wanted="subscription")
            bars = (sub or {}).get("bars") or api_symbols
            log.info("Subscribed to %s bar symbol(s) on %s", len(bars), self.feed)
            async for raw in ws:
                if self._stop.is_set():
                    return
                await self._handle(raw)

    async def _await_msg(self, ws: Any, *, wanted: str) -> dict[str, Any]:
        while True:
            item = await self._next_dict(ws)
            if item.get("T") == "error":
                raise RuntimeError(f"Alpaca stream error: {item}")
            if item.get("msg") == wanted:
                return item

    async def _await_type(self, ws: Any, *, wanted: str) -> dict[str, Any]:
        while True:
            item = await self._next_dict(ws)
            if item.get("T") == "error":
                raise RuntimeError(f"Alpaca stream error: {item}")
            if item.get("T") == wanted:
                return item

    async def _next_dict(self, ws: Any) -> dict[str, Any]:
        payload = json.loads(await ws.recv())
        messages = payload if isinstance(payload, list) else [payload]
        for item in messages:
            if isinstance(item, dict):
                return item
        raise RuntimeError(f"Unexpected Alpaca frame: {payload!r}")

    async def _handle(self, raw: str | bytes) -> None:
        payload = json.loads(raw)
        messages = payload if isinstance(payload, list) else [payload]
        for item in messages:
            if not isinstance(item, dict):
                continue
            if item.get("T") == "error":
                raise RuntimeError(f"Alpaca stream error: {item}")
            if item.get("T") in ("success", "subscription"):
                continue
            bar = bar_from_alpaca(item, feed=self.feed, source="alpaca_ws")
            if bar:
                await self.publisher.publish(bar)