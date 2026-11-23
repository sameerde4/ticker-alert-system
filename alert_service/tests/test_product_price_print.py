"""Product price print for forest gap days (prior→last preferred over flat open→last)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app.engine import PRICE_SPAN, AlertDraft, _live_slices, evaluate_symbol
from app.forest_live import ForestScore
from app.live_alerts import (
    dominant_product_price_move,
    forest_alone_under_percent,
    forest_price_draft_from_session,
)
from app.live_session import SessionState


def test_dominant_print_prefers_close_when_gap_and_close_both_clear():
    span, change, start, end = dominant_product_price_move(
        open_px=120.0,
        last_px=121.0,
        prior_close=100.0,
        price_move_threshold=0.03,
    )
    assert span == "close"
    assert change == pytest.approx(0.21)
    assert start == 100.0
    assert end == 121.0


def test_dominant_print_uses_gap_when_only_gap_clears():
    # Gap +10%; session fades so prior→last is only +2% (under 3%).
    span, change, start, end = dominant_product_price_move(
        open_px=110.0,
        last_px=102.0,
        prior_close=100.0,
        price_move_threshold=0.03,
    )
    assert span == "gap"
    assert change == pytest.approx(0.10)
    assert start == 100.0
    assert end == 110.0


def test_dominant_print_falls_back_to_loudest_when_nothing_clears():
    # Nothing clears 3%; open→last is the loudest absolute print.
    span, change, start, end = dominant_product_price_move(
        open_px=100.0,
        last_px=101.0,
        prior_close=100.5,
        price_move_threshold=0.03,
    )
    assert span == "live"
    assert change == pytest.approx(0.01)
    assert start == 100.0
    assert end == 101.0


def test_forest_alone_false_when_gap_feature_clears_even_if_draft_session_flat():
    draft = AlertDraft(
        kind="price",
        symbol="NVDA",
        bar_date=date(2026, 11, 23),
        headline_id=None,
        price_change_pct=-0.001,
        latest_close=164.65,
        prior_close=164.82,
        volume_ratio=None,
        volume_spike=False,
        sentiment_score=None,
        headline_title=None,
        summary="x",
        sections={
            "forest": {
                "anomalous": True,
                "features": {
                    "gap_return": 0.21,
                    "session_return": -0.001,
                    "close_return": 0.20,
                    "volume_zscore": -1.0,
                },
            }
        },
        triggered_at=datetime(2026, 11, 23, 19, 0, tzinfo=UTC),
        price_move_threshold=0.04,
        sentiment_threshold=25,
        origin="live",
    )
    assert forest_alone_under_percent(draft, 0.04) is False


def test_seeded_evaluate_keeps_prior_close_product_print_on_gap_day():
    """News upgrade must not wipe a +20% prior→last forest print back to flat open→last."""
    eastern = ZoneInfo("America/New_York")
    now = datetime(2026, 11, 23, 14, 0, tzinfo=eastern)
    today = now.date()
    prior = 100.0
    open_px = 120.0
    last = 121.0
    seed = AlertDraft(
        kind="price",
        symbol="NVDA",
        bar_date=today,
        headline_id=None,
        price_change_pct=(last - prior) / prior,
        latest_close=last,
        prior_close=prior,
        volume_ratio=None,
        volume_spike=False,
        sentiment_score=None,
        headline_title=None,
        summary="forest seed",
        sections={
            "entry": "price",
            "price_span": PRICE_SPAN["close"],
            "forest": {
                "anomalous": True,
                "product_span": "close",
                "prior_close": prior,
                "session_open": open_px,
                "session_last": last,
                "features": {
                    "gap_return": 0.20,
                    "session_return": (last - open_px) / open_px,
                    "close_return": (last - prior) / prior,
                    "volume_zscore": -1.0,
                },
            },
        },
        triggered_at=now.astimezone(UTC),
        price_move_threshold=0.04,
        sentiment_threshold=25,
        origin="live",
    )
    drafts = evaluate_symbol(
        symbol="NVDA",
        bars=[
            {"dt": today - timedelta(days=1), "open": prior, "close": prior, "volume": 1_000_000},
            {"dt": today, "open": open_px, "close": last, "volume": 1_000_000},
        ],
        headlines=[],
        now=now,
        price_move_threshold=0.04,
        volume_spike_threshold=2.0,
        volume_lookback=20,
        sentiment_threshold=25,
        news_lookback_hours=72,
        fusion_window_hours=48,
        live_session={"price": last, "open": open_px, "prior_close": prior},
        seed_price_draft=seed,
    )
    assert len(drafts) == 1
    assert drafts[0].price_change_pct == pytest.approx(0.21)
    assert drafts[0].prior_close == prior
    assert drafts[0].latest_close == last
    assert "prior close" in str((drafts[0].sections or {}).get("price_span") or "")


def test_live_slices_prefer_supplied_prior_close_over_missing_bars():
    today = date(2026, 11, 23)
    slices = _live_slices(
        [],  # no daily_bars yet
        today,
        {"price": 164.65, "open": 164.82, "prior_close": 136.0},
    )
    assert slices["gap"][0] == pytest.approx((164.82 - 136.0) / 136.0)
    assert slices["close"][0] == pytest.approx((164.65 - 136.0) / 136.0)
    assert slices["session"][0] == pytest.approx((164.65 - 164.82) / 164.82)


def test_forest_draft_recovers_prior_from_gap_feature_when_prior_omitted():
    state = SessionState(
        symbol="AMD",
        session_day=date(2026, 11, 23),
        open=110.0,
        last=109.5,
        last_ts=datetime(2026, 11, 23, 19, 0, tzinfo=UTC),
        volume=1_000_000,
    )
    scored = ForestScore(
        features={
            "gap_return": 0.10,
            "session_return": -0.004545,
            "close_return": 0.095,
            "volume_zscore": 2.0,
        },
        forest_score=-0.1,
        score_cutoff=0.0,
        anomalous=True,
        model_id="isolation_forest_v1",
    )
    draft = forest_price_draft_from_session(
        state,
        scored,
        price_move_threshold=0.03,
        sentiment_threshold=25,
        now=state.last_ts,
        # prior_close omitted on purpose — recover from gap.
    )
    assert draft is not None
    assert draft.price_change_pct is not None
    assert draft.price_change_pct > 0.09
    assert forest_alone_under_percent(draft, 0.03) is False
    assert (draft.sections or {}).get("forest", {}).get("prior_close") is not None
