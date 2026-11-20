"""Retroactive FinBERT climate backfill for price-led rows."""

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.climate_backfill import draft_from_alert_row, draft_from_price_alert
from app.engine import evaluate_symbol
from app.evidence import attach_evidence_story


def test_draft_from_price_alert_keeps_forest_and_levels():
    alert = {
        "symbol": "AAPL",
        "kind": "price",
        "bar_date": "2026-11-20",
        "price_change_pct": -0.04,
        "latest_close": 96.0,
        "prior_close": 100.0,
        "volume_ratio": None,
        "volume_spike": False,
        "summary": "Price led…",
        "sections": {
            "forest": {"anomalous": True, "model_id": "isolation_forest_v1"},
            "price_span": "open → last",
            "entry": "price",
        },
        "origin": "live",
        "price_move_threshold": 0.03,
        "sentiment_threshold": 25,
        "triggered_at": "2026-11-20T18:00:00+00:00",
    }
    draft = draft_from_price_alert(alert)
    assert draft is not None
    assert draft.kind == "price"
    assert draft.symbol == "AAPL"
    assert draft.bar_date == date(2026, 11, 20)
    assert draft.price_change_pct == -0.04
    assert draft.origin == "live"
    assert draft.sections["forest"]["anomalous"] is True


def test_seed_price_draft_attaches_mild_climate_without_requiring_percent_gate():
    """Backfill seed keeps a price row even when we only re-run news/climate."""
    eastern = ZoneInfo("America/New_York")
    day = date(2026, 11, 17)
    now = datetime(2026, 11, 17, 20, 0, tzinfo=eastern)
    seed = draft_from_price_alert(
        {
            "symbol": "AAPL",
            "bar_date": day.isoformat(),
            "price_change_pct": -0.04,
            "latest_close": 96.0,
            "prior_close": 100.0,
            "volume_spike": False,
            "summary": "seed",
            "sections": {"price_span": "open → last", "entry": "price"},
            "origin": "live",
            "price_move_threshold": 0.03,
            "sentiment_threshold": 25,
        }
    )
    assert seed is not None
    mild = [
        {
            "id": f"00000000-0000-0000-0000-00000000000{i}",
            "title": f"Soft negative {i}",
            "source": "Reuters",
            "published_at": now - timedelta(hours=2 + i),
            "sentiment_score": 35.0,
        }
        for i in range(3)
    ]
    drafts = evaluate_symbol(
        symbol="AAPL",
        bars=[
            {"dt": day - timedelta(days=1), "open": 100, "close": 100, "volume": 1_000_000},
            {"dt": day, "open": 100, "close": 100, "volume": 1_000_000},
        ],
        headlines=mild,
        now=now.astimezone(UTC),
        price_move_threshold=0.03,
        volume_spike_threshold=2.0,
        volume_lookback=20,
        sentiment_threshold=25,
        news_lookback_hours=72,
        fusion_window_hours=48,
        seed_price_draft=seed,
    )
    assert len(drafts) == 1
    assert drafts[0].kind == "news_price"
    assert drafts[0].sections["news_join_path"] == "climate"
    assert drafts[0].sentiment_score == 35.0
    assert len(drafts[0].articles) == 3


def test_forest_evidence_bullets_are_one_driver_per_line():
    from app.forest_wording import forest_evidence_bullets

    bullets = forest_evidence_bullets(
        {
            "anomalous": True,
            "features": {
                "gap_return": -0.0601,
                "session_return": 0.0015,
                "close_return": -0.058,
                "volume_zscore": -4.29,
            },
        }
    )
    assert len(bullets) == 2
    assert all("Marked anomalous" not in line for line in bullets)
    assert any("vol z" in line for line in bullets)
    assert any("gap" in line for line in bullets)


def test_draft_from_alert_row_restamps_live_news_to_price_first():
    alert = {
        "symbol": "AAPL",
        "kind": "news",
        "bar_date": "2026-11-20",
        "price_change_pct": None,
        "latest_close": None,
        "prior_close": None,
        "volume_spike": False,
        "sentiment_score": 82.0,
        "summary": "News led…",
        "articles": [{"title": "Beats", "sentiment_score": 82.0}],
        "sections": {
            "entry": "news",
            "second_supports": False,
            "observed_price_change_pct": 0.0039,
            "forest": {
                "anomalous": True,
                "model_id": "isolation_forest_v1",
                "forest_score": -0.21,
                "score_cutoff": 0.0,
            },
            "evidence": {
                "entry": "news",
                "headline": "News checked → price checked → price does not confirm the news",
            },
        },
        "origin": "live",
        "price_move_threshold": 0.03,
        "sentiment_threshold": 25,
    }
    draft = draft_from_alert_row(alert)
    assert draft is not None
    assert draft.origin == "live"
    repaired = attach_evidence_story(draft)
    assert repaired.sections["entry"] == "price"
    assert repaired.sections["evidence"]["entry"] == "price"
    assert repaired.sections["evidence"]["headline"].startswith("Price noticed")
