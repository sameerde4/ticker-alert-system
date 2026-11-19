from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.engine import AlertDraft
from app.live_alerts import forest_price_draft_from_session, price_draft_from_session
from app.live_session import SessionBook
from app.forest_live import ForestScore
from app.store import merge_alert_origin, normalize_alert_origin

eastern = ZoneInfo("America/New_York")


def test_normalize_alert_origin_defaults_and_accepts_known_values():
    assert normalize_alert_origin(None) == "watchlist"
    assert normalize_alert_origin("LIVE") == "live"
    assert normalize_alert_origin("both") == "both"
    assert normalize_alert_origin("nope") == "watchlist"


def test_merge_alert_origin_becomes_both_when_paths_differ():
    assert merge_alert_origin("live", "live") == "live"
    assert merge_alert_origin("watchlist", "watchlist") == "watchlist"
    assert merge_alert_origin("live", "watchlist") == "both"
    assert merge_alert_origin("watchlist", "live") == "both"
    assert merge_alert_origin("both", "live") == "both"


def test_alert_draft_defaults_to_watchlist_origin():
    draft = AlertDraft(
        kind="price",
        symbol="AAPL",
        bar_date=datetime(2026, 11, 19).date(),
        headline_id=None,
        price_change_pct=0.04,
        latest_close=104.0,
        prior_close=100.0,
        volume_ratio=None,
        volume_spike=False,
        sentiment_score=None,
        headline_title=None,
        summary="x",
    )
    assert draft.origin == "watchlist"


def test_live_price_drafts_set_origin_live():
    book = SessionBook()
    state = book.apply(
        {
            "symbol": "AAPL",
            "ts": "2026-11-18T15:00:00Z",
            "open": 100.0,
            "close": 104.0,
        }
    )
    assert state is not None
    draft = price_draft_from_session(
        state,
        price_move_threshold=0.03,
        sentiment_threshold=25.0,
        now=datetime(2026, 11, 18, 15, 0, tzinfo=timezone.utc),
    )
    assert draft is not None
    assert draft.origin == "live"

    scored = ForestScore(
        features={
            "gap_return": 0.0,
            "session_return": 0.04,
            "close_return": 0.04,
            "volume_zscore": 1.0,
        },
        forest_score=-0.2,
        score_cutoff=-0.1,
        anomalous=True,
        model_id="isolation_forest_v1",
    )
    forest = forest_price_draft_from_session(
        state,
        scored,
        price_move_threshold=0.03,
        sentiment_threshold=25.0,
        now=datetime(2026, 11, 18, 15, 0, tzinfo=timezone.utc),
    )
    assert forest is not None
    assert forest.origin == "live"
