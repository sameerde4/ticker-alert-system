from fastapi.testclient import TestClient

from app.main import app


def test_health_and_ui_without_a_database():
    client = TestClient(app)
    assert client.get("/health").json() == {"status": "ok"}
    page = client.get("/ui")
    assert page.status_code == 200
    assert "Ticker Alert System" in page.text
    assert "historyTab" in page.text
    assert "Alert History" in page.text
    assert "https://finance.yahoo.com/quote/" in page.text
    assert 'link.target = "_blank"' in page.text
    assert "function symbolLink" in page.text
    for column in ("symbol", "sector", "type", "when", "price", "sentiment"):
        assert f'data-sort="{column}"' in page.text


def test_watchlist_reports_database_down():
    client = TestClient(app)
    response = client.get("/v1/watchlist")
    assert response.status_code == 503


def test_rebuild_rejects_a_bad_day_count_before_the_database():
    client = TestClient(app)
    response = client.post("/v1/admin/rebuild", json={"days": 0})
    assert response.status_code == 400
    page = client.get("/ui")
    assert "Rebuild history" in page.text
    assert "Wipe and rebuild" in page.text
    assert "Sentiment scoring" in page.text
    assert "FinBERT" in page.text
    assert "Custom scoring" in page.text
    assert "positive probability minus the negative" in page.text
    assert "not a hosted analysis API" in page.text
    assert "previous three words" in page.text
    assert "never averaged" in page.text


def test_unknown_scorer_is_rejected_before_the_database():
    client = TestClient(app)
    response = client.put("/v1/settings/scorer", json={"sentiment_scorer": "both"})
    assert response.status_code == 400


def test_bad_symbol_is_rejected_before_the_database():
    client = TestClient(app)
    response = client.post("/v1/watchlist", json={"symbol": "not a ticker"})
    assert response.status_code == 400
