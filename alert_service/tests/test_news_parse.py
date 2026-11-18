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
