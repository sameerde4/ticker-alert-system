"""Retroactively attach FinBERT climate to price-led alerts that were saved without it."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import UTC, date, datetime, time
from typing import Any

import asyncpg

from .checks import _headlines_for_rules
from .config import settings
from .engine import EASTERN, AlertDraft, evaluate_symbol
from .evidence import attach_evidence_story
from .forest_wording import enrich_price_draft_with_forest_wording
from .news import fetch_headlines
from .store import get_alert_rules, list_price_alerts_missing_climate, load_bars, upsert_alert

log = logging.getLogger(__name__)


def _parse_day(value: Any) -> date | None:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str) and value:
        return date.fromisoformat(value[:10])
    return None


def _as_of_for_day(day: date, now: datetime) -> datetime:
    today = now.astimezone(EASTERN).date()
    if day == today:
        return now
    return datetime.combine(day, time(20, 0), tzinfo=EASTERN)


def draft_from_price_alert(alert: dict[str, Any]) -> AlertDraft | None:
    """Rebuild a price AlertDraft from a saved row (keeps forest / price span)."""
    day = _parse_day(alert.get("bar_date"))
    if day is None:
        return None
    sections = alert.get("sections") if isinstance(alert.get("sections"), dict) else {}
    triggered = alert.get("triggered_at")
    if isinstance(triggered, str):
        try:
            triggered = datetime.fromisoformat(triggered.replace("Z", "+00:00"))
        except ValueError:
            triggered = None
    return AlertDraft(
        kind="price",
        symbol=str(alert["symbol"]),
        bar_date=day,
        headline_id=None,
        price_change_pct=alert.get("price_change_pct"),
        latest_close=alert.get("latest_close"),
        prior_close=alert.get("prior_close"),
        volume_ratio=alert.get("volume_ratio"),
        volume_spike=bool(alert.get("volume_spike")),
        sentiment_score=None,
        headline_title=None,
        summary=str(alert.get("summary") or ""),
        articles=(),
        sections=dict(sections),
        triggered_at=triggered,
        price_move_threshold=alert.get("price_move_threshold"),
        sentiment_threshold=alert.get("sentiment_threshold"),
        origin=str(alert.get("origin") or "watchlist"),
    )


def _merge_preserved(result: AlertDraft, seed: AlertDraft) -> AlertDraft:
    """Keep origin + forest block from the saved price row after climate refresh."""
    from dataclasses import replace

    sections = dict(result.sections or {})
    seed_sections = seed.sections if isinstance(seed.sections, dict) else {}
    forest = seed_sections.get("forest")
    if isinstance(forest, dict) and "forest" not in sections:
        sections["forest"] = forest
    if seed_sections.get("price_span") and not sections.get("price_span"):
        sections["price_span"] = seed_sections["price_span"]
    origin = seed.origin if seed.origin in ("live", "watchlist", "both") else result.origin
    out = replace(result, origin=origin, sections=sections)
    if isinstance(forest, dict) and forest.get("anomalous"):
        out = enrich_price_draft_with_forest_wording(out)
    return out


async def backfill_price_alert_climate(
    pool: asyncpg.Pool,
    *,
    limit: int = 500,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Re-fetch/score near-term headlines for price-led rows missing climate sentiment.

    Preserves each row's price levels, origin, and forest block; re-runs the current
    FinBERT climate / join logic on top.
    """
    moment = now or datetime.now(UTC)
    async with pool.acquire() as conn:
        rules = await get_alert_rules(conn)
        targets = await list_price_alerts_missing_climate(conn, limit=limit)

    by_symbol: dict[str, list[dict[str, Any]]] = {}
    for row in targets:
        by_symbol.setdefault(str(row["symbol"]), []).append(row)

    updated: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    errors: list[dict[str, str]] = []

    for symbol, rows in by_symbol.items():
        try:
            raw = await asyncio.to_thread(fetch_headlines, symbol)
        except Exception as exc:
            log.warning("Climate backfill fetch failed for %s: %s", symbol, exc)
            errors.append({"symbol": symbol, "error": str(exc)})
            continue
        async with pool.acquire() as conn:
            try:
                scored = await _headlines_for_rules(conn, symbol, raw, "finbert")
                bars = await load_bars(conn, symbol)
            except Exception as exc:
                errors.append({"symbol": symbol, "error": str(exc)})
                continue
            for alert in rows:
                seed = draft_from_price_alert(alert)
                if seed is None:
                    skipped.append({"symbol": symbol, "reason": "missing_bar_date"})
                    continue
                day = seed.bar_date
                assert day is not None
                as_of = _as_of_for_day(day, moment)
                try:
                    drafts = evaluate_symbol(
                        symbol=symbol,
                        bars=bars,
                        headlines=scored,
                        now=as_of,
                        price_move_threshold=float(
                            alert.get("price_move_threshold")
                            or rules["price_move_threshold"]
                        ),
                        volume_spike_threshold=settings.volume_spike_threshold,
                        volume_lookback=settings.volume_lookback,
                        sentiment_threshold=float(
                            alert.get("sentiment_threshold")
                            or rules["sentiment_threshold"]
                        ),
                        news_lookback_hours=settings.news_lookback_hours,
                        fusion_window_hours=settings.fusion_window_hours,
                        seed_price_draft=seed,
                    )
                except Exception as exc:
                    errors.append({"symbol": symbol, "error": str(exc)})
                    continue
                kept = [item for item in drafts if item.bar_date == day]
                if not kept:
                    skipped.append({"symbol": symbol, "reason": "no_draft"})
                    continue
                result = _merge_preserved(kept[0], seed)
                result = attach_evidence_story(result)
                saved = await upsert_alert(conn, result)
                updated.append(
                    {
                        "symbol": saved["symbol"],
                        "bar_date": saved["bar_date"],
                        "kind": saved["kind"],
                        "sentiment_score": saved.get("sentiment_score"),
                        "articles": len(saved.get("articles") or []),
                        "news_join_path": (saved.get("sections") or {}).get("news_join_path"),
                    }
                )

    return {
        "candidates": len(targets),
        "symbols": len(by_symbol),
        "updated": updated,
        "updated_count": len(updated),
        "skipped": skipped,
        "errors": errors,
    }


def draft_from_alert_row(alert: dict[str, Any]) -> AlertDraft | None:
    """Rebuild any saved alert row so evidence can be re-stamped without re-scoring."""
    day = _parse_day(alert.get("bar_date"))
    if day is None:
        return None
    sections = alert.get("sections") if isinstance(alert.get("sections"), dict) else {}
    triggered = alert.get("triggered_at")
    if isinstance(triggered, str):
        try:
            triggered = datetime.fromisoformat(triggered.replace("Z", "+00:00"))
        except ValueError:
            triggered = None
    articles = alert.get("articles") or []
    if not isinstance(articles, list):
        articles = []
    return AlertDraft(
        kind=str(alert.get("kind") or "price"),
        symbol=str(alert["symbol"]),
        bar_date=day,
        headline_id=None,
        price_change_pct=alert.get("price_change_pct"),
        latest_close=alert.get("latest_close"),
        prior_close=alert.get("prior_close"),
        volume_ratio=alert.get("volume_ratio"),
        volume_spike=bool(alert.get("volume_spike")),
        sentiment_score=alert.get("sentiment_score"),
        headline_title=alert.get("headline_title"),
        summary=str(alert.get("summary") or ""),
        articles=tuple(articles),
        sections=dict(sections),
        triggered_at=triggered,
        price_move_threshold=alert.get("price_move_threshold"),
        sentiment_threshold=alert.get("sentiment_threshold"),
        origin=str(alert.get("origin") or "watchlist"),
    )


async def restamp_evidence_stories(
    pool: asyncpg.Pool,
    *,
    limit: int = 500,
) -> dict[str, Any]:
    """Re-attach What happened for recent alerts (fixes Live news-led showing news→price).

    Patches ``sections`` only — does not bump ``updated_at`` or rewrite timeline history.
    """
    from .store import list_alerts

    async with pool.acquire() as conn:
        rows = await list_alerts(conn, limit=limit)

    updated: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    async with pool.acquire() as conn:
        for alert in rows:
            draft = draft_from_alert_row(alert)
            if draft is None:
                skipped.append({"symbol": str(alert.get("symbol")), "reason": "bad_row"})
                continue
            old_evidence = (alert.get("sections") or {}).get("evidence") or {}
            repaired = attach_evidence_story(draft)
            new_sections = repaired.sections or {}
            new_evidence = new_sections.get("evidence") or {}
            # Compare the full evidence block so Price noticed copy refreshes too.
            if json.dumps(old_evidence, sort_keys=True, default=str) == json.dumps(
                new_evidence, sort_keys=True, default=str
            ) and (alert.get("sections") or {}).get("entry") == new_sections.get("entry"):
                skipped.append({"symbol": draft.symbol, "reason": "unchanged"})
                continue
            await conn.execute(
                """
                UPDATE alerts
                SET sections = $3::jsonb
                WHERE symbol = $1 AND bar_date = $2
                """,
                draft.symbol,
                draft.bar_date,
                json.dumps(new_sections),
            )
            updated.append(
                {
                    "symbol": draft.symbol,
                    "kind": draft.kind,
                    "origin": draft.origin,
                    "entry": new_evidence.get("entry"),
                    "headline": new_evidence.get("headline"),
                }
            )
    return {
        "candidates": len(rows),
        "updated": updated,
        "updated_count": len(updated),
        "skipped": skipped,
    }
