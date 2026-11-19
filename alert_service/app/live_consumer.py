"""Kafka consumer: minute bars → open-to-last price alerts in Postgres."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from typing import Any

import asyncpg
from aiokafka import AIOKafkaConsumer

from .config import settings
from .live_alerts import price_draft_from_session, should_write_live_price
from .live_session import SessionBook
from .store import (
    clear_live_consumer_heartbeat,
    get_alert_for_day,
    get_alert_rules,
    list_watchlist,
    touch_live_consumer_heartbeat,
    upsert_alert,
)

log = logging.getLogger(__name__)


class LiveBarConsumer:
    """Consume ``prices.raw.bars`` and write session-move price alerts for the watchlist."""

    def __init__(
        self,
        pool: asyncpg.Pool,
        *,
        bootstrap: str | None = None,
        topic: str | None = None,
        group_id: str | None = None,
        watchlist_refresh_seconds: int | None = None,
    ):
        self.pool = pool
        self.bootstrap = bootstrap or settings.kafka_bootstrap_servers
        self.topic = topic or settings.kafka_topic_bars
        self.group_id = group_id or settings.kafka_group_id
        self.watchlist_refresh_seconds = max(
            5, watchlist_refresh_seconds or settings.live_watchlist_refresh_seconds
        )
        self.book = SessionBook()
        self._watchlist: set[str] = set()
        self._price_threshold = settings.price_move_threshold
        self._sentiment_threshold = settings.sentiment_threshold
        self._rules_loaded_at = 0.0
        self._heartbeat_at = 0.0
        self._consumer: AIOKafkaConsumer | None = None
        self._stop = asyncio.Event()

    def request_stop(self) -> None:
        self._stop.set()

    async def run(self) -> None:
        await self._refresh_rules()
        consumer = AIOKafkaConsumer(
            self.topic,
            bootstrap_servers=self.bootstrap,
            group_id=self.group_id,
            enable_auto_commit=True,
            auto_offset_reset="latest",
            value_deserializer=_decode_json,
            key_deserializer=lambda raw: raw.decode("utf-8") if raw else None,
        )
        await consumer.start()
        self._consumer = consumer
        log.info(
            "Live consumer connected to %s topic=%s group=%s watchlist=%s",
            self.bootstrap,
            self.topic,
            self.group_id,
            len(self._watchlist),
        )
        try:
            await self._heartbeat()
            while not self._stop.is_set():
                await self._refresh_rules_if_due()
                await self._heartbeat_if_due()
                batches = await consumer.getmany(timeout_ms=1000, max_records=200)
                if not batches:
                    continue
                for _tp, messages in batches.items():
                    for message in messages:
                        await self._handle_bar(message.value)
        finally:
            try:
                async with self.pool.acquire() as conn:
                    await clear_live_consumer_heartbeat(conn)
            except Exception as exc:
                log.warning("Could not clear live heartbeat: %s", exc)
            await consumer.stop()
            self._consumer = None
            log.info("Live consumer stopped.")

    async def _heartbeat_if_due(self) -> None:
        now = asyncio.get_running_loop().time()
        if now - self._heartbeat_at < 5:
            return
        await self._heartbeat()

    async def _heartbeat(self) -> None:
        async with self.pool.acquire() as conn:
            await touch_live_consumer_heartbeat(conn)
        self._heartbeat_at = asyncio.get_running_loop().time()

    async def _refresh_rules_if_due(self) -> None:
        now = asyncio.get_running_loop().time()
        if now - self._rules_loaded_at < self.watchlist_refresh_seconds:
            return
        await self._refresh_rules()

    async def _refresh_rules(self) -> None:
        async with self.pool.acquire() as conn:
            rules = await get_alert_rules(conn)
            symbols = [row["symbol"] for row in await list_watchlist(conn)]
        self._watchlist = {symbol.upper() for symbol in symbols}
        self._price_threshold = float(rules["price_move_threshold"])
        self._sentiment_threshold = float(rules["sentiment_threshold"])
        self._rules_loaded_at = asyncio.get_running_loop().time()
        log.info(
            "Live rules refreshed: watchlist=%s price_threshold=%.4f",
            len(self._watchlist),
            self._price_threshold,
        )

    async def _handle_bar(self, bar: Any) -> None:
        if not isinstance(bar, dict):
            return
        symbol = str(bar.get("symbol") or "").upper()
        if not symbol or symbol not in self._watchlist:
            return
        state = self.book.apply(bar)
        if state is None:
            return
        draft = price_draft_from_session(
            state,
            price_move_threshold=self._price_threshold,
            sentiment_threshold=self._sentiment_threshold,
            now=datetime.now(UTC),
        )
        if draft is None:
            return
        async with self.pool.acquire() as conn:
            existing = await get_alert_for_day(conn, draft.symbol, draft.bar_date)
            if not should_write_live_price(existing):
                log.debug(
                    "Skip live price for %s %s; existing kind=%s",
                    draft.symbol,
                    draft.bar_date,
                    (existing or {}).get("kind"),
                )
                return
            if existing and _same_price_snapshot(existing, draft):
                return
            saved = await upsert_alert(conn, draft)
            log.info(
                "Live price alert %s %s change=%.2f%%",
                saved["symbol"],
                saved["bar_date"],
                float(saved["price_change_pct"] or 0) * 100,
            )


def _same_price_snapshot(existing: dict[str, Any], draft) -> bool:
    """Avoid rewriting when the percent and prints have not moved."""
    try:
        same_change = abs(float(existing.get("price_change_pct") or 0) - float(draft.price_change_pct or 0)) < 1e-8
        same_last = abs(float(existing.get("latest_close") or 0) - float(draft.latest_close or 0)) < 1e-6
        same_open = abs(float(existing.get("prior_close") or 0) - float(draft.prior_close or 0)) < 1e-6
    except (TypeError, ValueError):
        return False
    return same_change and same_last and same_open


def _decode_json(raw: bytes | None) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        log.warning("Skipping non-JSON Kafka payload")
        return None
