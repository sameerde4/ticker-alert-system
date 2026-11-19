"""Apply the same Isolation Forest gate on Watchlist Scan today / rebuild as live.

Percent rule and forest are OR gates for a price-led day. Volume z-score is inside
the forest feature vector; the plain volume-spike note on daily closes is not a
standalone alert trigger.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from .config import settings
from .engine import PRICE_SPAN, AlertDraft, price_change_pct
from .forest_live import ForestScore, LiveForestScorer, history_from_daily_rows
from .forest_wording import enrich_price_draft_with_forest_wording, forest_price_summary

log = logging.getLogger(__name__)


def load_watchlist_forest_scorer() -> LiveForestScorer:
    """Same lake registry the live consumer uses."""
    return LiveForestScorer(Path(settings.lake_root))


def score_session_from_bars(
    scorer: LiveForestScorer,
    bars: list[dict[str, Any]],
    *,
    session_day: date,
    live_session: dict[str, float] | None = None,
) -> tuple[ForestScore, dict[str, float]] | None:
    """Score gap / session / close / volume-z for ``session_day`` (optional live last)."""
    if not scorer.enabled or not settings.live_forest_alerts:
        return None
    ordered = sorted(bars, key=lambda row: row["dt"])
    today_rows = [row for row in ordered if row["dt"] == session_day]
    if not today_rows:
        return None
    today = today_rows[-1]
    hist = history_from_daily_rows(ordered, session_day=session_day)
    if hist is None:
        return None
    try:
        open_px = float(today["open"])
        close_px = float(today["close"])
        volume = float(today.get("volume") or 0)
    except (TypeError, ValueError, KeyError):
        return None
    if live_session is not None:
        try:
            open_px = float(live_session["open"])
            close_px = float(live_session["price"])
        except (TypeError, ValueError, KeyError):
            return None
    if open_px <= 0 or close_px <= 0 or volume < 0:
        return None
    scored = scorer.score_session(
        open_px=open_px,
        last_px=close_px,
        prior_close=hist.prior_close,
        session_volume=volume,
        prior_volumes=hist.prior_volumes,
    )
    if scored is None:
        return None
    return scored, {
        "open": open_px,
        "last": close_px,
        "prior_close": hist.prior_close,
    }


def apply_forest_to_drafts(
    drafts: list[AlertDraft],
    *,
    scorer: LiveForestScorer,
    symbol: str,
    bars: list[dict[str, Any]],
    session_day: date,
    now: datetime,
    price_move_threshold: float,
    sentiment_threshold: float,
    live_session: dict[str, float] | None = None,
    origin: str = "watchlist",
) -> list[AlertDraft]:
    """OR the forest into Scan today / rebuild drafts the same way live does.

    - Forest anomalous + no draft → open a forest price-only row.
    - Forest anomalous + existing draft → attach ``sections.forest`` and enrich wording.
    - Forest not anomalous / unavailable → leave drafts unchanged.
    """
    scored_ctx = score_session_from_bars(
        scorer, bars, session_day=session_day, live_session=live_session
    )
    if scored_ctx is None:
        return drafts
    scored, levels = scored_ctx
    if not scored.anomalous:
        return drafts

    forest_block = {
        "model_id": scored.model_id,
        "forest_score": scored.forest_score,
        "score_cutoff": scored.score_cutoff,
        "anomalous": True,
        "features": scored.features,
        "session_open": levels["open"],
        "session_last": levels["last"],
        "prior_close": levels["prior_close"],
    }
    change = price_change_pct(levels["last"], levels["open"])
    moment = now if now.tzinfo else now.replace(tzinfo=UTC)

    if not drafts:
        summary = forest_price_summary(
            symbol,
            model_id=scored.model_id,
            forest_score=scored.forest_score,
            score_cutoff=scored.score_cutoff,
            features=scored.features,
            open_px=levels["open"],
            last_px=levels["last"],
            price_move_threshold=price_move_threshold,
            change=change,
        )
        draft = AlertDraft(
            kind="price",
            symbol=symbol,
            bar_date=session_day,
            headline_id=None,
            price_change_pct=change,
            latest_close=levels["last"],
            prior_close=levels["open"],
            volume_ratio=None,
            volume_spike=False,
            sentiment_score=None,
            headline_title=None,
            summary=summary,
            sections={
                "forest": forest_block,
                "entry": "price",
                "second_supports": False,
                "price_span": PRICE_SPAN["live"],
            },
            triggered_at=moment.astimezone(UTC),
            price_move_threshold=price_move_threshold,
            sentiment_threshold=sentiment_threshold,
            origin=origin,
        )
        return [enrich_price_draft_with_forest_wording(draft)]

    out: list[AlertDraft] = []
    for draft in drafts:
        sections = dict(draft.sections or {})
        sections["forest"] = forest_block
        merged = replace(draft, sections=sections, origin=draft.origin or origin)
        out.append(enrich_price_draft_with_forest_wording(merged))
    return out
