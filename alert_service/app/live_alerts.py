"""Turn a live session state into a price AlertDraft when the move clears the rule."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .engine import PRICE_SPAN, AlertDraft, cash_session_open, price_change_pct, price_summary
from .forest_live import ForestScore
from .forest_wording import enrich_price_draft_with_forest_wording, forest_price_summary
from .live_session import SessionState


def dominant_product_price_move(
    *,
    open_px: float,
    last_px: float,
    prior_close: float | None,
    price_move_threshold: float,
) -> tuple[str, float, float, float]:
    """Pick the product price print for a live/forest card.

    Open→last is the RTH percent gate, but a huge overnight gap (or last vs prior
    close) is what humans mean by "the stock is up/down today." Prefer any slice
    that clears the Settings floor; among those (or overall) prefer
    prior→last, then gap, then open→last.
    """
    session = price_change_pct(last_px, open_px)
    candidates: list[tuple[str, float, float, float]] = []
    if session is not None:
        candidates.append(("live", session, open_px, last_px))
    if prior_close is not None and prior_close > 0:
        gap = price_change_pct(open_px, prior_close)
        close = price_change_pct(last_px, prior_close)
        if gap is not None:
            candidates.append(("gap", gap, prior_close, open_px))
        if close is not None:
            candidates.append(("close", close, prior_close, last_px))
    if not candidates:
        # Degenerate: still return open→last zeros rather than crash.
        return ("live", 0.0, open_px, last_px)

    # When several slices clear the floor, prefer prior→last (the day move people
    # mean), then gap, then open→last. Otherwise take the loudest absolute print.
    preference = {"close": 0, "gap": 1, "live": 2}
    clearing = [row for row in candidates if abs(row[1]) >= float(price_move_threshold)]
    if clearing:
        clearing.sort(key=lambda row: (preference.get(row[0], 9), -abs(row[1])))
        name, change, start_px, end_px = clearing[0]
        return name, change, start_px, end_px
    candidates.sort(key=lambda row: (-abs(row[1]), preference.get(row[0], 9)))
    name, change, start_px, end_px = candidates[0]
    return name, change, start_px, end_px


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
        sections={"price_span": PRICE_SPAN["live"]},
        triggered_at=state.last_ts.astimezone(UTC) if state.last_ts.tzinfo else state.last_ts.replace(tzinfo=UTC),
        price_move_threshold=price_move_threshold,
        sentiment_threshold=sentiment_threshold,
        origin="live",
    )


def forest_price_draft_from_session(
    state: SessionState,
    scored: ForestScore,
    *,
    price_move_threshold: float,
    sentiment_threshold: float,
    now: datetime | None = None,
    prior_close: float | None = None,
) -> AlertDraft | None:
    """Build a price alert when the registered Isolation Forest marks the session anomalous."""
    moment = now or datetime.now(UTC)
    if not cash_session_open(moment):
        return None
    if eastern_day_mismatch(state, moment):
        return None
    if not scored.anomalous:
        return None
    # Prefer true prior close when the scorer had one; otherwise recover from gap.
    prior = prior_close
    if prior is None or prior <= 0:
        gap = scored.features.get("gap_return") if isinstance(scored.features, dict) else None
        try:
            if gap is not None and float(gap) > -0.999:
                prior = state.open / (1.0 + float(gap))
        except (TypeError, ValueError, ZeroDivisionError):
            prior = None
    span_key, change, start_px, end_px = dominant_product_price_move(
        open_px=state.open,
        last_px=state.last,
        prior_close=prior if prior and prior > 0 else None,
        price_move_threshold=price_move_threshold,
    )
    session_change = price_change_pct(state.last, state.open)
    summary = forest_price_summary(
        state.symbol,
        model_id=scored.model_id,
        forest_score=scored.forest_score,
        score_cutoff=scored.score_cutoff,
        features=scored.features,
        open_px=state.open,
        last_px=state.last,
        price_move_threshold=price_move_threshold,
        change=session_change,
        product_change=change,
        product_span=span_key,
        from_px=start_px,
        to_px=end_px,
    )
    span_caption = PRICE_SPAN.get(span_key, PRICE_SPAN["live"])
    draft = AlertDraft(
        kind="price",
        symbol=state.symbol,
        bar_date=state.session_day,
        headline_id=None,
        price_change_pct=change,
        latest_close=end_px,
        prior_close=start_px,
        volume_ratio=None,
        volume_spike=False,
        sentiment_score=None,
        headline_title=None,
        summary=summary,
        sections={
            "forest": {
                "model_id": scored.model_id,
                "forest_score": scored.forest_score,
                "score_cutoff": scored.score_cutoff,
                "anomalous": True,
                "features": scored.features,
                "session_open": state.open,
                "session_last": state.last,
                "prior_close": prior if prior and prior > 0 else None,
                "product_span": span_key,
            },
            "entry": "price",
            "second_supports": False,
            "price_span": span_caption,
        },
        triggered_at=state.last_ts.astimezone(UTC) if state.last_ts.tzinfo else state.last_ts.replace(tzinfo=UTC),
        price_move_threshold=price_move_threshold,
        sentiment_threshold=sentiment_threshold,
        origin="live",
    )
    return enrich_price_draft_with_forest_wording(draft)


def eastern_day_mismatch(state: SessionState, now: datetime) -> bool:
    from .engine import eastern_date

    return state.session_day != eastern_date(now)


def forest_alone_under_percent(draft: AlertDraft, price_move_threshold: float) -> bool:
    """True when forest fired but every product price print is under the Settings floor.

    Checks the draft print plus forest gap / session / close features. A huge
    overnight gap that clears the floor is not "under percent" just because
    open→last was flat. Those rows need news support before we keep a bare
    forest-only card when still under every print.
    """
    forest = (draft.sections or {}).get("forest")
    if not isinstance(forest, dict) or not forest.get("anomalous"):
        return False
    floor = float(price_move_threshold)
    candidates: list[float] = []
    try:
        if draft.price_change_pct is not None:
            candidates.append(abs(float(draft.price_change_pct)))
    except (TypeError, ValueError):
        pass
    features = forest.get("features") if isinstance(forest.get("features"), dict) else {}
    for key in ("gap_return", "session_return", "close_return"):
        try:
            value = features.get(key)
            if value is not None:
                candidates.append(abs(float(value)))
        except (TypeError, ValueError):
            continue
    if any(value >= floor for value in candidates):
        return False
    return True


def should_write_live_price(existing: dict[str, Any] | None) -> bool:
    """Legacy helper: live may refresh a missing or price-only day.

    Prefer ``should_write_live_alert`` when the draft may upgrade to news / news_price.
    """
    if existing is None:
        return True
    return existing.get("kind") == "price"
