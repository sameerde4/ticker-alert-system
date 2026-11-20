"""Kafka consumer: minute bars → price alerts, forest scores, then price→news upgrade."""

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
)
from .live_session import SessionBook, SessionState
from .live_upgrade import should_write_live_alert, upgrade_price_draft_with_news
from .store import (
    clear_live_consumer_heartbeat,
    fetch_recent_daily_bars,
    get_alert_for_day,
    get_alert_rules,
    get_live_alerts_armed,
    insert_live_feature_row,
    touch_live_consumer_heartbeat,
    upsert_alert,
)
from .symbols import known_universe_symbol, universe_symbols

log = logging.getLogger(__name__)


class LiveBarConsumer:
    """Consume ``prices.raw.bars`` for the S&P 500: percent + forest, then news upgrade.

    Home Live alerts (S&P 500 scope) is fed by this path. Watchlist is only the focus set
    for Scan today — not a filter on which Kafka bars become live alerts.
    """

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
        self._universe: set[str] = set(universe_symbols())
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
        self._last_news_lookup: dict[str, float] = {}
        self._news_lookup_min_interval = 120.0
        self._armed_checked_at = 0.0
        self._armed_cached = True

    def request_stop(self) -> None:
        self._stop.set()

    async def run(self) -> None:
        """Run until stop is requested. When disarmed, idle without Kafka/heartbeat."""
        await self._refresh_rules()
        while not self._stop.is_set():
            if not await self._is_armed():
                await self._idle_while_disarmed()
                continue
            await self._run_armed_session()

    async def _is_armed(self) -> bool:
        now = asyncio.get_running_loop().time()
        if now - self._armed_checked_at < 2:
            return self._armed_cached
        async with self.pool.acquire() as conn:
            self._armed_cached = await get_live_alerts_armed(conn)
        self._armed_checked_at = now
        return self._armed_cached

    async def _idle_while_disarmed(self) -> None:
        try:
            async with self.pool.acquire() as conn:
                await clear_live_consumer_heartbeat(conn)
        except Exception as exc:
            log.warning("Could not clear live heartbeat while disarmed: %s", exc)
        log.info("Live alerts disarmed — consumer idle (click Live alerts on Home to arm).")
        while not self._stop.is_set():
            if await self._is_armed():
                log.info("Live alerts armed — connecting to Kafka.")
                return
            await asyncio.sleep(2)

    async def _run_armed_session(self) -> None:
        # Fresh open→last state each arm so a REST session backfill can set the
        # real 9:30 open (mid-day "latest bar only" polls otherwise use a minute open).
        self.book = SessionBook()
        self._last_feature_write.clear()
        self._last_news_lookup.clear()
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
            "Live consumer connected to %s topic=%s group=%s universe=%s forest=%s",
            self.bootstrap,
            self.topic,
            self.group_id,
            len(self._universe),
            "on" if self.forest.enabled else "off",
        )
        # Heartbeat on its own task so FinBERT/Perplexity work in _handle_bar cannot
        # starve the UI cue (armed + stale heartbeat shows "Live alerts starting…").
        hb_task = asyncio.create_task(self._heartbeat_loop(), name="live-heartbeat")
        try:
            await self._heartbeat()
            while not self._stop.is_set():
                if not await self._is_armed():
                    log.info("Live alerts disarmed — leaving Kafka session.")
                    break
                await self._refresh_rules_if_due()
                batches = await consumer.getmany(timeout_ms=1000, max_records=200)
                if not batches:
                    continue
                for _tp, messages in batches.items():
                    for message in messages:
                        await self._handle_bar(message.value)
        finally:
            hb_task.cancel()
            try:
                await hb_task
            except asyncio.CancelledError:
                pass
            try:
                async with self.pool.acquire() as conn:
                    await clear_live_consumer_heartbeat(conn)
            except Exception as exc:
                log.warning("Could not clear live heartbeat: %s", exc)
            await consumer.stop()
            self._consumer = None
            log.info("Live consumer session stopped.")

    async def _heartbeat_loop(self) -> None:
        """Keep the Home cue green while this armed Kafka session is alive."""
        while not self._stop.is_set():
            try:
                await self._heartbeat()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("Live heartbeat failed: %s", exc)
            try:
                await asyncio.sleep(5)
            except asyncio.CancelledError:
                raise

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
            # Refresh forest history only for symbols already seen this session
            # (lazy-loaded on first bar). Avoid a full S&P 500 DB walk every 30s.
            active = sorted(self._history)
            history: dict[str, SymbolHistory] = {}
            if active:
                from .engine import eastern_date

                session_day = eastern_date(datetime.now(UTC))
                lake_root = Path(settings.lake_root)
                for symbol in active:
                    rows = await fetch_recent_daily_bars(conn, symbol, limit=40)
                    hist = history_from_daily_rows(rows, session_day=session_day)
                    if hist is None:
                        hist = history_from_lake(lake_root, symbol, session_day=session_day)
                    if hist is not None:
                        history[symbol.upper()] = hist
        self._universe = set(universe_symbols())
        self._price_threshold = float(rules["price_move_threshold"])
        self._sentiment_threshold = float(rules["sentiment_threshold"])
        self._history = history
        self._rules_loaded_at = asyncio.get_running_loop().time()
        self.forest.reload()
        log.info(
            "Live rules refreshed: universe=%s price_threshold=%.4f forest_history=%s forest=%s",
            len(self._universe),
            self._price_threshold,
            len(self._history),
            "on" if self.forest.enabled else "off",
        )

    async def _ensure_history(self, symbol: str) -> SymbolHistory | None:
        key = symbol.upper()
        cached = self._history.get(key)
        if cached is not None:
            return cached
        from .engine import eastern_date

        session_day = eastern_date(datetime.now(UTC))
        lake_root = Path(settings.lake_root)
        async with self.pool.acquire() as conn:
            rows = await fetch_recent_daily_bars(conn, key, limit=40)
        hist = history_from_daily_rows(rows, session_day=session_day)
        if hist is None:
            hist = history_from_lake(lake_root, key, session_day=session_day)
        if hist is not None:
            self._history[key] = hist
        return hist

    async def _handle_bar(self, bar: Any) -> None:
        if not isinstance(bar, dict):
            return
        symbol = str(bar.get("symbol") or "").upper()
        if not symbol:
            return
        if self._universe:
            if symbol not in self._universe:
                return
        elif not known_universe_symbol(symbol):
            return
        state = self.book.apply(bar)
        if state is None:
            return

        forest_draft = await self._score_forest(state)

        percent_draft = price_draft_from_session(
            state,
            price_move_threshold=self._price_threshold,
            sentiment_threshold=self._sentiment_threshold,
            now=datetime.now(UTC),
        )
        # Prefer forest wording when both fire; percent alone is enough otherwise.
        draft = forest_draft or percent_draft
        if draft is None:
            return
        if forest_draft is not None and percent_draft is not None:
            # Keep forest sections but allow percent snapshot fields from the shared state.
            draft = forest_draft
        await self._maybe_write_alert(draft, state)

    async def _score_forest(self, state: SessionState):
        if not self.forest.enabled:
            return None
        hist = await self._ensure_history(state.symbol)
        if hist is None or hist.prior_close <= 0:
            return None
        scored = self.forest.score_session(
            open_px=state.open,
            last_px=state.last,
            prior_close=hist.prior_close,
            session_volume=state.volume,
            prior_volumes=hist.prior_volumes,
        )
        if scored is None:
            return None

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
            return forest_price_draft_from_session(
                state,
                scored,
                price_move_threshold=self._price_threshold,
                sentiment_threshold=self._sentiment_threshold,
                now=datetime.now(UTC),
            )
        return None

    async def _maybe_write_alert(self, draft, state: SessionState) -> None:
        async with self.pool.acquire() as conn:
            existing = await get_alert_for_day(conn, draft.symbol, draft.bar_date)

        if not should_write_live_alert(existing, draft):
            log.debug(
                "Skip live alert for %s %s; existing kind=%s draft=%s",
                draft.symbol,
                draft.bar_date,
                (existing or {}).get("kind"),
                draft.kind,
            )
            return

        same_prints = bool(existing and _same_price_snapshot(existing, draft))
        has_evidence = isinstance((existing or {}).get("sections"), dict) and (
            (existing or {}).get("sections") or {}
        ).get("evidence")
        now_mono = asyncio.get_running_loop().time()
        last_news = self._last_news_lookup.get(state.symbol, 0.0)
        news_due = (now_mono - last_news) >= self._news_lookup_min_interval

        if same_prints and has_evidence and not news_due and existing.get("kind") in (
            "news",
            "news_price",
            "price",
        ):
            return

        # Price noticed → fetch/score headlines → maybe upgrade → Perplexity for news kinds.
        try:
            upgraded = await upgrade_price_draft_with_news(
                self.pool,
                draft,
                state,
                price_move_threshold=self._price_threshold,
                sentiment_threshold=self._sentiment_threshold,
                now=datetime.now(UTC),
            )
            self._last_news_lookup[state.symbol] = now_mono
        except Exception as exc:
            log.warning("Live price→news upgrade failed for %s: %s", state.symbol, exc)
            from .evidence import attach_evidence_story

            upgraded = attach_evidence_story(draft)

        if not should_write_live_alert(existing, upgraded):
            return

        if (
            existing
            and _same_price_snapshot(existing, upgraded)
            and existing.get("kind") == upgraded.kind
            and _same_evidence_outcome(existing, upgraded)
        ):
            return

        async with self.pool.acquire() as conn:
            saved = await upsert_alert(conn, upgraded)
        log.info(
            "Live alert %s %s kind=%s change=%s",
            saved["symbol"],
            saved["bar_date"],
            saved["kind"],
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


def _same_evidence_outcome(existing: dict[str, Any], draft) -> bool:
    left = ((existing.get("sections") or {}).get("evidence") or {}).get("headline")
    right = ((draft.sections or {}).get("evidence") or {}).get("headline")
    return left == right and existing.get("kind") == draft.kind


def _decode_json(raw: bytes | None) -> Any:
    if not raw:
        return None
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        log.warning("Skipping non-JSON Kafka payload")
        return None
