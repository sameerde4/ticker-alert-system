from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from app.engine import cash_session_open, evaluate_symbol, headline_price_slice, headline_session
from app.prices import open_to_last, price_versus_24h, sector_label
from app.symbols import known_universe_symbol, trades_all_day

NOW = datetime(2026, 11, 17, 21, 30, tzinfo=UTC)


def _bars(latest_close, prior_close, latest_volume=2_000_000, prior_volume=1_000_000):
    today = NOW.date()
    return [
        {"dt": today - timedelta(days=2), "open": prior_close, "close": prior_close, "volume": prior_volume},
        {"dt": today - timedelta(days=1), "open": prior_close, "close": prior_close, "volume": prior_volume},
        {"dt": today, "open": prior_close, "close": latest_close, "volume": latest_volume},
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
    assert "spike rule" in drafts[0].sections["price"]
    assert "+4.00%" in drafts[0].sections["price"]
    assert drafts[0].sections["entry"] == "price"
    assert "Price led" in drafts[0].summary


def test_news_alert_without_a_price_move():
    drafts = _evaluate(_bars(100, 100), [_headline()])
    assert [d.kind for d in drafts] == ["news"]
    assert drafts[0].sentiment_score == 17
    assert drafts[0].price_change_pct is None
    assert drafts[0].latest_close is None
    assert "candidate reason" not in drafts[0].summary
    assert "Combined sentiment is 17/100" in drafts[0].sections["news"]
    assert "does not support a price alert" in drafts[0].summary
    assert drafts[0].sections["entry"] == "news"
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
    assert "disagree" in news[0].sections["news"]
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
    assert "candidate reason" in alert.summary
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
    assert drafts[0].price_change_pct is None
    assert "candidate reason" not in drafts[0].summary
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


def test_around_the_clock_symbol_uses_the_last_24_hours():
    drafts = evaluate_symbol(
        symbol="BTC-USD",
        bars=[],
        headlines=[],
        now=NOW,
        price_move_threshold=0.03,
        volume_spike_threshold=2.0,
        volume_lookback=20,
        sentiment_threshold=25,
        news_lookback_hours=72,
        fusion_window_hours=48,
        trailing_24h={"price": 105, "prior_price": 100},
    )
    assert [draft.kind for draft in drafts] == ["price"]
    assert drafts[0].price_change_pct == 0.05
    assert "24 hours before this check" in drafts[0].sections["price"]
    assert drafts[0].triggered_at == NOW
    quiet = evaluate_symbol(
        symbol="BTC-USD",
        bars=[],
        headlines=[],
        now=NOW,
        price_move_threshold=0.03,
        volume_spike_threshold=2.0,
        volume_lookback=20,
        sentiment_threshold=25,
        news_lookback_hours=72,
        fusion_window_hours=48,
        trailing_24h={"price": 101, "prior_price": 100},
    )
    assert quiet == []


def test_price_versus_24h_picks_the_print_a_day_earlier():
    now = datetime(2026, 11, 17, 22, 30, tzinfo=UTC)
    points = [
        (now - timedelta(hours=30), 80),
        (now - timedelta(hours=25), 90),
        (now - timedelta(hours=24, minutes=30), 100),
        (now - timedelta(hours=1), 110),
    ]
    assert price_versus_24h(points, now) == (110, 100)
    assert price_versus_24h([(now - timedelta(hours=2), 100)], now) is None
    naive_now = datetime(2026, 11, 17, 22, 30)
    naive_points = [
        (datetime(2026, 11, 16, 22, 0), 100),
        (datetime(2026, 11, 17, 22, 0), 104),
    ]
    assert price_versus_24h(naive_points, naive_now) == (104, 100)


def test_price_versus_24h_rejects_a_stale_or_thin_window():
    now = datetime(2026, 11, 17, 22, 30, tzinfo=UTC)
    stale_latest = [
        (now - timedelta(hours=25), 100),
        (now - timedelta(hours=4), 110),
    ]
    assert price_versus_24h(stale_latest, now) is None
    thin_prior = [
        (now - timedelta(hours=31), 100),
        (now - timedelta(hours=1), 110),
    ]
    assert price_versus_24h(thin_prior, now) is None


def test_a_stock_without_todays_bar_does_not_invent_a_price_alert():
    bars = _bars(110, 100)
    for bar in bars:
        bar["dt"] = bar["dt"] - timedelta(days=2)
    assert _evaluate(bars, []) == []


def test_around_the_clock_news_and_price_use_the_hours_after_the_headline():
    published = NOW - timedelta(hours=2)
    drafts = evaluate_symbol(
        symbol="BTC-USD",
        bars=[],
        headlines=[_headline(published_at=published)],
        now=NOW,
        price_move_threshold=0.03,
        volume_spike_threshold=2.0,
        volume_lookback=20,
        sentiment_threshold=25,
        news_lookback_hours=72,
        fusion_window_hours=48,
        trailing_24h={
            "price": 105,
            "prior_price": 100,
            "points": [
                (published - timedelta(hours=1), 100),
                (published, 100),
                (NOW, 105),
            ],
        },
    )
    assert [draft.kind for draft in drafts] == ["news_price"]
    assert drafts[0].price_change_pct == 0.05
    assert "four hours after the headline" in drafts[0].summary
    assert drafts[0].triggered_at == NOW


def test_a_crypto_headline_does_not_borrow_the_trailing_day():
    published = NOW - timedelta(hours=2)
    drafts = evaluate_symbol(
        symbol="BTC-USD",
        bars=[],
        headlines=[_headline(published_at=published)],
        now=NOW,
        price_move_threshold=0.03,
        volume_spike_threshold=2.0,
        volume_lookback=20,
        sentiment_threshold=25,
        news_lookback_hours=72,
        fusion_window_hours=48,
        trailing_24h={
            "price": 110,
            "prior_price": 100,
            "points": [
                (published, 100),
                (NOW, 100),
            ],
        },
    )
    assert [draft.kind for draft in drafts] == ["price"]
    assert drafts[0].price_change_pct == 0.10
    assert "did not line up" in drafts[0].summary
    assert drafts[0].sections["entry"] == "price"
    assert drafts[0].sections["second_supports"] is False
    assert "candidate reason" not in drafts[0].summary
    assert drafts[0].articles[0]["title"] == "Shares plunge after guidance cut"
    assert drafts[0].sentiment_score is not None


def test_a_premarket_headline_lines_up_with_the_overnight_gap():
    eastern = ZoneInfo("America/New_York")
    today = NOW.astimezone(eastern).date()
    bars = _bars(100, 100)
    bars[-1]["open"] = 105
    bars[-1]["close"] = 105
    published = datetime(today.year, today.month, today.day, 8, 15, tzinfo=eastern)
    drafts = _evaluate(bars, [_headline(published_at=published, sentiment_score=80)])
    assert [draft.kind for draft in drafts] == ["news_price"]
    assert drafts[0].price_change_pct == 0.05
    assert "overnight gap" in drafts[0].summary


def test_a_midday_headline_does_not_explain_the_overnight_gap():
    eastern = ZoneInfo("America/New_York")
    today = NOW.astimezone(eastern).date()
    bars = _bars(106, 100)
    bars[-1]["open"] = 106
    published = datetime(today.year, today.month, today.day, 13, 0, tzinfo=eastern)
    drafts = _evaluate(bars, [_headline(published_at=published, sentiment_score=80, title="Shares surge at noon")])
    assert [draft.kind for draft in drafts] == ["price"]
    assert drafts[0].price_change_pct == 0.06
    assert "did not line up" in drafts[0].summary
    assert drafts[0].sections["second_supports"] is False
    assert "candidate reason" not in drafts[0].summary
    assert "overnight gap" not in drafts[0].summary


def test_an_after_close_headline_lines_up_with_the_close():
    eastern = ZoneInfo("America/New_York")
    today = NOW.astimezone(eastern).date()
    published = datetime(today.year, today.month, today.day, 16, 40, tzinfo=eastern)
    drafts = _evaluate(_bars(104, 100), [_headline(published_at=published)])
    assert [draft.kind for draft in drafts] == ["news_price"]
    assert "close versus the prior close" in drafts[0].summary
    assert drafts[0].price_change_pct == 0.04


def test_headline_price_slice_follows_the_eastern_clock():
    eastern = ZoneInfo("America/New_York")
    assert headline_price_slice(datetime(2026, 11, 17, 8, 0, tzinfo=eastern)) == "gap"
    assert headline_price_slice(datetime(2026, 11, 17, 9, 30, tzinfo=eastern)) == "session"
    assert headline_price_slice(datetime(2026, 11, 17, 16, 1, tzinfo=eastern)) == "close"
    assert headline_price_slice(datetime(2026, 11, 14, 11, 0, tzinfo=eastern)) == "close"


def test_sector_label_uses_the_stock_sector_fund_category_or_crypto():
    assert sector_label({"quoteType": "EQUITY", "sector": "Technology"}, "NVDA") == "Technology"
    assert sector_label({"quoteType": "CRYPTOCURRENCY"}, "BTC-USD") == "Crypto"
    assert sector_label({}, "ETH-USD") == "Crypto"
    assert sector_label({"quoteType": "ETF", "category": "Technology"}, "SMH") == "Technology"
    assert sector_label({"quoteType": "ETF", "category": "Large Blend"}, "SPY") == "Large Blend"
    assert sector_label({"quoteType": "MUTUALFUND", "category": "Large Blend"}, "VFIAX") == "Large Blend"
    assert sector_label({"quoteType": "ETF", "category": "Digital Assets"}, "IBIT") == "Crypto"
    assert sector_label({"quoteType": "ETF"}, "SMH") is None
    assert sector_label({}, "AAPL") is None


def test_a_past_evening_scores_that_days_headlines():
    eastern = ZoneInfo("America/New_York")
    day = datetime(2026, 11, 13, tzinfo=eastern)
    session = day.date()
    prior = session - timedelta(days=1)
    drafts = evaluate_symbol(
        symbol="LITE",
        bars=[
            {"dt": prior, "open": 100, "close": 100, "volume": 1_000_000},
            {"dt": session, "open": 100, "close": 90, "volume": 1_000_000},
        ],
        headlines=[
            _headline(
                title="Lumentum sinks after outlook cut",
                published_at=datetime(2026, 11, 13, 11, 0, tzinfo=eastern),
                sentiment_score=10,
            )
        ],
        now=datetime(2026, 11, 13, 20, 0, tzinfo=eastern),
        price_move_threshold=0.03,
        volume_spike_threshold=2.0,
        volume_lookback=20,
        sentiment_threshold=25,
        news_lookback_hours=72,
        fusion_window_hours=48,
    )
    assert [draft.kind for draft in drafts] == ["news_price"]
    assert drafts[0].bar_date == session
    assert drafts[0].sentiment_score == 10
    assert drafts[0].price_change_pct == -0.1


def test_cash_session_is_the_weekday_regular_hours():
    eastern = ZoneInfo("America/New_York")
    assert cash_session_open(datetime(2026, 11, 17, 9, 30, tzinfo=eastern))
    assert cash_session_open(datetime(2026, 11, 17, 11, 0, tzinfo=eastern))
    assert cash_session_open(datetime(2026, 11, 17, 15, 59, tzinfo=eastern))
    assert not cash_session_open(datetime(2026, 11, 17, 9, 29, tzinfo=eastern))
    assert not cash_session_open(datetime(2026, 11, 17, 16, 0, tzinfo=eastern))
    assert not cash_session_open(datetime(2026, 11, 14, 11, 0, tzinfo=eastern))


def test_open_to_last_uses_the_opening_print():
    eastern = ZoneInfo("America/New_York")
    now = datetime(2026, 11, 17, 11, 0, tzinfo=eastern)
    points = [
        (datetime(2026, 11, 17, 8, 0, tzinfo=eastern), 90.0, 91.0),
        (datetime(2026, 11, 17, 9, 30, tzinfo=eastern), 100.0, 101.0),
        (datetime(2026, 11, 17, 10, 45, tzinfo=eastern), 104.0, 106.0),
    ]
    assert open_to_last(points, now) == {"price": 106.0, "open": 100.0}
    assert open_to_last(points, datetime(2026, 11, 17, 14, 0, tzinfo=eastern)) is None
    assert open_to_last(points, datetime(2026, 11, 17, 16, 5, tzinfo=eastern)) is None
    assert open_to_last(points, datetime(2026, 11, 14, 11, 0, tzinfo=eastern)) is None
    yesterday = [
        (datetime(2026, 11, 16, 10, 0, tzinfo=eastern), 80.0, 80.0),
        (datetime(2026, 11, 17, 10, 40, tzinfo=eastern), 100.0, 104.0),
    ]
    assert open_to_last(yesterday, now) == {"price": 104.0, "open": 100.0}


def _live(now, **overrides):
    args = dict(
        symbol="AAPL",
        bars=[
            {"dt": now.date() - timedelta(days=1), "open": 100, "close": 100, "volume": 1_000_000},
            {"dt": now.date(), "open": 100, "close": 101, "volume": 1_000_000},
        ],
        headlines=[],
        now=now,
        price_move_threshold=0.03,
        volume_spike_threshold=2.0,
        volume_lookback=20,
        sentiment_threshold=25,
        news_lookback_hours=72,
        fusion_window_hours=48,
        live_session={"price": 106, "open": 100},
    )
    args.update(overrides)
    return evaluate_symbol(**args)


def test_a_live_session_alerts_from_the_open_before_the_close():
    eastern = ZoneInfo("America/New_York")
    now = datetime(2026, 11, 17, 11, 0, tzinfo=eastern)
    drafts = _live(now)
    assert [draft.kind for draft in drafts] == ["price"]
    assert drafts[0].price_change_pct == 0.06
    assert drafts[0].triggered_at == now.astimezone(UTC)
    assert "from the open of $100.00" in drafts[0].sections["price"]
    assert "prior close" not in drafts[0].sections["price"]


def test_a_small_move_from_the_open_does_not_borrow_the_partial_close():
    eastern = ZoneInfo("America/New_York")
    now = datetime(2026, 11, 17, 11, 0, tzinfo=eastern)
    today = now.date()
    drafts = _live(
        now,
        bars=[
            {"dt": today - timedelta(days=1), "open": 100, "close": 100, "volume": 1_000_000},
            {"dt": today, "open": 109, "close": 110, "volume": 1_000_000},
        ],
        live_session={"price": 110, "open": 109},
    )
    assert drafts == []


def test_a_down_move_from_the_open_is_timed_at_the_check():
    eastern = ZoneInfo("America/New_York")
    now = datetime(2026, 11, 17, 14, 15, tzinfo=eastern)
    drafts = _live(now, live_session={"price": 94, "open": 100})
    assert [draft.kind for draft in drafts] == ["price"]
    assert drafts[0].price_change_pct == -0.06
    assert drafts[0].triggered_at == now.astimezone(UTC)
    assert "down -6.00%" in drafts[0].sections["price"]


def test_a_premarket_headline_uses_the_gap_while_the_session_is_open():
    eastern = ZoneInfo("America/New_York")
    now = datetime(2026, 11, 17, 11, 0, tzinfo=eastern)
    today = now.date()
    drafts = _live(
        now,
        bars=[
            {"dt": today - timedelta(days=1), "open": 100, "close": 100, "volume": 1_000_000},
        ],
        live_session={"price": 111, "open": 110},
        headlines=[
            _headline(
                title="Apple jumps before the open",
                published_at=datetime(2026, 11, 17, 8, 0, tzinfo=eastern),
                sentiment_score=90,
            )
        ],
    )
    assert [draft.kind for draft in drafts] == ["news_price"]
    assert "overnight gap" in drafts[0].summary
    assert drafts[0].price_change_pct == 0.1


def test_the_larger_live_slice_wins_when_the_gap_and_the_session_both_clear():
    eastern = ZoneInfo("America/New_York")
    now = datetime(2026, 11, 17, 12, 0, tzinfo=eastern)
    today = now.date()
    drafts = _live(
        now,
        bars=[{"dt": today - timedelta(days=1), "open": 100, "close": 100, "volume": 1_000_000}],
        live_session={"price": 130, "open": 110},
        headlines=[
            _headline(
                title="Apple jumps before the open",
                published_at=datetime(2026, 11, 17, 8, 0, tzinfo=eastern),
                sentiment_score=90,
            ),
            _headline(
                id="22222222-2222-2222-2222-222222222222",
                title="Apple extends the gain after the open",
                published_at=datetime(2026, 11, 17, 11, 0, tzinfo=eastern),
                sentiment_score=88,
            ),
        ],
    )
    assert [draft.kind for draft in drafts] == ["news_price"]
    assert "regular session so far" in drafts[0].summary
    assert abs(drafts[0].price_change_pct - (130 / 110 - 1)) < 1e-9


def test_a_midday_headline_can_match_the_move_from_the_open():
    eastern = ZoneInfo("America/New_York")
    now = datetime(2026, 11, 17, 12, 0, tzinfo=eastern)
    published = datetime(2026, 11, 17, 11, 0, tzinfo=eastern)
    drafts = _live(
        now,
        headlines=[_headline(title="Apple slides after a supply note", published_at=published, sentiment_score=10)],
    )
    assert [draft.kind for draft in drafts] == ["news_price"]
    assert "regular session so far" in drafts[0].summary
    assert drafts[0].triggered_at == now.astimezone(UTC)


def test_continuous_markets_and_the_local_symbol_list():
    assert trades_all_day("BTC-USD")
    assert trades_all_day("eth-usd")
    assert not trades_all_day("AAPL")
    assert not trades_all_day("BRK-B")
    assert known_universe_symbol("AAPL")
    assert known_universe_symbol("MSFT")
    assert not known_universe_symbol("BTC-USD")
    assert not known_universe_symbol("ZZZZ")
