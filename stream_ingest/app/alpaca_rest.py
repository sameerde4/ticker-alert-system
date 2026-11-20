"""Poll Alpaca delayed SIP minute bars for symbols beyond the WebSocket cap."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta, time
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from .messages import bar_from_rest
from .publisher import BarPublisher
from .symbols import from_alpaca_symbol, to_alpaca_symbol

log = logging.getLogger(__name__)

_EASTERN = ZoneInfo("America/New_York")


class AlpacaRestBarPoller:
    """Fetch recent 1-minute bars over REST. Free Basic SIP history is 15+ minutes old."""

    def __init__(
        self,
        *,
        data_url: str,
        key_id: str,
        secret_key: str,
        feed: str,
        symbols: list[str],
        publisher: BarPublisher,
        poll_seconds: int = 60,
        symbols_per_request: int = 100,
    ):
        self.data_url = data_url.rstrip("/")
        self.key_id = key_id
        self.secret_key = secret_key
        self.feed = feed
        self.symbols = symbols
        self.publisher = publisher
        self.poll_seconds = max(15, poll_seconds)
        self.symbols_per_request = max(1, symbols_per_request)
        self._stop = asyncio.Event()
        self._seen: dict[str, str] = {}
        self._session_backfilled = False

    def request_stop(self) -> None:
        self._stop.set()

    async def run(self) -> None:
        if not self.symbols:
            log.info("REST bar poller has no symbols; idle.")
            await self._stop.wait()
            return
        log.info(
            "REST bar poller watching %s symbol(s) every %ss",
            len(self.symbols),
            self.poll_seconds,
        )
        async with httpx.AsyncClient(timeout=30.0) as client:
            while not self._stop.is_set():
                try:
                    if not self._session_backfilled:
                        await self._backfill_session(client)
                        self._session_backfilled = True
                    await self._poll_once(client)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    log.warning("REST bar poll failed: %s", exc)
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=self.poll_seconds)
                except asyncio.TimeoutError:
                    continue

    async def _backfill_session(self, client: httpx.AsyncClient) -> None:
        """Publish today's RTH bars from the cash open so live SessionBook gets the real open.

        Latest-only polls start mid-session with a minute bar open (~last price), so
        open→last never clears the percent rule. One ordered backfill fixes that.
        """
        window = _session_backfill_window()
        if window is None:
            log.info("REST session backfill skipped (outside the cash session window).")
            return
        start, end = window
        log.info(
            "REST session backfill from %s to %s for %s symbol(s)",
            start.isoformat(),
            end.isoformat(),
            len(self.symbols),
        )
        published = 0
        for chunk in _chunks(self.symbols, self.symbols_per_request):
            bars_by_symbol = await self._fetch_bars(client, chunk, start=start, end=end)
            for symbol in chunk:
                rows = bars_by_symbol.get(symbol) or []
                for row in rows:
                    bar = bar_from_rest(symbol, row, feed=self.feed)
                    if not bar or not bar.get("ts"):
                        continue
                    stamp = str(bar["ts"])
                    if self._seen.get(symbol) == stamp:
                        continue
                    # Keep the newest stamp per symbol; still publish every distinct bar.
                    prior = self._seen.get(symbol)
                    if prior is not None and stamp <= prior:
                        continue
                    self._seen[symbol] = stamp
                    await self.publisher.publish(bar)
                    published += 1
        log.info("REST session backfill published %s bar(s)", published)

    async def _poll_once(self, client: httpx.AsyncClient) -> None:
        # Stay outside the free-plan 15-minute SIP restriction.
        end = datetime.now(UTC) - timedelta(minutes=16)
        start = end - timedelta(minutes=5)
        published = 0
        for chunk in _chunks(self.symbols, self.symbols_per_request):
            bars_by_symbol = await self._fetch_bars(client, chunk, start=start, end=end)
            for symbol, rows in bars_by_symbol.items():
                if not rows:
                    continue
                latest = rows[-1]
                bar = bar_from_rest(symbol, latest, feed=self.feed)
                if not bar or not bar.get("ts"):
                    continue
                stamp = str(bar["ts"])
                if self._seen.get(symbol) == stamp:
                    continue
                self._seen[symbol] = stamp
                await self.publisher.publish(bar)
                published += 1
        if published:
            log.info("REST poll published %s new bar(s)", published)

    async def _fetch_bars(
        self,
        client: httpx.AsyncClient,
        symbols: list[str],
        *,
        start: datetime,
        end: datetime,
    ) -> dict[str, list[dict[str, Any]]]:
        return await fetch_stock_bars(
            client,
            data_url=self.data_url,
            key_id=self.key_id,
            secret_key=self.secret_key,
            feed=self.feed,
            symbols=symbols,
            start=start,
            end=end,
        )


def _session_backfill_window(now: datetime | None = None) -> tuple[datetime, datetime] | None:
    """UTC [cash open, delayed-safe end] for today's RTH, or None when there is nothing to load."""
    now_utc = now or datetime.now(UTC)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=UTC)
    else:
        now_utc = now_utc.astimezone(UTC)
    now_et = now_utc.astimezone(_EASTERN)
    if now_et.weekday() >= 5:
        return None
    open_et = datetime.combine(now_et.date(), time(9, 30), tzinfo=_EASTERN)
    if now_et < open_et:
        return None
    end = now_utc - timedelta(minutes=16)
    start = open_et.astimezone(UTC)
    if start >= end:
        return None
    return start, end


async def fetch_stock_bars(
    client: httpx.AsyncClient,
    *,
    data_url: str,
    key_id: str,
    secret_key: str,
    feed: str,
    symbols: list[str],
    start: datetime,
    end: datetime,
) -> dict[str, list[dict[str, Any]]]:
    api_symbols = [to_alpaca_symbol(symbol) for symbol in symbols]
    params = {
        "symbols": ",".join(api_symbols),
        "timeframe": "1Min",
        "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "end": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "adjustment": "raw",
        "feed": rest_feed(feed),
        "limit": 10000,
        "sort": "asc",
    }
    response = await client.get(
        f"{data_url.rstrip('/')}/v2/stocks/bars",
        params=params,
        headers={
            "APCA-API-KEY-ID": key_id,
            "APCA-API-SECRET-KEY": secret_key,
        },
    )
    if response.status_code >= 400:
        raise RuntimeError(f"Alpaca REST {response.status_code}: {response.text[:300]}")
    body = response.json()
    bars = body.get("bars") or {}
    if not isinstance(bars, dict):
        return {}
    # Keys come back as Alpaca form (BRK.B); map to canonical BRK-B for the rest of the app.
    return {
        from_alpaca_symbol(str(symbol)): list(rows or [])
        for symbol, rows in bars.items()
    }


async def probe_latest_bars(
    *,
    data_url: str,
    key_id: str,
    secret_key: str,
    feed: str,
    symbols: list[str],
    lookback_hours: int = 48,
) -> list[dict[str, Any]]:
    """Fetch the newest delayed bar for each symbol. Works after the cash session closes."""
    end = datetime.now(UTC) - timedelta(minutes=16)
    start = end - timedelta(hours=max(1, lookback_hours))
    out: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=30.0) as client:
        for chunk in _chunks(symbols, 100):
            bars_by_symbol = await fetch_stock_bars(
                client,
                data_url=data_url,
                key_id=key_id,
                secret_key=secret_key,
                feed=feed,
                symbols=chunk,
                start=start,
                end=end,
            )
            for symbol in chunk:
                rows = bars_by_symbol.get(symbol) or []
                if not rows:
                    continue
                bar = bar_from_rest(symbol, rows[-1], feed=feed)
                if bar:
                    out.append(bar)
    return out


def rest_feed(feed: str) -> str:
    return "sip" if feed == "delayed_sip" else feed


def _chunks(values: list[str], size: int) -> list[list[str]]:
    return [values[i : i + size] for i in range(0, len(values), size)]
