from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from app.engine import evaluate_symbol, headline_session

NOW = datetime(2026, 11, 17, 21, 30, tzinfo=UTC)


def _bars(latest_close, prior_close, latest_volume=2_000_000, prior_volume=1_000_000):
    today = NOW.date()
    return [
        {"dt": today - timedelta(days=2), "close": prior_close, "volume": prior_volume},
        {"dt": today - timedelta(days=1), "close": prior_close, "volume": prior_volume},
        {"dt": today, "close": latest_close, "volume": latest_volume},
    ]


def _headline(**overrides):
    item = {
        "id": "11111111-1111-1111-1111-111111111111",
        "title": "Shares plunge after guidance cut",
        "source": "Reuters",
        "published_at": NOW - timedelta(hours=2),
        "sentiment_score": 17,
    }
    item.update(overrides)
    return item


def _evaluate(bars, headlines):
    return evaluate_symbol(
        symbol="AAPL",
        bars=bars,
        headlines=headlines,
        now=NOW,
        price_move_threshold=0.03,
        volume_spike_threshold=2.0,
        volume_lookback=20,
        sentiment_threshold=25,
        news_lookback_hours=72,
        fusion_window_hours=48,
    )


def test_small_move_does_not_open_a_price_alert():
    drafts = _evaluate(_bars(101, 100), [])
    assert [d.kind for d in drafts] == []


def test_price_alert_includes_volume_spike():
    drafts = _evaluate(_bars(104, 100, latest_volume=3_000_000, prior_volume=1_000_000), [])
    assert [d.kind for d in drafts] == ["price"]
    assert drafts[0].volume_spike is True
    assert "spike rule" in drafts[0].summary
    assert "+4.00%" in drafts[0].summary


def test_news_alert_without_a_price_move():
    drafts = _evaluate(_bars(100, 100), [_headline()])
    assert [d.kind for d in drafts] == ["news"]
    assert drafts[0].sentiment_score == 17
    assert drafts[0].price_change_pct == 0.0
    assert "Combined sentiment is 17/100" in drafts[0].summary
    assert "plunge" in drafts[0].articles[0]["reason"]
    assert drafts[0].articles[0]["published_at"] == (NOW - timedelta(hours=2)).isoformat()
    assert drafts[0].triggered_at == NOW - timedelta(hours=2)


def test_mixed_headlines_become_one_news_alert():
    positive = _headline(
        id="22222222-2222-2222-2222-222222222222",
        title="Shares surge to a record",
        source="Bloomberg",
        url="https://example.com/surge",
        sentiment_score=75,
        published_at=NOW - timedelta(hours=1),
    )
    drafts = _evaluate(
        _bars(100, 100),
        [_headline(url="https://example.com/plunge", sentiment_score=25), positive],
    )
    news = [d for d in drafts if d.kind == "news"]
    assert len(news) == 1
    assert news[0].sentiment_score == 50
    assert "disagree" in news[0].summary
    assert [article["url"] for article in news[0].articles] == [
        "https://example.com/surge",
        "https://example.com/plunge",
    ]
    assert [article["sentiment_score"] for article in news[0].articles] == [75, 25]


def test_price_and_news_become_one_alert():
    drafts = _evaluate(_bars(104, 100), [_headline()])
    assert [d.kind for d in drafts] == ["news_price"]
    alert = drafts[0]
    assert alert.sentiment_score == 17
    assert "news + price" in alert.sections["synthesis"]
    assert alert.triggered_at == datetime(2026, 11, 17, 16, 0, tzinfo=ZoneInfo("America/New_York"))
    assert "+4.00%" in alert.sections["price"]
    assert "Combined sentiment is 17/100" in alert.sections["news"]
    assert alert.summary == alert.sections["synthesis"]


def test_old_headline_does_not_fuse_or_alert():
    old = _headline(published_at=NOW - timedelta(days=10), sentiment_score=5)
    drafts = _evaluate(_bars(104, 100), [old])
    assert [d.kind for d in drafts] == ["price"]


def test_alert_remembers_the_rules_that_fired_it():
    drafts = _evaluate(_bars(104, 100), [_headline()])
    assert drafts[0].price_move_threshold == 0.03
    assert drafts[0].sentiment_threshold == 25


def test_previous_session_is_left_alone():
    bars = _bars(104, 100)
    for bar in bars:
        bar["dt"] = bar["dt"] - timedelta(days=1)
    drafts = _evaluate(bars, [_headline()])
    assert [draft.kind for draft in drafts] == ["news"]
    assert drafts[0].bar_date == NOW.astimezone(ZoneInfo("America/New_York")).date()


def test_next_morning_story_stays_on_its_own_day():
    eastern = ZoneInfo("America/New_York")
    today = NOW.astimezone(eastern).date()
    yesterday = today - timedelta(days=1)
    bars = [
        {"dt": yesterday - timedelta(days=1), "close": 100, "volume": 1_000_000},
        {"dt": yesterday, "close": 92, "volume": 1_000_000},
        {"dt": today, "close": 92, "volume": 1_000_000},
    ]
    published = datetime(today.year, today.month, today.day, 9, 17, tzinfo=eastern)
    drafts = _evaluate(
        bars,
        [_headline(title="Lumentum gains 4% as optical stocks jump", published_at=published, sentiment_score=75)],
    )
    assert [draft.kind for draft in drafts] == ["news"]
    assert drafts[0].bar_date == today
    assert drafts[0].price_change_pct == 0.0
    assert drafts[0].sentiment_score == 75


def test_headline_session_uses_the_eastern_publish_day():
    eastern = ZoneInfo("America/New_York")
    tuesday_premarket = datetime(2026, 11, 17, 9, 17, tzinfo=eastern)
    saturday = datetime(2026, 11, 14, 11, 0, tzinfo=eastern)
    sunday = datetime(2026, 11, 15, 18, 0, tzinfo=eastern)
    assert headline_session(tuesday_premarket) == tuesday_premarket.date()
    assert headline_session(saturday) == datetime(2026, 11, 13).date()
    assert headline_session(sunday) == datetime(2026, 11, 13).date()


def test_mild_sentiment_stays_below_the_news_threshold():
    mild = _headline(sentiment_score=60, title="Company hosts an investor day")
    drafts = _evaluate(_bars(100, 100), [mild])
    assert drafts == []
