from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from app.engine import AlertDraft
from app.live_alerts import price_draft_from_session, should_write_live_price
from app.live_consumer import _decode_json, _same_price_snapshot
from app.live_session import SessionBook, parse_bar_ts
from app.store import heartbeat_is_fresh

eastern = ZoneInfo("America/New_York")


def test_parse_bar_ts_accepts_zulu_and_offset():
    stamp = parse_bar_ts("2026-11-18T15:30:00Z")
    assert stamp is not None
    assert stamp.year == 2026
    assert stamp.hour == 15
    offset = parse_bar_ts("2026-11-18T10:30:00-05:00")
    assert offset is not None
    assert offset.utcoffset() == timedelta(hours=-5)


def test_parse_bar_ts_rejects_junk():
    assert parse_bar_ts(None) is None
    assert parse_bar_ts("") is None
    assert parse_bar_ts("not-a-time") is None


def test_session_book_keeps_first_open_and_latest_close():
    book = SessionBook()
    first = book.apply(
        {
            "symbol": "AAPL",
            "ts": "2026-11-18T14:30:00Z",  # 9:30 ET
            "open": 100.0,
            "close": 101.0,
        }
    )
    assert first is not None
    assert first.open == 100.0
    assert first.last == 101.0

    second = book.apply(
        {
            "symbol": "AAPL",
            "ts": "2026-11-18T16:00:00Z",  # 11:00 ET
            "open": 102.0,
            "close": 110.0,
        }
    )
    assert second is not None
    assert second.open == 100.0
    assert second.last == 110.0
    assert book.live_session("aapl") == {"price": 110.0, "open": 100.0}


def test_session_book_ignores_out_of_order_bars():
    book = SessionBook()
    book.apply(
        {
            "symbol": "AAPL",
            "ts": "2026-11-18T16:00:00Z",
            "open": 100.0,
            "close": 105.0,
        }
    )
    older = book.apply(
        {
            "symbol": "AAPL",
            "ts": "2026-11-18T15:00:00Z",
            "open": 99.0,
            "close": 120.0,
        }
    )
    assert older is not None
    assert older.open == 100.0
    assert older.last == 105.0


def test_session_book_resets_on_a_new_session_day():
    book = SessionBook()
    book.apply(
        {
            "symbol": "AAPL",
            "ts": "2026-11-17T15:00:00Z",
            "open": 90.0,
            "close": 91.0,
        }
    )
    nxt = book.apply(
        {
            "symbol": "AAPL",
            "ts": "2026-11-18T14:30:00Z",
            "open": 100.0,
            "close": 101.0,
        }
    )
    assert nxt is not None
    assert nxt.session_day.isoformat() == "2026-11-18"
    assert nxt.open == 100.0
    assert nxt.last == 101.0


def test_session_book_ignores_premarket_after_hours_and_bad_payloads():
    book = SessionBook()
    assert (
        book.apply(
            {
                "symbol": "AAPL",
                "ts": "2026-11-18T13:00:00Z",  # 8:00 ET
                "open": 99.0,
                "close": 99.5,
            }
        )
        is None
    )
    assert (
        book.apply(
            {
                "symbol": "AAPL",
                "ts": "2026-11-18T21:05:00Z",  # 16:05 ET
                "open": 110.0,
                "close": 111.0,
            }
        )
        is None
    )
    assert book.apply({"symbol": "", "ts": "2026-11-18T15:00:00Z", "open": 1, "close": 1}) is None
    assert book.apply({"symbol": "AAPL", "ts": "2026-11-18T15:00:00Z", "open": 0, "close": 1}) is None
    assert book.apply({"symbol": "AAPL", "ts": "bad", "open": 1, "close": 1}) is None


def test_price_draft_fires_when_open_to_last_clears_threshold():
    book = SessionBook()
    state = book.apply(
        {
            "symbol": "MSFT",
            "ts": "2026-11-18T15:00:00Z",
            "open": 100.0,
            "close": 104.0,
        }
    )
    assert state is not None
    now = datetime(2026, 11, 18, 11, 0, tzinfo=eastern)
    draft = price_draft_from_session(
        state,
        price_move_threshold=0.03,
        sentiment_threshold=25.0,
        now=now,
    )
    assert draft is not None
    assert draft.kind == "price"
    assert draft.symbol == "MSFT"
    assert draft.price_change_pct == 0.04
    assert "from the open" in draft.summary


def test_price_draft_skips_below_threshold_and_outside_session():
    book = SessionBook()
    state = book.apply(
        {
            "symbol": "MSFT",
            "ts": "2026-11-18T15:00:00Z",
            "open": 100.0,
            "close": 101.0,
        }
    )
    assert state is not None
    during = datetime(2026, 11, 18, 11, 0, tzinfo=eastern)
    assert (
        price_draft_from_session(
            state,
            price_move_threshold=0.03,
            sentiment_threshold=25.0,
            now=during,
        )
        is None
    )
    after = datetime(2026, 11, 18, 17, 0, tzinfo=eastern)
    hot = book.apply(
        {
            "symbol": "MSFT",
            "ts": "2026-11-18T16:00:00Z",
            "open": 100.0,
            "close": 110.0,
        }
    )
    assert hot is not None
    assert (
        price_draft_from_session(
            hot,
            price_move_threshold=0.03,
            sentiment_threshold=25.0,
            now=after,
        )
        is None
    )


def test_should_write_live_price_leaves_news_alone():
    assert should_write_live_price(None)
    assert should_write_live_price({"kind": "price"})
    assert not should_write_live_price({"kind": "news"})
    assert not should_write_live_price({"kind": "news_price"})


def test_same_price_snapshot_avoids_noise_rewrites():
    draft = AlertDraft(
        kind="price",
        symbol="AAPL",
        bar_date=datetime(2026, 11, 18).date(),
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
    assert _same_price_snapshot(
        {"price_change_pct": 0.04, "latest_close": 104.0, "prior_close": 100.0},
        draft,
    )
    assert not _same_price_snapshot(
        {"price_change_pct": 0.05, "latest_close": 105.0, "prior_close": 100.0},
        draft,
    )


def test_decode_json_skips_bad_payloads():
    assert _decode_json(b'{"symbol":"AAPL"}') == {"symbol": "AAPL"}
    assert _decode_json(None) is None
    assert _decode_json(b"not-json") is None


def test_heartbeat_is_fresh_within_stale_window():
    now = datetime(2026, 11, 18, 16, 0, tzinfo=eastern)
    fresh = now - timedelta(seconds=10)
    stale = now - timedelta(seconds=30)
    assert heartbeat_is_fresh(fresh, now=now, stale_after_seconds=15)
    assert not heartbeat_is_fresh(stale, now=now, stale_after_seconds=15)
    assert not heartbeat_is_fresh(None, now=now, stale_after_seconds=15)
