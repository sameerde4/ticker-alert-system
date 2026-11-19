"""Turn a live session state into a price AlertDraft when the move clears the rule."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .engine import AlertDraft, cash_session_open, price_change_pct, price_summary
from .live_session import SessionState


def price_draft_from_session(
    state: SessionState,
    *,
    price_move_threshold: float,
    sentiment_threshold: float,
    now: datetime | None = None,
) -> AlertDraft | None:
    """Build a price alert when open → last clears the saved percent during RTH."""
    moment = now or datetime.now(UTC)
    if not cash_session_open(moment):
        return None
    if eastern_day_mismatch(state, moment):
        return None
    change = price_change_pct(state.last, state.open)
    if change is None or abs(change) < price_move_threshold:
        return None
    return AlertDraft(
        kind="price",
        symbol=state.symbol,
        bar_date=state.session_day,
        headline_id=None,
        price_change_pct=change,
        latest_close=state.last,
        prior_close=state.open,
        volume_ratio=None,
        volume_spike=False,
        sentiment_score=None,
        headline_title=None,
        summary=price_summary(
            state.symbol,
            change,
            state.last,
            state.open,
            None,
            False,
            price_move_threshold=price_move_threshold,
            volume_spike_threshold=2.0,
            from_open=True,
        ),
        triggered_at=state.last_ts.astimezone(UTC) if state.last_ts.tzinfo else state.last_ts.replace(tzinfo=UTC),
        price_move_threshold=price_move_threshold,
        sentiment_threshold=sentiment_threshold,
    )


def eastern_day_mismatch(state: SessionState, now: datetime) -> bool:
    from .engine import eastern_date

    return state.session_day != eastern_date(now)


def should_write_live_price(existing: dict[str, Any] | None) -> bool:
    """Live path only inserts or refreshes a price row. News / news_price stay untouched."""
    if existing is None:
        return True
    return existing.get("kind") == "price"
