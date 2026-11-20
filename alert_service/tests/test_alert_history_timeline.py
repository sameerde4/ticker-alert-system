"""Symbol-day update_history timeline on upsert merge."""

from datetime import UTC, date, datetime

from app.engine import AlertDraft
from app.store import merge_alert_update_history


def _draft(**kwargs):
    base = dict(
        kind="price",
        symbol="AAPL",
        bar_date=date(2026, 11, 20),
        headline_id=None,
        price_change_pct=-0.04,
        latest_close=96.0,
        prior_close=100.0,
        volume_ratio=None,
        volume_spike=False,
        sentiment_score=None,
        headline_title=None,
        summary="Price led",
        articles=(),
        sections={"entry": "price"},
        triggered_at=datetime(2026, 11, 20, 14, 42, tzinfo=UTC),
        price_move_threshold=0.03,
        sentiment_threshold=25.0,
        origin="live",
    )
    base.update(kwargs)
    return AlertDraft(**base)


def test_first_write_opens_timeline():
    draft = _draft()
    sections = merge_alert_update_history(
        draft,
        existing=None,
        written_at=datetime(2026, 11, 20, 14, 42, tzinfo=UTC),
    )
    assert sections["first_triggered_at"].startswith("2026-11-20T14:42")
    assert len(sections["update_history"]) == 1
    assert sections["update_history"][0]["event"] == "opened"
    assert "Alert created as price-led" in sections["update_history"][0]["note"]


def test_second_write_appends_update_and_keeps_first_triggered():
    existing = {
        "kind": "price",
        "created_at": "2026-11-20T14:42:00+00:00",
        "triggered_at": "2026-11-20T14:42:00+00:00",
        "sentiment_score": None,
        "articles": [],
        "sections": {
            "first_triggered_at": "2026-11-20T14:42:00+00:00",
            "update_history": [
                {
                    "at": "2026-11-20T14:42:00+00:00",
                    "event": "opened",
                    "kind": "price",
                    "note": "opened as price",
                }
            ],
        },
    }
    draft = _draft(
        kind="news_price",
        sentiment_score=35.0,
        articles=({"title": "Soft", "sentiment_score": 35.0},),
        sections={"entry": "price", "news_join_path": "climate", "second_supports": True},
        triggered_at=datetime(2026, 11, 20, 19, 10, tzinfo=UTC),
    )
    sections = merge_alert_update_history(
        draft,
        existing=existing,
        written_at=datetime(2026, 11, 20, 19, 10, tzinfo=UTC),
    )
    assert sections["first_triggered_at"] == "2026-11-20T14:42:00+00:00"
    assert len(sections["update_history"]) == 2
    assert sections["update_history"][-1]["event"] == "updated"
    assert "Alert type changed to price + news" in sections["update_history"][-1]["note"]
    assert "was price-led" in sections["update_history"][-1]["note"]
    assert "news joined via the climate average" in sections["update_history"][-1]["note"]
