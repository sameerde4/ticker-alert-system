"""Experimental S&P 500 Screener: rank session movers, then grade headlines for the top names.

Price screening reads the local lake (fast). Headlines + FinBERT run only for the top N
matches so a full-index Yahoo fan-out is avoided. Results are ephemeral — they do not
write the alerts table (test feature beside Live / Watchlist).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from .config import settings
from .engine import (
    AlertDraft,
    cash_session_open,
    eastern_date,
    evaluate_symbol,
    price_change_pct,
    scan_focus_moment,
)
from .evidence import attach_evidence_story
from .news import fetch_headlines
from .prices import fetch_open_to_last
from .scoring import attach_scores
from .symbols import universe_symbols
from .watchlist_forest import apply_forest_to_drafts, load_watchlist_forest_scorer

log = logging.getLogger(__name__)

DEFAULT_SCREENER_LIMIT = 10
_MAX_SCREENER_LIMIT = 25


def _lake_root() -> Path:
    return Path(settings.lake_root)


def _raw_daily_path(symbol: str) -> Path:
    return _lake_root() / "raw" / "prices" / "daily" / f"symbol={symbol.upper()}" / "part-000.parquet"


def load_lake_bars(symbol: str, *, through: date, lookback_days: int = 40) -> list[dict[str, Any]]:
    """Daily bars from the lake for one symbol, oldest first, ending at ``through``."""
    import pandas as pd

    path = _raw_daily_path(symbol)
    if not path.is_file():
        return []
    try:
        frame = pd.read_parquet(path)
    except Exception as exc:
        log.warning("Screener could not read %s (%s)", path, exc)
        return []
    if frame is None or frame.empty or "dt" not in frame.columns or "close" not in frame.columns:
        return []
    frame = frame.copy()
    frame["dt"] = pd.to_datetime(frame["dt"], errors="coerce")
    frame = frame.dropna(subset=["dt"])
    if frame.empty:
        return []
    frame["dt"] = frame["dt"].dt.date
    frame = frame[frame["dt"] <= through].sort_values("dt")
    if frame.empty:
        return []
    if lookback_days > 0:
        frame = frame.tail(max(lookback_days, 2))
    rows: list[dict[str, Any]] = []
    for _, row in frame.iterrows():
        close = _as_float(row.get("close"))
        if close is None or close <= 0:
            continue
        rows.append(
            {
                "dt": row["dt"],
                "open": _as_float(row.get("open")) or close,
                "high": _as_float(row.get("high")) or close,
                "low": _as_float(row.get("low")) or close,
                "close": close,
                "volume": int(_as_float(row.get("volume")) or 0),
            }
        )
    return rows


def session_move_from_bars(
    bars: list[dict[str, Any]], *, session_day: date
) -> dict[str, Any] | None:
    """Close-vs-prior move for ``session_day`` (or the latest bar on/before that day)."""
    if len(bars) < 2:
        return None
    # Prefer an exact session_day bar; otherwise the latest bar on or before it.
    latest_idx = None
    for i in range(len(bars) - 1, -1, -1):
        if bars[i]["dt"] <= session_day:
            latest_idx = i
            break
    if latest_idx is None or latest_idx == 0:
        return None
    latest = bars[latest_idx]
    prior = bars[latest_idx - 1]
    change = price_change_pct(latest.get("close"), prior.get("close"))
    if change is None:
        return None
    return {
        "bar_date": latest["dt"],
        "latest_close": float(latest["close"]),
        "prior_close": float(prior["close"]),
        "change_pct": float(change),
        "bars": bars,
    }


def rank_session_movers(
    *,
    session_day: date,
    change_percent: float,
    limit: int = DEFAULT_SCREENER_LIMIT,
    symbols: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Scan lake dailies for names that clear the signed % filter; return top ``limit``.

    Positive ``change_percent`` (e.g. 3) keeps movers ≥ +3%, ranked largest gain first.
    Negative (e.g. -3) keeps movers ≤ -3%, ranked largest decline first.
    """
    threshold = float(change_percent) / 100.0
    if threshold == 0:
        raise ValueError("Enter a non-zero percent filter (for example 3 or -3).")
    cap = max(1, min(int(limit), _MAX_SCREENER_LIMIT))
    names = symbols if symbols is not None else universe_symbols()
    hits: list[dict[str, Any]] = []
    scanned = 0
    missing_lake = 0
    for symbol in names:
        bars = load_lake_bars(symbol, through=session_day)
        if not bars:
            missing_lake += 1
            continue
        scanned += 1
        move = session_move_from_bars(bars, session_day=session_day)
        if move is None:
            continue
        change = move["change_pct"]
        if threshold > 0 and change < threshold:
            continue
        if threshold < 0 and change > threshold:
            continue
        hits.append(
            {
                "symbol": symbol,
                "change_pct": change,
                "bar_date": move["bar_date"],
                "latest_close": move["latest_close"],
                "prior_close": move["prior_close"],
                "bars": move["bars"],
            }
        )
    reverse = threshold > 0
    hits.sort(key=lambda row: row["change_pct"], reverse=reverse)
    top = hits[:cap]
    for rank, row in enumerate(top, start=1):
        row["rank"] = rank
    return top


def draft_as_alert(draft: AlertDraft, *, rank: int | None = None) -> dict[str, Any]:
    """Shape an ephemeral draft like a stored alert row for the card UI."""
    bar = draft.bar_date.isoformat() if draft.bar_date else None
    payload: dict[str, Any] = {
        "id": f"screener-{draft.symbol}-{bar or 'none'}",
        "symbol": draft.symbol,
        "kind": draft.kind,
        "bar_date": bar,
        "headline_id": draft.headline_id,
        "price_change_pct": draft.price_change_pct,
        "latest_close": draft.latest_close,
        "prior_close": draft.prior_close,
        "volume_ratio": draft.volume_ratio,
        "volume_spike": draft.volume_spike,
        "sentiment_score": draft.sentiment_score,
        "headline_title": draft.headline_title,
        "summary": draft.summary,
        "articles": list(draft.articles),
        "sections": dict(draft.sections or {}),
        "triggered_at": draft.triggered_at.isoformat() if draft.triggered_at else None,
        "updated_at": None,
        "created_at": None,
        "price_move_threshold": draft.price_move_threshold,
        "sentiment_threshold": draft.sentiment_threshold,
        "origin": "screener",
    }
    if rank is not None:
        payload["screener_rank"] = rank
    return payload


async def run_screener(
    pool: Any | None = None,
    *,
    change_percent: float,
    limit: int = DEFAULT_SCREENER_LIMIT,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Rank lake movers, then run headline grade + forest on the top names only."""
    moment = now or datetime.now(UTC)
    focus = scan_focus_moment(moment)
    focus_day = eastern_date(focus)
    threshold_pct = float(change_percent)
    if threshold_pct == 0:
        raise ValueError("Enter a non-zero percent filter (for example 3 or -3).")
    cap = max(1, min(int(limit), _MAX_SCREENER_LIMIT))

    top = await asyncio.to_thread(
        rank_session_movers,
        session_day=focus_day,
        change_percent=threshold_pct,
        limit=cap,
    )
    forest = load_watchlist_forest_scorer()
    # Screener uses the signed filter as the price gate for evaluate_symbol.
    price_threshold = abs(threshold_pct) / 100.0
    sentiment_threshold = float(settings.sentiment_threshold)
    if pool is not None:
        try:
            from .store import get_alert_rules

            async with pool.acquire() as conn:
                rules = await get_alert_rules(conn)
            sentiment_threshold = float(rules["sentiment_threshold"])
        except Exception:
            pass

    alerts: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for row in top:
        symbol = row["symbol"]
        try:
            headlines = await asyncio.to_thread(fetch_headlines, symbol)
            scored = attach_scores(
                [
                    {
                        **item,
                        "id": item.get("id") or str(uuid.uuid4()),
                        "sentiment_score": item.get("sentiment_score", 50.0),
                    }
                    for item in headlines
                ],
                "finbert",
            )
            live = None
            if cash_session_open(moment):
                live = await asyncio.to_thread(fetch_open_to_last, symbol, now=moment)
            drafts = evaluate_symbol(
                symbol=symbol,
                bars=row["bars"],
                headlines=scored,
                now=focus,
                price_move_threshold=price_threshold,
                volume_spike_threshold=settings.volume_spike_threshold,
                volume_lookback=settings.volume_lookback,
                sentiment_threshold=sentiment_threshold,
                news_lookback_hours=settings.news_lookback_hours,
                fusion_window_hours=settings.fusion_window_hours,
                live_session=live,
            )
            drafts = apply_forest_to_drafts(
                drafts,
                scorer=forest,
                symbol=symbol,
                bars=row["bars"],
                session_day=focus_day,
                now=focus,
                price_move_threshold=price_threshold,
                sentiment_threshold=sentiment_threshold,
                live_session=live,
                origin="screener",
            )
            kept = [
                attach_evidence_story(draft)
                for draft in drafts
                if draft.bar_date == row["bar_date"] or draft.bar_date == focus_day
            ]
            if not kept:
                # Always surface a price card for a ranked mover even if evaluate
                # skipped (e.g. focus-day mismatch on sparse bars).
                kept = [
                    attach_evidence_story(
                        AlertDraft(
                            kind="price",
                            symbol=symbol,
                            bar_date=row["bar_date"],
                            headline_id=None,
                            price_change_pct=row["change_pct"],
                            latest_close=row["latest_close"],
                            prior_close=row["prior_close"],
                            volume_ratio=None,
                            volume_spike=False,
                            sentiment_score=None,
                            headline_title=None,
                            summary=(
                                f"{symbol} moved {_fmt_pct(row['change_pct'])} on the "
                                f"screener session ({row['bar_date'].isoformat()})."
                            ),
                            sections={
                                "price": (
                                    f"Screener rank #{row['rank']}: "
                                    f"{_fmt_pct(row['change_pct'])} close versus prior close."
                                ),
                                "entry": "price",
                                "second_supports": False,
                                "price_span": "prior close → close",
                            },
                            triggered_at=focus,
                            price_move_threshold=price_threshold,
                            sentiment_threshold=sentiment_threshold,
                            origin="screener",
                        )
                    )
                ]
            for draft in kept:
                alerts.append(draft_as_alert(draft, rank=row["rank"]))
        except Exception as exc:
            log.exception("Screener failed for %s", symbol)
            errors.append({"symbol": symbol, "error": str(exc)})

    # Ephemeral test feature: skip Perplexity; cards keep deterministic / FinBERT wording.
    _ = pool

    return {
        "focus_day": focus_day.isoformat(),
        "change_percent": threshold_pct,
        "limit": cap,
        "matched": len(top),
        "screened_from": "lake",
        "candidates": [
            {
                "rank": row["rank"],
                "symbol": row["symbol"],
                "change_pct": row["change_pct"],
                "bar_date": row["bar_date"].isoformat(),
            }
            for row in top
        ],
        "errors": errors,
        "alerts": alerts,
        "reasoning": "rules",
        "reasoning_error": None,
        "ephemeral": True,
        "note": (
            "Test screener: ranked from lake session closes, then headlines for the top names only. "
            "Results are not saved to Alert History."
        ),
    }


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fmt_pct(value: float) -> str:
    pct = value * 100.0
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.2f}%"
