"""One watchlist pass: refresh bars and headlines, then write alerts."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

import asyncpg

from .config import settings
from .engine import EASTERN, eastern_date, evaluate_symbol, headline_session
from .news import fetch_headlines
from .prices import fetch_daily_bars
from .scoring import attach_scores
from .sectors import ensure_symbol_sectors
from .store import (
    clear_symbol_day,
    delete_all_alerts,
    get_alert_rules,
    list_alert_days,
    list_watchlist,
    load_bars,
    load_headlines,
    upsert_alert,
    upsert_bars,
    upsert_headlines,
)

MAX_REBUILD_DAYS = 40


async def _headlines_for_rules(conn, symbol: str, incoming: list[dict[str, Any]] | None, scorer: str):
    """Store fetched headlines, then rescore every saved headline with one scorer."""
    if incoming:
        pending = []
        for item in incoming:
            copy = dict(item)
            copy.setdefault("sentiment_score", 50.0)
            pending.append(copy)
        await upsert_headlines(conn, symbol, pending)
    stored = await load_headlines(conn, symbol)
    scored = attach_scores(stored, scorer)
    for item in scored:
        await conn.execute(
            "UPDATE headlines SET sentiment_score = $1 WHERE id = $2::uuid",
            item["sentiment_score"],
            item["id"],
        )
    return scored


async def run_check(pool: asyncpg.Pool, *, now: datetime | None = None) -> dict[str, Any]:
    moment = now or datetime.now(UTC)
    async with pool.acquire() as conn:
        rules = await get_alert_rules(conn)
        symbols = [row["symbol"] for row in await list_watchlist(conn)]
        await ensure_symbol_sectors(conn, symbols)

    errors: list[dict[str, str]] = []
    alerts: list[dict[str, Any]] = []
    for symbol in symbols:
        try:
            bars = await asyncio.to_thread(
                fetch_daily_bars, symbol, lookback_days=settings.bar_lookback_days
            )
            headlines = await asyncio.to_thread(fetch_headlines, symbol)
        except Exception as exc:
            errors.append({"symbol": symbol, "error": str(exc)})
            continue
        async with pool.acquire() as conn:
            if bars:
                await upsert_bars(conn, symbol, bars)
            stored_bars = await load_bars(conn, symbol)
            stored_news = await _headlines_for_rules(
                conn, symbol, headlines, "finbert"
            )
            drafts = evaluate_symbol(
                symbol=symbol,
                bars=stored_bars,
                headlines=stored_news,
                now=moment,
                price_move_threshold=rules["price_move_threshold"],
                volume_spike_threshold=settings.volume_spike_threshold,
                volume_lookback=settings.volume_lookback,
                sentiment_threshold=rules["sentiment_threshold"],
                news_lookback_hours=settings.news_lookback_hours,
                fusion_window_hours=settings.fusion_window_hours,
            )
            today = eastern_date(moment)
            drafts = [draft for draft in drafts if draft.bar_date == today]
            await clear_symbol_day(conn, symbol, today)
            for draft in drafts:
                alerts.append(await upsert_alert(conn, draft))
    return {"checked": symbols, "errors": errors, "alerts": alerts}


async def realign_saved_alerts(pool: asyncpg.Pool, *, now: datetime | None = None) -> dict[str, Any]:
    """Rewrite saved alerts so each headline stays on the trading day it was published.

    A day that already has an alert keeps the thresholds it fired under. Days that
    only have headlines use the current settings. Other days are not removed.
    """
    moment = now or datetime.now(UTC)
    async with pool.acquire() as conn:
        rules = await get_alert_rules(conn)
        symbols = [
            row["symbol"]
            for row in await conn.fetch(
                """
                SELECT symbol FROM watchlist
                UNION
                SELECT symbol FROM alerts
                ORDER BY symbol
                """
            )
        ]

    written: list[dict[str, Any]] = []
    for symbol in symbols:
        async with pool.acquire() as conn:
            bars = await load_bars(conn, symbol)
            headlines = await _headlines_for_rules(
                conn, symbol, None, "finbert"
            )
            saved_days = await list_alert_days(conn, symbol)
        by_day = {row["bar_date"]: row for row in saved_days}
        sessions = set(by_day)
        for item in headlines:
            sessions.add(headline_session(item["published_at"]))
        for day in sorted(session for session in sessions if session is not None):
            saved = by_day.get(day)
            price_threshold = (
                float(saved["price_move_threshold"])
                if saved and saved["price_move_threshold"] is not None
                else rules["price_move_threshold"]
            )
            sentiment_threshold = (
                float(saved["sentiment_threshold"])
                if saved and saved["sentiment_threshold"] is not None
                else rules["sentiment_threshold"]
            )
            as_of = datetime.combine(day, time(20, 0), tzinfo=EASTERN)
            if day == eastern_date(moment):
                as_of = moment
            bars_asof = [bar for bar in bars if bar["dt"] <= day]
            drafts = evaluate_symbol(
                symbol=symbol,
                bars=bars_asof,
                headlines=headlines,
                now=as_of,
                price_move_threshold=price_threshold,
                volume_spike_threshold=settings.volume_spike_threshold,
                volume_lookback=settings.volume_lookback,
                sentiment_threshold=sentiment_threshold,
                news_lookback_hours=settings.news_lookback_hours,
                fusion_window_hours=settings.fusion_window_hours,
            )
            drafts = [draft for draft in drafts if draft.bar_date == day]
            async with pool.acquire() as conn:
                if drafts:
                    for draft in drafts:
                        written.append(await upsert_alert(conn, draft))
                else:
                    await clear_symbol_day(conn, symbol, day)
    return {"alerts": written}


def rebuild_start(today: date, days: int) -> date:
    """First calendar day of a rebuild. ``days`` of 1 is today only."""
    if isinstance(days, bool) or not isinstance(days, int) or days < 1 or days > MAX_REBUILD_DAYS:
        raise ValueError(f"Days must be a whole number from 1 to {MAX_REBUILD_DAYS}.")
    return today - timedelta(days=days - 1)


async def rebuild_history(pool: asyncpg.Pool, *, days: int, now: datetime | None = None) -> dict[str, Any]:
    """Delete every saved alert, then rerun the current rules over the last ``days`` calendar days.

    Each watchlist symbol is checked once per trading session in that window. Headlines
    already stored are kept and joined with whatever Yahoo returns now.
    """
    moment = now or datetime.now(UTC)
    today = eastern_date(moment)
    start = rebuild_start(today, days)
    async with pool.acquire() as conn:
        rules = await get_alert_rules(conn)
        symbols = [row["symbol"] for row in await list_watchlist(conn)]
        await delete_all_alerts(conn)
        await ensure_symbol_sectors(conn, symbols)

    errors: list[dict[str, str]] = []
    alerts: list[dict[str, Any]] = []
    fetch_days = days + settings.volume_lookback + 5
    for symbol in symbols:
        try:
            bars = await asyncio.to_thread(fetch_daily_bars, symbol, lookback_days=fetch_days)
            headlines = await asyncio.to_thread(fetch_headlines, symbol)
        except Exception as exc:
            errors.append({"symbol": symbol, "error": str(exc)})
            continue
        async with pool.acquire() as conn:
            if bars:
                await upsert_bars(conn, symbol, bars)
            stored_bars = await load_bars(conn, symbol)
            stored_news = await _headlines_for_rules(
                conn, symbol, headlines, "finbert"
            )
            sessions: set[date] = set()
            for bar in stored_bars:
                if start <= bar["dt"] <= today:
                    sessions.add(bar["dt"])
            for item in stored_news:
                day = headline_session(item["published_at"])
                if start <= day <= today:
                    sessions.add(day)
            for day in sorted(sessions):
                as_of = moment if day == today else datetime.combine(day, time(20, 0), tzinfo=EASTERN)
                bars_asof = [bar for bar in stored_bars if bar["dt"] <= day]
                drafts = evaluate_symbol(
                    symbol=symbol,
                    bars=bars_asof,
                    headlines=stored_news,
                    now=as_of,
                    price_move_threshold=rules["price_move_threshold"],
                    volume_spike_threshold=settings.volume_spike_threshold,
                    volume_lookback=settings.volume_lookback,
                    sentiment_threshold=rules["sentiment_threshold"],
                    news_lookback_hours=settings.news_lookback_hours,
                    fusion_window_hours=settings.fusion_window_hours,
                )
                for draft in drafts:
                    if draft.bar_date == day:
                        alerts.append(await upsert_alert(conn, draft))
    return {
        "days": days,
        "start": start.isoformat(),
        "checked": symbols,
        "errors": errors,
        "alerts": alerts,
    }
