"""After a live price alert: fetch near-term headlines, join like Scan today, optional Perplexity."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import asyncpg

from .checks import _headlines_for_rules, reason_alert_drafts
from .config import settings
from .engine import AlertDraft, eastern_date, evaluate_symbol
from .evidence import attach_evidence_story
from .forest_wording import enrich_price_draft_with_forest_wording
from .live_session import SessionState
from .news import fetch_headlines
from .store import load_bars

log = logging.getLogger(__name__)


async def upgrade_price_draft_with_news(
    pool: asyncpg.Pool,
    draft: AlertDraft,
    state: SessionState,
    *,
    price_move_threshold: float,
    sentiment_threshold: float,
    now: datetime | None = None,
) -> AlertDraft:
    """Same join rules as Scan today: price first, then near-term headlines for the live session."""
    moment = now or datetime.now(UTC)
    try:
        raw = await asyncio.to_thread(fetch_headlines, state.symbol)
    except Exception as exc:
        log.warning("Live news fetch failed for %s: %s", state.symbol, exc)
        return attach_evidence_story(draft)

    async with pool.acquire() as conn:
        scored = await _headlines_for_rules(conn, state.symbol, raw, "finbert")
        bars = await load_bars(conn, state.symbol)

    drafts = evaluate_symbol(
        symbol=state.symbol,
        bars=bars,
        headlines=scored,
        now=moment,
        price_move_threshold=price_move_threshold,
        volume_spike_threshold=settings.volume_spike_threshold,
        volume_lookback=settings.volume_lookback,
        sentiment_threshold=sentiment_threshold,
        news_lookback_hours=settings.news_lookback_hours,
        fusion_window_hours=settings.fusion_window_hours,
        live_session={"price": state.last, "open": state.open},
    )
    today = eastern_date(moment)
    kept = [item for item in drafts if item.bar_date == today]
    if not kept:
        return attach_evidence_story(draft)

    # evaluate_symbol defaults origin to watchlist; keep the live tag from the price draft.
    live_origin = draft.origin if draft.origin in ("live", "both") else "live"
    result = replace(kept[0], origin=live_origin)
    forest = (draft.sections or {}).get("forest")
    if isinstance(forest, dict):
        sections = dict(result.sections or {})
        sections["forest"] = forest
        result = replace(result, sections=sections)
        # Price-only: rebuild Summary/Price with forest-aware deterministic wording.
        # News / news_price: keep Together text; enrich only the Price accordion.
        result = enrich_price_draft_with_forest_wording(result)

    result = attach_evidence_story(result)
    if result.kind in ("news", "news_price"):
        reasoned, _source, error = await reason_alert_drafts(pool, [result])
        if error:
            log.warning("Live Perplexity reasoning failed for %s: %s", state.symbol, error)
        result = reasoned[0] if reasoned else result
        # Re-apply forest Price section after Perplexity overwrites synthesis.
        result = enrich_price_draft_with_forest_wording(result)
        result = attach_evidence_story(result)
        # Perplexity / evidence helpers must not drop the live origin tag.
        if result.origin != live_origin:
            result = replace(result, origin=live_origin)
    return result


def should_write_live_alert(existing: dict[str, Any] | None, draft: AlertDraft) -> bool:
    """Live may insert/refresh price and may upgrade price → news / news_price.

    Never overwrite a news or news_price row that already exists from Scan today with a
    weaker price-only draft. Upgrading price → news_price is allowed.
    """
    if existing is None:
        return True
    existing_kind = existing.get("kind")
    if existing_kind == "price":
        return True
    if existing_kind in ("news", "news_price") and draft.kind in ("news", "news_price"):
        # Refresh an earlier live upgrade with newer prints / headlines.
        return True
    return False
