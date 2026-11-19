"""Kafka consumer: minute bars → open-to-last price alerts + live forest feature rows."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import asyncpg
from aiokafka import AIOKafkaConsumer

from .config import settings
from .forest_live import (
    LiveForestScorer,
    SymbolHistory,
    history_from_daily_rows,
    history_from_lake,
)
from .live_alerts import (
    forest_price_draft_from_session,
    price_draft_from_session,
    should_write_live_price,
)
from .live_session import SessionBook
from .store import (
    clear_live_consumer_heartbeat,
    fetch_recent_daily_bars,
    get_alert_for_day,
    get_alert_rules,
    insert_live_feature_row,
    list_watchlist,
    touch_live_consumer_heartbeat,
    upsert_alert,
)

log = logging.getLogger(__name__)


class LiveBarConsumer:
    """Consume ``prices.raw.bars``: percent-rule alerts, forest scores, feature sink."""

    def __init__(
        self,
        pool: asyncpg.Pool,
        *,
        bootstrap: str | None = None,
        topic: str | None = None,
        group_id: str | None = None,
        watchlist_refresh_seconds: int | None = None,
        forest: LiveForestScorer | None = None,
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
        self.forest = forest if forest is not None else LiveForestScorer(Path(settings.lake_root))
        self._history: dict[str, SymbolHistory] = {}
        self._last_feature_write: dict[str, float] = {}
        self._feature_min_interval = max(5, int(settings.live_feature_min_interval_seconds))

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
            "Live consumer connected to %s topic=%s group=%s watchlist=%s forest=%s",
            self.bootstrap,
            self.topic,
            self.group_id,
            len(self._watchlist),
            "on" if self.forest.enabled else "off",
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
            history: dict[str, SymbolHistory] = {}
            from .engine import eastern_date

            session_day = eastern_date(datetime.now(UTC))
            lake_root = Path(settings.lake_root)
            for symbol in symbols:
                rows = await fetch_recent_daily_bars(conn, symbol, limit=40)
                hist = history_from_daily_rows(rows, session_day=session_day)
                if hist is None:
                    hist = history_from_lake(lake_root, symbol, session_day=session_day)
                if hist is not None:
                    history[symbol.upper()] = hist
        self._watchlist = {symbol.upper() for symbol in symbols}
        self._price_threshold = float(rules["price_move_threshold"])
        self._sentiment_threshold = float(rules["sentiment_threshold"])
        self._history = history
        self._rules_loaded_at = asyncio.get_running_loop().time()
        self.forest.reload()
        log.info(
            "Live rules refreshed: watchlist=%s price_threshold=%.4f forest_history=%s forest=%s",
            len(self._watchlist),
            self._price_threshold,
            len(self._history),
            "on" if self.forest.enabled else "off",
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

        await self._score_forest(state)

        draft = price_draft_from_session(
            state,
            price_move_threshold=self._price_threshold,
            sentiment_threshold=self._sentiment_threshold,
            now=datetime.now(UTC),
        )
        if draft is None:
            return
        await self._maybe_write_price(draft)

    async def _score_forest(self, state) -> None:
        if not self.forest.enabled:
            return
        hist = self._history.get(state.symbol)
        if hist is None:
            return
        # Re-fit history exclusion to this bar's session day when needed.
        if hist.prior_close <= 0:
            return
        scored = self.forest.score_session(
            open_px=state.open,
            last_px=state.last,
            prior_close=hist.prior_close,
            session_volume=state.volume,
            prior_volumes=hist.prior_volumes,
        )
        if scored is None:
            return

        now_mono = asyncio.get_running_loop().time()
        last_write = self._last_feature_write.get(state.symbol, 0.0)
        should_sink = (now_mono - last_write) >= self._feature_min_interval or scored.anomalous
        if should_sink:
            try:
                async with self.pool.acquire() as conn:
                    await insert_live_feature_row(
                        conn,
                        symbol=state.symbol,
                        session_day=state.session_day,
                        observed_at=state.last_ts if state.last_ts.tzinfo else state.last_ts.replace(tzinfo=UTC),
                        gap_return=scored.features["gap_return"],
                        session_return=scored.features["session_return"],
                        close_return=scored.features["close_return"],
                        volume_zscore=scored.features["volume_zscore"],
                        forest_score=scored.forest_score,
                        score_cutoff=scored.score_cutoff,
                        anomalous=scored.anomalous,
                        model_id=scored.model_id,
                        open_px=state.open,
                        last_px=state.last,
                        prior_close=hist.prior_close,
                        session_volume=state.volume,
                    )
                self._last_feature_write[state.symbol] = now_mono
            except Exception as exc:
                log.warning("Could not sink live feature row for %s: %s", state.symbol, exc)

        if scored.anomalous and settings.live_forest_alerts:
            forest_draft = forest_price_draft_from_session(
                state,
                scored,
                price_move_threshold=self._price_threshold,
                sentiment_threshold=self._sentiment_threshold,
                now=datetime.now(UTC),
            )
            if forest_draft is not None:
                await self._maybe_write_price(forest_draft)

    async def _maybe_write_price(self, draft) -> None:
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
            # Prefer keeping a richer forest summary if we already have one and this
            # draft is only the percent-rule text with the same prints.
            if (
                existing
                and isinstance((existing.get("sections") or {}), dict)
                and (existing.get("sections") or {}).get("forest")
                and "forest" not in (draft.sections or {})
                and _same_price_snapshot(existing, draft)
            ):
                return
            saved = await upsert_alert(conn, draft)
            log.info(
                "Live price alert %s %s change=%s",
                saved["symbol"],
                saved["bar_date"],
                f"{float(saved['price_change_pct'] or 0) * 100:.2f}%",
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
