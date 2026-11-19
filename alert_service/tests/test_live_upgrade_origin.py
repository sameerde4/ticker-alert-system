"""Live price→news upgrade must keep origin=live (evaluate_symbol defaults to watchlist)."""

from __future__ import annotations

from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from app.engine import AlertDraft
from app.live_session import SessionBook
from app.live_upgrade import upgrade_price_draft_with_news

eastern = ZoneInfo("America/New_York")


def _live_price_draft() -> AlertDraft:
    return AlertDraft(
        kind="price",
        symbol="AAPL",
        bar_date=date(2026, 11, 19),
        headline_id=None,
        price_change_pct=0.04,
        latest_close=104.0,
        prior_close=100.0,
        volume_ratio=None,
        volume_spike=False,
        sentiment_score=None,
        headline_title=None,
        summary="live price",
        origin="live",
    )


def _session_state():
    book = SessionBook()
    state = book.apply(
        {
            "symbol": "AAPL",
            "ts": "2026-11-19T15:00:00Z",
            "open": 100.0,
            "close": 104.0,
        }
    )
    assert state is not None
    return state


@pytest.mark.asyncio
async def test_upgrade_keeps_live_origin_when_evaluate_returns_watchlist_default():
    live_draft = _live_price_draft()
    evaluated = AlertDraft(
        kind="news_price",
        symbol="AAPL",
        bar_date=date(2026, 11, 19),
        headline_id=None,
        price_change_pct=0.04,
        latest_close=104.0,
        prior_close=100.0,
        volume_ratio=None,
        volume_spike=False,
        sentiment_score=20.0,
        headline_title=None,
        summary="joined",
        # Default path from evaluate_symbol — the bug before the fix.
        origin="watchlist",
        sections={"entry": "price", "second_supports": True},
    )
    pool = _pool_mock()

    with (
        patch("app.live_upgrade.fetch_headlines", return_value=[{"title": "x"}]),
        patch("app.live_upgrade._headlines_for_rules", new=AsyncMock(return_value=[])),
        patch("app.live_upgrade.load_bars", new=AsyncMock(return_value=[])),
        patch("app.live_upgrade.evaluate_symbol", return_value=[evaluated]),
        patch("app.live_upgrade.reason_alert_drafts", new=AsyncMock(return_value=([evaluated], "rules", None))),
        patch("app.live_upgrade.eastern_date", return_value=date(2026, 11, 19)),
    ):
        result = await upgrade_price_draft_with_news(
            pool,
            live_draft,
            _session_state(),
            price_move_threshold=0.03,
            sentiment_threshold=25.0,
            now=datetime(2026, 11, 19, 15, 0, tzinfo=timezone.utc),
        )

    assert result.origin == "live"
    assert result.kind == "news_price"


def _pool_mock():
    conn = AsyncMock()
    cm = AsyncMock()
    cm.__aenter__.return_value = conn
    cm.__aexit__.return_value = False
    pool = MagicMock()
    pool.acquire = MagicMock(return_value=cm)
    return pool


@pytest.mark.asyncio
async def test_upgrade_keeps_live_origin_after_perplexity_rewrite():
    live_draft = _live_price_draft()
    evaluated = AlertDraft(
        kind="news_price",
        symbol="AAPL",
        bar_date=date(2026, 11, 19),
        headline_id=None,
        price_change_pct=0.04,
        latest_close=104.0,
        prior_close=100.0,
        volume_ratio=None,
        volume_spike=False,
        sentiment_score=20.0,
        headline_title=None,
        summary="joined",
        origin="watchlist",
        sections={"entry": "price", "second_supports": True},
    )
    reasoned = AlertDraft(
        kind="news_price",
        symbol="AAPL",
        bar_date=date(2026, 11, 19),
        headline_id=None,
        price_change_pct=0.04,
        latest_close=104.0,
        prior_close=100.0,
        volume_ratio=None,
        volume_spike=False,
        sentiment_score=20.0,
        headline_title=None,
        summary="perplexity rewrite",
        origin="watchlist",
        sections={"entry": "price", "second_supports": True, "model_label": "x"},
    )
    pool = _pool_mock()

    with (
        patch("app.live_upgrade.fetch_headlines", return_value=[{"title": "x"}]),
        patch("app.live_upgrade._headlines_for_rules", new=AsyncMock(return_value=[])),
        patch("app.live_upgrade.load_bars", new=AsyncMock(return_value=[])),
        patch("app.live_upgrade.evaluate_symbol", return_value=[evaluated]),
        patch(
            "app.live_upgrade.reason_alert_drafts",
            new=AsyncMock(return_value=([reasoned], "perplexity", None)),
        ),
        patch("app.live_upgrade.eastern_date", return_value=date(2026, 11, 19)),
    ):
        result = await upgrade_price_draft_with_news(
            pool,
            live_draft,
            _session_state(),
            price_move_threshold=0.03,
            sentiment_threshold=25.0,
            now=datetime(2026, 11, 19, 15, 0, tzinfo=timezone.utc),
        )

    assert result.origin == "live"
    assert "perplexity" in result.summary.lower() or result.summary == "perplexity rewrite"
