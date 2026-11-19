"""Watchlist Scan today uses the same percent OR forest price gate as live."""

from __future__ import annotations

from datetime import UTC, date, datetime
from unittest.mock import MagicMock

from app.engine import AlertDraft
from app.forest_live import ForestScore
from app.watchlist_forest import apply_forest_to_drafts


def _bars(session_day: date, *, n_prior: int = 25, volume: float = 5_000_000) -> list[dict]:
    rows = []
    base = session_day.toordinal() - n_prior
    for i in range(n_prior):
        day = date.fromordinal(base + i)
        rows.append(
            {
                "dt": day,
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.0,
                "volume": 1_000_000.0,
            }
        )
    rows.append(
        {
            "dt": session_day,
            "open": 100.0,
            "high": 110.0,
            "low": 95.0,
            "close": 101.0,  # +1% open→last — under a 3% rule
            "volume": volume,
        }
    )
    return rows


def _scorer(anomalous: bool) -> MagicMock:
    scored = ForestScore(
        features={
            "gap_return": 0.02,
            "session_return": 0.01,
            "close_return": 0.03,
            "volume_zscore": 4.5 if anomalous else 0.2,
        },
        forest_score=-0.2 if anomalous else 0.3,
        score_cutoff=0.0,
        anomalous=anomalous,
        model_id="isolation_forest_test",
    )
    scorer = MagicMock()
    scorer.enabled = True
    scorer.score_session.return_value = scored
    return scorer


def test_forest_alone_opens_price_alert_when_under_percent(monkeypatch):
    monkeypatch.setattr("app.watchlist_forest.settings.live_forest_alerts", True)
    day = date(2026, 11, 18)
    out = apply_forest_to_drafts(
        [],
        scorer=_scorer(True),
        symbol="AAPL",
        bars=_bars(day),
        session_day=day,
        now=datetime(2026, 11, 18, 20, 0, tzinfo=UTC),
        price_move_threshold=0.03,
        sentiment_threshold=25,
    )
    assert len(out) == 1
    assert out[0].kind == "price"
    assert out[0].sections["forest"]["anomalous"] is True
    assert "stayed under" in out[0].summary
    assert "Isolation Forest" in out[0].summary


def test_forest_not_anomalous_leaves_empty(monkeypatch):
    monkeypatch.setattr("app.watchlist_forest.settings.live_forest_alerts", True)
    day = date(2026, 11, 18)
    out = apply_forest_to_drafts(
        [],
        scorer=_scorer(False),
        symbol="AAPL",
        bars=_bars(day),
        session_day=day,
        now=datetime(2026, 11, 18, 20, 0, tzinfo=UTC),
        price_move_threshold=0.03,
        sentiment_threshold=25,
    )
    assert out == []


def test_forest_enriches_existing_percent_price_draft(monkeypatch):
    monkeypatch.setattr("app.watchlist_forest.settings.live_forest_alerts", True)
    day = date(2026, 11, 18)
    draft = AlertDraft(
        kind="price",
        symbol="AAPL",
        bar_date=day,
        headline_id=None,
        price_change_pct=0.04,
        latest_close=104.0,
        prior_close=100.0,
        volume_ratio=1.1,
        volume_spike=False,
        sentiment_score=None,
        headline_title=None,
        summary="Percent rule sentence",
        sections={
            "price": "Percent rule sentence",
            "synthesis": "Percent rule sentence",
            "entry": "price",
            "second_supports": False,
        },
        price_move_threshold=0.03,
        sentiment_threshold=25,
        origin="watchlist",
    )
    out = apply_forest_to_drafts(
        [draft],
        scorer=_scorer(True),
        symbol="AAPL",
        bars=_bars(day, volume=8_000_000),
        session_day=day,
        now=datetime(2026, 11, 18, 20, 0, tzinfo=UTC),
        price_move_threshold=0.03,
        sentiment_threshold=25,
    )
    assert len(out) == 1
    assert out[0].sections["forest"]["anomalous"] is True
    assert "Isolation Forest" in out[0].summary
    assert out[0].sections["forest"]["session_open"] == 100.0


def test_forest_attaches_to_news_draft_without_changing_kind(monkeypatch):
    monkeypatch.setattr("app.watchlist_forest.settings.live_forest_alerts", True)
    day = date(2026, 11, 18)
    draft = AlertDraft(
        kind="news",
        symbol="AAPL",
        bar_date=day,
        headline_id=None,
        price_change_pct=None,
        latest_close=101.0,
        prior_close=100.0,
        volume_ratio=None,
        volume_spike=False,
        sentiment_score=80.0,
        headline_title="Apple news",
        summary="News-led summary",
        sections={"entry": "news", "second_supports": False, "news": "news text"},
        price_move_threshold=0.03,
        sentiment_threshold=25,
        origin="watchlist",
    )
    out = apply_forest_to_drafts(
        [draft],
        scorer=_scorer(True),
        symbol="AAPL",
        bars=_bars(day),
        session_day=day,
        now=datetime(2026, 11, 18, 20, 0, tzinfo=UTC),
        price_move_threshold=0.03,
        sentiment_threshold=25,
    )
    assert len(out) == 1
    assert out[0].kind == "news"
    assert out[0].sections["forest"]["anomalous"] is True
    assert "Isolation Forest" in (out[0].sections.get("price") or "")


def test_forest_skipped_when_alerts_disabled(monkeypatch):
    monkeypatch.setattr("app.watchlist_forest.settings.live_forest_alerts", False)
    day = date(2026, 11, 18)
    out = apply_forest_to_drafts(
        [],
        scorer=_scorer(True),
        symbol="AAPL",
        bars=_bars(day),
        session_day=day,
        now=datetime(2026, 11, 18, 20, 0, tzinfo=UTC),
        price_move_threshold=0.03,
        sentiment_threshold=25,
    )
    assert out == []


def test_forest_skipped_without_enough_prior_volume(monkeypatch):
    monkeypatch.setattr("app.watchlist_forest.settings.live_forest_alerts", True)
    day = date(2026, 11, 18)
    thin = _bars(day, n_prior=5)
    out = apply_forest_to_drafts(
        [],
        scorer=_scorer(True),
        symbol="AAPL",
        bars=thin,
        session_day=day,
        now=datetime(2026, 11, 18, 20, 0, tzinfo=UTC),
        price_move_threshold=0.03,
        sentiment_threshold=25,
    )
    assert out == []
