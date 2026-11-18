from app.news import choose_headline_items, parse_yahoo_news_items


def test_parse_modern_yahoo_content_and_score():
    items = parse_yahoo_news_items(
        [
            {
                "content": {
                    "title": "Shares plunge after results",
                    "summary": "The company missed expectations.",
                    "pubDate": "2026-11-17T18:00:00Z",
                    "provider": {"displayName": "Reuters"},
                    "canonicalUrl": {"url": "https://example.com/aapl"},
                }
            }
        ]
    )
    assert len(items) == 1
    assert items[0]["source"] == "Reuters"
    assert items[0]["url"] == "https://example.com/aapl"
    assert "sentiment_score" not in items[0]


def test_parse_skips_items_without_a_time():
    assert parse_yahoo_news_items([{"title": "No clock"}]) == []


def _item(title: str) -> dict:
    return {"title": title, "providerPublishTime": 1763400000, "publisher": "Wire"}


def test_search_fallback_keeps_only_headlines_that_name_the_ticker():
    chosen = choose_headline_items(
        "AAPL",
        ticker_raw=[],
        search_raw=[
            _item("Coca-Cola stock may struggle"),
            _item("AAPL shares plunge after guidance cut"),
        ],
    )
    assert [item["title"] for item in chosen] == ["AAPL shares plunge after guidance cut"]


def test_quote_news_drops_stories_that_only_tag_the_ticker():
    chosen = choose_headline_items(
        "AAPL",
        ticker_raw=[
            _item("Apple outage hits the App Store"),
            _item("Software stock selloff spreads"),
        ],
        search_raw=[],
        mention_tokens={"AAPL", "APPLE"},
    )
    assert [item["title"] for item in chosen] == ["Apple outage hits the App Store"]


def test_older_pages_are_requested_until_the_rebuild_window():
    from datetime import date

    from app.news import _need_older_headlines

    window = date(2026, 11, 13)
    assert _need_older_headlines(date(2026, 11, 17), window, received=40, asked=40)
    assert not _need_older_headlines(date(2026, 11, 13), window, received=40, asked=40)
    assert not _need_older_headlines(date(2026, 11, 17), window, received=12, asked=40)
    assert not _need_older_headlines(date(2026, 11, 17), window, received=200, asked=200)
    assert not _need_older_headlines(None, window, received=40, asked=40)


def test_a_windowed_fetch_pages_past_today(monkeypatch):
    from datetime import UTC, date, datetime, timedelta

    from app.news import fetch_headlines

    calls = []

    class FakeTicker:
        def __init__(self, symbol):
            self.symbol = symbol

        @property
        def info(self):
            return {"shortName": "Lumentum"}

        def get_news(self, count=10, tab="news"):
            calls.append(count)
            start = datetime(2026, 11, 18, 0, 0, tzinfo=UTC)
            rows = []
            for index in range(count):
                when = start - timedelta(hours=index)
                rows.append(
                    {
                        "content": {
                            "title": f"LITE story {index}",
                            "pubDate": when.strftime("%Y-%m-%dT%H:%M:%SZ"),
                            "provider": {"displayName": "Wire"},
                        }
                    }
                )
            return rows

    monkeypatch.setattr("yfinance.Ticker", FakeTicker)
    items = fetch_headlines("LITE", through=date(2026, 11, 13))
    assert calls == [40, 80]
    assert items
    from app.engine import headline_session

    assert min(headline_session(item["published_at"]) for item in items) <= date(2026, 11, 13)
