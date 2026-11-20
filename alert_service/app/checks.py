"""One watchlist pass: refresh bars and headlines, then write alerts."""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, time, timedelta
from typing import Any

import asyncpg

from .config import settings
from .engine import (
    EASTERN,
    cash_session_open,
    eastern_date,
    evaluate_symbol,
    headline_session,
    scan_focus_moment,
)
from .news import fetch_headlines
from .prices import fetch_daily_bars, fetch_last_24h, fetch_open_to_last
from .symbols import trades_all_day
from .scoring import attach_scores
from .sectors import ensure_symbol_sectors
from .evidence import attach_evidence_story
from .perplexity import complete_reasoning
from .perplexity_catalog import known_model
from .watchlist_forest import apply_forest_to_drafts, load_watchlist_forest_scorer
from .store import (
    clear_symbol_day,
    clear_watchlist_alerts,
    get_alert_rules,
    list_alert_days,
    list_watchlist,
    load_bars,
    load_headlines,
    perplexity_api_key,
    perplexity_model,
    upsert_alert,
    upsert_bars,
    upsert_headlines,
)

MAX_REBUILD_DAYS = 40
_REASON_BATCH = 8


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
    # Pre-open / weekend: evaluate the last completed session so Scan today is not empty.
    focus = scan_focus_moment(moment)
    focus_day = eastern_date(focus)
    async with pool.acquire() as conn:
        rules = await get_alert_rules(conn)
        symbols = [row["symbol"] for row in await list_watchlist(conn)]
        await ensure_symbol_sectors(conn, symbols)

    errors: list[dict[str, str]] = []
    alerts: list[Any] = []
    forest = load_watchlist_forest_scorer()
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
            trailing = None
            live = None
            # Live open→last only while the cash session is open on the wall clock.
            if trades_all_day(symbol):
                trailing = await asyncio.to_thread(fetch_last_24h, symbol, now=moment)
            elif cash_session_open(moment):
                live = await asyncio.to_thread(fetch_open_to_last, symbol, now=moment)
            drafts = evaluate_symbol(
                symbol=symbol,
                bars=stored_bars,
                headlines=stored_news,
                now=focus,
                price_move_threshold=rules["price_move_threshold"],
                volume_spike_threshold=settings.volume_spike_threshold,
                volume_lookback=settings.volume_lookback,
                sentiment_threshold=rules["sentiment_threshold"],
                news_lookback_hours=settings.news_lookback_hours,
                fusion_window_hours=settings.fusion_window_hours,
                trailing_24h=trailing,
                live_session=live,
            )
            drafts = apply_forest_to_drafts(
                drafts,
                scorer=forest,
                symbol=symbol,
                bars=stored_bars,
                session_day=focus_day,
                now=focus,
                price_move_threshold=rules["price_move_threshold"],
                sentiment_threshold=rules["sentiment_threshold"],
                live_session=live,
                origin="watchlist",
            )
            kept = [attach_evidence_story(draft) for draft in drafts if draft.bar_date == focus_day]
            await clear_symbol_day(conn, symbol, focus_day)
            for draft in kept:
                alerts.append(draft)
    reasoned, reasoning, reasoning_error = await reason_alert_drafts(pool, alerts)
    reasoned = [attach_evidence_story(draft) for draft in reasoned]
    saved = []
    async with pool.acquire() as conn:
        for draft in reasoned:
            saved.append(await upsert_alert(conn, draft))
    return {
        "checked": symbols,
        "errors": errors,
        "alerts": saved,
        "reasoning": reasoning,
        "reasoning_error": reasoning_error,
    }


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
    forest = load_watchlist_forest_scorer()
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
            drafts = apply_forest_to_drafts(
                [draft for draft in drafts if draft.bar_date == day],
                scorer=forest,
                symbol=symbol,
                bars=bars_asof,
                session_day=day,
                now=as_of,
                price_move_threshold=price_threshold,
                sentiment_threshold=sentiment_threshold,
                origin="watchlist",
            )
            drafts = [draft for draft in drafts if draft.bar_date == day]
            async with pool.acquire() as conn:
                if drafts:
                    for draft in drafts:
                        written.append(await upsert_alert(conn, draft))
                else:
                    await clear_symbol_day(conn, symbol, day)
    return {"alerts": written}


async def reason_alert_drafts(
    pool: asyncpg.Pool, drafts: list[Any]
) -> tuple[list[Any], str, str | None]:
    """Ask Perplexity for richer news / news+price write-ups when a key is saved.

    Price-only alerts keep the deterministic rule sentence. Used by Scan today and
    the live price → news upgrade path.
    """
    from .perplexity import drafts_for_reasoning

    if not drafts:
        return drafts, "rules", None
    async with pool.acquire() as conn:
        saved = await perplexity_api_key(conn)
        model = known_model(await perplexity_model(conn))
    key = saved or settings.perplexity_api_key.strip()
    if not key:
        return drafts, "rules", None
    eligible = drafts_for_reasoning(drafts)
    if not eligible:
        return drafts, "rules", None
    updated: list[Any] = list(drafts)
    errors: list[str] = []
    # One response has to hold several sentences per alert. A five-day rebuild is too
    # many for a single reply, so the call is split and each batch keeps its own result.
    for start in range(0, len(eligible), _REASON_BATCH):
        batch = eligible[start : start + _REASON_BATCH]
        part, error = await asyncio.to_thread(complete_reasoning, key, batch, model)
        by_key = {(draft.symbol, draft.bar_date): draft for draft in part}
        updated = [by_key.get((draft.symbol, draft.bar_date), draft) for draft in updated]
        if error:
            errors.append(error)
    from .perplexity import drafts_for_reasoning as _eligible

    missed = [
        draft
        for draft in _eligible(updated)
        if "model_label" not in (draft.sections or {})
    ]
    if missed and len(missed) < len(eligible):
        part, error = await asyncio.to_thread(complete_reasoning, key, missed, model)
        by_key = {(draft.symbol, draft.bar_date): draft for draft in part}
        updated = [by_key.get((draft.symbol, draft.bar_date), draft) for draft in updated]
        if error:
            errors.append(error)
    if errors and not any("model_label" in draft.sections for draft in updated):
        return updated, "rules", errors[0]
    if errors:
        return updated, "perplexity", errors[0]
    return updated, "perplexity", None


# Back-compat for any older imports / tests.
_reason = reason_alert_drafts


def rebuild_start(today: date, days: int) -> date:
    """First calendar day of a rebuild. ``days`` of 1 is today only."""
    if isinstance(days, bool) or not isinstance(days, int) or days < 1 or days > MAX_REBUILD_DAYS:
        raise ValueError(f"Days must be a whole number from 1 to {MAX_REBUILD_DAYS}.")
    return today - timedelta(days=days - 1)


async def rebuild_history(pool: asyncpg.Pool, *, days: int, now: datetime | None = None) -> dict[str, Any]:
    """Clear Watchlist history only, then rerun rules over the last ``days`` calendar days.

    Live rows are left alone (``both`` is demoted to live first). Each watchlist symbol
    is checked once per trading session in that window. Yahoo's quote news is paged
    back through the first day of the window, and each story is scored for the trading
    day it was published. A past day is judged as of 8:00 PM Eastern, so that day's
    headlines fall inside the news lookback.
    """
    moment = now or datetime.now(UTC)
    today = eastern_date(moment)
    start = rebuild_start(today, days)
    async with pool.acquire() as conn:
        rules = await get_alert_rules(conn)
        symbols = [row["symbol"] for row in await list_watchlist(conn)]
        cleared = await clear_watchlist_alerts(conn)
        await ensure_symbol_sectors(conn, symbols)

    errors: list[dict[str, str]] = []
    pending: list[Any] = []
    forest = load_watchlist_forest_scorer()
    fetch_days = days + settings.volume_lookback + 5
    for symbol in symbols:
        try:
            bars = await asyncio.to_thread(fetch_daily_bars, symbol, lookback_days=fetch_days)
            headlines = await asyncio.to_thread(fetch_headlines, symbol, through=start)
        except Exception as exc:
            errors.append({"symbol": symbol, "error": str(exc)})
            continue
        in_window = [
            item
            for item in headlines
            if start <= headline_session(item["published_at"]) <= today
        ]
        async with pool.acquire() as conn:
            if bars:
                await upsert_bars(conn, symbol, bars)
            stored_bars = await load_bars(conn, symbol)
            stored_news = await _headlines_for_rules(
                conn, symbol, in_window, "finbert"
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
                drafts = apply_forest_to_drafts(
                    [draft for draft in drafts if draft.bar_date == day],
                    scorer=forest,
                    symbol=symbol,
                    bars=bars_asof,
                    session_day=day,
                    now=as_of,
                    price_move_threshold=rules["price_move_threshold"],
                    sentiment_threshold=rules["sentiment_threshold"],
                    origin="watchlist",
                )
                for draft in drafts:
                    if draft.bar_date == day:
                        pending.append(draft)
    pending = [attach_evidence_story(draft) for draft in pending]
    reasoned, reasoning, reasoning_error = await reason_alert_drafts(pool, pending)
    reasoned = [attach_evidence_story(draft) for draft in reasoned]
    saved: list[dict[str, Any]] = []
    async with pool.acquire() as conn:
        for draft in reasoned:
            saved.append(await upsert_alert(conn, draft))
    return {
        "days": days,
        "start": start.isoformat(),
        "checked": symbols,
        "cleared": cleared,
        "errors": errors,
        "alerts": saved,
        "reasoning": reasoning,
        "reasoning_error": reasoning_error,
    }
